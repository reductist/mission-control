from __future__ import annotations

from http import HTTPStatus

import pytest

import mission_control.plugin_lifecycle as plugin_lifecycle
from mission_control.builtin_plugins import prepare_builtin_agenda_plugins
from mission_control.database import Database
from mission_control.plugin_lifecycle import PluginLifecycleError
from mission_control.plugins import Capability, StandardEntityCapability
from mission_control.server import MissionControlApplication


def household_settings() -> dict[str, object]:
    return {
        "cases": {
            "upstairs-shower-leak": {
                "title": "Repair upstairs shower leak",
                "state": "open",
                "area": "Upstairs bathroom and kitchen",
                "summary": (
                    "Water from the upstairs shower is reaching the kitchen light below."
                ),
                "contacts": [
                    {
                        "name": "Example Plumbing",
                        "role": "Plumber",
                        "phone": "+1-555-0100",
                        "email": "service@example.invalid",
                        "website": "https://example.invalid/",
                    }
                ],
                "links": [
                    {
                        "label": "Ceiling leak photo",
                        "kind": "photo",
                        "url": "https://photos.example.invalid/shower-leak",
                    }
                ],
                "related_task_ids": ["choose-plumber"],
                "appointments": {
                    "inspection": {
                        "title": "Plumber inspection",
                        "kind": "inspection",
                        "starts_at": "2026-10-12T09:00:00-04:00",
                        "ends_at": "2026-10-12T11:00:00-04:00",
                        "detail": "Inspect the shower and affected kitchen light.",
                    }
                },
            }
        }
    }


def household_plugins():
    return prepare_builtin_agenda_plugins(
        ("household",),
        configurations={"household": household_settings()},
    )


def test_household_configuration_validates_before_runtime_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_import(_name: str):
        raise AssertionError("plugin implementation imported during preparation")

    monkeypatch.setattr(plugin_lifecycle, "import_module", unexpected_import)
    (prepared,) = household_plugins()

    assert prepared.registration.capabilities == (
        Capability.AGENDA,
        Capability.ENTITY_DETAILS,
    )
    envelopes = {
        item.entity_type: tuple(capability.value for capability in item.capabilities)
        for item in prepared.registration.entity_types
    }
    expected = (
        StandardEntityCapability.ENTITY_ANNOTATE.value,
        StandardEntityCapability.ACTIVITY_READ.value,
    )
    assert envelopes == {"appointment": expected, "case": expected}


def test_household_rejects_invalid_links_before_runtime_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = household_settings()
    cases = settings["cases"]
    assert isinstance(cases, dict)
    case = cases["upstairs-shower-leak"]
    assert isinstance(case, dict)
    links = case["links"]
    assert isinstance(links, list)
    links[0]["url"] = "javascript:alert(1)"

    def unexpected_import(_name: str):
        raise AssertionError("invalid configuration imported plugin code")

    monkeypatch.setattr(plugin_lifecycle, "import_module", unexpected_import)
    with pytest.raises(PluginLifecycleError, match="household"):
        prepare_builtin_agenda_plugins(
            ("household",), configurations={"household": settings}
        )


def test_household_projects_case_visit_contacts_links_and_durable_notes(
    tmp_path,
) -> None:
    database = Database(tmp_path / "mission-control.db")
    first = MissionControlApplication(
        database,
        write_token="known-token",
        builtin_plugins=household_plugins(),
    )

    entries = {
        item["id"]: item
        for item in first.dashboard()["agenda"]
        if item["source"]["plugin_id"] == "household"
    }
    assert set(entries) == {
        "upstairs-shower-leak",
        "upstairs-shower-leak:inspection",
    }
    assert entries["upstairs-shower-leak"]["kind"] == "initiative"
    assert entries["upstairs-shower-leak:inspection"]["timing"] == {
        "kind": "timed",
        "starts_at": "2026-10-12T09:00:00-04:00",
        "ends_at": "2026-10-12T11:00:00-04:00",
    }

    detail = first.entity_detail("household", "case", "upstairs-shower-leak")
    attributes = {item["label"]: item["value"] for item in detail["attributes"]}
    assert attributes["Area"] == "Upstairs bathroom and kitchen"
    assert attributes["Plumber"] == "Example Plumbing"
    assert attributes["Example Plumbing phone"] == "tel:+1-555-0100"
    assert attributes["Example Plumbing email"] == "mailto:service@example.invalid"
    assert attributes["Photo: Ceiling leak photo"].startswith("https://")
    assert attributes["Related task"] == "choose-plumber"
    assert detail["affordances"] == [
        {"capability": "entity.annotate", "command": "add-note"}
    ]

    status, result = first.execute_command(
        {
            "schema_version": "mission-control.command/v1",
            "command_id": "record-shower-test",
            "target": detail["source"],
            "expected_revision": detail["revision"],
            "command": "add-note",
            "arguments": {
                "body": "Ran the shower with the drain plugged; no ceiling drip appeared."
            },
        },
        authorized=True,
    )
    assert status is HTTPStatus.OK, result
    assert result["status"] == "accepted"

    restarted = MissionControlApplication(
        database,
        write_token="known-token",
        builtin_plugins=household_plugins(),
    )
    persisted = restarted.entity_detail(
        "household", "case", "upstairs-shower-leak"
    )
    note = next(item for item in persisted["activity"] if item["kind"] == "note")
    assert note["body"].startswith("Ran the shower")


def test_household_rejects_an_appointment_with_a_nonpositive_window(tmp_path) -> None:
    settings = household_settings()
    cases = settings["cases"]
    assert isinstance(cases, dict)
    case = cases["upstairs-shower-leak"]
    assert isinstance(case, dict)
    appointments = case["appointments"]
    assert isinstance(appointments, dict)
    inspection = appointments["inspection"]
    assert isinstance(inspection, dict)
    inspection["ends_at"] = inspection["starts_at"]

    prepared = prepare_builtin_agenda_plugins(
        ("household",), configurations={"household": settings}
    )
    application = MissionControlApplication(
        Database(tmp_path / "mission-control.db"), builtin_plugins=prepared
    )
    assert application.failed_plugin_activations["household"].code == "activation-failed"
