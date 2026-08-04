from __future__ import annotations

import sqlite3

import pytest

from mission_control.agenda import SourceRef
from mission_control.annotations import (
    AnnotationRepository,
    CorruptAnnotationRecordError,
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
