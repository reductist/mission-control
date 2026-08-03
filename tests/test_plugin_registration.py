from __future__ import annotations

import copy
import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from mission_control.cli import main
from mission_control.plugins import (
    ArgumentType,
    ArrayArgument,
    Capability,
    EntityCapability,
    JsonArray,
    ObjectArgument,
    PluginRegistrationError,
    load_registration,
    parse_plugin_registration,
    registration_to_dict,
    StandardEntityCapability,
)


REFERENCE_REGISTRATION = (
    Path(__file__).parents[1] / "plugins" / "reference" / "registration.json"
)


def reference_document() -> dict[str, object]:
    return json.loads(REFERENCE_REGISTRATION.read_text(encoding="utf-8"))


def test_reference_plugin_parses_into_immutable_domain_values():
    registration = load_registration(REFERENCE_REGISTRATION)

    assert registration.plugin_id.value == "reference"
    assert registration.capabilities == (
        Capability.CLI,
        Capability.EVENTS,
        Capability.HEALTH,
    )
    assert tuple(argument.name for argument in registration.arguments) == (
        "message",
        "repeat",
    )

    with pytest.raises(FrozenInstanceError):
        registration.name = "mutated"  # type: ignore[misc]


def test_parser_detaches_from_mutable_source_data():
    source = reference_document()
    accepted = parse_plugin_registration(source)

    source["arguments"]["message"]["description"] = "mutated after parsing"  # type: ignore[index]

    assert registration_to_dict(accepted)["arguments"]["message"]["description"] != (
        source["arguments"]["message"]["description"]  # type: ignore[index]
    )


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


def test_nested_argument_definitions_and_array_defaults_become_immutable():
    source = reference_document()
    source["arguments"] = {
        "settings": {
            "type": "object",
            "properties": {
                "labels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "default": ["one", "two"],
                }
            },
        }
    }

    registration = parse_plugin_registration(source)
    settings = registration.arguments[0].definition

    assert isinstance(settings, ObjectArgument)
    labels = settings.properties[0].definition
    assert isinstance(labels, ArrayArgument)
    assert labels.kind is ArgumentType.ARRAY
    assert labels.default == JsonArray(("one", "two"))
    assert registration_to_dict(registration)["arguments"] == source["arguments"]


def test_non_json_registration_value_is_rejected():
    registration = reference_document()
    registration["runtime_object"] = object()

    with pytest.raises(
        PluginRegistrationError,
        match=r"^\$\.runtime_object: plugin registration must contain only JSON values",
    ):
        parse_plugin_registration(registration)


@pytest.mark.parametrize(
    ("mutation", "expected_path"),
    [
        (lambda registration: registration.update({"capabilites": ["cli"]}), "$"),
        (
            lambda registration: registration["arguments"]["repeat"].update(
                {"minimum": "one"}
            ),
            "arguments.repeat",
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
    invalid["arguments"]["repeat"]["minimum"] = "one"  # type: ignore[index]
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(invalid), encoding="utf-8")

    assert main(["plugin", "validate", str(path)]) == 2
    captured = capsys.readouterr()
    assert "arguments.repeat" in captured.err
    assert captured.out == ""
