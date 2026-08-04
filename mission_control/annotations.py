"""Core-owned append-only annotations for plugin-owned entities."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, cast
from uuid import uuid4

from mission_control.agenda import SourceRef
from mission_control.commands import (
    Accepted,
    CommandContext,
    CommandEnvelope,
    CommandError,
    CommandOutcome,
    Rejected,
    freeze_json_object,
    thaw_json_object,
)
from mission_control.database import Database

NOTE_BODY_MAX_LENGTH: Final = 16_384
NOTE_ACTOR_MAX_LENGTH: Final = 256
_PLUGIN_ID = re.compile(r"[a-z][a-z0-9-]*")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]*")


class CorruptAnnotationRecordError(ValueError):
    """A persisted note violates the core annotation domain invariants."""

    def __init__(self, note_id: object, detail: str) -> None:
        super().__init__(f"invalid persisted entity note {note_id!r}: {detail}")


@dataclass(frozen=True, slots=True)
class EntityNote:
    """One immutable textual observation associated with an entity."""

    sequence: int
    note_id: str
    target: SourceRef
    body: str
    actor: str
    occurred_at: datetime

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


def _identifier(value: object, field: str, *, maximum: int | None = None) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    if (
        maximum is not None and len(value) > maximum
    ) or _IDENTIFIER.fullmatch(value) is None:
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
        )

    def list(self, target: SourceRef) -> tuple[EntityNote, ...]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT sequence, note_id, body, actor, occurred_at
                FROM entity_notes
                WHERE plugin_id = ? AND entity_type = ? AND entity_id = ?
                ORDER BY sequence
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
                note = EntityNote(
                    row["sequence"],
                    row["note_id"],
                    target,
                    row["body"],
                    row["actor"],
                    datetime.fromisoformat(row["occurred_at"]),
                )
            except (TypeError, ValueError) as error:
                raise CorruptAnnotationRecordError(
                    row["note_id"], str(error)
                ) from error
            notes.append(note)
        return tuple(notes)

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
                    }
                }
            ),
        )
