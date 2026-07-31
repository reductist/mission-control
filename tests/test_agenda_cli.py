from __future__ import annotations

import json
from io import StringIO

from rich.console import Console

from mission_control.agenda import aggregate_agenda, parse_agenda_contribution
from mission_control.cli import main
from mission_control.presentation import agenda_table


def render_text(renderable, *, width: int = 72) -> str:
    buffer = StringIO()
    console = Console(
        file=buffer,
        width=width,
        color_system=None,
        force_terminal=False,
        highlight=False,
    )
    console.print(renderable)
    return buffer.getvalue()


def test_agenda_table_is_readable_without_color_at_narrow_width():
    contribution = parse_agenda_contribution(
        {
            "schema_version": "mission-control.agenda/v1",
            "provider": {"plugin_id": "landscape"},
            "revision": "1",
            "generated_at": "2026-07-29T13:00:00-04:00",
            "entries": [
                {
                    "id": "equipment-access",
                    "source": {
                        "plugin_id": "landscape",
                        "entity_type": "initiative",
                        "entity_id": "equipment-access",
                    },
                    "title": "Improve backyard equipment access",
                    "context": "Backyard",
                    "kind": "initiative",
                    "state": "open",
                },
                {
                    "id": "measure-dropoff",
                    "source": {
                        "plugin_id": "landscape",
                        "entity_type": "task",
                        "entity_id": "measure-dropoff",
                    },
                    "title": "Measure driveway drop-off",
                    "kind": "action",
                    "state": "ready",
                    "timing": {"kind": "anytime"},
                },
            ],
        }
    )

    output = render_text(agenda_table(aggregate_agenda((contribution,))))

    assert "\x1b[" not in output
    assert "Agenda" in output
    assert "initiative" in output
    assert "Measure" in output
    assert "landscape" in output
    assert all(len(line) <= 72 for line in output.splitlines())


def test_cli_projects_core_tasks_to_json_and_table(tmp_path, capsys):
    database = tmp_path / "mission-control.db"

    assert main(["--database", str(database), "task", "add", "Review agenda PR"]) == 0
    task = json.loads(capsys.readouterr().out)
    assert main(
        [
            "--database",
            str(database),
            "task",
            "update",
            task["id"],
            "--state",
            "ready",
            "--review-after",
            "2026-08-02",
        ]
    ) == 0
    capsys.readouterr()

    assert main(["--database", str(database), "agenda", "list"]) == 0
    machine_output = json.loads(capsys.readouterr().out)
    assert machine_output == [
        {
            "context": "Core tasks",
            "id": task["id"],
            "kind": "action",
            "source": {
                "entity_id": task["id"],
                "entity_type": "task",
                "plugin_id": "core",
            },
            "state": "ready",
            "timing": {"due_on": "2026-08-02", "kind": "due-on"},
            "title": "Review agenda PR",
        }
    ]

    assert main(
        ["--database", str(database), "agenda", "list", "--format", "table"]
    ) == 0
    human_output = capsys.readouterr().out
    assert "Agenda" in human_output
    assert "Review agenda PR" in human_output
    assert "core" in human_output
    assert "\x1b[" not in human_output


def test_done_core_tasks_are_not_projected(tmp_path, capsys):
    database = tmp_path / "mission-control.db"
    assert main(["--database", str(database), "task", "add", "Finished work"]) == 0
    task = json.loads(capsys.readouterr().out)
    assert main(
        [
            "--database",
            str(database),
            "task",
            "update",
            task["id"],
            "--state",
            "done",
        ]
    ) == 0
    capsys.readouterr()

    assert main(["--database", str(database), "agenda", "list"]) == 0
    assert json.loads(capsys.readouterr().out) == []


def test_cli_includes_explicit_landscape_provider(tmp_path, capsys):
    database = tmp_path / "mission-control.db"

    assert main(
        [
            "--database",
            str(database),
            "agenda",
            "list",
            "--plugin",
            "landscape",
        ]
    ) == 0
    output = json.loads(capsys.readouterr().out)

    assert {entry["source"]["plugin_id"] for entry in output} == {"landscape"}
    assert {entry["id"] for entry in output} >= {
        "equipment-access",
        "measure-access-route",
        "compare-access-concepts",
    }
