from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

import pytest

import mission_control.plugin_lifecycle as builtin_plugins
from mission_control.agenda import SourceRef
from mission_control.builtin_plugins import (
    BuiltinPluginError,
    activate_builtin_agenda_plugins,
    load_builtin_agenda_contributions,
    prepare_builtin_agenda_plugins,
)
from mission_control.database import Database
from mission_control.plugin_api import CapabilityRouter, PluginCallContractError
from mission_control.plugins import Capability, PluginId, StandardEntityCapability


def test_landscape_provider_validates_real_equipment_access_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_import(_name: str):
        raise AssertionError("plugin implementation imported before activation")

    monkeypatch.setattr(builtin_plugins, "import_module", unexpected_import)
    (contribution,) = load_builtin_agenda_contributions(("landscape",))

    assert contribution.provider.plugin_id.value == "landscape"
    assert contribution.revision == "equipment-access-v1"
    assert len({entry.entry_id for entry in contribution.entries}) == len(
        contribution.entries
    )
    assert {entry.entry_id for entry in contribution.entries} == {
        "equipment-access",
        "measure-access-route",
        "define-equipment-envelope",
        "compare-access-concepts",
        "prepare-fall-leaf-workflow",
    }
    assert any(getattr(entry, "state", None).value == "blocked" for entry in contribution.entries)
    assert sum(getattr(getattr(entry, "timing", None), "kind", None) == "window" for entry in contribution.entries) == 2


def test_builtin_provider_selection_rejects_duplicates() -> None:
    with pytest.raises(BuiltinPluginError, match="selected more than once"):
        load_builtin_agenda_contributions(("landscape", "landscape"))


def test_manifest_compatibility_is_rejected_before_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_document = builtin_plugins._document
    imported = False

    def incompatible_registration(plugin_id: str, name: str) -> object:
        document = deepcopy(original_document(plugin_id, name))
        if name == "registration.json":
            document["plugin_api"] = ">=2.0.0 <3.0.0"
        return document

    def unexpected_import(_name: str):
        nonlocal imported
        imported = True
        raise AssertionError("incompatible plugin implementation imported")

    monkeypatch.setattr(builtin_plugins, "_document", incompatible_registration)
    monkeypatch.setattr(builtin_plugins, "import_module", unexpected_import)

    with pytest.raises(BuiltinPluginError, match="host provides 1.0.0"):
        prepare_builtin_agenda_plugins(("landscape",))
    assert imported is False


def test_landscape_declares_its_public_command_capability() -> None:
    (prepared,) = prepare_builtin_agenda_plugins(("landscape",))

    assert prepared.registration.capabilities == (
        Capability.AGENDA,
        Capability.CLOSED_ITEMS,
        Capability.COMMANDS,
        Capability.ENTITY_DETAILS,
    )
    envelopes = {
        entity.entity_type: tuple(
            capability.value for capability in entity.capabilities
        )
        for entity in prepared.registration.entity_types
    }
    assert envelopes == {
        "action": (
            StandardEntityCapability.ENTITY_ANNOTATE.value,
            StandardEntityCapability.ACTIVITY_READ.value,
            StandardEntityCapability.LIFECYCLE_COMPLETE.value,
            StandardEntityCapability.LIFECYCLE_REOPEN.value,
        ),
        "initiative": (StandardEntityCapability.ACTIVITY_READ.value,),
    }


def test_executable_runtime_cannot_claim_a_capability_without_a_call_adapter(
    tmp_path,
) -> None:
    (prepared,) = prepare_builtin_agenda_plugins(("landscape",))
    unsupported = replace(
        prepared,
        registration=replace(
            prepared.registration,
            capabilities=(*prepared.registration.capabilities, Capability.UI),
        ),
    )

    with pytest.raises(BuiltinPluginError, match="without a public call adapter"):
        activate_builtin_agenda_plugins(
            Database(tmp_path / "mission-control.db"), (unsupported,)
        )


