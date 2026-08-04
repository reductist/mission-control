"""Core-owned append-only annotations for plugin-owned entities."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final, cast
from uuid import uuid4

from mission_control.agenda import SourceRef
from mission_control.commands import (
    Accepted,
    CommandContext,
    CommandEnvelope,
    CommandError,
    CommandOutcome,
    CommandTargetState,
    Rejected,
    Stale,
    freeze_json_object,
    thaw_json_object,
)
from mission_control.database import Database
from mission_control.plugins import (
    EntityAffordance,
    EntityCapability,
    PluginId,
    StandardEntityCapability,
)

NOTE_BODY_MAX_LENGTH: Final = 16_384
NOTE_ACTOR_MAX_LENGTH: Final = 256
_PLUGIN_ID = re.compile(r"[a-z][a-z0-9-]*")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]*")


class CorruptAnnotationRecordError(ValueError):
    """A persisted note violates the core annotation domain invariants."""

    def __init__(self, note_id: object, detail: str) -> None:
        super().__init__(f"invalid persisted entity note {note_id!r}: {detail}")


class StaleAnnotationRevisionError(ValueError):
    """A note lifecycle command used an obsolete note revision."""

    def __init__(self, current_revision: str) -> None:
        super().__init__("entity note revision is stale")
        self.current_revision = current_revision


class AnnotationStateTransitionError(ValueError):
    """A note is already in the requested visibility state."""


class EntityNoteState(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"


@dataclass(frozen=True, slots=True)
class EntityNote:
    """One immutable observation plus its append-only lifecycle projection."""

    sequence: int
    note_id: str
    target: SourceRef
    body: str
    actor: str
    occurred_at: datetime
    state: EntityNoteState
    revision: str

    def __post_init__(self) -> None:
        if not isinstance(self.sequence, int) or isinstance(self.sequence, bool):
            raise TypeError("note sequence must be an integer")
        if self.sequence < 1:
            raise ValueError("note sequence must be positive")
        _identifier(self.note_id, "note id", maximum=128)
        _target(self.target)
        _normalized_text(self.body, "note body", maximum=NOTE_BODY_MAX_LENGTH)
        _normalized_text(self.actor, "note actor", maximum=NOTE_ACTOR_MAX_LENGTH)
        if not isinstance(self.occurred_at, datetime):
            raise TypeError("note occurred_at must be a datetime")
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("note occurred_at must be timezone-aware")
        if not isinstance(self.state, EntityNoteState):
            raise TypeError("note state must be an EntityNoteState")
        _identifier(self.revision, "note revision", maximum=128)


@dataclass(frozen=True, slots=True)
class EntityNoteStatusEvent:
    """One immutable transition in a note's active/inactive lifecycle."""

    sequence: int
    event_id: str
    note_id: str
    target: SourceRef
    previous_revision: str
    state: EntityNoteState
    actor: str
    occurred_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.sequence, int) or isinstance(self.sequence, bool):
            raise TypeError("note status sequence must be an integer")
        if self.sequence < 1:
            raise ValueError("note status sequence must be positive")
        _identifier(self.event_id, "note status event id", maximum=128)
        _identifier(self.note_id, "note id", maximum=128)
        _target(self.target)
        _identifier(self.previous_revision, "previous note revision", maximum=128)
        if not isinstance(self.state, EntityNoteState):
            raise TypeError("note status state must be an EntityNoteState")
        _normalized_text(self.actor, "note status actor", maximum=NOTE_ACTOR_MAX_LENGTH)
        if not isinstance(self.occurred_at, datetime):
            raise TypeError("note status occurred_at must be a datetime")
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("note status occurred_at must be timezone-aware")


def _identifier(value: object, field: str, *, maximum: int | None = None) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    if (maximum is not None and len(value) > maximum) or _IDENTIFIER.fullmatch(
        value
    ) is None:
        raise ValueError(f"{field} contains unsupported characters")


def _target(value: object) -> None:
    if not isinstance(value, SourceRef):
        raise TypeError("note target must be a source reference")
    if _PLUGIN_ID.fullmatch(value.plugin_id.value) is None:
        raise ValueError("note target plugin id contains unsupported characters")
    _identifier(value.entity_type, "note target entity type")
    _identifier(value.entity_id, "note target entity id")


