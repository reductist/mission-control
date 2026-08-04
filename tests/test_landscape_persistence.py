from __future__ import annotations

import json
import sqlite3
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
from importlib.resources import files

import pytest

from mission_control.agenda import SourceRef
from mission_control.builtin_plugins import prepare_builtin_agenda_plugins
from mission_control.builtin_plugins.landscape.domain import (
    LandscapeActionState,
    LandscapeEntityKind,
)
from mission_control.builtin_plugins.landscape.repository import (
    CorruptLandscapeRecordError,
    LandscapeMigrationRunner,
    LandscapeRepository,
    SQLiteLandscapeRepository,
    StaleLandscapeActionRevisionError,
)
from mission_control.database import Database
from mission_control.migrations import MigrationRunner
from mission_control.server import MissionControlApplication
from mission_control.plugins import PluginId


def prepared_landscape():
    return prepare_builtin_agenda_plugins(("landscape",))


def initialized_repository(tmp_path) -> LandscapeRepository:
    database = Database(tmp_path / "mission-control.db")
    MigrationRunner(database).apply()
    LandscapeMigrationRunner(database).apply()
    repository = SQLiteLandscapeRepository(database)
    repository.import_agenda_seed(prepared_landscape()[0].seed)
    return repository


def test_landscape_owns_namespaced_idempotent_migrations(tmp_path) -> None:
    database = Database(tmp_path / "mission-control.db")
    assert MigrationRunner(database).apply() == [1, 2, 3]
    runner = LandscapeMigrationRunner(database)

    assert runner.apply() == [1, 2]
    assert runner.apply() == []

    with database.connect() as connection:
        core_version = connection.execute(
            "SELECT max(version) FROM schema_migrations"
        ).fetchone()[0]
        landscape_version = connection.execute(
            "SELECT max(version) FROM landscape_schema_migrations"
        ).fetchone()[0]
    assert (core_version, landscape_version) == (3, 2)


def test_landscape_text_bounds_migrate_existing_state_without_loss(tmp_path) -> None:
    database = Database(tmp_path / "mission-control.db")
    MigrationRunner(database).apply()
    migration = files("mission_control.builtin_plugins.landscape").joinpath(
        "migrations", "0001_initial.sql"
    )
    with database.connect() as connection:
        connection.executescript(migration.read_text(encoding="utf-8"))

    repository = SQLiteLandscapeRepository(database)
    repository.import_agenda_seed(prepared_landscape()[0].seed)
    before = repository.list_actions()

    assert LandscapeMigrationRunner(database).apply() == [2]
    assert repository.list_actions() == before


def test_packaged_seed_imports_once_into_immutable_domain_values(tmp_path) -> None:
    repository = initialized_repository(tmp_path)

    initiatives = repository.list_initiatives()
    actions = repository.list_actions()
    assert {item.initiative_id for item in initiatives} == {"equipment-access"}
    assert {item.action_id for item in actions} == {
        "measure-access-route",
        "define-equipment-envelope",
        "compare-access-concepts",
        "prepare-fall-leaf-workflow",
    }
    assert repository.import_agenda_seed(prepared_landscape()[0].seed) is False
    with pytest.raises(FrozenInstanceError):
        actions[0].title = "mutable"  # type: ignore[misc]


def test_seed_import_is_atomic_when_an_entry_identity_is_invalid(tmp_path) -> None:
    database = Database(tmp_path / "mission-control.db")
    MigrationRunner(database).apply()
    LandscapeMigrationRunner(database).apply()
    repository = SQLiteLandscapeRepository(database)
    seed = prepared_landscape()[0].seed
    action = seed.entries[1]
    invalid_action = replace(
        action,
        source=replace(action.source, entity_type="task"),
    )
    invalid_seed = replace(seed, entries=(seed.entries[0], invalid_action))

    with pytest.raises(ValueError, match="must use entity type 'action'"):
        repository.import_agenda_seed(invalid_seed)

    assert repository.list_initiatives() == ()
    assert repository.list_actions() == ()


def test_state_and_history_survive_restart_without_seed_overwrite(tmp_path) -> None:
    database = Database(tmp_path / "mission-control.db")
    prepared = prepared_landscape()
    first = MissionControlApplication(database, builtin_plugins=prepared)
    first_repository = first.agenda_providers[0].repository
    changed = first_repository.complete_action("measure-access-route")
    assert changed.version == 2
    assert (
        len(
            first_repository.history(LandscapeEntityKind.ACTION, "measure-access-route")
        )
        == 2
    )

    restarted = MissionControlApplication(database, builtin_plugins=prepared)
    restarted_repository = restarted.agenda_providers[0].repository
    persisted = restarted_repository.get_action("measure-access-route")
    assert persisted.state is LandscapeActionState.DONE
    assert persisted.version == 2
    assert (
        len(
            restarted_repository.history(
                LandscapeEntityKind.ACTION, "measure-access-route"
            )
        )
        == 2
    )
    assert "measure-access-route" not in {
        entry["id"] for entry in restarted.dashboard()["agenda"]
    }
    closed = restarted.dashboard()["closed_items"]
    item = next(entry for entry in closed if entry["id"] == "measure-access-route")
    assert item["revision"] == "2"
    assert item["state"] == "done"
    assert item["affordances"] == [
        {"capability": "entity.annotate", "command": "add-note"},
        {"capability": "lifecycle.reopen", "command": "reopen"},
    ]


