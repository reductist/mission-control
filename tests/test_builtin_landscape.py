from __future__ import annotations

import sys

import pytest

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
