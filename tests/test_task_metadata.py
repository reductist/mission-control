from datetime import UTC, datetime
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import json
from importlib.resources import files

import pytest

from mission_control.agenda import agenda_entry_to_dict, project_core_tasks
from mission_control.database import Database
from mission_control.migrations import MigrationRunner
from mission_control.task_metadata import TASK_TAG_CATALOG, normalize_deadline, normalize_tags
from mission_control.tasks import StaleTaskRevisionError, TaskRepository


def test_concurrent_edits_accept_only_one_matching_revision(tmp_path):
    repo = repository(tmp_path)
    task = repo.create("Concurrent synthetic task")
    barrier = Barrier(2)

    def edit(tag):
        barrier.wait(timeout=5)
        try:
            repo.update(task.id, tags=[tag], expected_revision=task.updated_at)
            return "accepted"
        except StaleTaskRevisionError:
            return "stale"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(edit, ["yard", "maintenance"]))
    assert sorted(results) == ["accepted", "stale"]
    assert len(repo.history(task.id)) == 2


def repository(tmp_path):
    database = Database(tmp_path / "tasks.db")
    MigrationRunner(database).apply()
    return TaskRepository(database)


def test_deadline_tags_persist_clear_and_project_without_review_date(tmp_path):
    repo = repository(tmp_path)
    deadline = {"kind": "due-on", "due_on": "2026-10-15", "time_zone": "Europe/Zurich"}
    task = repo.create("Synthetic social task", deadline=deadline, tags=["yard", "maintenance"])
    assert repo.get(task.id).deadline == deadline
    assert repo.get(task.id).tags == ["yard", "maintenance"]
    entry = project_core_tasks([task], generated_at=datetime.now(UTC)).entries[0]
    assert agenda_entry_to_dict(entry)["timing"] == {"kind": "due-on", "due_on": "2026-10-15"}
    timed = {"kind": "due-at", "due_at": "2026-10-25T02:30:00+01:00", "time_zone": "Europe/Zurich"}
    task = repo.update(task.id, deadline=timed, tags=["personal-social"], expected_revision=task.updated_at)
    assert repo.get(task.id).deadline == timed
    entry = project_core_tasks([task], generated_at=datetime.now(UTC)).entries[0]
    assert agenda_entry_to_dict(entry)["timing"]["due_at"] == timed["due_at"]
    task = repo.update(task.id, deadline=None, tags=[], review_after="2026-10-15")
    assert task.deadline is None and task.tags == []
    entry = project_core_tasks([task], generated_at=datetime.now(UTC)).entries[0]
    assert agenda_entry_to_dict(entry)["timing"] == {"kind": "anytime"}
    assert repo.history(task.id)[-1]["payload"]["changes"]["deadline"]["to"] is None


@pytest.mark.parametrize("instant", ["2026-10-25T02:30:00+02:00", "2026-10-25T02:30:00+01:00"])
def test_dst_fold_offsets_both_roundtrip(instant):
    deadline = {"kind": "due-at", "due_at": instant, "time_zone": "Europe/Zurich"}
    assert normalize_deadline(deadline) == deadline


@pytest.mark.parametrize("deadline", [
    {"kind": "due-at", "due_at": "2026-03-29T02:30:00+01:00", "time_zone": "Europe/Zurich"},
    {"kind": "due-at", "due_at": "2026-07-01T12:00:00+01:00", "time_zone": "Europe/Zurich"},
    {"kind": "due-at", "due_at": "2026-07-01T12:00:00", "time_zone": "Europe/Zurich"},
    {"kind": "due-at", "due_at": "2026-07-01 12:00:00+02:00", "time_zone": "Europe/Zurich"},
    {"kind": "due-on", "due_on": "2026-02-30", "time_zone": "UTC"},
    {"kind": "due-on", "due_on": "20261015", "time_zone": "UTC"},
    {"kind": "due-on", "due_on": "2026-10-15", "time_zone": "Unknown/Zone"},
    {"kind": "due-on", "due_on": "2026-10-15", "time_zone": "UTC", "extra": True},
])
def test_invalid_deadlines_rejected_without_write(tmp_path, deadline):
    repo = repository(tmp_path)
    task = repo.create("Keep existing data")
    with pytest.raises((TypeError, ValueError)):
        repo.update(task.id, deadline=deadline)
    assert repo.get(task.id) == task
    assert len(repo.history(task.id)) == 1


@pytest.mark.parametrize("tags", [["yard", "yard"], ["unknown"], "yard", [None]])
def test_invalid_tags(tags):
    with pytest.raises((TypeError, ValueError)):
        normalize_tags(tags)


def test_task_schema_catalog_ids_agree():
    schema = json.loads(files("mission_control").joinpath("schemas", "core-task-request.schema.json").read_text())
    assert schema["$defs"]["tags"]["items"]["enum"] == [tag["id"] for tag in TASK_TAG_CATALOG]


def test_upgrade_preserves_legacy_tasks_and_events(tmp_path):
    database = Database(tmp_path / "legacy.db")
    root = files("mission_control").joinpath("migrations")
    with database.connect() as connection:
        for migration in sorted(root.iterdir(), key=lambda path: path.name):
            if migration.name.startswith("0005"):
                continue
            connection.executescript(migration.read_text())
        connection.execute("INSERT INTO tasks(id,title,description,state,blocked,review_after,created_at,updated_at) VALUES ('legacy','Existing task','','ready',0,'2026-10-15','old','old')")
        connection.execute("INSERT INTO task_events(event_id,task_id,event_type,payload_json,occurred_at) VALUES ('old-event','legacy','task.created','{}','old')")
    assert MigrationRunner(database).apply() == [5]
    task = TaskRepository(database).get("legacy")
    assert task.title == "Existing task" and task.review_after == "2026-10-15"
    assert task.deadline is None and task.tags == []
    assert TaskRepository(database).history("legacy")[0]["event_id"] == "old-event"
