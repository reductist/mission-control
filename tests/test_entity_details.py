from __future__ import annotations

import json
from pathlib import Path

import pytest

from mission_control.builtin_plugins import prepare_builtin_agenda_plugins
from mission_control.entity_details import (
    EntityDetailContractError,
    entity_detail_to_dict,
    parse_entity_detail,
    validate_entity_detail_capabilities,
)


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


def test_landscape_registration_envelopes_its_detail_affordances_and_activity() -> None:
    (prepared,) = prepare_builtin_agenda_plugins(("landscape",))
    detail = parse_entity_detail(example("valid-landscape-entity-detail.json"))

    validate_entity_detail_capabilities(prepared.registration, detail)
