from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from mission_control.builtin_plugins import load_builtin_agenda_contributions
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
    assert any(
        entry["id"] == "measure-access-route" for entry in dashboard["agenda"]
    )
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
            assert response.headers["Content-Security-Policy"].startswith("default-src 'self'")
        assert 'content="known-token"' in index
        assert "Mission Control" in index

        with urlopen(f"{base_url}/assets/styles.css") as response:
            assert response.headers["Content-Type"].startswith("text/css")
            assert b"--sidebar" in response.read()

        status, health = request_json(f"{base_url}/api/health")
        assert status == 200
        assert health == {"status": "ok", "version": "0.1.0"}

        status, dashboard = request_json(f"{base_url}/api/dashboard")
        assert status == 200
        assert dashboard["summary"]["open"] == 1


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
        assert [event["event_type"] for event in application.repository.history(created["id"])] == [
            "task.created",
            "task.updated",
        ]


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
