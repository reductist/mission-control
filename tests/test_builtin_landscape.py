from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest

import mission_control.builtin_plugins as builtin_plugins
from mission_control.builtin_plugins import (
    BuiltinPluginError,
    activate_builtin_agenda_plugins,
    load_builtin_agenda_contributions,
    prepare_builtin_agenda_plugins,
)
from mission_control.database import Database
from mission_control.plugins import Capability, StandardEntityCapability


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


def test_landscape_declares_its_public_command_capability() -> None:
    (prepared,) = prepare_builtin_agenda_plugins(("landscape",))

    assert prepared.registration.capabilities == (
        Capability.AGENDA,
        Capability.COMMANDS,
    )
    envelopes = {
        entity.entity_type: tuple(
            capability.value for capability in entity.capabilities
        )
        for entity in prepared.registration.entity_types
    }
    assert envelopes == {
        "action": (
            StandardEntityCapability.LIFECYCLE_COMPLETE.value,
            StandardEntityCapability.LIFECYCLE_REOPEN.value,
        ),
        "initiative": (),
    }


def test_activation_rejects_command_capability_drift(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (prepared,) = prepare_builtin_agenda_plugins(("landscape",))
    read_only_provider = SimpleNamespace(
        plugin_id=prepared.registration.plugin_id,
        command_owner=None,
    )
    implementation = SimpleNamespace(
        activate=lambda _database, _seed: read_only_provider
    )
    monkeypatch.setattr(builtin_plugins, "import_module", lambda _name: implementation)

    with pytest.raises(
        BuiltinPluginError,
        match="registration and activated command capability must match",
    ):
        activate_builtin_agenda_plugins(
            Database(tmp_path / "mission-control.db"), (prepared,)
        )


def test_activation_requires_state_dependent_affordances(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (prepared,) = prepare_builtin_agenda_plugins(("landscape",))
    owner_without_affordances = SimpleNamespace(handle=lambda _command, _context: None)
    provider = SimpleNamespace(
        plugin_id=prepared.registration.plugin_id,
        command_owner=owner_without_affordances,
    )
    implementation = SimpleNamespace(activate=lambda _database, _seed: provider)
    monkeypatch.setattr(builtin_plugins, "import_module", lambda _name: implementation)

    with pytest.raises(
        BuiltinPluginError,
        match="must expose current entity affordances",
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
