from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from mission_control.contacts import ContactRepository, StaleContactRevisionError
from mission_control.database import Database
from mission_control.migrations import MigrationRunner
from mission_control.server import MissionControlApplication, build_server


def synthetic_card() -> dict[str, object]:
    return {
        "@type": "Card",
        "version": "2.0",
        "kind": "individual",
        "name": {"full": "Alex Example"},
        "emails": {
            "primary": {
                "@type": "EmailAddress",
                "address": "alex@example.invalid",
                "pref": 1,
            }
        },
        "example.invalid:retained": {"value": "synthetic-only"},
    }


@contextmanager
def running_server(application: MissionControlApplication):
    server = build_server(application, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def request_json(url, *, method="GET", body=None, token=None):
    data = None if body is None else json.dumps(body).encode()
    headers = {"Content-Type": "application/json"} if data else {}
    if token:
        headers["X-Mission-Control-Token"] = token
    request = Request(url, data=data, headers=headers, method=method)
    with urlopen(request) as response:
        return response.status, json.load(response)


def test_contact_repository_persists_standard_envelope_and_extensions(tmp_path):
    database = Database(tmp_path / "contacts.db")
    MigrationRunner(database).apply()
    repository = ContactRepository(database)

    created = repository.create(synthetic_card())
    assert created["kind"] == "contact"
    assert created["standard"] == {
        "name": "jscontact",
        "version": "2.0",
        "profile": "mission-control.jscontact/v1",
    }
    assert created["source"]["plugin_id"] == "core"
    assert created["record"]["uid"].startswith("urn:uuid:")
    assert created["revision"] == "1"

    card = json.loads(json.dumps(created["record"]))
    card["name"]["full"] = "Alex Updated"
    updated = repository.update(
        created["source"]["entity_id"], card, expected_revision="1"
    )
    assert updated["revision"] == "2"
    assert updated["record"]["example.invalid:retained"] == {
        "value": "synthetic-only"
    }
    assert updated["record"]["uid"] == created["record"]["uid"]

    reloaded = ContactRepository(database).list()
    assert reloaded == [updated]


def test_contact_repository_rejects_stale_updates_and_identity_changes(tmp_path):
    database = Database(tmp_path / "contacts.db")
    MigrationRunner(database).apply()
    repository = ContactRepository(database)
    created = repository.create(synthetic_card())
    contact_id = created["source"]["entity_id"]

    with pytest.raises(StaleContactRevisionError):
        repository.update(contact_id, created["record"], expected_revision="0")

    changed_uid = json.loads(json.dumps(created["record"]))
    changed_uid["uid"] = "urn:uuid:different"
    with pytest.raises(ValueError, match="uid cannot be changed"):
        repository.update(contact_id, changed_uid, expected_revision="1")


def test_contact_http_create_edit_and_reload(tmp_path):
    database = Database(tmp_path / "contacts.db")
    application = MissionControlApplication(database, write_token="known-token")

    with running_server(application) as base_url:
        status, created = request_json(
            f"{base_url}/api/contacts",
            method="POST",
            body={"record": synthetic_card()},
            token="known-token",
        )
        assert status == 200
        contact_id = created["source"]["entity_id"]

        edited = json.loads(json.dumps(created["record"]))
        edited["phones"] = {
            "primary": {"@type": "Phone", "number": "+1-555-0100"}
        }
        status, updated = request_json(
            f"{base_url}/api/contacts/{contact_id}",
            method="PATCH",
            body={"record": edited, "expected_revision": created["revision"]},
            token="known-token",
        )
        assert status == 200
        assert updated["record"]["phones"]["primary"]["number"] == "+1-555-0100"

        with pytest.raises(HTTPError) as stale:
            request_json(
                f"{base_url}/api/contacts/{contact_id}",
                method="PATCH",
                body={"record": edited, "expected_revision": "1"},
                token="known-token",
            )
        assert stale.value.code == 409

    restarted = MissionControlApplication(database, write_token="known-token")
    assert restarted.dashboard()["contacts"] == [updated]


def test_contact_http_requires_write_token_and_valid_card(tmp_path):
    application = MissionControlApplication(
        Database(tmp_path / "contacts.db"), write_token="known-token"
    )
    with running_server(application) as base_url:
        with pytest.raises(HTTPError) as unauthorized:
            request_json(
                f"{base_url}/api/contacts",
                method="POST",
                body={"record": synthetic_card()},
            )
        assert unauthorized.value.code == 403

        with pytest.raises(HTTPError) as invalid:
            request_json(
                f"{base_url}/api/contacts",
                method="POST",
                body={"record": {"@type": "NotACard"}},
                token="known-token",
            )
        assert invalid.value.code == 400
