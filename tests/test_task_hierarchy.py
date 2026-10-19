from __future__ import annotations

from datetime import UTC, datetime
from importlib.resources import files

import pytest

from mission_control.agenda import agenda_to_list, aggregate_agenda, project_core_tasks
from mission_control.closed_items import project_core_closed_items
from mission_control.database import Database
from mission_control.migrations import MigrationRunner
from mission_control.server import ApiError, MissionControlApplication
from mission_control.tasks import (
    StaleTaskRevisionError,
    TaskRepository,
    UnfinishedChildrenError,
)


def repository_for(tmp_path) -> TaskRepository:
    database = Database(tmp_path / "mission-control.db")
    MigrationRunner(database).apply()
    return TaskRepository(database)


def test_two_level_hierarchy_rejects_invalid_parent_cycles_and_depth(tmp_path):
    repository = repository_for(tmp_path)
    parent = repository.create("Synthetic parent")
    child = repository.create("Synthetic child", parent_id=parent.id)

    assert child.parent_id == parent.id
    with pytest.raises(ValueError, match="does not exist"):
        repository.create("Orphan", parent_id="missing")
    with pytest.raises(ValueError, match="own parent"):
        repository.update(parent.id, parent_id=parent.id)
    with pytest.raises(ValueError, match="two levels"):
        repository.create("Grandchild", parent_id=child.id)
    with pytest.raises(ValueError, match="parent task cannot be attached"):
        repository.update(parent.id, parent_id=repository.create("Other").id)


def test_move_and_reorder_are_presentation_only(tmp_path):
    repository = repository_for(tmp_path)
    first_parent = repository.create("First parent")
    second_parent = repository.create("Second parent")
    first = repository.create("First", parent_id=first_parent.id)
    second = repository.create("Second", parent_id=first_parent.id)

    repository.update(second.id, sibling_order=0)
    children = [task for task in repository.list() if task.parent_id == first_parent.id]
    assert [task.id for task in children] == [second.id, first.id]
    assert all(task.waiting_on is None and not task.blocked for task in children)

    moved = repository.update(first.id, parent_id=second_parent.id)
    assert moved.parent_id == second_parent.id
    assert moved.sibling_order == 0


def test_reorder_advances_shifted_sibling_revisions_for_conflict_detection(tmp_path):
    repository = repository_for(tmp_path)
    parent = repository.create("Parent")
    first = repository.create("First", parent_id=parent.id)
    second = repository.create("Second", parent_id=parent.id)
    third = repository.create("Third", parent_id=parent.id)
    viewed_second_revision = second.updated_at

    repository.update(third.id, sibling_order=0, expected_revision=third.updated_at)
    assert repository.get(second.id).updated_at != viewed_second_revision
    with pytest.raises(StaleTaskRevisionError):
        repository.update(
            second.id,
            sibling_order=0,
            expected_revision=viewed_second_revision,
        )
    assert repository.history(first.id)[-1]["event_type"] == "task.reordered"


def test_parent_progress_keeps_canceled_distinct_and_completion_explicit(tmp_path):
    repository = repository_for(tmp_path)
    parent = repository.create("Release parent")
    done = repository.create("Done child", parent_id=parent.id)
    canceled = repository.create("Canceled child", parent_id=parent.id)
    open_child = repository.create("Open child", parent_id=parent.id)
    repository.update(done.id, state="done")
    repository.update(canceled.id, state="canceled")

    assert repository.progress(parent.id) == {
        "total": 3,
        "done": 1,
        "canceled": 1,
        "unfinished": 1,
        "closed": 2,
        "percent": 67,
        "ready_to_close": False,
    }
    with pytest.raises(UnfinishedChildrenError) as error:
        repository.update(parent.id, state="done")
    assert error.value.child_ids == (open_child.id,)
    assert repository.get(parent.id).state == "backlog"

    repository.update(open_child.id, state="done")
    assert repository.progress(parent.id)["ready_to_close"] is True
    assert repository.get(parent.id).state == "backlog"
    repository.update(parent.id, state="done")
    assert repository.progress(parent.id)["ready_to_close"] is False


