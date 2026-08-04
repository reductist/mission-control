from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from mission_control.builtin_plugins import (
    load_builtin_agenda_contributions,
    prepare_builtin_agenda_plugins,
)
from mission_control.builtin_plugins.landscape.domain import LandscapeEntityKind
from mission_control.database import Database
from mission_control.server import MissionControlApplication, build_server


@contextmanager
def running_server(application: MissionControlApplication):
    server = build_server(application, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def request_json(
    url: str,
    *,
    method: str = "GET",
    body: object | None = None,
    token: str | None = None,
):
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if token is not None:
        headers["X-Mission-Control-Token"] = token
    request = Request(url, data=data, headers=headers, method=method)
    with urlopen(request) as response:
        return response.status, json.load(response)


def test_demo_seed_is_idempotent_and_dashboard_is_synthetic(tmp_path):
    database = Database(tmp_path / "mission-control.db")

    contributions = load_builtin_agenda_contributions(("landscape",))
    first = MissionControlApplication(
        database,
        demo=True,
        write_token="test-token",
        agenda_contributions=contributions,
    )
    second = MissionControlApplication(
        database,
        demo=True,
        write_token="test-token",
        agenda_contributions=contributions,
    )

    dashboard = second.dashboard()
    assert dashboard["mode"] == "demo"
    assert dashboard["summary"]["open"] == 1
    assert len(dashboard["tasks"]) == 1
    assert dashboard["demo"]["house"]["status"] == "Exploring, not rushing"
    assert "yard" not in dashboard["demo"]
    assert {entry["source"]["plugin_id"] for entry in dashboard["agenda"]} == {
        "core",
        "landscape",
    }
    assert any(entry["id"] == "measure-access-route" for entry in dashboard["agenda"])
    assert len(first.repository.history(dashboard["tasks"][0]["id"])) >= 1


def test_http_dashboard_assets_and_health(tmp_path):
    application = MissionControlApplication(
        Database(tmp_path / "mission-control.db"),
        demo=True,
        write_token="known-token",
    )

    with running_server(application) as base_url:
        with urlopen(f"{base_url}/") as response:
            index = response.read().decode("utf-8")
            assert response.headers["Content-Security-Policy"].startswith(
                "default-src 'self'"
            )
        assert 'content="known-token"' in index
        assert "Mission Control" in index

        with urlopen(f"{base_url}/assets/styles.css") as response:
            assert response.headers["Content-Type"].startswith("text/css")
            assert b"--sidebar" in response.read()

        with urlopen(f"{base_url}/assets/app.js") as response:
            script = response.read()
            assert (
                b'querySelectorAll("button[data-command]:not([data-activity-command])")'
                in script
            )
            assert b'request("/api/commands"' in script
            assert b'affordance.capability === "lifecycle.complete"' in script
            assert b'affordance.capability === "lifecycle.reopen"' in script
            assert b'capability === "entity.annotate"' in script
            assert b'capability === "lifecycle.dismiss"' in script
            assert b"toggle-removed-notes" in script
            assert b"data-activity-command" in script
            assert b"window.confirm" in script
            assert b"/api/entities/" in script
            assert b"error.status === 409" in script

        status, health = request_json(f"{base_url}/api/health")
        assert status == 200
        assert health == {"status": "ok", "version": "0.1.0"}

        status, dashboard = request_json(f"{base_url}/api/dashboard")
        assert status == 200
        assert dashboard["summary"]["open"] == 1
        assert "closed_items" in dashboard


def test_landscape_upgrade_preserves_legacy_demo_tasks_for_manual_cleanup(tmp_path):
    database = Database(tmp_path / "mission-control.db")
    old_demo = MissionControlApplication(database, write_token="test-token")
    measure = old_demo.repository.create(
        "Measure the driveway drop-off for equipment access",
        "Record the rise, run, and usable landing area before choosing a solution.",
    )
    old_demo.repository.update(measure.id, state="ready")
    lighting = old_demo.repository.create(
        "Review low-voltage shade lighting options",
        "Favor an extensible system that can charge from a sunnier location.",
    )
    old_demo.repository.update(lighting.id, state="ready")

    upgraded = MissionControlApplication(
        database,
        write_token="test-token",
        agenda_contributions=load_builtin_agenda_contributions(("landscape",)),
    )
    dashboard = upgraded.dashboard()

    assert {task["id"] for task in dashboard["tasks"]} == {measure.id, lighting.id}
    assert {entry["source"]["plugin_id"] for entry in dashboard["agenda"]} == {
        "core",
        "landscape",
    }


def test_task_mutations_require_token_and_append_history(tmp_path):
    application = MissionControlApplication(
        Database(tmp_path / "mission-control.db"),
        write_token="known-token",
    )

    with running_server(application) as base_url:
        with pytest.raises(HTTPError) as forbidden:
            request_json(
                f"{base_url}/api/tasks",
                method="POST",
                body={"title": "Untrusted write"},
            )
        assert forbidden.value.code == 403

        _, created = request_json(
            f"{base_url}/api/tasks",
            method="POST",
            body={"title": "Show the real interaction"},
            token="known-token",
        )
        assert created["state"] == "backlog"

        _, completed = request_json(
            f"{base_url}/api/tasks/{created['id']}",
            method="PATCH",
            body={"state": "done"},
            token="known-token",
        )
        assert completed["state"] == "done"
        assert [
            event["event_type"]
            for event in application.repository.history(created["id"])
        ] == [
            "task.created",
            "task.updated",
        ]


def test_command_endpoint_routes_core_task_state_with_revision_and_auth(tmp_path):
    application = MissionControlApplication(
        Database(tmp_path / "mission-control.db"),
        write_token="known-token",
    )
    task = application.repository.create("Use public command route")
    command = {
        "schema_version": "mission-control.command/v1",
        "command_id": "command-1",
        "target": {
            "plugin_id": "core",
            "entity_type": "task",
            "entity_id": task.id,
        },
        "expected_revision": task.updated_at,
        "command": "set-state",
        "arguments": {"state": "done"},
    }

    with running_server(application) as base_url:
        with pytest.raises(HTTPError) as forbidden:
            request_json(
                f"{base_url}/api/commands",
                method="POST",
                body=command,
            )
        assert forbidden.value.code == 403
        unauthorized = json.load(forbidden.value)
        assert unauthorized["status"] == "unauthorized"

        _, accepted = request_json(
            f"{base_url}/api/commands",
            method="POST",
            body=command,
            token="known-token",
        )
        assert accepted["status"] == "accepted"
        assert accepted["result"]["task"]["state"] == "done"

        with pytest.raises(HTTPError) as conflict:
            request_json(
                f"{base_url}/api/commands",
                method="POST",
                body=command,
                token="known-token",
            )
        assert conflict.value.code == 409
        stale = json.load(conflict.value)
        assert stale["status"] == "stale"
        assert stale["current_revision"] == accepted["revision"]


def test_completed_core_task_moves_to_history_and_reopens_through_command(tmp_path):
    application = MissionControlApplication(
        Database(tmp_path / "mission-control.db"),
        write_token="known-token",
    )
    task = application.repository.create("Restore this from History")
    complete = {
        "schema_version": "mission-control.command/v1",
        "command_id": "core-complete-history-1",
        "target": {
            "plugin_id": "core",
            "entity_type": "task",
            "entity_id": task.id,
        },
        "expected_revision": task.updated_at,
        "command": "set-state",
        "arguments": {"state": "done"},
    }

    with running_server(application) as base_url:
        _, completed = request_json(
            f"{base_url}/api/commands",
            method="POST",
            body=complete,
            token="known-token",
        )
        _, dashboard = request_json(f"{base_url}/api/dashboard")
        item = next(
            entry for entry in dashboard["closed_items"] if entry["id"] == task.id
        )
        assert item["revision"] == completed["revision"]
        assert item["affordances"] == [
            {"capability": "lifecycle.reopen", "command": "set-state"}
        ]
        assert task.id not in {entry["id"] for entry in dashboard["agenda"]}

        _, reopened = request_json(
            f"{base_url}/api/commands",
            method="POST",
            body={
                **complete,
                "command_id": "core-reopen-history-1",
                "expected_revision": item["revision"],
                "arguments": {"state": "ready"},
            },
            token="known-token",
        )
        assert reopened["status"] == "accepted"
        _, dashboard = request_json(f"{base_url}/api/dashboard")
        assert task.id not in {item["id"] for item in dashboard["closed_items"]}
        assert task.id in {entry["id"] for entry in dashboard["agenda"]}


def test_landscape_commands_complete_survive_restart_and_reopen(tmp_path):
    database = Database(tmp_path / "mission-control.db")
    prepared = prepare_builtin_agenda_plugins(("landscape",))
    first = MissionControlApplication(
        database,
        write_token="known-token",
        builtin_plugins=prepared,
    )
    initial = next(
        entry
        for entry in first.dashboard()["agenda"]
        if entry["id"] == "measure-access-route"
    )
    assert initial["affordances"] == [
        {"capability": "entity.annotate", "command": "add-note"},
        {"capability": "lifecycle.complete", "command": "complete"},
    ]
    complete = {
        "schema_version": "mission-control.command/v1",
        "command_id": "landscape-complete-1",
        "target": initial["source"],
        "expected_revision": initial["revision"],
        "command": "complete",
        "arguments": {},
    }

    with running_server(first) as base_url:
        _, completed = request_json(
            f"{base_url}/api/commands",
            method="POST",
            body=complete,
            token="known-token",
        )
        assert completed["status"] == "accepted"
        assert completed["revision"] == "2"
        assert completed["result"]["action"]["state"] == "done"
        _, dashboard = request_json(f"{base_url}/api/dashboard")
        assert "measure-access-route" not in {
            entry["id"] for entry in dashboard["agenda"]
        }
        closed_item = next(
            item
            for item in dashboard["closed_items"]
            if item["id"] == "measure-access-route"
        )
        assert closed_item["revision"] == "2"
        assert closed_item["affordances"] == [
            {"capability": "entity.annotate", "command": "add-note"},
            {"capability": "lifecycle.reopen", "command": "reopen"},
        ]

    restarted = MissionControlApplication(
        database,
        write_token="known-token",
        builtin_plugins=prepared,
    )
    repository = restarted.agenda_providers[0].repository
    assert repository.get_action("measure-access-route").state.value == "done"
    assert (
        len(repository.history(LandscapeEntityKind.ACTION, "measure-access-route")) == 2
    )
    reopen = {
        **complete,
        "command_id": "landscape-reopen-1",
        "expected_revision": completed["revision"],
        "command": "reopen",
    }

    with running_server(restarted) as base_url:
        _, reopened = request_json(
            f"{base_url}/api/commands",
            method="POST",
            body=reopen,
            token="known-token",
        )
        assert reopened["status"] == "accepted"
        assert reopened["revision"] == "3"
        _, dashboard = request_json(f"{base_url}/api/dashboard")
        restored = next(
            entry
            for entry in dashboard["agenda"]
            if entry["id"] == "measure-access-route"
        )
        assert restored["state"] == "ready"
        assert restored["revision"] == "3"
        assert restored["affordances"] == [
            {"capability": "entity.annotate", "command": "add-note"},
            {"capability": "lifecycle.complete", "command": "complete"},
        ]
        assert "measure-access-route" not in {
            item["id"] for item in dashboard["closed_items"]
        }
    assert (
        len(repository.history(LandscapeEntityKind.ACTION, "measure-access-route")) == 3
    )


def test_landscape_entity_detail_composes_durable_notes_and_domain_activity(tmp_path):
    database = Database(tmp_path / "mission-control.db")
    prepared = prepare_builtin_agenda_plugins(("landscape",))
    first = MissionControlApplication(
        database,
        write_token="known-token",
        builtin_plugins=prepared,
    )

    with running_server(first) as base_url:
        status, detail = request_json(
            f"{base_url}/api/entities/landscape/action/measure-access-route"
        )
        assert status == 200
        assert detail["title"] == "Measure the backyard access route"
        assert detail["state"] == "ready"
        assert detail["revision"] == "1"
        assert detail["attributes"][0] == {
            "key": "timing",
            "label": "Timing",
            "value": "2026-08-01 to 2026-09-15",
        }
        assert detail["activity"][0]["activity_type"] == "landscape.action-imported"

        _, added = request_json(
            f"{base_url}/api/commands",
            method="POST",
            token="known-token",
            body={
                "schema_version": "mission-control.command/v1",
                "command_id": "record-measurements-1",
                "target": detail["source"],
                "expected_revision": detail["revision"],
                "command": "add-note",
                "arguments": {"body": "Vertical drop: 42 inches; usable run: 18 feet."},
            },
        )
        assert added["status"] == "accepted"
        assert added["revision"] == "1"

        _, changed = request_json(
            f"{base_url}/api/entities/landscape/action/measure-access-route"
        )
        note = changed["activity"][-1]
        assert note["kind"] == "note"
        assert note["body"].startswith("Vertical drop")
        assert note["actor"] == "local-operator"

        _, completed = request_json(
            f"{base_url}/api/commands",
            method="POST",
            token="known-token",
            body={
                "schema_version": "mission-control.command/v1",
                "command_id": "complete-after-measurements-1",
                "target": detail["source"],
                "expected_revision": detail["revision"],
                "command": "complete",
                "arguments": {},
            },
        )
        assert completed["revision"] == "2"

    restarted = MissionControlApplication(
        database,
        write_token="known-token",
        builtin_plugins=prepared,
    )
    persisted = restarted.entity_detail("landscape", "action", "measure-access-route")
    assert persisted["state"] == "done"
    assert [entry["activity_type"] for entry in persisted["activity"]] == [
        "landscape.action-imported",
        "core.note-added",
        "landscape.action-state-changed",
    ]
    assert persisted["activity"][1]["body"].startswith("Vertical drop")
    assert {item["capability"] for item in persisted["affordances"]} == {
        "entity.annotate",
        "lifecycle.reopen",
    }


def test_note_remove_restore_uses_its_own_revision_and_survives_restart(tmp_path):
    database = Database(tmp_path / "mission-control.db")
    prepared = prepare_builtin_agenda_plugins(("landscape",))
    first = MissionControlApplication(
        database,
        write_token="known-token",
        builtin_plugins=prepared,
    )

    with running_server(first) as base_url:
        _, detail = request_json(
            f"{base_url}/api/entities/landscape/action/measure-access-route"
        )
        _, added = request_json(
            f"{base_url}/api/commands",
            method="POST",
            token="known-token",
            body={
                "schema_version": "mission-control.command/v1",
                "command_id": "add-removable-note",
                "target": detail["source"],
                "expected_revision": detail["revision"],
                "command": "add-note",
                "arguments": {"body": "Accidental note"},
            },
        )
        assert added["revision"] == detail["revision"]
        assert added["result"]["note"]["state"] == "active"
        assert added["result"]["note"]["source"]["plugin_id"] == "core"
        _, with_note = request_json(
            f"{base_url}/api/entities/landscape/action/measure-access-route"
        )
        note = next(item for item in with_note["activity"] if item["kind"] == "note")
        assert note["state"] == "active"
        assert note["source"] == {
            "plugin_id": "core",
            "entity_type": "annotation",
            "entity_id": note["activity_id"].removeprefix("note:"),
        }
        assert note["affordances"] == [
            {"capability": "lifecycle.dismiss", "command": "dismiss"}
        ]
        dismiss = {
            "schema_version": "mission-control.command/v1",
            "command_id": "dismiss-removable-note",
            "target": note["source"],
            "expected_revision": note["revision"],
            "command": "dismiss",
            "arguments": {},
        }

        with pytest.raises(HTTPError) as forbidden:
            request_json(
                f"{base_url}/api/commands",
                method="POST",
                body=dismiss,
            )
        assert forbidden.value.code == 403

        _, dismissed = request_json(
            f"{base_url}/api/commands",
            method="POST",
            token="known-token",
            body=dismiss,
        )
        assert dismissed["status"] == "accepted"
        assert dismissed["revision"] != note["revision"]
        _, inactive_detail = request_json(
            f"{base_url}/api/entities/landscape/action/measure-access-route"
        )
        inactive = next(
            item for item in inactive_detail["activity"] if item["kind"] == "note"
        )
        assert inactive["state"] == "inactive"
        assert inactive["revision"] == dismissed["revision"]
        assert inactive["affordances"] == [
            {"capability": "lifecycle.reopen", "command": "reopen"}
        ]
        assert inactive_detail["revision"] == detail["revision"]
        assert "core.note-dismissed" in {
            item["activity_type"] for item in inactive_detail["activity"]
        }

        with pytest.raises(HTTPError) as stale_response:
            request_json(
                f"{base_url}/api/commands",
                method="POST",
                token="known-token",
                body=dismiss,
            )
        assert stale_response.value.code == 409

        _, completed = request_json(
            f"{base_url}/api/commands",
            method="POST",
            token="known-token",
            body={
                "schema_version": "mission-control.command/v1",
                "command_id": "complete-with-inactive-note",
                "target": detail["source"],
                "expected_revision": detail["revision"],
                "command": "complete",
                "arguments": {},
            },
        )
        assert completed["revision"] == "2"

    restarted = MissionControlApplication(
        database,
        write_token="known-token",
        builtin_plugins=prepared,
    )
    with running_server(restarted) as base_url:
        _, persisted = request_json(
            f"{base_url}/api/entities/landscape/action/measure-access-route"
        )
        inactive = next(
            item for item in persisted["activity"] if item["kind"] == "note"
        )
        assert persisted["state"] == "done"
        assert inactive["state"] == "inactive"
        _, restored = request_json(
            f"{base_url}/api/commands",
            method="POST",
            token="known-token",
            body={
                **dismiss,
                "command_id": "restore-removable-note",
                "expected_revision": inactive["revision"],
                "command": "reopen",
            },
        )
        assert restored["status"] == "accepted"
        _, active_detail = request_json(
            f"{base_url}/api/entities/landscape/action/measure-access-route"
        )
        active = next(
            item for item in active_detail["activity"] if item["kind"] == "note"
        )
        assert active["state"] == "active"
        assert {
            item["activity_type"]
            for item in active_detail["activity"]
            if item["activity_type"].startswith("core.note-")
        } == {"core.note-added", "core.note-dismissed", "core.note-reopened"}

    with database.connect() as connection:
        note_row = connection.execute(
            "SELECT body FROM entity_notes WHERE note_id = ?",
            (note["source"]["entity_id"],),
        ).fetchone()
        status_count = connection.execute(
            "SELECT count(*) FROM entity_note_status_events WHERE note_id = ?",
            (note["source"]["entity_id"],),
        ).fetchone()[0]
    assert note_row["body"] == "Accidental note"
    assert status_count == 2


def test_entity_detail_unknown_targets_and_undeclared_notes_are_rejected(tmp_path):
    application = MissionControlApplication(
        Database(tmp_path / "mission-control.db"),
        write_token="known-token",
        builtin_plugins=prepare_builtin_agenda_plugins(("landscape",)),
    )

    with running_server(application) as base_url:
        with pytest.raises(HTTPError) as missing:
            request_json(f"{base_url}/api/entities/landscape/action/not-present")
        assert missing.value.code == 404

        _, initiative = request_json(
            f"{base_url}/api/entities/landscape/initiative/equipment-access"
        )
        with pytest.raises(HTTPError) as unavailable:
            request_json(
                f"{base_url}/api/commands",
                method="POST",
                token="known-token",
                body={
                    "schema_version": "mission-control.command/v1",
                    "command_id": "note-initiative-1",
                    "target": initiative["source"],
                    "expected_revision": initiative["revision"],
                    "command": "add-note",
                    "arguments": {"body": "Should not be accepted"},
                },
            )
        assert unavailable.value.code == 400
        assert json.load(unavailable.value)["error"]["code"] == "unavailable-command"


def test_unknown_mutation_fields_are_rejected(tmp_path):
    application = MissionControlApplication(
        Database(tmp_path / "mission-control.db"),
        write_token="known-token",
    )

    with running_server(application) as base_url:
        with pytest.raises(HTTPError) as invalid:
            request_json(
                f"{base_url}/api/tasks",
                method="POST",
                body={"title": "A task", "owner": "core"},
                token="known-token",
            )
        assert invalid.value.code == 400
        document = json.load(invalid.value)
        assert document["error"]["code"] == "unknown-fields"
