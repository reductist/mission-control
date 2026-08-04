from __future__ import annotations

import json
import sqlite3
from importlib.resources import files

from mission_control.cli import main
from mission_control.database import Database
from mission_control.migrations import MigrationRunner
from mission_control.tasks import TaskRepository


def test_migrations_are_idempotent(tmp_path):
    database = Database(tmp_path / "mission-control.db")
    runner = MigrationRunner(database)

    assert runner.apply() == [1, 2, 3]
    assert runner.apply() == []

    with database.connect() as connection:
        assert [
            row[0]
            for row in connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            ).fetchall()
        ] == [1, 2, 3]


def test_task_create_writes_projection_and_event(tmp_path):
    database = Database(tmp_path / "mission-control.db")
    MigrationRunner(database).apply()
    repository = TaskRepository(database)

    task = repository.create("Write the next right thing", "Keep the slice small")

    assert task.state == "backlog"
    assert repository.list() == [task]
    history = repository.history(task.id)
    assert history[0]["event_type"] == "task.created"
    assert history[0]["payload"]["title"] == task.title


def test_entity_note_migration_upgrades_existing_core_state_without_loss(tmp_path):
    database = Database(tmp_path / "mission-control.db")
    initial = files("mission_control").joinpath("migrations", "0001_initial.sql")
    with database.connect() as connection:
        connection.executescript(initial.read_text(encoding="utf-8"))
    task = TaskRepository(database).create("Preserve this task")

    assert MigrationRunner(database).apply() == [2, 3]
    assert TaskRepository(database).get(task.id) == task
    with database.connect() as connection:
        assert (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'entity_notes'"
            ).fetchone()
            is not None
        )
        assert (
            connection.execute(
                "SELECT 1 FROM sqlite_master "
                "WHERE type = 'table' AND name = 'entity_note_status_events'"
            ).fetchone()
            is not None
        )


def test_note_status_migration_preserves_schema_v2_notes(tmp_path) -> None:
    database = Database(tmp_path / "mission-control.db")
    migration_root = files("mission_control").joinpath("migrations")
    with database.connect() as connection:
        for name in ("0001_initial.sql", "0002_entity_notes.sql"):
            connection.executescript(
                migration_root.joinpath(name).read_text(encoding="utf-8")
            )
        connection.execute(
            """
            INSERT INTO entity_notes(
              note_id, plugin_id, entity_type, entity_id, body, actor, occurred_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "note-before-status-migration",
                "landscape",
                "action",
                "measure-access-route",
                "Preserve this note",
                "operator",
                "2026-08-04T15:58:00+00:00",
            ),
        )

    assert MigrationRunner(database).apply() == [3]
    with database.connect() as connection:
        note = connection.execute(
            "SELECT body, actor, occurred_at FROM entity_notes WHERE note_id = ?",
            ("note-before-status-migration",),
        ).fetchone()
        status_count = connection.execute(
            "SELECT count(*) FROM entity_note_status_events"
        ).fetchone()[0]
    assert tuple(note) == (
        "Preserve this note",
        "operator",
        "2026-08-04T15:58:00+00:00",
    )
    assert status_count == 0


def test_task_events_are_immutable(tmp_path):
    database = Database(tmp_path / "mission-control.db")
    MigrationRunner(database).apply()
    task = TaskRepository(database).create("Protect history")

    with database.connect() as connection:
        try:
            connection.execute("DELETE FROM task_events WHERE task_id = ?", (task.id,))
        except sqlite3.IntegrityError as error:
            assert "immutable" in str(error)
        else:
            raise AssertionError("immutable event was deleted")


def test_cli_init_add_and_list(tmp_path, capsys):
    database_path = tmp_path / "mission-control.db"

    assert main(["--database", str(database_path), "init"]) == 0
    capsys.readouterr()

    assert main(["--database", str(database_path), "task", "add", "First task"]) == 0
    created = json.loads(capsys.readouterr().out)

    assert main(["--database", str(database_path), "task", "list"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert listed == [created]