def test_dates_and_tags_do_not_inherit_and_child_schedule_keeps_parent_context(tmp_path):
    repository = repository_for(tmp_path)
    parent = repository.create(
        "Dated parent",
        deadline={"kind": "due-on", "due_on": "2026-11-01", "time_zone": "UTC"},
        tags=["Parent tag"],
    )
    child = repository.create(
        "Dated child",
        parent_id=parent.id,
        deadline={"kind": "due-on", "due_on": "2026-10-20", "time_zone": "UTC"},
        tags=["Child tag"],
    )
    plain = repository.create("Plain child", parent_id=parent.id)

    assert plain.deadline is None and plain.tags == []
    contribution = project_core_tasks(repository.list(), generated_at=datetime.now(UTC))
    entries = {item["id"]: item for item in agenda_to_list(aggregate_agenda([contribution]))}
    assert entries[parent.id]["timing"]["due_on"] == "2026-11-01"
    assert entries[child.id]["timing"]["due_on"] == "2026-10-20"
    assert "Dated parent" in entries[child.id]["context"]
    assert "Parent: Dated parent" in entries[child.id]["detail"]
    assert entries[plain.id]["timing"] == {"kind": "anytime"}


def test_custom_tags_normalize_and_prevent_accidental_duplicates(tmp_path):
    repository = repository_for(tmp_path)
    task = repository.create("Tagged", tags=["  Custom   Label  ", "yard"])
    assert task.tags == ["Custom Label", "yard"]
    with pytest.raises(ValueError, match="ignoring case and whitespace"):
        repository.update(task.id, tags=["Mold", " mold "])

    application = MissionControlApplication(repository.database)
    catalog = application.dashboard()["task_tag_catalog"]
    assert any(item["id"] == "Custom Label" for item in catalog)


def test_tags_reuse_catalog_and_first_custom_label_identity(tmp_path):
    repository = repository_for(tmp_path)
    first = repository.create("First", tags=["Ｍｏｌｄ Review", "YARD"])
    second = repository.create("Second", tags=["mold review", "Yard"])
    assert first.tags == ["Mold Review", "yard"]
    assert second.tags == ["Mold Review", "yard"]

    application = MissionControlApplication(repository.database)
    catalog = application.dashboard()["task_tag_catalog"]
    assert [item["id"] for item in catalog].count("Mold Review") == 1
    assert not any(item["id"] in {"YARD", "Yard"} for item in catalog)


def test_parent_completion_api_surfaces_unfinished_children(tmp_path):
    application = MissionControlApplication(Database(tmp_path / "api.db"))
    parent = application.create_task({"title": "Parent"})
    application.create_task({"title": "Child", "parent_id": parent["id"]})

    with pytest.raises(ApiError) as error:
        application.update_task(parent["id"], {"state": "done"})
    assert error.value.status.value == 409
    assert error.value.code == "unfinished-children"


def test_hierarchy_migration_preserves_ids_metadata_events_and_foreign_keys(tmp_path):
    database = Database(tmp_path / "upgrade.db")
    migration_root = files("mission_control").joinpath("migrations")
    with database.connect() as connection:
        for name in (
            "0001_initial.sql",
            "0002_entity_notes.sql",
            "0003_entity_note_status_events.sql",
            "0004_plugin_schema_migrations.sql",
            "0005_task_metadata.sql",
        ):
            connection.executescript(migration_root.joinpath(name).read_text())
        connection.execute(
            "INSERT INTO tasks(id,title,description,state,blocked,created_at,updated_at,deadline_json,tags_json) "
            "VALUES ('keep-id','Keep title','Keep note','ready',0,'created','updated',?,?)",
            ('{"kind":"due-on","due_on":"2026-10-20","time_zone":"UTC"}', '["yard"]'),
        )
        connection.execute(
            "INSERT INTO task_events(event_id,task_id,event_type,payload_json,occurred_at) "
            "VALUES ('keep-event','keep-id','task.created','{}','created')"
        )

    assert MigrationRunner(database).apply() == [6]
    task = TaskRepository(database).get("keep-id")
    assert (task.title, task.description, task.state, task.tags) == (
        "Keep title",
        "Keep note",
        "ready",
        ["yard"],
    )
    assert TaskRepository(database).history("keep-id")[0]["event_id"] == "keep-event"
    with database.connect() as connection:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_canceled_items_are_closed_but_not_done(tmp_path):
    repository = repository_for(tmp_path)
    task = repository.create("Canceled")
    repository.update(task.id, state="canceled")
    projection = project_core_closed_items(
        repository.list(), generated_at=datetime.now(UTC)
    )
    assert len(projection.items) == 1
    assert projection.items[0].state == "canceled"