def _normalized_text(value: object, field: str, *, maximum: int) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    if not value or value != value.strip():
        raise ValueError(f"{field} must be normalized and nonblank")
    if len(value) > maximum:
        raise ValueError(f"{field} must contain at most {maximum} characters")
    return value


class AnnotationRepository:
    """Persist shared notes without taking ownership of plugin entity state."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def add(self, target: SourceRef, body: object, *, actor: object) -> EntityNote:
        _target(target)
        normalized_body = self._required_text(
            body, "note body", maximum=NOTE_BODY_MAX_LENGTH
        )
        normalized_actor = self._required_text(
            actor, "note actor", maximum=NOTE_ACTOR_MAX_LENGTH
        )
        note_id = str(uuid4())
        occurred_at = datetime.now(UTC)
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO entity_notes(
                  note_id, plugin_id, entity_type, entity_id, body, actor, occurred_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    note_id,
                    target.plugin_id.value,
                    target.entity_type,
                    target.entity_id,
                    normalized_body,
                    normalized_actor,
                    occurred_at.isoformat(),
                ),
            )
            sequence = cursor.lastrowid
        assert isinstance(sequence, int)
        return EntityNote(
            sequence,
            note_id,
            target,
            normalized_body,
            normalized_actor,
            occurred_at,
            EntityNoteState.ACTIVE,
            note_id,
        )

    def list(self, target: SourceRef) -> tuple[EntityNote, ...]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                  note.sequence,
                  note.note_id,
                  note.body,
                  note.actor,
                  note.occurred_at,
                  COALESCE(status.state, 'active') AS state,
                  COALESCE(status.event_id, note.note_id) AS revision,
                  status.sequence AS status_sequence,
                  status.event_id AS status_event_id,
                  status.previous_revision AS status_previous_revision,
                  status.actor AS status_actor,
                  status.occurred_at AS status_occurred_at
                FROM entity_notes AS note
                LEFT JOIN entity_note_status_events AS status
                  ON status.sequence = (
                    SELECT latest.sequence
                    FROM entity_note_status_events AS latest
                    WHERE latest.note_id = note.note_id
                    ORDER BY latest.sequence DESC
                    LIMIT 1
                  )
                WHERE note.plugin_id = ?
                  AND note.entity_type = ?
                  AND note.entity_id = ?
                ORDER BY note.sequence
                """,
                (
                    target.plugin_id.value,
                    target.entity_type,
                    target.entity_id,
                ),
            ).fetchall()
        notes: list[EntityNote] = []
        for row in rows:
            try:
                note = self._note_from_row(row, target)
            except (TypeError, ValueError) as error:
                raise CorruptAnnotationRecordError(
                    row["note_id"], str(error)
                ) from error
            notes.append(note)
        return tuple(notes)

    def get(self, note_id: object) -> EntityNote:
        """Return one note with its current lifecycle projection."""

        _identifier(note_id, "note id", maximum=128)
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT
                  note.sequence,
                  note.note_id,
                  note.plugin_id,
                  note.entity_type,
                  note.entity_id,
                  note.body,
                  note.actor,
                  note.occurred_at,
                  COALESCE(status.state, 'active') AS state,
                  COALESCE(status.event_id, note.note_id) AS revision,
                  status.sequence AS status_sequence,
                  status.event_id AS status_event_id,
                  status.previous_revision AS status_previous_revision,
                  status.actor AS status_actor,
                  status.occurred_at AS status_occurred_at
                FROM entity_notes AS note
                LEFT JOIN entity_note_status_events AS status
                  ON status.sequence = (
                    SELECT latest.sequence
                    FROM entity_note_status_events AS latest
                    WHERE latest.note_id = note.note_id
                    ORDER BY latest.sequence DESC
                    LIMIT 1
                  )
                WHERE note.note_id = ?
                """,
                (note_id,),
            ).fetchone()
        if row is None:
            raise KeyError(str(note_id))
        target = SourceRef(
            PluginId(row["plugin_id"]),
            row["entity_type"],
            row["entity_id"],
        )
        try:
            return self._note_from_row(row, target)
        except (TypeError, ValueError) as error:
            raise CorruptAnnotationRecordError(note_id, str(error)) from error

    def transition(
        self,
        note_id: object,
        state: EntityNoteState,
        *,
        actor: object,
        expected_revision: object,
    ) -> EntityNote:
        """Append one lifecycle transition using the note revision as predecessor."""

        _identifier(note_id, "note id", maximum=128)
        if not isinstance(state, EntityNoteState):
            raise TypeError("note state must be an EntityNoteState")
        normalized_actor = self._required_text(
            actor, "note status actor", maximum=NOTE_ACTOR_MAX_LENGTH
        )
        _identifier(expected_revision, "expected note revision", maximum=128)
        event_id = str(uuid4())
        occurred_at = datetime.now(UTC)
        try:
            with self.database.connect() as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO entity_note_status_events(
                      event_id,
                      note_id,
                      previous_revision,
                      state,
                      actor,
                      occurred_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event_id,
                        note_id,
                        expected_revision,
                        state.value,
                        normalized_actor,
                        occurred_at.isoformat(),
                    ),
                )
                sequence = cursor.lastrowid
        except sqlite3.IntegrityError as error:
            self._raise_transition_error(note_id, state, expected_revision, error)
            raise AssertionError("transition error mapper returned") from error
        assert isinstance(sequence, int)
        return self.get(note_id)

    def status_history(self, target: SourceRef) -> tuple[EntityNoteStatusEvent, ...]:
        """Return immutable note lifecycle events for one parent entity."""

        _target(target)
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                  status.sequence,
                  status.event_id,
                  status.note_id,
                  status.previous_revision,
                  status.state,
                  status.actor,
                  status.occurred_at
                FROM entity_note_status_events AS status
                JOIN entity_notes AS note ON note.note_id = status.note_id
                WHERE note.plugin_id = ?
                  AND note.entity_type = ?
                  AND note.entity_id = ?
                ORDER BY status.sequence
                """,
                (
                    target.plugin_id.value,
                    target.entity_type,
                    target.entity_id,
                ),
            ).fetchall()
        events: list[EntityNoteStatusEvent] = []
        for row in rows:
            try:
                event = EntityNoteStatusEvent(
                    row["sequence"],
                    row["event_id"],
                    row["note_id"],
                    target,
                    row["previous_revision"],
                    EntityNoteState(row["state"]),
                    row["actor"],
                    datetime.fromisoformat(row["occurred_at"]),
                )
            except (TypeError, ValueError) as error:
                raise CorruptAnnotationRecordError(
                    row["note_id"], str(error)
                ) from error
            events.append(event)
        return tuple(events)

    @staticmethod
    def _note_from_row(row, target: SourceRef) -> EntityNote:
        note = EntityNote(
            row["sequence"],
            row["note_id"],
            target,
            row["body"],
            row["actor"],
            datetime.fromisoformat(row["occurred_at"]),
            EntityNoteState(row["state"]),
            row["revision"],
        )
        if row["status_sequence"] is not None:
            EntityNoteStatusEvent(
                row["status_sequence"],
                row["status_event_id"],
                row["note_id"],
                target,
                row["status_previous_revision"],
                EntityNoteState(row["state"]),
                row["status_actor"],
                datetime.fromisoformat(row["status_occurred_at"]),
            )
        return note

    def _raise_transition_error(
        self,
        note_id: object,
        requested_state: EntityNoteState,
        expected_revision: object,
        error: Exception,
    ) -> None:
        try:
            current = self.get(note_id)
        except KeyError:
            raise KeyError(str(note_id)) from error
        if current.revision != expected_revision:
            raise StaleAnnotationRevisionError(current.revision) from error
        if current.state is requested_state:
            raise AnnotationStateTransitionError(
                f"entity note is already {requested_state.value}"
            ) from error
        raise error

    @staticmethod
    def _required_text(value: object, field: str, *, maximum: int) -> str:
        if not isinstance(value, str):
            raise TypeError(f"{field} must be a string")
        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{field} must not be blank")
        if len(normalized) > maximum:
            raise ValueError(f"{field} must contain at most {maximum} characters")
        return normalized


