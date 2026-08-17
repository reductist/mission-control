"""Mission Control administrative CLI."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console

from mission_control import __version__
from mission_control.agenda import aggregate_agenda, agenda_to_list, project_core_tasks
from mission_control.application_config import (
    ApplicationConfigError,
    load_application_config,
    prepare_application_plugins,
)
from mission_control.database import Database
from mission_control.migrations import MigrationRunner
from mission_control.plugin_lifecycle import (
    PluginLifecycleError,
    activate_agenda_plugins,
)
from mission_control.plugins import (
    PluginDiscoveryError,
    PluginRegistrationError,
    catalog_to_list,
    load_registration,
    registration_to_dict,
    scan_plugin_catalog,
)
from mission_control.presentation import agenda_table, plugin_catalog_table, task_table
from mission_control.render import render_tasks_markdown
from mission_control.tasks import TASK_STATES, TaskRepository

OUTPUT_FORMATS = ("json", "table")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mcctl")
    parser.add_argument(
        "--config",
        metavar="PATH",
        help="read the canonical TOML application configuration",
    )
    parser.add_argument(
        "--config-dir",
        action="append",
        default=[],
        metavar="PATH",
        help="merge lexically ordered *.toml fragments from PATH; may be repeated",
    )
    parser.add_argument(
        "--database",
        default=argparse.SUPPRESS,
        help="override the configured SQLite database path",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    subcommands.add_parser("version", help="print the installed version")
    subcommands.add_parser("init", help="initialize or migrate the database")
    subcommands.add_parser("doctor", help="check database readiness")

    config = subcommands.add_parser("config", help="inspect application configuration")
    config_commands = config.add_subparsers(dest="config_command", required=True)
    for name, help_text in (
        ("validate", "validate configuration and enabled plugin preflight"),
        ("effective", "render the redacted effective configuration"),
    ):
        command = config_commands.add_parser(name, help=help_text)
        command.add_argument("path", help="base TOML configuration path")
        command.add_argument(
            "--fragment-dir",
            action="append",
            default=[],
            metavar="PATH",
            help="merge lexically ordered *.toml fragments from PATH",
        )
    explain = config_commands.add_parser(
        "explain", help="show a value and the layers that assigned it"
    )
    explain.add_argument("path", help="base TOML configuration path")
    explain.add_argument("pointer", help="effective value as an RFC 6901 JSON Pointer")
    explain.add_argument(
        "--fragment-dir",
        action="append",
        default=[],
        metavar="PATH",
        help="merge lexically ordered *.toml fragments from PATH",
    )

    task = subcommands.add_parser("task", help="manage tasks")
    task_commands = task.add_subparsers(dest="task_command", required=True)

    add = task_commands.add_parser("add", help="create a task")
    add.add_argument("title")
    add.add_argument("--description", default="")

    update = task_commands.add_parser("update", help="update a task")
    update.add_argument("task_id")
    update.add_argument("--title", default=argparse.SUPPRESS)
    update.add_argument("--description", default=argparse.SUPPRESS)
    update.add_argument("--state", choices=TASK_STATES, default=argparse.SUPPRESS)

    blocked = update.add_mutually_exclusive_group()
    blocked.add_argument(
        "--blocked",
        dest="blocked",
        action="store_const",
        const=True,
        default=argparse.SUPPRESS,
    )
    blocked.add_argument(
        "--unblocked",
        dest="blocked",
        action="store_const",
        const=False,
        default=argparse.SUPPRESS,
    )

    waiting_on = update.add_mutually_exclusive_group()
    waiting_on.add_argument("--waiting-on", default=argparse.SUPPRESS)
    waiting_on.add_argument(
        "--clear-waiting-on",
        dest="waiting_on",
        action="store_const",
        const=None,
        default=argparse.SUPPRESS,
    )

    review_after = update.add_mutually_exclusive_group()
    review_after.add_argument("--review-after", default=argparse.SUPPRESS)
    review_after.add_argument(
        "--clear-review-after",
        dest="review_after",
        action="store_const",
        const=None,
        default=argparse.SUPPRESS,
    )

    task_list = task_commands.add_parser("list", help="list tasks")
    task_list.add_argument(
        "--format",
        choices=OUTPUT_FORMATS,
        default="json",
        help="output format (default: %(default)s)",
    )

    history = task_commands.add_parser("history", help="show immutable task history")
    history.add_argument("task_id")

    agenda = subcommands.add_parser(
        "agenda", help="render the aggregated read-only agenda"
    )
    agenda_commands = agenda.add_subparsers(dest="agenda_command", required=True)
    agenda_list = agenda_commands.add_parser(
        "list", help="list projected core and provider agenda entries"
    )
    agenda_list.add_argument(
        "--format",
        choices=OUTPUT_FORMATS,
        default="json",
        help="output format (default: %(default)s)",
    )

    render = subcommands.add_parser("render", help="render read models")
    render_commands = render.add_subparsers(dest="render_command", required=True)
    markdown = render_commands.add_parser("markdown", help="render tasks as Markdown")
    markdown.add_argument(
        "--output",
        help="write to a file instead of standard output",
    )

    plugin = subcommands.add_parser("plugin", help="inspect plugin contracts")
    plugin_commands = plugin.add_subparsers(dest="plugin_command", required=True)

    validate = plugin_commands.add_parser(
        "validate", help="parse a registration document before activation"
    )
    validate.add_argument("registration")

    plugin_list = plugin_commands.add_parser(
        "list", help="discover registrations and render an immutable catalog"
    )
    plugin_list.add_argument(
        "--root",
        action="append",
        dest="roots",
        type=Path,
        help="plugin root or registration.json path; may be repeated (default: ./plugins)",
    )
    plugin_list.add_argument(
        "--format",
        choices=OUTPUT_FORMATS,
        default="json",
        help="output format (default: %(default)s)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    stdout = Console(file=sys.stdout, highlight=False)
    stderr = Console(file=sys.stderr, highlight=False)

    if args.command == "version":
        print(__version__)
        return 0

    if args.command == "plugin" and args.plugin_command == "validate":
        try:
            registration = load_registration(args.registration)
        except (OSError, PluginRegistrationError) as error:
            stderr.print(f"error: {error}", markup=False)
            return 2
        print(json.dumps(registration_to_dict(registration), sort_keys=True))
        return 0

    if args.command == "plugin" and args.plugin_command == "list":
        roots = tuple(args.roots or (Path("plugins"),))
        try:
            catalog = scan_plugin_catalog(roots)
        except PluginDiscoveryError as error:
            stderr.print(f"error: {error}", markup=False)
            return 2
        if args.format == "table":
            stdout.print(plugin_catalog_table(catalog))
        else:
            print(json.dumps(catalog_to_list(catalog), sort_keys=True))
        return 0

    if args.command == "config":
        try:
            snapshot = load_application_config(
                base_path=args.path,
                fragment_dirs=args.fragment_dir,
            )
            prepare_application_plugins(snapshot)
            if args.config_command == "validate":
                print(
                    json.dumps(
                        {
                            "schema_version": snapshot.to_dict()["schema_version"],
                            "valid": True,
                        },
                        sort_keys=True,
                    )
                )
            elif args.config_command == "effective":
                print(json.dumps(snapshot.to_dict(redacted=True), sort_keys=True))
            else:
                print(json.dumps(asdict(snapshot.explain(args.pointer)), sort_keys=True))
        except ApplicationConfigError as error:
            stderr.print(f"error: {error}", markup=False)
            return 2
        return 0

    overrides = (
        {"database": {"path": args.database}} if hasattr(args, "database") else None
    )
    try:
        snapshot = load_application_config(
            base_path=args.config,
            fragment_dirs=args.config_dir,
            overrides=overrides,
        )
        prepared_plugins = prepare_application_plugins(snapshot)
    except ApplicationConfigError as error:
        stderr.print(f"error: {error}", markup=False)
        return 2
    database = Database(Path(snapshot.database_path))

    runner = MigrationRunner(database)

    if args.command == "init":
        applied = runner.apply()
        if applied:
            print(
                f"initialized {database.path} (applied: {', '.join(map(str, applied))})"
            )
        else:
            print(f"{database.path} is already current")
        return 0

    if args.command == "doctor":
        runner.apply()
        with database.connect() as connection:
            version = connection.execute(
                "SELECT max(version) FROM schema_migrations"
            ).fetchone()[0]
            connection.execute("SELECT 1").fetchone()
        print(f"ok: database={database.path} schema={version}")
        return 0

    runner.apply()
    repository = TaskRepository(database)

    if args.command == "agenda" and args.agenda_command == "list":
        try:
            providers = activate_agenda_plugins(database, prepared_plugins)
        except PluginLifecycleError as error:
            stderr.print(f"error: {error}", markup=False)
            return 2
        generated_at = datetime.now(UTC)
        contribution = project_core_tasks(repository.list(), generated_at=generated_at)
        agenda_snapshot = aggregate_agenda(
            (
                contribution,
                *(
                    provider.contribution(generated_at=generated_at)
                    for provider in providers
                ),
            )
        )
        if args.format == "table":
            stdout.print(agenda_table(agenda_snapshot))
        else:
            print(json.dumps(agenda_to_list(agenda_snapshot), sort_keys=True))
        return 0

    if args.command == "task":
        if args.task_command == "add":
            task = repository.create(args.title, args.description)
            print(json.dumps(asdict(task), sort_keys=True))
            return 0

        if args.task_command == "update":
            fields = (
                "title",
                "description",
                "state",
                "blocked",
                "waiting_on",
                "review_after",
            )
            changes = {
                field: getattr(args, field) for field in fields if hasattr(args, field)
            }
            task = repository.update(args.task_id, **changes)
            print(json.dumps(asdict(task), sort_keys=True))
            return 0

        if args.task_command == "list":
            tasks = repository.list()
            if args.format == "table":
                stdout.print(task_table(tasks))
            else:
                print(json.dumps([asdict(task) for task in tasks], sort_keys=True))
            return 0

        if args.task_command == "history":
            print(json.dumps(repository.history(args.task_id), sort_keys=True))
            return 0

    if args.command == "render" and args.render_command == "markdown":
        document = render_tasks_markdown(repository.list())
        if args.output:
            Path(args.output).write_text(document, encoding="utf-8")
        else:
            sys.stdout.write(document)
        return 0

    raise AssertionError("unreachable command")
if __name__ == "__main__":
    raise SystemExit(main())
