from __future__ import annotations

import copy
import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from mission_control.cli import main
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
    assert registration.capabilities == (
        Capability.CLI,
        Capability.EVENTS,
        Capability.HEALTH,
    )
    assert registration.configuration.document_version == (
        "mission-control.reference.config/v1"
    )

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
