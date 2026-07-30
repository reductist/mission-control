from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from mission_control.agenda import (
    Action,
    ActionState,
    AgendaAggregationError,
    AgendaContributionError,
    AnytimeTiming,
    DueOnTiming,
    Event,
    Initiative,
    aggregate_agenda,
    agenda_to_list,
    parse_agenda_contribution,
    parse_agenda_query,
    project_core_tasks,
)
from mission_control.tasks import Task


def contribution_document(plugin_id: str = "landscape") -> dict[str, object]:
    return {
        "schema_version": "mission-control.agenda/v1",
        "provider": {"plugin_id": plugin_id},
        "revision": "revision-1",
        "generated_at": "2026-07-29T12:00:00-04:00",
        "entries": [
            {
                "id": "access-plan",
                "source": {
                    "plugin_id": plugin_id,
                    "entity_type": "initiative",
                    "entity_id": "access-plan",
                },
                "title": "Improve backyard equipment access",
                "kind": "initiative",
                "state": "open",
            },
            {
                "id": "measure-dropoff",
                "source": {
                    "plugin_id": plugin_id,
                    "entity_type": "task",
                    "entity_id": "measure-dropoff",
                },
                "title": "Measure driveway drop-off",
                "kind": "action",
                "state": "ready",
                "timing": {"kind": "anytime"},
            },
            {
                "id": "contractor-visit",
                "source": {
                    "plugin_id": plugin_id,
                    "entity_type": "visit",
                    "entity_id": "contractor-visit",
                },
                "title": "Contractor site visit",
                "kind": "event",
                "timing": {
                    "kind": "timed",
                    "starts_at": "2026-08-01T10:00:00-04:00",
                    "ends_at": "2026-08-01T11:00:00-04:00",
                },
            },
        ],
    }


def test_parse_tagged_agenda_variants_into_frozen_values():
    contribution = parse_agenda_contribution(contribution_document())

    assert isinstance(contribution.entries[0], Initiative)
    assert isinstance(contribution.entries[1], Action)
    assert isinstance(contribution.entries[1].timing, AnytimeTiming)
    assert isinstance(contribution.entries[2], Event)
    with pytest.raises(FrozenInstanceError):
        contribution.revision = "changed"  # type: ignore[misc]


def test_query_horizon_and_selection_flags_are_explicit():
    query = parse_agenda_query(
        {
            "schema_version": "mission-control.agenda-query/v1",
            "window": {
                "starts_at": "2026-07-29T00:00:00-04:00",
                "ends_at": "2026-10-31T23:59:59-04:00",
            },
            "include_unscheduled": True,
            "include_initiatives": True,
        }
    )

    assert query.include_unscheduled is True
    assert query.include_initiatives is True
    assert query.ends_at > query.starts_at


def test_query_and_occurrence_windows_must_move_forward():
    with pytest.raises(AgendaContributionError, match="query must end after"):
        parse_agenda_query(
            {
                "schema_version": "mission-control.agenda-query/v1",
                "window": {
                    "starts_at": "2026-08-01T00:00:00Z",
                    "ends_at": "2026-08-01T00:00:00Z",
                },
                "include_unscheduled": False,
                "include_initiatives": False,
            }
        )

    document = contribution_document()
    event = document["entries"][2]  # type: ignore[index]
    event["timing"]["ends_at"] = "2026-08-01T09:00:00-04:00"  # type: ignore[index]
    with pytest.raises(AgendaContributionError, match="event must end after"):
        parse_agenda_contribution(document)


def test_provider_ownership_and_duplicate_ids_are_enforced():
    document = contribution_document()
    document["entries"][0]["source"]["plugin_id"] = "other"  # type: ignore[index]
    with pytest.raises(AgendaContributionError, match="must match provider"):
        parse_agenda_contribution(document)

    document = contribution_document()
    document["entries"][1]["id"] = "access-plan"  # type: ignore[index]
    with pytest.raises(AgendaContributionError, match="duplicate agenda id"):
        parse_agenda_contribution(document)


def test_aggregate_is_deterministic_and_rejects_duplicate_providers():
    landscape = parse_agenda_contribution(contribution_document("landscape"))
    maintenance_document = contribution_document("home-maintenance")
    maintenance_document["entries"] = maintenance_document["entries"][1:2]  # type: ignore[index]
    maintenance = parse_agenda_contribution(maintenance_document)

    first = aggregate_agenda((landscape, maintenance))
    second = aggregate_agenda((maintenance, landscape))

    assert agenda_to_list(first) == agenda_to_list(second)
    assert [entry.kind.value for entry in first.entries] == [
        "event",
        "action",
        "action",
        "initiative",
    ]
    with pytest.raises(AgendaAggregationError, match="multiple agenda snapshots"):
        aggregate_agenda((landscape, landscape))


def test_core_tasks_project_through_the_same_contract():
    ready = Task(
        id="ready-task",
        title="Review agenda contract",
        description="Keep the aggregate read-only",
        state="ready",
        blocked=False,
        waiting_on=None,
        review_after="2026-08-02",
        created_at="2026-07-29T00:00:00+00:00",
        updated_at="2026-07-29T00:00:00+00:00",
    )
    blocked = Task(
        id="blocked-task",
        title="Wait for schema review",
        description="",
        state="in-progress",
        blocked=True,
        waiting_on="reviewer",
        review_after=None,
        created_at="2026-07-29T00:00:00+00:00",
        updated_at="2026-07-29T00:00:00+00:00",
    )
    done = Task(
        id="done-task",
        title="Do not show completed work",
        description="",
        state="done",
        blocked=False,
        waiting_on=None,
        review_after=None,
        created_at="2026-07-29T00:00:00+00:00",
        updated_at="2026-07-29T00:00:00+00:00",
    )

    contribution = project_core_tasks(
        (blocked, done, ready), generated_at=datetime.now(UTC)
    )

    assert contribution.provider.plugin_id.value == "core"
    assert [entry.entry_id for entry in contribution.entries] == [
        "blocked-task",
        "ready-task",
    ]
    assert isinstance(contribution.entries[1], Action)
    assert contribution.entries[0].state is ActionState.BLOCKED
    assert isinstance(contribution.entries[1].timing, DueOnTiming)
