from __future__ import annotations

import json
from pathlib import Path

import pytest

from mission_control.builtin_plugins import prepare_builtin_agenda_plugins
from mission_control.agenda import SourceRef
from mission_control.entity_details import (
    ActivityNoteState,
    EntityDetailContractError,
    entity_detail_to_dict,
    parse_entity_detail,
    validate_entity_detail_capabilities,
)
from mission_control.plugins import PluginId


EXAMPLES = Path(__file__).parent.parent / "schema" / "examples"


def example(name: str) -> object:
    path = EXAMPLES / name
    return json.loads(path.read_text(encoding="utf-8"))


def test_entity_detail_contract_round_trips_immutable_values() -> None:
    detail = parse_entity_detail(example("valid-landscape-entity-detail.json"))

    assert detail.source.plugin_id.value == "landscape"
    assert detail.source.entity_id == "measure-access-route"
    assert detail.attributes[0].key == "timing"
    assert detail.activity[-1].body.startswith("Vertical drop")
    assert detail.activity[-1].state is ActivityNoteState.ACTIVE
    assert detail.activity[-1].source.entity_type == "annotation"
    assert detail.activity[-1].affordances[0].capability.value == "lifecycle.dismiss"
    assert entity_detail_to_dict(detail) == example(
        "valid-landscape-entity-detail.json"
    )


def test_unknown_entity_detail_fields_are_rejected() -> None:
    with pytest.raises(EntityDetailContractError, match="copied_plugin_state"):
        parse_entity_detail(example("invalid-entity-detail-key.json"))


def test_duplicate_display_and_activity_identities_are_rejected() -> None:
    document = example("valid-landscape-entity-detail.json")
    document["attributes"].append(document["attributes"][0])
    with pytest.raises(EntityDetailContractError, match="duplicate attribute"):
        parse_entity_detail(document)

    document = example("valid-landscape-entity-detail.json")
    document["activity"].append(document["activity"][0])
    with pytest.raises(EntityDetailContractError, match="duplicate activity"):
        parse_entity_detail(document)


def test_note_activity_requires_body_actor_and_timezone() -> None:
    document = example("valid-landscape-entity-detail.json")
    del document["activity"][1]["body"]
    with pytest.raises(EntityDetailContractError):
        parse_entity_detail(document)

    document = example("valid-landscape-entity-detail.json")
    document["activity"][1]["occurred_at"] = "2026-08-04T13:00:00"
    with pytest.raises(EntityDetailContractError, match="timezone-aware"):
        parse_entity_detail(document)


def test_note_activity_lifecycle_state_and_affordance_must_agree() -> None:
    document = example("valid-landscape-entity-detail.json")
    document["activity"][1]["state"] = "inactive"
    with pytest.raises(EntityDetailContractError, match="does not match"):
        parse_entity_detail(document)

    document = example("valid-landscape-entity-detail.json")
    document["activity"][1]["source"]["entity_id"] = "different-note"
    with pytest.raises(EntityDetailContractError, match="core annotation source"):
        parse_entity_detail(document)


def test_landscape_registration_envelopes_its_detail_affordances_and_activity() -> None:
    (prepared,) = prepare_builtin_agenda_plugins(("landscape",))
    detail = parse_entity_detail(example("valid-landscape-entity-detail.json"))

    with pytest.raises(ValueError, match="cannot supply core annotation"):
        validate_entity_detail_capabilities(prepared.registration, detail)
    validate_entity_detail_capabilities(
        prepared.registration, detail, allow_core_notes=True
    )


def test_plugin_activity_cannot_spoof_core_annotation_events() -> None:
    (prepared,) = prepare_builtin_agenda_plugins(("landscape",))
    document = example("valid-landscape-entity-detail.json")
    document["activity"] = [document["activity"][0]]
    document["activity"][0]["activity_type"] = "core.note-dismissed"
    detail = parse_entity_detail(document)

    with pytest.raises(ValueError, match="declared owner"):
        validate_entity_detail_capabilities(prepared.registration, detail)


def test_provider_detail_must_match_the_complete_requested_source() -> None:
    (prepared,) = prepare_builtin_agenda_plugins(("landscape",))
    document = example("valid-landscape-entity-detail.json")
    document["activity"] = [document["activity"][0]]
    detail = parse_entity_detail(document)
    requested = SourceRef(PluginId("landscape"), "action", "another-action")

    with pytest.raises(ValueError, match="different entity source"):
        validate_entity_detail_capabilities(
            prepared.registration, detail, expected_source=requested
        )
