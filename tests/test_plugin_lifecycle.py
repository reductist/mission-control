from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from mission_control.database import Database
from mission_control.migrations import MigrationRunner
from mission_control.plugin_lifecycle import (
    PluginDatabase,
    _execute_migration_script,
    _validate_permissions,
    bundled_plugin_ids,
    prepare_agenda_plugins,
    prepare_plugins,
)
from mission_control.plugins import Permission, PluginId


def test_bundled_manifest_identity_does_not_depend_on_directory_name() -> None:
    assert bundled_plugin_ids() == ("google-calendar", "landscape")


def test_generic_preflight_accepts_external_non_agenda_bundle() -> None:
    root = Path(__file__).parents[1] / "plugins" / "reference"

    (prepared,) = prepare_plugins(
        ("reference",),
        roots=(root,),
        configurations={"reference": {"message": "hello"}},
    )

    assert prepared.registration.plugin_id == PluginId("reference")
    assert prepared.configuration.to_dict() == {"message": "hello", "repeat": 1}


def test_plugin_database_enforces_declared_namespace(tmp_path) -> None:
    database = Database(tmp_path / "mission-control.db")
    MigrationRunner(database).apply()
    scoped = PluginDatabase(database, PluginId("example"), enabled=True)

    with scoped.connect() as connection:
        connection.execute("CREATE TABLE example_records (value TEXT NOT NULL)")
        connection.execute("INSERT INTO example_records VALUES ('owned')")
        assert (
            connection.execute("SELECT value FROM example_records").fetchone()[0]
            == "owned"
        )

        with pytest.raises(sqlite3.DatabaseError, match="not authorized|prohibited"):
            connection.execute("SELECT title FROM tasks")
        with pytest.raises(sqlite3.DatabaseError, match="not authorized|prohibited"):
            connection.execute("ALTER TABLE tasks ADD COLUMN stolen TEXT")
        connection.execute("CREATE VIEW example_tasks AS SELECT * FROM tasks")
        with pytest.raises(sqlite3.DatabaseError, match="not authorized|prohibited"):
            connection.execute("SELECT * FROM example_tasks")

    with database.connect() as connection:
        connection.execute(
            "CREATE TABLE landscape_events ("
            "sequence INTEGER PRIMARY KEY AUTOINCREMENT, value TEXT NOT NULL)"
        )
        connection.execute("INSERT INTO landscape_events(value) VALUES ('owned')")

    with scoped.connect() as connection:
        with pytest.raises(sqlite3.DatabaseError, match="not authorized|prohibited"):
            connection.execute(
                "UPDATE sqlite_sequence SET seq = 999 "
                "WHERE name = 'landscape_events'"
            )

    with database.connect() as connection:
        assert connection.execute(
            "SELECT seq FROM sqlite_sequence WHERE name = 'landscape_events'"
        ).fetchone()[0] == 1


def test_plugin_without_database_permission_cannot_access_even_its_namespace(
    tmp_path,
) -> None:
    scoped = PluginDatabase(
        Database(tmp_path / "mission-control.db"),
        PluginId("example"),
        enabled=False,
    )

    with scoped.connect() as connection:
        with pytest.raises(sqlite3.DatabaseError, match="not authorized|prohibited"):
            connection.execute("CREATE TABLE example_records (value TEXT NOT NULL)")


def test_migration_executor_accepts_multiple_statements_on_one_line(tmp_path) -> None:
    with Database(tmp_path / "mission-control.db").connect() as connection:
        _execute_migration_script(
            connection,
            "CREATE TABLE one (value TEXT); CREATE TABLE two (value TEXT);",
        )
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }

    assert tables == {"one", "two"}


def test_declared_storage_requires_matching_permission() -> None:
    (prepared,) = prepare_agenda_plugins(
        ("google-calendar",),
        configurations={
            "google-calendar": {"mode": "demo", "demo_anchor_date": "2026-08-14"}
        },
    )
    without_database = replace(
        prepared.registration,
        permissions=tuple(
            permission
            for permission in prepared.registration.permissions
            if permission is not Permission.DATABASE
        ),
    )
    with pytest.raises(ValueError, match="migration set requires database permission"):
        _validate_permissions(without_database)


def test_unrelated_malformed_external_manifest_does_not_poison_selected_plugin(
    tmp_path,
) -> None:
    root = tmp_path / "plugins"
    unrelated = root / "broken"
    unrelated.mkdir(parents=True)
    (unrelated / "registration.json").write_text(
        json.dumps({"id": "broken"}), encoding="utf-8"
    )

    (landscape,) = prepare_agenda_plugins(("landscape",), roots=(root,))

    assert landscape.registration.plugin_id == PluginId("landscape")


def test_malformed_external_manifest_is_attributed_to_its_selected_id(
    tmp_path,
) -> None:
    root = tmp_path / "plugins"
    conflicting = root / "landscape-copy"
    conflicting.mkdir(parents=True)
    (conflicting / "registration.json").write_text(
        json.dumps({"id": "landscape"}), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="landscape-copy"):
        prepare_agenda_plugins(("landscape",), roots=(root,))
