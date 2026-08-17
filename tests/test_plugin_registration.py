from __future__ import annotations

import copy
import json
import shutil
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from mission_control.cli import main
from mission_control.plugin_api import PluginCallRejected
from mission_control.plugins import (
    Capability,
    EntityCapability,
    PluginCompatibilityError,
    PluginConfigurationError,
    PluginRegistrationError,
    StandardEntityCapability,
    ensure_plugin_api_compatible,
    load_registration,
    parse_plugin_registration,
    registration_to_dict,
    validate_plugin_configuration,
)


REFERENCE_ROOT = Path(__file__).parents[1] / "plugins" / "reference"
REFERENCE_REGISTRATION = REFERENCE_ROOT / "registration.json"


def reference_document() -> dict[str, object]:
    return json.loads(REFERENCE_REGISTRATION.read_text(encoding="utf-8"))


def reference_resource(name: str) -> object:
    return json.loads((REFERENCE_ROOT / name).read_text(encoding="utf-8"))


def test_reference_plugin_parses_into_immutable_domain_values():
    registration = load_registration(REFERENCE_REGISTRATION)

    assert registration.plugin_id.value == "reference"
    assert registration.capabilities == (Capability.HEALTH,)
    assert registration.configuration.document_version == (
        "mission-control.reference.config/v1"
    )
    assert registration.schema_version.value == "mission-control.plugin/v3"

    with pytest.raises(FrozenInstanceError):
        registration.name = "mutated"  # type: ignore[misc]


def test_parser_detaches_from_mutable_source_data():
    source = reference_document()
    accepted = parse_plugin_registration(source)

    source["configuration"]["schema_resource"] = "mutated.json"  # type: ignore[index]

    assert registration_to_dict(accepted)["configuration"] != source["configuration"]


def test_runtime_is_immutable_and_registration_round_trips():
    source = reference_document()
    source["runtime"] = {
        "entrypoint": "example.reference:activate",
        "migration_set": "reference",
        "agenda_seed": "agenda.json",
    }

    registration = parse_plugin_registration(source)

    assert registration.runtime is not None
    assert registration.runtime.entrypoint == "example.reference:activate"
    assert registration_to_dict(registration) == source


def test_setup_entrypoint_is_immutable_and_round_trips():
    source = reference_document()
    source["setup"] = {"entrypoint": "example.reference_setup:activate"}

    registration = parse_plugin_registration(source)

    assert registration.setup is not None
    assert registration.setup.entrypoint == "example.reference_setup:activate"
    assert registration_to_dict(registration) == source


def test_plugin_api_compatibility_is_checked_explicitly():
    source = reference_document()
    registration = parse_plugin_registration(source)

    ensure_plugin_api_compatible(registration)

    source["plugin_api"] = ">=2.0.0 <3.0.0"
    incompatible = parse_plugin_registration(source)
    with pytest.raises(PluginCompatibilityError, match="host provides 1.0.0"):
        ensure_plugin_api_compatible(incompatible)


def test_entity_capability_envelopes_are_immutable_and_round_trip():
    source = reference_document()
    source["entity_types"] = {
        "action": {
            "capabilities": [
                "lifecycle.complete",
                "lifecycle.reopen",
                "reference.record-result",
            ]
        }
    }

    registration = parse_plugin_registration(source)

    assert registration.entity_types[0].entity_type == "action"
    assert registration.entity_types[0].capabilities == (
        EntityCapability(StandardEntityCapability.LIFECYCLE_COMPLETE.value),
        EntityCapability(StandardEntityCapability.LIFECYCLE_REOPEN.value),
        EntityCapability("reference.record-result"),
    )
    assert registration_to_dict(registration) == source


@pytest.mark.parametrize(
    ("capabilities", "message"),
    [
        (["other.record-result"], "must use namespace 'reference'"),
        (["lifecycle.complete", "lifecycle.complete"], "duplicate entity capability"),
    ],
)
def test_registration_rejects_invalid_entity_capability_envelopes(
    capabilities, message
):
    source = reference_document()
    source["entity_types"] = {"action": {"capabilities": capabilities}}

    with pytest.raises(PluginRegistrationError, match=message):
        parse_plugin_registration(source)


def test_v1_argument_dsl_is_rejected():
    source = reference_document()
    source["schema_version"] = "mission-control.plugin/v1"
    source["arguments"] = {"message": {"type": "string"}}

    with pytest.raises(PluginRegistrationError, match="schema_version|Additional"):
        parse_plugin_registration(source)


def test_closed_v2_registration_is_rejected_after_setup_contract_transition():
    source = reference_document()
    source["schema_version"] = "mission-control.plugin/v2"

    with pytest.raises(PluginRegistrationError, match="schema_version"):
        parse_plugin_registration(source)


def test_non_json_registration_value_is_rejected():
    registration = reference_document()
    registration["runtime_object"] = object()

    with pytest.raises(
        PluginRegistrationError,
        match=r"^\$\.runtime_object: plugin registration must contain only JSON values",
    ):
        parse_plugin_registration(registration)


