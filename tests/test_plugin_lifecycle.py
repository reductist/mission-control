from __future__ import annotations

import json
import shutil
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from mission_control.database import Database
from mission_control.migrations import MigrationRunner
from mission_control.plugin_lifecycle import (
    PluginDatabase,
    PluginResourceSource,
    _apply_declared_migrations,
    _execute_migration_script,
    _import_plugin_module,
    _validate_permissions,
    activate_agenda_plugins,
    bundled_plugin_ids,
    filesystem_plugin_sources,
    plugin_sql_prefix,
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
    prefix = plugin_sql_prefix(PluginId("example"))
    assert scoped.namespace == prefix
    assert scoped.table_name("records") == f"{prefix}records"
    with pytest.raises(ValueError, match="safe SQL identifier"):
        scoped.table_name("other-plugin.records")

    with scoped.connect() as connection:
        connection.execute(
            f"CREATE TABLE {prefix}records (value TEXT NOT NULL)"
        )
        connection.execute(f"INSERT INTO {prefix}records VALUES ('owned')")
        assert (
            connection.execute(f"SELECT value FROM {prefix}records").fetchone()[0]
            == "owned"
        )

        for statement in (
            "SELECT title FROM tasks",
            "SELECT version FROM schema_migrations",
            "SELECT plugin_id FROM plugin_schema_migrations",
            "SELECT note_id FROM entity_notes",
        ):
            with pytest.raises(
                sqlite3.DatabaseError, match="not authorized|prohibited"
            ):
                connection.execute(statement)
        with pytest.raises(sqlite3.DatabaseError, match="not authorized|prohibited"):
            connection.execute("ALTER TABLE tasks ADD COLUMN stolen TEXT")
        connection.execute(f"CREATE VIEW {prefix}tasks AS SELECT * FROM tasks")
        with pytest.raises(sqlite3.DatabaseError, match="not authorized|prohibited"):
            connection.execute(f"SELECT * FROM {prefix}tasks")

    with database.connect() as connection:
        related_prefix = plugin_sql_prefix(PluginId("example--extra"))
        assert not related_prefix.startswith(prefix)
        connection.execute(
            f"CREATE TABLE {related_prefix}events ("
            "sequence INTEGER PRIMARY KEY AUTOINCREMENT, value TEXT NOT NULL)"
        )
        connection.execute(
            f"INSERT INTO {related_prefix}events(value) VALUES ('owned')"
        )

    with scoped.connect() as connection:
        with pytest.raises(sqlite3.DatabaseError, match="not authorized|prohibited"):
            connection.execute(f"SELECT value FROM {related_prefix}events")
        with pytest.raises(sqlite3.DatabaseError, match="not authorized|prohibited"):
            connection.execute(
                "UPDATE sqlite_sequence SET seq = 999 "
                f"WHERE name = '{related_prefix}events'"
            )

    with database.connect() as connection:
        assert connection.execute(
            "SELECT seq FROM sqlite_sequence WHERE name = ?",
            (f"{related_prefix}events",),
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
            connection.execute(
                "CREATE TABLE plugin__7__example__records (value TEXT NOT NULL)"
            )


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
            "google-calendar": {
                "connections": {
                    "demo": {
                        "label": "Google demo",
                        "mode": "demo",
                        "demo_anchor_date": "2026-08-14",
                        "calendars": {"mode": "defaults"},
                        "tasks": {"mode": "all"},
                    }
                }
            }
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


def test_nested_external_runtime_module_stays_within_plugin_root(tmp_path) -> None:
    source = Path(__file__).parents[1] / "plugins" / "reference"
    plugin_root = tmp_path / "reference"
    shutil.copytree(source, plugin_root)
    registration_path = plugin_root / "registration.json"
    registration = json.loads(registration_path.read_text(encoding="utf-8"))
    registration["runtime"]["entrypoint"] = "nested.runtime:activate"
    registration_path.write_text(json.dumps(registration), encoding="utf-8")
    nested = plugin_root / "nested"
    nested.mkdir()
    (nested / "runtime.py").write_text("MARKER = 'nested-local'\n", encoding="utf-8")

    (prepared,) = prepare_plugins(
        ("reference",),
        roots=(plugin_root,),
        configurations={"reference": {"message": "hello"}},
    )

    assert _import_plugin_module(prepared, "nested.runtime").MARKER == "nested-local"


def test_external_runtime_and_plugin_directory_symlinks_cannot_escape_root(
    tmp_path,
) -> None:
    source = Path(__file__).parents[1] / "plugins" / "reference"
    plugin_root = tmp_path / "reference"
    shutil.copytree(source, plugin_root)
    nested = plugin_root / "nested"
    nested.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("MARKER = 'escaped'\n", encoding="utf-8")
    (nested / "escape.py").symlink_to(outside)
    (prepared,) = prepare_plugins(
        ("reference",),
        roots=(plugin_root,),
        configurations={"reference": {"message": "hello"}},
    )

    with pytest.raises(ValueError, match="unsafe plugin runtime module"):
        _import_plugin_module(prepared, "nested.escape")

    parent = tmp_path / "catalog"
    parent.mkdir()
    (parent / "escaped-plugin").symlink_to(plugin_root, target_is_directory=True)
    assert filesystem_plugin_sources((parent,)) == ()


def test_unsupported_runtime_capability_is_rejected_during_preflight(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = Path(__file__).parents[1] / "plugins" / "reference"
    plugin_root = tmp_path / "reference"
    shutil.copytree(source, plugin_root)
    registration_path = plugin_root / "registration.json"
    registration = json.loads(registration_path.read_text(encoding="utf-8"))
    registration["capabilities"].append("ui")
    registration_path.write_text(json.dumps(registration), encoding="utf-8")
    imported = False

    def unexpected_import(_name: str):
        nonlocal imported
        imported = True
        raise AssertionError("invalid plugin imported")

    monkeypatch.setattr("mission_control.plugin_lifecycle.import_module", unexpected_import)

    with pytest.raises(ValueError, match="without a public call adapter"):
        prepare_plugins(
            ("reference",),
            roots=(plugin_root,),
            configurations={"reference": {"message": "hello"}},
        )
    assert imported is False


def test_plugin_migration_symlinks_cannot_escape_plugin_root(tmp_path) -> None:
    source = Path(__file__).parents[1] / "plugins" / "reference"
    (prepared,) = prepare_plugins(
        ("reference",),
        roots=(source,),
        configurations={"reference": {"message": "hello"}},
    )
    registration = replace(
        prepared.registration,
        permissions=(Permission.DATABASE,),
        runtime=replace(prepared.registration.runtime, migration_set="reference"),
    )
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "0001_escape.sql").write_text(
        "CREATE TABLE stolen(value TEXT);", encoding="utf-8"
    )

    directory_root = tmp_path / "directory-plugin"
    directory_root.mkdir()
    (directory_root / "migrations").symlink_to(outside, target_is_directory=True)
    directory_escape = replace(
        prepared,
        registration=registration,
        source=PluginResourceSource(directory_root, str(directory_root)),
    )
    with pytest.raises(ValueError, match="unsafe plugin migration directory"):
        _apply_declared_migrations(
            Database(tmp_path / "directory.db"), directory_escape
        )

    file_root = tmp_path / "file-plugin"
    migrations = file_root / "migrations"
    migrations.mkdir(parents=True)
    (migrations / "0001_escape.sql").symlink_to(outside / "0001_escape.sql")
    file_escape = replace(
        prepared,
        registration=registration,
        source=PluginResourceSource(file_root, str(file_root)),
    )
    database = Database(tmp_path / "file.db")
    MigrationRunner(database).apply()
    with pytest.raises(ValueError, match="unsafe plugin migration resource"):
        _apply_declared_migrations(database, file_escape)


def test_prefix_safe_storage_uses_a_new_non_destructive_migration_epoch(
    tmp_path,
) -> None:
    database = Database(tmp_path / "mission-control.db")
    MigrationRunner(database).apply()
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO plugin_schema_migrations"
            "(plugin_id, migration_set, version, checksum) VALUES (?, ?, ?, ?)",
            ("landscape", "landscape", 1, "legacy-checksum"),
        )
    (prepared,) = prepare_agenda_plugins(("landscape",))

    (provider,) = activate_agenda_plugins(database, (prepared,))

    assert provider.plugin_id == PluginId("landscape")
    with database.connect() as connection:
        epochs = {
            row[0]
            for row in connection.execute(
                "SELECT migration_set FROM plugin_schema_migrations "
                "WHERE plugin_id = 'landscape'"
            )
        }
    assert epochs == {"landscape", "landscape_v2"}
