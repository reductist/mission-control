"""Landscape-owned persistence and agenda projection."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, date, datetime
from importlib.resources import files
from typing import Final, Protocol
from uuid import uuid4

from ...agenda import (
    Action,
    ActionState,
    AgendaContribution,
    AgendaSchemaVersion,
    AnytimeTiming,
    DueAtTiming,
    DueOnTiming,
    Initiative,
    InitiativeState,
    ProviderRef,
    SourceRef,
    WindowTiming,
)
from ...database import Database
from ...plugins import PluginId
from .domain import (
    LandscapeAction,
    LandscapeActionState,
    LandscapeAnytime,
    LandscapeDueAt,
    LandscapeDueOn,
    LandscapeEntityKind,
    LandscapeEvent,
    LandscapeInitiative,
    LandscapeInitiativeState,
    LandscapeTiming,
    LandscapeTimingKind,
    LandscapeWindow,
)

PLUGIN_ID: Final = PluginId("landscape")
INITIAL_IMPORT_ID: Final = "equipment-access-v1"


class LandscapeMigrationRunner:
    """Apply only migrations owned by Landscape."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def apply(self) -> list[int]:
        applied: list[int] = []
        migration_root = files(__package__).joinpath("migrations")
        with self.database.connect() as connection:
            existing = (
                {
                    row[0]
                    for row in connection.execute(
                        "SELECT version FROM landscape_schema_migrations"
                    ).fetchall()
                }
                if self._has_migration_table(connection)
                else set()
            )
            for migration in sorted(
                migration_root.iterdir(), key=lambda path: path.name
            ):
                if migration.suffix != ".sql":
                    continue
                version = int(migration.name.split("_", 1)[0])
                if version in existing:
                    continue
                script = migration.read_text(encoding="utf-8")
                connection.executescript(f"BEGIN IMMEDIATE;\n{script}\nCOMMIT;")
                applied.append(version)
        return applied

    @staticmethod
    def _has_migration_table(connection: sqlite3.Connection) -> bool:
        row = connection.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type = 'table' AND name = 'landscape_schema_migrations'"
        ).fetchone()
        return row is not None


class LandscapeRepository(Protocol):
    """Domain-specific persistence required by Landscape."""

    def list_initiatives(self) -> tuple[LandscapeInitiative, ...]: ...

    def list_actions(self) -> tuple[LandscapeAction, ...]: ...

    def get_action(self, action_id: str) -> LandscapeAction: ...

    def set_action_state(
        self, action_id: str, state: LandscapeActionState
    ) -> LandscapeAction: ...

    def history(
        self, entity_kind: LandscapeEntityKind, entity_id: str
    ) -> tuple[LandscapeEvent, ...]: ...

    def agenda_contribution(self, *, generated_at: datetime) -> AgendaContribution: ...