def test_plugin_configuration_uses_generated_schema_and_defaults():
    registration = load_registration(REFERENCE_REGISTRATION)

    configured = validate_plugin_configuration(
        registration, reference_resource, {"message": "hello"}, {}
    )

    assert configured.settings.to_dict() == {"message": "hello", "repeat": 1}
    assert configured.credentials == ()
    with pytest.raises(PluginConfigurationError, match="minimum|schema"):
        validate_plugin_configuration(
            registration, reference_resource, {"message": "hello", "repeat": 0}, {}
        )
    with pytest.raises(PluginConfigurationError, match="unknown field"):
        validate_plugin_configuration(
            registration,
            reference_resource,
            {"message": "hello", "secret": True},
            {},
        )


@pytest.mark.parametrize(
    ("mutation", "expected_path"),
    [
        (lambda registration: registration.update({"capabilites": ["cli"]}), "$"),
        (
            lambda registration: registration["configuration"].update(
                {"schema_resource": "../config.json"}
            ),
            "configuration.schema_resource",
        ),
        (
            lambda registration: registration.update({"capabilities": ["shell"]}),
            "capabilities.0",
        ),
    ],
)
def test_invalid_registration_is_rejected(mutation, expected_path):
    registration = reference_document()
    mutation(registration)

    with pytest.raises(PluginRegistrationError, match=expected_path.replace(".", r"\.")):
        parse_plugin_registration(registration)


def test_cli_validates_without_initializing_database(tmp_path, capsys):
    database = tmp_path / "must-not-be-created.db"

    assert main(
        [
            "--database",
            str(database),
            "plugin",
            "validate",
            str(REFERENCE_REGISTRATION),
        ]
    ) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["id"] == "reference"
    assert output == reference_document()
    assert not database.exists()


def test_cli_reports_invalid_registration(tmp_path, capsys):
    invalid = copy.deepcopy(reference_document())
    invalid["configuration"]["schema_resource"] = "../schema.json"  # type: ignore[index]
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(invalid), encoding="utf-8")

    assert main(["plugin", "validate", str(path)]) == 2
    captured = capsys.readouterr()
    assert "configuration.schema_resource" in captured.err
    assert captured.out == ""


def test_cli_conformance_runs_external_reference_through_json_adapter(
    tmp_path, capsys
):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"message": "Reference runtime ready"}), encoding="utf-8")

    assert (
        main(
            [
                "plugin",
                "conformance",
                str(REFERENCE_REGISTRATION),
                "--settings",
                str(settings),
            ]
        )
        == 0
    )

    assert json.loads(capsys.readouterr().out) == {
        "plugin_id": "reference",
        "valid": True,
        "operations": ["health.get", "runtime.describe"],
        "probed": ["health.get"],
    }


def test_cli_conformance_runs_bundled_plugins_through_the_same_adapter(
    tmp_path, capsys
) -> None:
    root = Path(__file__).parents[1] / "mission_control" / "builtin_plugins"
    google_settings = tmp_path / "google-settings.json"
    google_settings.write_text(
        json.dumps(
            {
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
        ),
        encoding="utf-8",
    )

    assert main(
        [
            "plugin",
            "conformance",
            str(root / "google" / "registration.json"),
            "--settings",
            str(google_settings),
        ]
    ) == 0
    google = json.loads(capsys.readouterr().out)
    assert google["plugin_id"] == "google-calendar"
    assert google["probed"] == ["health.get", "jobs.list"]

    assert main(
        [
            "plugin",
            "conformance",
            str(root / "landscape" / "registration.json"),
        ]
    ) == 0
    landscape = json.loads(capsys.readouterr().out)
    assert landscape["plugin_id"] == "landscape"
    assert landscape["probed"] == []


def test_cli_conformance_accepts_workspace_principal_catalog(
    tmp_path, capsys
) -> None:
    plugin_root = tmp_path / "reference"
    shutil.copytree(REFERENCE_REGISTRATION.parent, plugin_root)
    schema_path = plugin_root / "config.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    schema["properties"]["settings"]["properties"]["message"].update(
        {"x-mission-control-reference": "workspace-principal"}
    )
    schema_path.write_text(json.dumps(schema), encoding="utf-8")
    settings = tmp_path / "settings.json"
    settings.write_text('{"message":"pat"}', encoding="utf-8")
    workspace = tmp_path / "workspace.json"
    workspace.write_text(
        '{"principals":{"pat":{"label":"Pat","kind":"person"}},"accents":[]}',
        encoding="utf-8",
    )

    assert main(
        [
            "plugin",
            "conformance",
            str(plugin_root / "registration.json"),
            "--settings",
            str(settings),
            "--workspace",
            str(workspace),
        ]
    ) == 0
    assert json.loads(capsys.readouterr().out)["valid"] is True


def test_cli_conformance_sanitizes_rejection_and_still_stops_provider(
    tmp_path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"message": "hello"}), encoding="utf-8")
    stopped = False

    class RejectingProvider:
        operations = ("health.get", "runtime.describe", "runtime.stop")

        def health(self):
            raise PluginCallRejected("not-ready", "private rejection secret")

        def stop(self):
            nonlocal stopped
            stopped = True

    monkeypatch.setattr(
        "mission_control.cli.activate_plugins",
        lambda _database, _prepared: (RejectingProvider(),),
    )

    assert main(
        [
            "plugin",
            "conformance",
            str(REFERENCE_REGISTRATION),
            "--settings",
            str(settings),
        ]
    ) == 2
    captured = capsys.readouterr()
    assert "not-ready" in captured.err
    assert "private rejection secret" not in captured.err
    assert stopped is True