def test_activation_rejects_missing_declared_runtime_operations(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (prepared,) = prepare_builtin_agenda_plugins(("landscape",))
    operations = {
        "agenda.snapshot": lambda _inputs: {},
        "closed-items.snapshot": lambda _inputs: {},
        "entity-details.get": lambda _inputs: None,
    }
    implementation = type(
        "Implementation",
        (),
        {"activate": staticmethod(lambda _context: CapabilityRouter("landscape", operations))},
    )
    monkeypatch.setattr(builtin_plugins, "import_module", lambda _name: implementation)

    with pytest.raises(
        BuiltinPluginError,
        match="missing operations required by its manifest",
    ):
        activate_builtin_agenda_plugins(
            Database(tmp_path / "mission-control.db"), (prepared,)
        )


def test_activation_rejects_operations_outside_manifest_capabilities(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (prepared,) = prepare_builtin_agenda_plugins(("landscape",))
    operations = {
        "agenda.snapshot": lambda _inputs: {},
        "closed-items.snapshot": lambda _inputs: {},
        "commands.execute": lambda _inputs: {},
        "commands.state": lambda _inputs: None,
        "entity-details.get": lambda _inputs: None,
        "health.get": lambda _inputs: {},
    }
    implementation = type(
        "Implementation",
        (),
        {"activate": staticmethod(lambda _context: CapabilityRouter("landscape", operations))},
    )
    monkeypatch.setattr(builtin_plugins, "import_module", lambda _name: implementation)

    with pytest.raises(
        BuiltinPluginError,
        match="operations outside its manifest capabilities",
    ):
        activate_builtin_agenda_plugins(
            Database(tmp_path / "mission-control.db"), (prepared,)
        )


def test_activation_sanitizes_a_hostile_handler_shape(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (prepared,) = prepare_builtin_agenda_plugins(("landscape",))

    class HostileHandler:
        def __getattribute__(self, name):
            if name == "call":
                raise RuntimeError("private handler inspection secret")
            return super().__getattribute__(name)

    implementation = type(
        "Implementation",
        (),
        {"activate": staticmethod(lambda _context: HostileHandler())},
    )
    monkeypatch.setattr(builtin_plugins, "import_module", lambda _name: implementation)

    with pytest.raises(BuiltinPluginError) as caught:
        activate_builtin_agenda_plugins(
            Database(tmp_path / "mission-control.db"), (prepared,)
        )

    assert "plugin activation failed (RuntimeError)" in str(caught.value)
    assert "private handler inspection secret" not in str(caught.value)


def test_adapter_rejects_malformed_state_dependent_affordances(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (prepared,) = prepare_builtin_agenda_plugins(("landscape",))
    operations = {
        "agenda.snapshot": lambda _inputs: {},
        "closed-items.snapshot": lambda _inputs: {},
        "commands.execute": lambda _inputs: {},
        "commands.state": lambda _inputs: {"revision": "missing-contract-fields"},
        "entity-details.get": lambda _inputs: None,
    }
    implementation = type(
        "Implementation",
        (),
        {"activate": staticmethod(lambda _context: CapabilityRouter("landscape", operations))},
    )
    monkeypatch.setattr(builtin_plugins, "import_module", lambda _name: implementation)

    (provider,) = activate_builtin_agenda_plugins(
        Database(tmp_path / "mission-control.db"), (prepared,)
    )

    with pytest.raises(PluginCallContractError, match="command target state"):
        provider.command_state(SourceRef(PluginId("landscape"), "action", "unknown"))


def test_activation_requires_a_json_capability_handler(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (prepared,) = prepare_builtin_agenda_plugins(("landscape",))
    implementation = type(
        "Implementation",
        (),
        {"activate": staticmethod(lambda _context: object())},
    )
    monkeypatch.setattr(builtin_plugins, "import_module", lambda _name: implementation)

    with pytest.raises(
        BuiltinPluginError,
        match="must return a JSON capability handler",
    ):
        activate_builtin_agenda_plugins(
            Database(tmp_path / "mission-control.db"), (prepared,)
        )


def test_invalid_registration_is_reported_as_a_named_builtin_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_document = builtin_plugins._document

    def invalid_registration(plugin_id: str, name: str) -> object:
        if name == "registration.json":
            return {"broken": True}
        return original_document(plugin_id, name)

    monkeypatch.setattr(builtin_plugins, "_document", invalid_registration)

    with pytest.raises(BuiltinPluginError, match=r"^landscape:"):
        load_builtin_agenda_contributions(("landscape",))


def test_invalid_agenda_is_reported_as_a_named_builtin_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_document = builtin_plugins._document

    def invalid_agenda(plugin_id: str, name: str) -> object:
        if name == "agenda.json":
            return {"broken": True}
        return original_document(plugin_id, name)

    monkeypatch.setattr(builtin_plugins, "_document", invalid_agenda)

    with pytest.raises(BuiltinPluginError, match=r"^landscape:"):
        load_builtin_agenda_contributions(("landscape",))


def test_registration_and_provider_ids_must_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_document = builtin_plugins._document

    def mismatched_agenda(plugin_id: str, name: str) -> object:
        document = deepcopy(original_document(plugin_id, name))
        if name == "agenda.json":
            document["provider"]["plugin_id"] = "other"
            for entry in document["entries"]:
                entry["source"]["plugin_id"] = "other"
        return document

    monkeypatch.setattr(builtin_plugins, "_document", mismatched_agenda)

    with pytest.raises(
        BuiltinPluginError,
        match="registration and agenda provider ids must match",
    ):
        load_builtin_agenda_contributions(("landscape",))


def test_registration_must_declare_every_projected_entity_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_document = builtin_plugins._document

    def incomplete_registration(plugin_id: str, name: str) -> object:
        document = deepcopy(original_document(plugin_id, name))
        if name == "registration.json":
            del document["entity_types"]["action"]
        return document

    monkeypatch.setattr(builtin_plugins, "_document", incomplete_registration)

    with pytest.raises(BuiltinPluginError, match="entity type 'action' is not declared"):
        load_builtin_agenda_contributions(("landscape",))
