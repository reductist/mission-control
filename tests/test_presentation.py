from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

from rich.console import Console

from mission_control.cli import main
from mission_control.plugins import scan_plugin_catalog
from mission_control.presentation import plugin_catalog_table, task_table
from mission_control.tasks import Task


REFERENCE_REGISTRATION = (
    Path(__file__).parents[1] / "plugins" / "reference" / "registration.json"
)


def render_text(renderable, *, width: int = 64) -> str:
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


def test_task_table_is_literal_no_color_and_narrow_width_safe():
    task = Task(
        id="00000000-0000-0000-0000-000000000001",
        title="Review [bold]literal[/bold] terminal output",
        description="",
        state="in-progress",
        blocked=True,
        waiting_on="operator verification",
        review_after="2026-07-30",
        created_at="2026-07-29T00:00:00+00:00",
        updated_at="2026-07-29T00:00:00+00:00",
    )

    output = render_text(task_table((task,)), width=64)

    assert "\x1b[" not in output
    assert "Tasks" in output
    assert "in-progress" in output
    assert "[bold]" in output
    assert "yes" in output
    assert all(len(line) <= 64 for line in output.splitlines())


def test_plugin_catalog_table_renders_immutable_snapshot_without_color():
    catalog = scan_plugin_catalog((REFERENCE_REGISTRATION.parents[1],))

    output = render_text(plugin_catalog_table(catalog), width=72)

    assert "\x1b[" not in output
    assert "Plugin Catalog" in output
    assert "available" in output
    assert "reference" in output
    assert all(len(line) <= 72 for line in output.splitlines())


def test_cli_task_list_keeps_json_default_and_adds_table_format(tmp_path, capsys):
    database = tmp_path / "mission-control.db"
    assert main(["--database", str(database), "task", "add", "Review output"]) == 0
    created = json.loads(capsys.readouterr().out)

    assert main(["--database", str(database), "task", "list"]) == 0
    machine_output = json.loads(capsys.readouterr().out)
    assert machine_output[0]["id"] == created["id"]
    assert machine_output[0]["title"] == "Review output"

    assert main(
        ["--database", str(database), "task", "list", "--format", "table"]
    ) == 0
    human_output = capsys.readouterr().out
    assert "Tasks" in human_output
    assert "Review output" in human_output
    assert "\x1b[" not in human_output


def test_cli_plugin_table_does_not_initialize_database(tmp_path, capsys):
    root = tmp_path / "plugins"
    plugin = root / "reference"
    plugin.mkdir(parents=True)
    registration = plugin / "registration.json"
    registration.write_text(
        REFERENCE_REGISTRATION.read_text(encoding="utf-8"), encoding="utf-8"
    )
    database = tmp_path / "must-not-be-created.db"

    assert main(
        [
            "--database",
            str(database),
            "plugin",
            "list",
            "--root",
            str(root),
            "--format",
            "table",
        ]
    ) == 0

    output = capsys.readouterr().out
    assert "Plugin Catalog" in output
    assert "available" in output
    assert "reference" in output
    assert "\x1b[" not in output
    assert not database.exists()
