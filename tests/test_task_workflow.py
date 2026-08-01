from __future__ import annotations

import json

import pytest

from mission_control.cli import main
from mission_control.database import Database
from mission_control.migrations import MigrationRunner
from mission_control.render import render_tasks_markdown
from mission_control.tasks import StaleTaskRevisionError, TaskRepository


def repository_for(tmp_path) -> TaskRepository:
    database = Database(tmp_path / "mission-control.db")
    MigrationRunner(database).apply()
    return TaskRepository(database)


def test_task_update_writes_projection_and_event(tmp_path):
    repository = repository_for(tmp_path)
    task = repository.create("Prepare review")

    updated = repository.update(
        task.id,
        description="Exercise the complete task loop",
        state="in-progress",
        blocked=True,
        waiting_on="CI",
        review_after="2026-07-29",
    )

    assert updated.description == "Exercise the complete task loop"
    assert updated.state == "in-progress"
    assert updated.blocked is True
    assert updated.waiting_on == "CI"
    assert updated.review_after == "2026-07-29"
    assert repository.get(task.id) == updated

    history = repository.history(task.id)
    assert [event["event_type"] for event in history] == ["task.created", "task.updated"]
    assert history[1]["payload"]["changes"]["state"] == {
        "from": "backlog",
        "to": "in-progress",
    }
    assert history[1]["payload"]["changes"]["blocked"] == {
        "from": False,
        "to": True,
    }


def test_invalid_update_leaves_projection_and_history_unchanged(tmp_path):
    repository = repository_for(tmp_path)
    task = repository.create("Protect transaction boundaries")

    with pytest.raises(ValueError, match="unsupported task state"):
        repository.update(task.id, state="cancelled")

    assert repository.get(task.id) == task
    assert len(repository.history(task.id)) == 1

    with pytest.raises(ValueError, match="must not be empty"):
        repository.update(task.id, title="   ")

    assert repository.get(task.id) == task
    assert len(repository.history(task.id)) == 1


def test_noop_update_does_not_append_event(tmp_path):
    repository = repository_for(tmp_path)
    task = repository.create("Avoid noisy history")

    assert repository.update(task.id, title=task.title) == task
    assert len(repository.history(task.id)) == 1


def test_expected_revision_rejects_stale_update_without_appending_event(tmp_path):
    repository = repository_for(tmp_path)
    task = repository.create("Protect a viewed revision")
    updated = repository.update(task.id, state="ready", expected_revision=task.updated_at)

    with pytest.raises(StaleTaskRevisionError) as stale:
        repository.update(task.id, state="done", expected_revision=task.updated_at)

    assert stale.value.current_revision == updated.updated_at
    assert repository.get(task.id) == updated
    assert len(repository.history(task.id)) == 2


def test_markdown_render_is_deterministic(tmp_path):
    repository = repository_for(tmp_path)
    backlog = repository.create("First task", "Keep it small")
    done = repository.create("Finished task")
    repository.update(done.id, state="done")

    document = render_tasks_markdown(repository.list())

    assert document == (
        "# Mission Control Tasks\n\n"
        "## Backlog\n\n"
        f"- [ ] First task (`{backlog.id}`)\n"
        "  - Description: Keep it small\n\n"
        "## Done\n\n"
        f"- [x] Finished task (`{done.id}`)\n"
    )


def test_cli_update_history_and_markdown(tmp_path, capsys):
    database_path = tmp_path / "mission-control.db"

    assert main(["--database", str(database_path), "task", "add", "Review workflow"]) == 0
    created = json.loads(capsys.readouterr().out)

    assert main(
        [
            "--database",
            str(database_path),
            "task",
            "update",
            created["id"],
            "--state",
            "ready",
            "--blocked",
            "--waiting-on",
            "reviewer",
        ]
    ) == 0
    updated = json.loads(capsys.readouterr().out)
    assert updated["state"] == "ready"
    assert updated["blocked"] is True

    assert main(["--database", str(database_path), "task", "history", created["id"]]) == 0
    history = json.loads(capsys.readouterr().out)
    assert [event["event_type"] for event in history] == ["task.created", "task.updated"]

    assert main(["--database", str(database_path), "render", "markdown"]) == 0
    markdown = capsys.readouterr().out
    assert "## Ready" in markdown
    assert "- [ ] Review workflow" in markdown
    assert "Waiting on: reviewer" in markdown