class SQLiteLandscapeRepository:
    """SQLite adapter for Landscape-owned records and events."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def import_agenda_seed(
        self,
        seed: AgendaContribution,
        *,
        import_id: str = INITIAL_IMPORT_ID,
    ) -> bool:
        """Import a validated packaged snapshot once without later overwrites."""

        if seed.provider.plugin_id != PLUGIN_ID:
            raise ValueError("Landscape seed must belong to the landscape provider")
        occurred_at = datetime.now(UTC).isoformat()
        with self.database.connect() as connection:
            imported = connection.execute(
                "SELECT 1 FROM landscape_seed_imports WHERE import_id = ?",
                (import_id,),
            ).fetchone()
            if imported is not None:
                return False

            for entry in seed.entries:
                if isinstance(entry, Initiative):
                    self._assert_seed_identity(entry, LandscapeEntityKind.INITIATIVE)
                    self._insert_initiative(connection, entry, occurred_at)
                elif isinstance(entry, Action):
                    self._assert_seed_identity(entry, LandscapeEntityKind.ACTION)
                    self._insert_action(connection, entry, occurred_at)
                else:
                    raise TypeError(
                        "Landscape's initial seed supports initiatives and actions only"
                    )
            connection.execute(
                "INSERT INTO landscape_seed_imports(import_id, source_revision, imported_at) "
                "VALUES (?, ?, ?)",
                (import_id, seed.revision, occurred_at),
            )
        return True

    @staticmethod
    def _assert_seed_identity(
        entry: Initiative | Action, expected_kind: LandscapeEntityKind
    ) -> None:
        if entry.entry_id != entry.source.entity_id:
            raise ValueError(
                f"Landscape seed entry {entry.entry_id!r} must match its source entity id"
            )
        if entry.source.entity_type != expected_kind.value:
            raise ValueError(
                f"Landscape seed entry {entry.entry_id!r} must use entity type "
                f"{expected_kind.value!r}"
            )

    def list_initiatives(self) -> tuple[LandscapeInitiative, ...]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM landscape_initiatives ORDER BY created_at, initiative_id"
            ).fetchall()
        return tuple(self._initiative_from_row(row) for row in rows)

    def list_actions(self) -> tuple[LandscapeAction, ...]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM landscape_actions ORDER BY created_at, action_id"
            ).fetchall()
        return tuple(self._action_from_row(row) for row in rows)

    def get_action(self, action_id: str) -> LandscapeAction:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM landscape_actions WHERE action_id = ?", (action_id,)
            ).fetchone()
        if row is None:
            raise KeyError(action_id)
        return self._action_from_row(row)

    def set_action_state(
        self, action_id: str, state: LandscapeActionState
    ) -> LandscapeAction:
        """Persist a state transition primitive for Landscape's future command owner."""

        if not isinstance(state, LandscapeActionState):
            raise TypeError("Landscape action state must be a LandscapeActionState")
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM landscape_actions WHERE action_id = ?", (action_id,)
            ).fetchone()
            if row is None:
                raise KeyError(action_id)
            current = self._action_from_row(row)
            if current.state is state:
                return current

            occurred_at = datetime.now(UTC).isoformat()
            next_version = current.version + 1
            connection.execute(
                "UPDATE landscape_actions SET state = ?, version = ?, updated_at = ? "
                "WHERE action_id = ?",
                (state.value, next_version, occurred_at, action_id),
            )
            self._insert_event(
                connection,
                LandscapeEntityKind.ACTION,
                action_id,
                "landscape.action-state-changed",
                {"from": current.state.value, "to": state.value},
                occurred_at,
            )
            updated = connection.execute(
                "SELECT * FROM landscape_actions WHERE action_id = ?", (action_id,)
            ).fetchone()
            assert updated is not None
            return self._action_from_row(updated)

    def history(
        self, entity_kind: LandscapeEntityKind, entity_id: str
    ) -> tuple[LandscapeEvent, ...]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT sequence, event_id, entity_kind, entity_id, event_type, "
                "payload_json, occurred_at FROM landscape_events "
                "WHERE entity_kind = ? AND entity_id = ? ORDER BY sequence",
                (entity_kind.value, entity_id),
            ).fetchall()
        return tuple(self._event_from_row(row) for row in rows)

    def agenda_contribution(self, *, generated_at: datetime) -> AgendaContribution:
        initiatives = self.list_initiatives()
        actions = self.list_actions()
        entries: list[Initiative | Action] = []

        for initiative in initiatives:
            if initiative.state is LandscapeInitiativeState.COMPLETED:
                continue
            entries.append(
                Initiative(
                    entry_id=initiative.initiative_id,
                    source=SourceRef(PLUGIN_ID, "initiative", initiative.initiative_id),
                    title=initiative.title,
                    state=InitiativeState(initiative.state.value),
                    context=initiative.context,
                    detail=initiative.detail,
                )
            )
        for action in actions:
            if action.state is LandscapeActionState.DONE:
                continue
            entries.append(
                Action(
                    entry_id=action.action_id,
                    source=SourceRef(PLUGIN_ID, "action", action.action_id),
                    title=action.title,
                    state=ActionState(action.state.value),
                    timing=self._agenda_timing(action.timing),
                    context=action.context,
                    detail=action.detail,
                )
            )

        revision_document = {
            "initiatives": [self._initiative_revision(item) for item in initiatives],
            "actions": [self._action_revision(item) for item in actions],
        }
        revision = hashlib.sha256(
            json.dumps(
                revision_document, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
        return AgendaContribution(
            schema_version=AgendaSchemaVersion.V1,
            provider=ProviderRef(PLUGIN_ID),
            revision=revision,
            generated_at=generated_at,
            entries=tuple(entries),
        )

    @classmethod
    def _insert_initiative(
        cls, connection: sqlite3.Connection, entry: Initiative, occurred_at: str
    ) -> None:
        try:
            connection.execute(
                "INSERT INTO landscape_initiatives(initiative_id, title, state, context, "
                "detail, version, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 1, ?, ?)",
                (
                    entry.source.entity_id,
                    entry.title,
                    entry.state.value,
                    entry.context,
                    entry.detail,
                    occurred_at,
                    occurred_at,
                ),
            )
        except sqlite3.IntegrityError as error:
            raise ValueError(
                f"Landscape seed initiative collides with existing id {entry.source.entity_id!r}"
            ) from error
        cls._insert_event(
            connection,
            LandscapeEntityKind.INITIATIVE,
            entry.source.entity_id,
            "landscape.initiative-imported",
            {"state": entry.state.value},
            occurred_at,
        )

    @classmethod
    def _insert_action(
        cls, connection: sqlite3.Connection, entry: Action, occurred_at: str
    ) -> None:
        due_on: str | None = None
        due_at: str | None = None
        starts_at: str | None = None
        ends_at: str | None = None
        if isinstance(entry.timing, DueOnTiming):
            due_on = entry.timing.due_on.isoformat()
        elif isinstance(entry.timing, DueAtTiming):
            due_at = entry.timing.due_at.isoformat()
        elif isinstance(entry.timing, WindowTiming):
            starts_at = entry.timing.starts_at.isoformat()
            ends_at = entry.timing.ends_at.isoformat()

        try:
            connection.execute(
                "INSERT INTO landscape_actions(action_id, title, state, timing_kind, "
                "due_on, due_at, starts_at, ends_at, context, detail, version, created_at, "
                "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)",
                (
                    entry.source.entity_id,
                    entry.title,
                    entry.state.value,
                    entry.timing.kind.value,
                    due_on,
                    due_at,
                    starts_at,
                    ends_at,
                    entry.context,
                    entry.detail,
                    occurred_at,
                    occurred_at,
                ),
            )
        except sqlite3.IntegrityError as error:
            raise ValueError(
                f"Landscape seed action collides with existing id {entry.source.entity_id!r}"
            ) from error
        cls._insert_event(
            connection,
            LandscapeEntityKind.ACTION,
            entry.source.entity_id,
            "landscape.action-imported",
            {"state": entry.state.value, "timing": entry.timing.kind.value},
            occurred_at,
        )

    @staticmethod
    def _insert_event(
        connection: sqlite3.Connection,
        entity_kind: LandscapeEntityKind,
        entity_id: str,
        event_type: str,
        payload: dict[str, object],
        occurred_at: str,
    ) -> None:
        connection.execute(
            "INSERT INTO landscape_events(event_id, entity_kind, entity_id, event_type, "
            "payload_json, occurred_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                str(uuid4()),
                entity_kind.value,
                entity_id,
                event_type,
                json.dumps(payload, sort_keys=True, separators=(",", ":")),
                occurred_at,
            ),
        )

    @staticmethod
    def _initiative_from_row(row: sqlite3.Row) -> LandscapeInitiative:
        return LandscapeInitiative(
            initiative_id=row["initiative_id"],
            title=row["title"],
            state=LandscapeInitiativeState(row["state"]),
            context=row["context"],
            detail=row["detail"],
            version=row["version"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    @classmethod
    def _action_from_row(cls, row: sqlite3.Row) -> LandscapeAction:
        return LandscapeAction(
            action_id=row["action_id"],
            title=row["title"],
            state=LandscapeActionState(row["state"]),
            timing=cls._timing_from_row(row),
            context=row["context"],
            detail=row["detail"],
            version=row["version"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    @staticmethod
    def _timing_from_row(row: sqlite3.Row) -> LandscapeTiming:
        kind = LandscapeTimingKind(row["timing_kind"])
        match kind:
            case LandscapeTimingKind.ANYTIME:
                return LandscapeAnytime()
            case LandscapeTimingKind.DUE_ON:
                return LandscapeDueOn(date.fromisoformat(row["due_on"]))
            case LandscapeTimingKind.DUE_AT:
                return LandscapeDueAt(datetime.fromisoformat(row["due_at"]))
            case LandscapeTimingKind.WINDOW:
                return LandscapeWindow(
                    datetime.fromisoformat(row["starts_at"]),
                    datetime.fromisoformat(row["ends_at"]),
                )
        raise AssertionError(f"unhandled Landscape timing kind: {kind}")

    @staticmethod
    def _event_from_row(row: sqlite3.Row) -> LandscapeEvent:
        return LandscapeEvent(
            sequence=row["sequence"],
            event_id=row["event_id"],
            entity_kind=LandscapeEntityKind(row["entity_kind"]),
            entity_id=row["entity_id"],
            event_type=row["event_type"],
            payload_json=row["payload_json"],
            occurred_at=datetime.fromisoformat(row["occurred_at"]),
        )

    @staticmethod
    def _agenda_timing(timing: LandscapeTiming):
        if isinstance(timing, LandscapeAnytime):
            return AnytimeTiming()
        if isinstance(timing, LandscapeDueOn):
            return DueOnTiming(timing.due_on)
        if isinstance(timing, LandscapeDueAt):
            return DueAtTiming(timing.due_at)
        if isinstance(timing, LandscapeWindow):
            return WindowTiming(timing.starts_at, timing.ends_at)
        raise AssertionError(f"unhandled Landscape timing: {timing!r}")

    @staticmethod
    def _initiative_revision(item: LandscapeInitiative) -> dict[str, object]:
        return {
            "id": item.initiative_id,
            "state": item.state.value,
            "version": item.version,
            "updated_at": item.updated_at.isoformat(),
        }

    @staticmethod
    def _action_revision(item: LandscapeAction) -> dict[str, object]:
        return {
            "id": item.action_id,
            "state": item.state.value,
            "version": item.version,
            "updated_at": item.updated_at.isoformat(),
        }
