from __future__ import annotations

from copy import deepcopy
import sys

import pytest

import mission_control.builtin_plugins as builtin_plugins
from mission_control.builtin_plugins import (
    BuiltinPluginError,
    load_builtin_agenda_contributions,
)


def test_landscape_provider_validates_real_equipment_access_work() -> None:
    assert "mission_control.builtin_plugins.landscape" not in sys.modules
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
    assert "mission_control.builtin_plugins.landscape" not in sys.modules


def test_builtin_provider_selection_rejects_duplicates() -> None:
    with pytest.raises(BuiltinPluginError, match="selected more than once"):
        load_builtin_agenda_contributions(("landscape", "landscape"))


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
