"""Google-owned cache, migrations, sync orchestration, and projections."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from importlib.resources import files

from mission_control.agenda import (
    AgendaContribution,
    AgendaSchemaVersion,
    ProviderRef,
    SourceRef,
)
from mission_control.builtin_plugins.google.client import GoogleApiError, GoogleClient
from mission_control.builtin_plugins.google.config import (
    GoogleConfig,
    GoogleConnectionConfig,
)
from mission_control.builtin_plugins.google.domain import (
    GoogleCollection,
    GoogleEntry,
    GoogleResourceError,
    calendar_event,
    google_task,
)
from mission_control.builtin_plugins.google.mapping import agenda_entry
from mission_control.database import Database
from mission_control.entity_details import (
    DetailAttribute,
    EntityDetail,
    EntityDetailSchemaVersion,
)
from mission_control.plugin_runtime import (
    PluginHealth,
    PluginHealthComponent,
    PluginHealthState,
)
from mission_control.plugins import (
    EntityAffordance,
    EntityCapability,
    PluginId,
    StandardEntityCapability,
)

PLUGIN_ID = PluginId("google-calendar")
ANNOTATE = EntityAffordance(
    EntityCapability(StandardEntityCapability.ENTITY_ANNOTATE.value), "add-note"
)


class GoogleMigrationRunner:
    def __init__(self, database: Database) -> None:
        self.database = database

    def apply(self) -> list[int]:
        applied: list[int] = []
        root = files(__package__).joinpath("migrations")
        with self.database.connect() as connection:
            existing = (
                {
                    row[0]
                    for row in connection.execute(
                        "SELECT version FROM plugin__15__google_calendar__schema_migrations"
                    ).fetchall()
                }
                if self._has_migration_table(connection)
                else set()
            )
            for migration in sorted(root.iterdir(), key=lambda path: path.name):
                if migration.suffix != ".sql":
                    continue
                version = int(migration.name.split("_", 1)[0])
                if version in existing:
                    continue
                connection.executescript(
                    f"BEGIN IMMEDIATE;\n{migration.read_text(encoding='utf-8')}\nCOMMIT;"
                )
                applied.append(version)
        return applied

    @staticmethod
    def _has_migration_table(connection: sqlite3.Connection) -> bool:
        return (
            connection.execute(
                "SELECT 1 FROM sqlite_master "
                "WHERE type = 'table' AND name = 'plugin__15__google_calendar__schema_migrations'"
            ).fetchone()
            is not None
        )


@dataclass(frozen=True, slots=True)
class GoogleSyncStatus:
    connection_id: str
    connection_label: str
    last_attempt_at: datetime | None
    last_success_at: datetime | None
    error_code: str | None
    error_detail: str | None
    source_mode: str | None
    source_fingerprint: str | None


class SQLiteGoogleRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def reconcile_collections(
        self,
        connection_id: str,
        kind: str,
        collections: Iterable[GoogleCollection],
    ) -> None:
        snapshot = tuple(collections)
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for item in snapshot:
                connection.execute(
                    "INSERT INTO plugin__15__google_calendar__collections("
                    "collection_key, connection_id, kind, external_id, label, "
                    "principal_ids_json, access_role"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(collection_key) DO UPDATE SET "
                    "label = excluded.label, principal_ids_json = excluded.principal_ids_json, "
                    "access_role = excluded.access_role",
                    (
                        item.collection_key,
                        item.connection_id,
                        item.kind,
                        item.external_id,
                        item.label,
                        json.dumps(item.principal_ids, separators=(",", ":")),
                        item.access_role,
                    ),
                )
            keys = tuple(item.collection_key for item in snapshot)
            if keys:
                placeholders = ",".join("?" for _ in keys)
                connection.execute(
                    f"DELETE FROM plugin__15__google_calendar__collections WHERE connection_id = ? AND kind = ? "
                    f"AND collection_key NOT IN ({placeholders})",
                    (connection_id, kind, *keys),
                )
            else:
                connection.execute(
                    "DELETE FROM plugin__15__google_calendar__collections "
                    "WHERE connection_id = ? AND kind = ?",
                    (connection_id, kind),
                )

    def reconcile_configured_connections(self, connection_ids: Iterable[str]) -> None:
        configured = tuple(sorted(connection_ids))
        with self.database.connect() as connection:
            if not configured:
                connection.execute("DELETE FROM plugin__15__google_calendar__connections")
                return
            placeholders = ",".join("?" for _ in configured)
            connection.execute(
                f"DELETE FROM plugin__15__google_calendar__connections "
                f"WHERE connection_id NOT IN ({placeholders})",
                configured,
            )

    def prepare_source(
        self,
        connection_id: str,
        connection_label: str,
        mode: str,
        fingerprint: str,
    ) -> bool:
        """Quarantine cache rows when fixture mode or OAuth identity changes."""

        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT source_mode, source_fingerprint FROM "
                "plugin__15__google_calendar__connections WHERE connection_id = ?",
                (connection_id,),
            ).fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO plugin__15__google_calendar__connections("
                    "connection_id, label, source_mode, source_fingerprint"
                    ") VALUES (?, ?, ?, ?)",
                    (connection_id, connection_label, mode, fingerprint),
                )
                return True
            if row["source_mode"] == mode and row["source_fingerprint"] == fingerprint:
                connection.execute(
                    "UPDATE plugin__15__google_calendar__connections SET label = ? "
                    "WHERE connection_id = ?",
                    (connection_label, connection_id),
                )
                return False
            connection.execute(
                "DELETE FROM plugin__15__google_calendar__collections WHERE connection_id = ?",
                (connection_id,),
            )
            connection.execute(
                "UPDATE plugin__15__google_calendar__connections SET label = ?, last_attempt_at = NULL, "
                "last_success_at = NULL, error_code = NULL, error_detail = NULL, "
                "source_mode = ?, source_fingerprint = ? WHERE connection_id = ?",
                (connection_label, mode, fingerprint, connection_id),
            )
        return True

    def replace_collection(
        self,
        collection: GoogleCollection,
        entries: Iterable[GoogleEntry],
        *,
        synced_at: datetime,
    ) -> None:
        snapshot = tuple(entries)
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "DELETE FROM plugin__15__google_calendar__entries WHERE collection_key = ?",
                (collection.collection_key,),
            )
            for item in snapshot:
                connection.execute(
                    "INSERT INTO plugin__15__google_calendar__entries("
                    "entity_id, collection_key, remote_id, entity_type, title, context, "
                    "detail, timing_kind, occurs_on, ends_before, starts_at, ends_at, "
                    "due_on, status, location, source_url, revision, updated_at"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        item.entity_id,
                        item.collection_key,
                        item.remote_id,
                        item.entity_type,
                        item.title,
                        item.context,
                        item.detail,
                        item.timing_kind,
                        _date_text(item.occurs_on),
                        _date_text(item.ends_before),
                        _datetime_text(item.starts_at),
                        _datetime_text(item.ends_at),
                        _date_text(item.due_on),
                        item.status,
                        item.location,
                        item.source_url,
                        item.revision,
                        item.updated_at.isoformat(),
                    ),
                )
            connection.execute(
                "UPDATE plugin__15__google_calendar__collections SET last_attempt_at = ?, last_success_at = ?, "
                "error_code = NULL, error_detail = NULL WHERE collection_key = ?",
                (
                    synced_at.isoformat(),
                    synced_at.isoformat(),
                    collection.collection_key,
                ),
            )

    def mark_collection_failure(
        self,
        collection: GoogleCollection,
        *,
        attempted_at: datetime,
        code: str,
        detail: str,
    ) -> None:
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE plugin__15__google_calendar__collections SET last_attempt_at = ?, error_code = ?, "
                "error_detail = ? WHERE collection_key = ?",
                (attempted_at.isoformat(), code, detail, collection.collection_key),
            )

    def record_attempt(self, connection_id: str, attempted_at: datetime) -> None:
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE plugin__15__google_calendar__connections SET last_attempt_at = ? "
                "WHERE connection_id = ?",
                (attempted_at.isoformat(), connection_id),
            )

    def record_success(self, connection_id: str, synced_at: datetime) -> None:
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE plugin__15__google_calendar__connections SET last_attempt_at = ?, last_success_at = ?, "
                "error_code = NULL, error_detail = NULL WHERE connection_id = ?",
                (synced_at.isoformat(), synced_at.isoformat(), connection_id),
            )

    def record_failure(
        self, connection_id: str, attempted_at: datetime, *, code: str, detail: str
    ) -> None:
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE plugin__15__google_calendar__connections SET last_attempt_at = ?, error_code = ?, "
                "error_detail = ? WHERE connection_id = ?",
                (attempted_at.isoformat(), code, detail, connection_id),
            )

    def clear_cache(self, connection_id: str) -> None:
        """Erase imported private data after terminal authorization failure."""

        with self.database.connect() as connection:
            connection.execute(
                "DELETE FROM plugin__15__google_calendar__collections WHERE connection_id = ?",
                (connection_id,),
            )

    def status(self, connection_id: str = "default") -> GoogleSyncStatus:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT last_attempt_at, last_success_at, error_code, error_detail, "
                "source_mode, source_fingerprint, connection_id, label "
                "FROM plugin__15__google_calendar__connections WHERE connection_id = ?",
                (connection_id,),
            ).fetchone()
        assert row is not None
        return GoogleSyncStatus(
            row["connection_id"],
            row["label"],
            _optional_datetime(row["last_attempt_at"]),
            _optional_datetime(row["last_success_at"]),
            row["error_code"],
            row["error_detail"],
            row["source_mode"],
            row["source_fingerprint"],
        )

    def statuses(self) -> tuple[GoogleSyncStatus, ...]:
        with self.database.connect() as connection:
            ids = tuple(
                row["connection_id"]
                for row in connection.execute(
                    "SELECT connection_id FROM plugin__15__google_calendar__connections "
                    "ORDER BY connection_id"
                ).fetchall()
            )
        return tuple(self.status(connection_id) for connection_id in ids)

    def list_entries(self) -> tuple[GoogleEntry, ...]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT e.*, c.connection_id, c.label AS connection_label, "
                "c.external_id AS collection_external_id, "
                "c.kind AS collection_kind, c.principal_ids_json "
                "FROM plugin__15__google_calendar__entries e JOIN "
                "plugin__15__google_calendar__collections c USING(collection_key) "
                "ORDER BY e.entity_type, e.entity_id"
            ).fetchall()
        return tuple(self._entry(row) for row in rows)

    def get_entry(self, entity_id: str) -> GoogleEntry:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT e.*, c.connection_id, c.label AS connection_label, "
                "c.external_id AS collection_external_id, "
                "c.kind AS collection_kind, c.principal_ids_json "
                "FROM plugin__15__google_calendar__entries e JOIN "
                "plugin__15__google_calendar__collections c USING(collection_key) "
                "WHERE e.entity_id = ?",
                (entity_id,),
            ).fetchone()
        if row is None:
            raise KeyError(entity_id)
        return self._entry(row)

    @staticmethod
    def _entry(row: sqlite3.Row) -> GoogleEntry:
        return GoogleEntry(
            entity_id=row["entity_id"],
            collection_key=row["collection_key"],
            remote_id=row["remote_id"],
            entity_type=row["entity_type"],
            title=row["title"],
            context=row["context"],
            detail=row["detail"],
            timing_kind=row["timing_kind"],
            occurs_on=_optional_date(row["occurs_on"]),
            ends_before=_optional_date(row["ends_before"]),
            starts_at=_optional_datetime(row["starts_at"]),
            ends_at=_optional_datetime(row["ends_at"]),
            due_on=_optional_date(row["due_on"]),
            status=row["status"],
            location=row["location"],
            source_url=row["source_url"],
            revision=row["revision"],
            updated_at=datetime.fromisoformat(row["updated_at"]),
            connection_id=row["connection_id"],
            connection_label=row["connection_label"],
            collection_external_id=row["collection_external_id"],
            collection_kind=row["collection_kind"],
            principal_ids=tuple(json.loads(row["principal_ids_json"])),
        )

    def contribution(self, *, generated_at: datetime) -> AgendaContribution:
        cached = self.list_entries()
        entries = tuple(agenda_entry(item) for item in cached)
        revision = hashlib.sha256(
            json.dumps(
                [(item.entity_id, item.revision) for item in cached],
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return AgendaContribution(
            schema_version=AgendaSchemaVersion.V2,
            provider=ProviderRef(PLUGIN_ID),
            revision=revision,
            generated_at=generated_at,
            entries=entries,
        )

    def entity_detail(self, target: SourceRef) -> EntityDetail | None:
        if target.plugin_id != PLUGIN_ID or target.entity_type not in {
            "calendar-event",
            "task",
        }:
            return None
        try:
            item = self.get_entry(target.entity_id)
        except KeyError:
            return None
        if item.entity_type != target.entity_type:
            return None
        attributes = [
            DetailAttribute("source", "Source", item.context),
            DetailAttribute("when", "When", _timing_label(item)),
        ]
        if item.location:
            attributes.append(DetailAttribute("location", "Location", item.location))
        if item.source_url:
            attributes.append(DetailAttribute("google-link", "Google link", item.source_url))
        return EntityDetail(
            schema_version=EntityDetailSchemaVersion.V1,
            source=target,
            title=item.title,
            description=item.detail,
            state=item.status,
            revision=item.revision,
            attributes=tuple(attributes),
            affordances=(ANNOTATE,),
            activity=(),
        )


class GoogleSynchronizer:
    def __init__(
        self,
        repository: SQLiteGoogleRepository,
        client: GoogleClient,
        config: GoogleConfig,
        connection: GoogleConnectionConfig,
    ) -> None:
        self.repository = repository
        self.client = client
        self.config = config
        self.connection = connection
        self._runtime_failure_at: datetime | None = None

    @property
    def runtime_failure_at(self) -> datetime | None:
        return self._runtime_failure_at

    def record_unexpected_failure(self) -> None:
        failed_at = datetime.now(UTC)
        self._runtime_failure_at = failed_at
        try:
            self.repository.record_failure(
                self.connection.connection_id,
                failed_at,
                code="job-failed",
                detail="Google refresh failed unexpectedly; cached data was retained.",
            )
        except sqlite3.Error:
            pass

    def sync_once(self) -> None:
        attempted_at = datetime.now(UTC)
        self.repository.record_attempt(self.connection.connection_id, attempted_at)
        calendar_failures, calendar_discovery_error = self._sync_calendars(attempted_at)
        if (
            calendar_discovery_error is not None
            and calendar_discovery_error[0] == "reconnect-required"
        ):
            task_failures, task_discovery_error = 0, None
        else:
            task_failures, task_discovery_error = self._sync_tasks(attempted_at)
        failures = calendar_failures + task_failures
        discovery_errors = tuple(
            error
            for error in (calendar_discovery_error, task_discovery_error)
            if error is not None
        )
        reconnect = next(
            (error for error in discovery_errors if error[0] == "reconnect-required"),
            None,
        )
        if reconnect is not None:
            self.repository.clear_cache(self.connection.connection_id)
            self.repository.record_failure(
                self.connection.connection_id,
                attempted_at,
                code=reconnect[0],
                detail=reconnect[1],
            )
        if failures:
            if reconnect is None:
                self.repository.record_failure(
                    self.connection.connection_id,
                    attempted_at,
                    code="partial-sync",
                    detail=f"{failures} Google source{'s' if failures != 1 else ''} could not refresh; healthy sources remain available.",
                )
        else:
            self.repository.record_success(
                self.connection.connection_id, attempted_at
            )
        self._runtime_failure_at = None

    def _sync_calendars(
        self, attempted_at: datetime
    ) -> tuple[int, tuple[str, str] | None]:
        if self.connection.calendars.mode == "disabled":
            self.repository.reconcile_collections(
                self.connection.connection_id, "calendar", ()
            )
            return 0, None
        try:
            discovered = self.client.calendars()
        except (GoogleApiError, GoogleResourceError, ValueError) as error:
            return 1, _safe_error(error)
        selected = []
        for collection, document in discovered:
            include = self.connection.calendars.includes(
                collection.external_id,
                default_selected=(
                    document.get("primary") is True
                    or document.get("selected") is True
                ),
            )
            if include:
                selected.append(
                    collection.for_connection(
                        self.connection.connection_id,
                        self.connection.label,
                        self.connection.principals_for(
                            "calendar", collection.external_id
                        ),
                    )
                )
        configured = set(self.connection.calendars.ids)
        missing = configured - {item.external_id for item in selected}
        self.repository.reconcile_collections(
            self.connection.connection_id, "calendar", selected
        )
        failures = len(missing)
        starts_at = attempted_at - timedelta(days=self.config.lookback_days)
        ends_at = attempted_at + timedelta(days=self.config.lookahead_days)
        for collection in selected:
            try:
                resources = self.client.events(
                    collection.external_id, starts_at=starts_at, ends_at=ends_at
                )
                entries = tuple(
                    entry
                    for entry in (
                        calendar_event(collection, resource) for resource in resources
                    )
                    if entry is not None
                )
                self.repository.replace_collection(
                    collection, entries, synced_at=attempted_at
                )
            except (GoogleApiError, GoogleResourceError, ValueError) as error:
                failures += 1
                code, detail = _safe_error(error)
                if code == "reconnect-required":
                    return failures, (code, detail)
                self.repository.mark_collection_failure(
                    collection,
                    attempted_at=attempted_at,
                    code=code,
                    detail=detail,
                )
        return failures, None

    def _sync_tasks(
        self, attempted_at: datetime
    ) -> tuple[int, tuple[str, str] | None]:
        if self.connection.tasks.mode == "disabled":
            self.repository.reconcile_collections(
                self.connection.connection_id, "task-list", ()
            )
            return 0, None
        try:
            discovered = self.client.task_lists()
        except (GoogleApiError, GoogleResourceError, ValueError) as error:
            return 1, _safe_error(error)
        configured = set(self.connection.tasks.ids)
        selected = [
            item.for_connection(
                self.connection.connection_id,
                self.connection.label,
                self.connection.principals_for("task-list", item.external_id),
            )
            for item in discovered
            if self.connection.tasks.includes(
                item.external_id, default_selected=True
            )
        ]
        missing = configured - {item.external_id for item in selected}
        self.repository.reconcile_collections(
            self.connection.connection_id, "task-list", selected
        )
        failures = len(missing)
        for collection in selected:
            try:
                entries = tuple(
                    entry
                    for entry in (
                        google_task(collection, resource)
                        for resource in self.client.tasks(collection.external_id)
                    )
                    if entry is not None
                )
                self.repository.replace_collection(
                    collection, entries, synced_at=attempted_at
                )
            except (GoogleApiError, GoogleResourceError, ValueError) as error:
                failures += 1
                code, detail = _safe_error(error)
                if code == "reconnect-required":
                    return failures, (code, detail)
                self.repository.mark_collection_failure(
                    collection,
                    attempted_at=attempted_at,
                    code=code,
                    detail=detail,
                )
        return failures, None


def plugin_health(
    repository: SQLiteGoogleRepository,
    *,
    runtime_failures: Mapping[str, datetime] | None = None,
) -> PluginHealth:
    now = datetime.now(UTC)
    statuses = repository.statuses()
    failures = runtime_failures or {}
    if not statuses:
        return PluginHealth(
            PLUGIN_ID,
            PluginHealthState.READY,
            "not-configured",
            "No Google Calendar connections are configured.",
            now,
        )
    failed_ids = {
        status.connection_id
        for status in statuses
        if status.connection_id in failures or status.error_code is not None
    }
    failed_labels = [
        status.connection_label
        for status in statuses
        if status.connection_id in failed_ids
    ]
    starting_labels = [
        status.connection_label
        for status in statuses
        if status.last_success_at is None and status.connection_id not in failed_ids
    ]
    if failed_labels:
        state = PluginHealthState.DEGRADED
        code = "connection-degraded"
        detail = "Google connection needs attention: " + ", ".join(failed_labels)
    elif starting_labels:
        state = (
            PluginHealthState.STARTING
            if len(starting_labels) == len(statuses)
            else PluginHealthState.DEGRADED
        )
        code = "awaiting-first-sync"
        detail = "Waiting for Google refresh: " + ", ".join(starting_labels)
    else:
        state = PluginHealthState.READY
        code = "synchronized"
        detail = f"{len(statuses)} Google connection{'s are' if len(statuses) != 1 else ' is'} current."
    last_success = max(
        (status.last_success_at for status in statuses if status.last_success_at),
        default=None,
    )
    components = tuple(
        _connection_health_component(status, status.connection_id in failures)
        for status in statuses
    )
    return PluginHealth(
        PLUGIN_ID, state, code, detail, now, last_success, components
    )


def _connection_health_component(
    status: GoogleSyncStatus, runtime_failed: bool
) -> PluginHealthComponent:
    if runtime_failed:
        state = PluginHealthState.DEGRADED
        code = "runtime-failure"
        detail = "The most recent scheduled refresh failed."
    elif status.error_code is not None:
        state = PluginHealthState.DEGRADED
        code = status.error_code
        detail = status.error_detail or "The Google connection needs attention."
    elif status.last_success_at is None:
        state = PluginHealthState.STARTING
        code = "awaiting-first-sync"
        detail = "Waiting for the first successful refresh."
    else:
        state = PluginHealthState.READY
        code = "synchronized"
        detail = "The connection is current."
    return PluginHealthComponent(
        status.connection_id,
        status.connection_label,
        state,
        code,
        detail,
        status.last_success_at,
    )


def _timing_label(item: GoogleEntry) -> str:
    if item.timing_kind == "all-day":
        assert item.occurs_on is not None
        if item.ends_before is not None and item.ends_before > item.occurs_on + timedelta(days=1):
            last_day = item.ends_before - timedelta(days=1)
            return f"{item.occurs_on.isoformat()} through {last_day.isoformat()}"
        return item.occurs_on.isoformat()
    if item.timing_kind == "timed":
        return f"{_required(item.starts_at).isoformat()} to {_required(item.ends_at).isoformat()}"
    if item.due_on is not None:
        return f"Due {item.due_on.isoformat()}"
    return "Anytime"


def _safe_error(error: Exception) -> tuple[str, str]:
    if isinstance(error, GoogleApiError):
        return error.code, error.detail
    return "invalid-upstream-resource", "Google returned data that could not be imported."


def _date_text(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _datetime_text(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _optional_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value is not None else None


def _optional_datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value is not None else None


def _required(value: datetime | None) -> datetime:
    assert value is not None
    return value