class AnnotationCommandHandler:
    """Handle the standardized ``entity.annotate`` capability in core."""

    def __init__(self, repository: AnnotationRepository) -> None:
        self.repository = repository

    def handle(
        self, command: CommandEnvelope, context: CommandContext
    ) -> CommandOutcome:
        arguments = cast(dict[str, object], thaw_json_object(command.arguments))
        if set(arguments) != {"body"}:
            return Rejected(
                command.command_id,
                command.target,
                CommandError(
                    "invalid-arguments",
                    "entity.annotate requires exactly one body argument.",
                ),
            )
        try:
            note = self.repository.add(
                command.target,
                arguments["body"],
                actor=context.actor,
            )
        except (TypeError, ValueError) as error:
            return Rejected(
                command.command_id,
                command.target,
                CommandError("invalid-note", str(error)),
            )

        affordance = _note_affordance(note.state)
        return Accepted(
            command.command_id,
            command.target,
            command.expected_revision,
            freeze_json_object(
                {
                    "note": {
                        "id": note.note_id,
                        "body": note.body,
                        "actor": note.actor,
                        "occurred_at": note.occurred_at.isoformat(),
                        "source": {
                            "plugin_id": "core",
                            "entity_type": "annotation",
                            "entity_id": note.note_id,
                        },
                        "state": note.state.value,
                        "revision": note.revision,
                        "affordances": [
                            {
                                "capability": affordance.capability.value,
                                "command": affordance.command,
                            }
                        ],
                    }
                }
            ),
        )