def test_projection_revision_changes_with_persisted_state(tmp_path) -> None:
    repository = initialized_repository(tmp_path)
    generated_at = datetime.now(UTC)
    before = repository.agenda_contribution(generated_at=generated_at)

    repository.complete_action("measure-access-route")
    after = repository.agenda_contribution(generated_at=generated_at)

    assert before.revision != after.revision
    assert {entry.entry_id for entry in before.entries} - {
        entry.entry_id for entry in after.entries
    } == {"measure-access-route"}

    closed = repository.closed_items_contribution(generated_at=generated_at)
    assert [item.item_id for item in closed.items] == ["measure-access-route"]
    reopened = repository.reopen_action("measure-access-route")
    assert reopened.revision == "3"
    assert repository.closed_items_contribution(generated_at=generated_at).items == ()


def test_action_projection_exposes_opaque_revision_and_rejects_stale_writes(
    tmp_path,
) -> None:
    repository = initialized_repository(tmp_path)
    before = repository.get_action("measure-access-route")
    projected = repository.agenda_contribution(generated_at=datetime.now(UTC))
    entry = next(
        item for item in projected.entries if item.entry_id == "measure-access-route"
    )
    assert entry.revision == before.revision == "1"

    changed = repository.complete_action(
        before.action_id,
        expected_revision=before.revision,
    )
    assert changed.revision == "2"

    with pytest.raises(StaleLandscapeActionRevisionError) as stale:
        repository.reopen_action(
            before.action_id,
            expected_revision=before.revision,
        )
    assert stale.value.current_revision == changed.revision
    assert len(repository.history(LandscapeEntityKind.ACTION, before.action_id)) == 2


def test_disabling_landscape_hides_but_does_not_delete_its_state(tmp_path) -> None:
    database = Database(tmp_path / "mission-control.db")
    prepared = prepared_landscape()
    enabled = MissionControlApplication(database, builtin_plugins=prepared)
    detail = enabled.entity_detail("landscape", "action", "measure-access-route")
    status, note = enabled.execute_command(
        {
            "schema_version": "mission-control.command/v1",
            "command_id": "persist-disabled-note-1",
            "target": detail["source"],
            "expected_revision": detail["revision"],
            "command": "add-note",
            "arguments": {"body": "Gate clearance is 54 inches."},
        },
        authorized=True,
    )
    assert status == 200
    assert note["status"] == "accepted"
    note_projection = note["result"]["note"]
    status, dismissed = enabled.execute_command(
        {
            "schema_version": "mission-control.command/v1",
            "command_id": "dismiss-before-disable-1",
            "target": note_projection["source"],
            "expected_revision": note_projection["revision"],
            "command": "dismiss",
            "arguments": {},
        },
        authorized=True,
    )
    assert status == 200
    assert dismissed["status"] == "accepted"
    enabled.agenda_providers[0].repository.complete_action("measure-access-route")

    disabled = MissionControlApplication(database)
    assert all(
        entry["source"]["plugin_id"] != "landscape"
        for entry in disabled.dashboard()["agenda"]
    )
    assert all(
        entry["source"]["plugin_id"] != "landscape"
        for entry in disabled.dashboard()["closed_items"]
    )
    target = SourceRef(PluginId("landscape"), "action", "measure-access-route")
    assert disabled.annotation_repository.list(target)[0].body.startswith(
        "Gate clearance"
    )
    assert disabled.annotation_repository.list(target)[0].state.value == "inactive"

    reenabled = MissionControlApplication(database, builtin_plugins=prepared)
    assert (
        reenabled.agenda_providers[0]
        .repository.get_action("measure-access-route")
        .state
        is LandscapeActionState.DONE
    )
    activity = reenabled.entity_detail("landscape", "action", "measure-access-route")[
        "activity"
    ]
    note_activity = next(item for item in activity if item["kind"] == "note")
    assert note_activity["body"].startswith("Gate clearance")
    assert note_activity["state"] == "inactive"
    assert "core.note-dismissed" in {item["activity_type"] for item in activity}


def test_landscape_events_are_immutable_at_the_database_boundary(tmp_path) -> None:
    repository = initialized_repository(tmp_path)
    event = repository.history(LandscapeEntityKind.ACTION, "measure-access-route")[0]

    with (
        Database(tmp_path / "mission-control.db").connect() as connection,
        pytest.raises(sqlite3.IntegrityError, match="immutable"),
    ):
        connection.execute(
            "DELETE FROM landscape_events WHERE event_id = ?", (event.event_id,)
        )

    assert json.loads(event.payload_json)["state"] == "ready"


def test_database_mirrors_critical_landscape_text_bounds(tmp_path) -> None:
    initialized_repository(tmp_path)

    with (
        Database(tmp_path / "mission-control.db").connect() as connection,
        pytest.raises(sqlite3.IntegrityError, match="invalid Landscape action text"),
    ):
        connection.execute(
            "UPDATE landscape_actions SET title = ? WHERE action_id = ?",
            ("x" * 257, "measure-access-route"),
        )


def test_corrupt_persisted_landscape_data_fails_explicitly(tmp_path) -> None:
    repository = initialized_repository(tmp_path)
    with Database(tmp_path / "mission-control.db").connect() as connection:
        connection.execute(
            "UPDATE landscape_actions SET updated_at = ? WHERE action_id = ?",
            ("2026-01-01T00:00:00", "measure-access-route"),
        )

    with pytest.raises(
        CorruptLandscapeRecordError,
        match=r"invalid persisted Landscape action 'measure-access-route'.*timezone-aware",
    ):
        repository.get_action("measure-access-route")
