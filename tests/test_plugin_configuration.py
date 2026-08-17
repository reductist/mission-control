from __future__ import annotations

import json
from pathlib import Path

import pytest

from mission_control.plugin_lifecycle import PluginLifecycleError, PluginResourceSource
from mission_control.plugins import (
    PluginConfigurationError,
    load_registration,
    load_plugin_configuration_bundle,
    validate_plugin_configuration,
)


ROOT = Path(__file__).parents[1]
REFERENCE_ROOT = ROOT / "plugins" / "reference"
GOOGLE_ROOT = ROOT / "mission_control" / "builtin_plugins" / "google"


def resource_reader(root: Path):
    def read(name: str) -> object:
        return json.loads((root / name).read_text(encoding="utf-8"))

    return read


def google_registration():
    return load_registration(GOOGLE_ROOT / "registration.json")


def test_configuration_bundle_preflight_does_not_require_a_complete_draft() -> None:
    registration = load_registration(REFERENCE_ROOT / "registration.json")

    bundle = load_plugin_configuration_bundle(
        registration, resource_reader(REFERENCE_ROOT)
    )

    schema, defaults, presentation = bundle.documents()
    assert schema["$id"] == "mission-control.reference.config/v1"
    assert defaults["configuration_schema"] == schema["$id"]
    assert presentation["configuration_schema"] == schema["$id"]


def test_reference_bundle_materializes_defaults_without_overwriting_values() -> None:
    registration = load_registration(REFERENCE_ROOT / "registration.json")
    reader = resource_reader(REFERENCE_ROOT)

    defaulted = validate_plugin_configuration(
        registration, reader, {"message": "hello"}, {}
    )
    explicit = validate_plugin_configuration(
        registration, reader, {"message": "hello", "repeat": 4}, {}
    )

    assert defaulted.settings.to_dict() == {"message": "hello", "repeat": 1}
    assert explicit.settings.to_dict() == {"message": "hello", "repeat": 4}


@pytest.mark.parametrize(
    ("settings", "credentials", "expected"),
    [
        (
            {
                "connections": {
                    "demo": {
                        "label": "Demo",
                        "mode": "demo",
                        "demo_anchor_date": "2026-02-31",
                        "calendars": {"mode": "defaults"},
                        "tasks": {"mode": "disabled"},
                    }
                }
            },
            {},
            "date format",
        ),
        (
            {
                "connections": {
                    "live": {
                        "label": "Live",
                        "mode": "live",
                        "credential": "missing",
                        "calendars": {"mode": "defaults"},
                        "tasks": {"mode": "disabled"},
                    }
                }
            },
            {},
            "unknown credential reference",
        ),
        (
            {
                "connections": {
                    "demo": {
                        "label": "Demo",
                        "mode": "demo",
                        "credential": "oauth",
                        "calendars": {"mode": "defaults"},
                        "tasks": {"mode": "disabled"},
                    }
                }
            },
            {"oauth": "/private/oauth.json"},
            "credential.*unknown field",
        ),
        (
            {
                "connections": {
                    "demo": {
                        "label": "Demo",
                        "mode": "demo",
                        "calendars": {"mode": "selected", "ids": []},
                        "tasks": {"mode": "disabled"},
                    }
                }
            },
            {},
            "configuration violates",
        ),
    ],
)
def test_google_cross_field_rules_are_enforced_by_generated_schema(
    settings, credentials, expected
) -> None:
    with pytest.raises(PluginConfigurationError, match=expected):
        validate_plugin_configuration(
            google_registration(),
            resource_reader(GOOGLE_ROOT),
            settings,
            credentials,
        )


def test_google_valid_date_and_credentials_materialize_effective_defaults() -> None:
    demo = validate_plugin_configuration(
        google_registration(),
        resource_reader(GOOGLE_ROOT),
        {
            "connections": {
                "demo": {
                    "label": "Demo",
                    "mode": "demo",
                    "demo_anchor_date": "2026-08-14",
                    "calendars": {"mode": "defaults"},
                    "tasks": {"mode": "all"},
                }
            }
        },
        {},
    )
    live = validate_plugin_configuration(
        google_registration(),
        resource_reader(GOOGLE_ROOT),
        {
            "connections": {
                "personal": {
                    "label": "Personal Google",
                    "mode": "live",
                    "credential": "oauth",
                    "calendars": {"mode": "selected", "ids": ["primary"]},
                    "tasks": {"mode": "disabled"},
                }
            }
        },
        {"oauth": "/private/oauth.json"},
    )

    assert demo.settings.to_dict() == {
        "connections": {
            "demo": {
                "label": "Demo",
                "mode": "demo",
                "demo_anchor_date": "2026-08-14",
                "calendars": {"mode": "defaults"},
                "tasks": {"mode": "all"},
            }
        },
        "lookahead_days": 42,
        "lookback_days": 42,
        "request_timeout_seconds": 15,
        "sync_interval_seconds": 300,
    }
    assert live.credentials == (("oauth", "/private/oauth.json"),)


def test_google_attribution_uses_core_workspace_principal_catalog() -> None:
    settings = {
        "connections": {
            "family": {
                "label": "Family Google",
                "mode": "demo",
                "calendars": {"mode": "defaults"},
                "tasks": {"mode": "disabled"},
                "attribution": {
                    "calendars": {
                        "primary": {"principal_ids": ["pat"]},
                    }
                },
            }
        }
    }

    validated = validate_plugin_configuration(
        google_registration(),
        resource_reader(GOOGLE_ROOT),
        settings,
        {},
        reference_catalogs={"workspace-principal": frozenset({"pat"})},
    )
    assert validated.settings.to_dict()["connections"]["family"]["attribution"] == {
        "calendars": {"primary": {"principal_ids": ["pat"]}}
    }

    with pytest.raises(
        PluginConfigurationError,
        match=r"/settings/connections/family/attribution/calendars/primary/principal_ids/0: unknown workspace-principal reference",
    ):
        validate_plugin_configuration(
            google_registration(),
            resource_reader(GOOGLE_ROOT),
            settings,
            {},
            reference_catalogs={"workspace-principal": frozenset()},
        )


