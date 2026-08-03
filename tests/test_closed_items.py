from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from mission_control.closed_items import (
    ClosedItemsAggregationError,
    ClosedItemsCapabilityError,
    ClosedItemsContributionError,
    aggregate_closed_items,
    closed_items_to_list,
    contribution_to_dict,
    parse_closed_items_contribution,
    validate_closed_items_capabilities,
)
from mission_control.plugins import parse_plugin_registration


FIXTURE = (
    Path(__file__).parents[1]
    / "schema"
    / "examples"
    / "valid-landscape-closed-items.json"
)


def document() -> dict[str, object]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def registration():
    return parse_plugin_registration(
        {
            "schema_version": "mission-control.plugin/v1",
            "id": "landscape",
            "name": "Yard",
            "version": "1",
            "plugin_api": ">=1 <2",
            "capabilities": ["agenda", "closed-items", "commands"],
            "entity_types": {
                "action": {
                    "capabilities": [
                        "lifecycle.complete",
                        "lifecycle.reopen",
                    ]
                }
            },
        }
    )


def test_closed_item_contract_is_immutable_and_round_trips() -> None:
    contribution = parse_closed_items_contribution(document())

    assert contribution.provider.plugin_id.value == "landscape"
    assert contribution.items[0].revision == "2"
    assert contribution.items[0].affordances[0].capability.value == "lifecycle.reopen"
    assert contribution_to_dict(contribution) == document()
    with pytest.raises(FrozenInstanceError):
        contribution.items[0].title = "changed"  # type: ignore[misc]


def test_closed_item_contract_rejects_ambiguous_mutation_metadata() -> None:
    missing_revision = document()
    del missing_revision["items"][0]["revision"]  # type: ignore[index]
    with pytest.raises(
        ClosedItemsContributionError,
        match="mutable affordances require an opaque revision",
    ):
        parse_closed_items_contribution(missing_revision)

    duplicate = document()
    duplicate["items"].append(duplicate["items"][0])  # type: ignore[union-attr,index]
    with pytest.raises(ClosedItemsContributionError, match="duplicate closed-item id"):
        parse_closed_items_contribution(duplicate)

    read_only = document()
    del read_only["items"][0]["revision"]  # type: ignore[index]
    del read_only["items"][0]["affordances"]  # type: ignore[index]
    parsed = parse_closed_items_contribution(read_only)
    assert parsed.items[0].affordances == ()


def test_closed_items_enforce_registration_capability_envelopes() -> None:
    contribution = parse_closed_items_contribution(document())
    validate_closed_items_capabilities(registration(), contribution)

    outside_envelope = replace(
        contribution.items[0].affordances[0],
        capability=replace(
            contribution.items[0].affordances[0].capability,
            value="entity.delete",
        ),
    )
    invalid = replace(
        contribution,
        items=(replace(contribution.items[0], affordances=(outside_envelope,)),),
    )
    with pytest.raises(ClosedItemsCapabilityError, match="exceeds the registered"):
        validate_closed_items_capabilities(registration(), invalid)


def test_closed_items_aggregate_newest_first_and_reject_duplicate_providers() -> None:
    contribution = parse_closed_items_contribution(document())
    older_item = replace(
        contribution.items[0],
        item_id="older-action",
        source=replace(contribution.items[0].source, entity_id="older-action"),
        title="Older action",
        closed_at=datetime.now(UTC) - timedelta(days=1),
    )
    newer_item = replace(contribution.items[0], closed_at=datetime.now(UTC))
    contribution = replace(contribution, items=(older_item, newer_item))

    aggregate = aggregate_closed_items((contribution,))

    assert [item.item_id for item in aggregate.items] == [
        "measure-access-route",
        "older-action",
    ]
    assert closed_items_to_list(aggregate)[0]["source"]["plugin_id"] == "landscape"  # type: ignore[index]
    with pytest.raises(ClosedItemsAggregationError, match="multiple closed-item"):
        aggregate_closed_items((contribution, contribution))