class AnnotationLifecycleCommandHandler:
    """Own lifecycle commands for core annotation targets."""

    plugin_id: Final = PluginId("core")
    entity_type: Final = "annotation"

    def __init__(self, repository: AnnotationRepository) -> None:
        self.repository = repository

    def command_state(self, target: SourceRef) -> CommandTargetState | None:
        if target.plugin_id != self.plugin_id or target.entity_type != self.entity_type:
            return None
        try:
            note = self.repository.get(target.entity_id)
        except KeyError:
            return None
        return CommandTargetState(note.revision, (_note_affordance(note.state),))

    def handle(
        self, command: CommandEnvelope, context: CommandContext
    ) -> CommandOutcome:
        if (
            command.target.plugin_id != self.plugin_id
            or command.target.entity_type != self.entity_type
        ):
            return Rejected(
                command.command_id,
                command.target,
                CommandError(
                    "unknown-target", "Core annotations own annotation targets only."
                ),
            )
        if command.arguments.values:
            return Rejected(
                command.command_id,
                command.target,
                CommandError(
                    "invalid-arguments",
                    f"{command.command} does not accept arguments.",
                ),
            )
        requested_state = {
            "dismiss": EntityNoteState.INACTIVE,
            "reopen": EntityNoteState.ACTIVE,
        }.get(command.command)
        if requested_state is None:
            return Rejected(
                command.command_id,
                command.target,
                CommandError(
                    "unknown-command",
                    f"Core annotations do not support command {command.command!r}.",
                ),
            )
        try:
            note = self.repository.transition(
                command.target.entity_id,
                requested_state,
                actor=context.actor,
                expected_revision=command.expected_revision,
            )
        except KeyError:
            return Rejected(
                command.command_id,
                command.target,
                CommandError("annotation-not-found", "Annotation not found."),
            )
        except StaleAnnotationRevisionError as error:
            return Stale(
                command.command_id,
                command.target,
                error.current_revision,
                CommandError(
                    "stale-revision",
                    "The note changed after this view was loaded; refresh before retrying.",
                ),
            )
        except AnnotationStateTransitionError as error:
            return Rejected(
                command.command_id,
                command.target,
                CommandError("unavailable-command", str(error)),
            )

        return Accepted(
            command.command_id,
            command.target,
            note.revision,
            freeze_json_object(
                {
                    "annotation": {
                        "id": note.note_id,
                        "state": note.state.value,
                    }
                }
            ),
        )


def _note_affordance(state: EntityNoteState) -> EntityAffordance:
    if state is EntityNoteState.ACTIVE:
        return EntityAffordance(
            EntityCapability(StandardEntityCapability.LIFECYCLE_DISMISS.value),
            "dismiss",
        )
    return EntityAffordance(
        EntityCapability(StandardEntityCapability.LIFECYCLE_REOPEN.value),
        "reopen",
    )