def test_semantic_references_follow_only_the_matching_union_branch() -> None:
    documents = {
        name: json.loads((REFERENCE_ROOT / name).read_text(encoding="utf-8"))
        for name in (
            "config.schema.json",
            "config.defaults.json",
            "config.presentation.json",
        )
    }
    documents["config.schema.json"]["properties"]["settings"]["properties"][
        "message"
    ] = {
        "oneOf": [
            {"const": "ordinary"},
            {
                "type": "string",
                "const": "person-reference",
                "x-mission-control-reference": "workspace-principal",
            },
        ]
    }

    validated = validate_plugin_configuration(
        load_registration(REFERENCE_ROOT / "registration.json"),
        documents.__getitem__,
        {"message": "ordinary"},
        {},
    )

    assert validated.settings.to_dict()["message"] == "ordinary"


@pytest.mark.parametrize(
    ("resource_name", "mutation", "message"),
    [
        (
            "config.schema.json",
            lambda value: value.update({"$id": "wrong"}),
            "schema identity mismatch",
        ),
        (
            "config.schema.json",
            lambda value: value.update({"$ref": "https://example.test/schema"}),
            "only local references",
        ),
        (
            "config.schema.json",
            lambda value: value.update({"$dynamicRef": "file:///tmp/schema.json"}),
            "only local references",
        ),
        (
            "config.schema.json",
            lambda value: value["properties"]["settings"].update(
                {"$id": "https://example.test/nested"}
            ),
            "identity and dialect only at its root",
        ),
        (
            "config.schema.json",
            lambda value: value["properties"]["settings"]["properties"][
                "message"
            ].update({"x-mission-control-reference": "credential"}),
            "credential references require credentials permission",
        ),
        (
            "config.schema.json",
            lambda value: value["properties"]["settings"].update(
                {"x-mission-control-reference": "workspace-principal"}
            ),
            "semantic references must annotate a string",
        ),
        (
            "config.schema.json",
            lambda value: value["properties"]["settings"]["properties"][
                "message"
            ].update({"x-mission-control-reference": "invented-catalog"}),
            "unsupported semantic reference",
        ),
        (
            "config.defaults.json",
            lambda value: value.update({"configuration_schema": "wrong"}),
            "schema identity mismatch",
        ),
        (
            "config.defaults.json",
            lambda value: value["defaults"].update(
                {"credentials": {"token": {"file": "/tmp/token"}}}
            ),
            "credential references cannot have defaults",
        ),
        (
            "config.defaults.json",
            lambda value: value["defaults"]["settings"].update(
                {"repeat": "invalid-default"}
            ),
            "declared defaults violate",
        ),
        (
            "config.presentation.json",
            lambda value: value["fields"].append(
                {"path": "/settings/absent", "label": "Absent"}
            ),
            "field path is absent",
        ),
        (
            "config.presentation.json",
            lambda value: value["fields"][0].update(
                {"widget": "credential-file"}
            ),
            "credential fields require credentials permission",
        ),
    ],
)
def test_bundle_resources_are_bound_to_registration_and_schema(
    resource_name, mutation, message
) -> None:
    documents = {
        name: json.loads((REFERENCE_ROOT / name).read_text(encoding="utf-8"))
        for name in (
            "config.schema.json",
            "config.defaults.json",
            "config.presentation.json",
        )
    }
    mutation(documents[resource_name])

    with pytest.raises(PluginConfigurationError, match=message):
        validate_plugin_configuration(
            load_registration(REFERENCE_ROOT / "registration.json"),
            documents.__getitem__,
            {"message": "hello"},
            {},
        )


def test_missing_resource_is_rejected_without_echoing_configuration() -> None:
    registration = load_registration(REFERENCE_ROOT / "registration.json")
    secret = "never-print-this"

    def missing(_name: str) -> object:
        raise FileNotFoundError("missing bundle")

    with pytest.raises(PluginConfigurationError) as caught:
        validate_plugin_configuration(
            registration, missing, {"message": secret}, {}
        )

    assert secret not in str(caught.value)


def test_default_validation_preserves_a_property_named_required() -> None:
    documents = {
        name: json.loads((REFERENCE_ROOT / name).read_text(encoding="utf-8"))
        for name in (
            "config.schema.json",
            "config.defaults.json",
            "config.presentation.json",
        )
    }
    settings_schema = documents["config.schema.json"]["properties"]["settings"]
    settings_schema["properties"]["required"] = {"type": "string"}
    documents["config.defaults.json"]["defaults"]["settings"]["required"] = "yes"

    validated = validate_plugin_configuration(
        load_registration(REFERENCE_ROOT / "registration.json"),
        documents.__getitem__,
        {"message": "hello"},
        {},
    )

    assert validated.settings.to_dict()["required"] == "yes"


def test_filesystem_resource_symlinks_cannot_escape_plugin_root(tmp_path) -> None:
    plugin_root = tmp_path / "plugin"
    plugin_root.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    (plugin_root / "config.schema.json").symlink_to(outside)
    source = PluginResourceSource(plugin_root, str(plugin_root))

    with pytest.raises(PluginLifecycleError, match="unsafe plugin resource"):
        source.document("config.schema.json")
