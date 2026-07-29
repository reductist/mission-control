from __future__ import annotations

import json
import sqlite3

from mission_control.cli import main
from mission_control.database import Database
from mission_control.migrations import MigrationRunner
from mission_control.tasks import TaskRepository


def test_migrations_are_idempotent(tmp_path):
    database = Database(tmp_path / "mission-control.db")
    runner = MigrationRunner(database)

    assert runner.apply() == [1]
    assert runner.apply() == []

    with database.connect() as connection:
        assert connection.execute("SELECT version FROM schema_migrations").fetchall()[0][0] == 1


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
