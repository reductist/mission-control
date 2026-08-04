from __future__ import annotations

import sqlite3

import pytest

from mission_control.agenda import SourceRef
from mission_control.annotations import (
    AnnotationStateTransitionError,
    AnnotationRepository,
    CorruptAnnotationRecordError,
    EntityNoteState,
    StaleAnnotationRevisionError,
)
from mission_control.database import Database
from mission_control.migrations import MigrationRunner
from mission_control.plugins import PluginId


def target(entity_id: str = "measure-access-route") -> SourceRef:
    return SourceRef(PluginId("landscape"), "action", entity_id)


def repository(tmp_path) -> AnnotationRepository:
    database = Database(tmp_path / "mission-control.db")
    MigrationRunner(database).apply()
    return AnnotationRepository(database)


def test_notes_are_normalized_scoped_and_persisted(tmp_path) -> None:
    first = repository(tmp_path)
    note = first.add(
        target(),
        "  Vertical drop: 42 inches.  ",
        actor="local-write-token",
    )

    assert note.body == "Vertical drop: 42 inches."
    assert first.list(target()) == (note,)
    assert first.list(target("define-equipment-envelope")) == ()

    restarted = AnnotationRepository(Database(tmp_path / "mission-control.db"))
    assert restarted.list(target()) == (note,)


@pytest.mark.parametrize("body", [None, "", "   ", "x" * 16_385])
def test_invalid_note_body_is_rejected(tmp_path, body: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        repository(tmp_path).add(target(), body, actor="local-write-token")


def test_note_rows_are_immutable_at_the_database_boundary(tmp_path) -> None:
    annotations = repository(tmp_path)
    note = annotations.add(target(), "Landing is 9 feet wide.", actor="operator")

    with (
        Database(tmp_path / "mission-control.db").connect() as connection,
        pytest.raises(sqlite3.IntegrityError, match="immutable"),
    ):
        connection.execute(
            "UPDATE entity_notes SET body = ? WHERE note_id = ?",
            ("changed", note.note_id),
        )


def test_note_visibility_transitions_are_append_only_and_reversible(tmp_path) -> None:
    annotations = repository(tmp_path)
    note = annotations.add(target(), "Landing is 9 feet wide.", actor="operator")

    inactive = annotations.transition(
        note.note_id,
        EntityNoteState.INACTIVE,
        actor="operator",
        expected_revision=note.revision,
    )
    assert inactive.state is EntityNoteState.INACTIVE
    assert inactive.revision != note.revision
    assert inactive.body == note.body

    restored = annotations.transition(
        note.note_id,
        EntityNoteState.ACTIVE,
        actor="operator",
        expected_revision=inactive.revision,
    )
    assert restored.state is EntityNoteState.ACTIVE
    assert restored.revision not in {note.revision, inactive.revision}
    assert [event.state for event in annotations.status_history(target())] == [
        EntityNoteState.INACTIVE,
        EntityNoteState.ACTIVE,
    ]

    with Database(tmp_path / "mission-control.db").connect() as connection:
        persisted = connection.execute(
            "SELECT body, actor, occurred_at FROM entity_notes WHERE note_id = ?",
            (note.note_id,),
        ).fetchone()
    assert tuple(persisted) == (note.body, note.actor, note.occurred_at.isoformat())


def test_note_visibility_rejects_stale_and_repeated_transitions(tmp_path) -> None:
    annotations = repository(tmp_path)
    note = annotations.add(target(), "Record once.", actor="operator")
    inactive = annotations.transition(
        note.note_id,
        EntityNoteState.INACTIVE,
        actor="operator",
        expected_revision=note.revision,
    )

    with pytest.raises(StaleAnnotationRevisionError) as stale:
        annotations.transition(
            note.note_id,
            EntityNoteState.ACTIVE,
            actor="operator",
            expected_revision=note.revision,
        )
    assert stale.value.current_revision == inactive.revision

    with pytest.raises(AnnotationStateTransitionError, match="already inactive"):
        annotations.transition(
            note.note_id,
            EntityNoteState.INACTIVE,
            actor="operator",
            expected_revision=inactive.revision,
        )


def test_note_status_rows_are_immutable_at_the_database_boundary(tmp_path) -> None:
    annotations = repository(tmp_path)
    note = annotations.add(target(), "Keep the audit trail.", actor="operator")
    inactive = annotations.transition(
        note.note_id,
        EntityNoteState.INACTIVE,
        actor="operator",
        expected_revision=note.revision,
    )

    with (
        Database(tmp_path / "mission-control.db").connect() as connection,
        pytest.raises(sqlite3.IntegrityError, match="immutable"),
    ):
        connection.execute(
            "DELETE FROM entity_note_status_events WHERE event_id = ?",
            (inactive.revision,),
        )


def test_corrupt_persisted_note_fails_during_rehydration(tmp_path) -> None:
    annotations = repository(tmp_path)
    with Database(tmp_path / "mission-control.db").connect() as connection:
        connection.execute(
            """
            INSERT INTO entity_notes(
              note_id, plugin_id, entity_type, entity_id, body, actor, occurred_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "corrupt-note",
                "landscape",
                "action",
                "measure-access-route",
                "Looks valid",
                "operator",
                "not-a-timestamp",
            ),
        )

    with pytest.raises(CorruptAnnotationRecordError, match="corrupt-note"):
        annotations.list(target())


def test_corrupt_persisted_note_status_fails_during_rehydration(tmp_path) -> None:
    annotations = repository(tmp_path)
    note = annotations.add(target(), "Valid note", actor="operator")
    with Database(tmp_path / "mission-control.db").connect() as connection:
        connection.execute(
            """
            INSERT INTO entity_note_status_events(
              event_id, note_id, previous_revision, state, actor, occurred_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "corrupt-status",
                note.note_id,
                note.revision,
                "inactive",
                "operator",
                "not-a-timestamp",
            ),
        )

    with pytest.raises(CorruptAnnotationRecordError, match=note.note_id):
        annotations.status_history(target())
    with pytest.raises(CorruptAnnotationRecordError, match=note.note_id):
        annotations.get(note.note_id)
