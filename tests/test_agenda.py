from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from mission_control.agenda import (
    Action,
    ActionState,
    AgendaAggregationError,
    AgendaCapabilityError,
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
    validate_agenda_capabilities,
    validate_agenda_attribution,
)
from mission_control.attribution import AttributionCatalog, AttributionCatalogError
from mission_control.plugins import (
    EntityAffordance,
    EntityCapability,
    parse_plugin_registration,
    registration_to_dict,
)
from mission_control.tasks import Task


def contribution_document(plugin_id: str = "landscape") -> dict[str, object]:
    return {
        "schema_version": "mission-control.agenda/v2",
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
                "attribution": {"principal_ids": []},
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
                "attribution": {"principal_ids": []},
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
                "attribution": {"principal_ids": []},
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


def test_parse_and_serialize_state_dependent_affordances():
    document = contribution_document()
    action = document["entries"][1]  # type: ignore[index]
    action["revision"] = "7"
    action["affordances"] = [
        {"capability": "lifecycle.complete", "command": "complete"}
    ]

    contribution = parse_agenda_contribution(document)
    parsed = contribution.entries[1]

    assert parsed.affordances == (
        EntityAffordance(EntityCapability("lifecycle.complete"), "complete"),
    )
    assert agenda_to_list(aggregate_agenda((contribution,)))[1]["affordances"] == [
        {"capability": "lifecycle.complete", "command": "complete"}
    ]


def test_affordances_require_revision_and_unambiguous_mappings():
    document = contribution_document()
    action = document["entries"][1]  # type: ignore[index]
    action["affordances"] = [
        {"capability": "lifecycle.complete", "command": "complete"}
    ]
    with pytest.raises(AgendaContributionError, match="require an opaque revision"):
        parse_agenda_contribution(document)

    action["revision"] = "1"
    action["affordances"].append(  # type: ignore[union-attr]
        {"capability": "lifecycle.complete", "command": "finish"}
    )
    with pytest.raises(AgendaContributionError, match="advertised more than once"):
        parse_agenda_contribution(document)


def test_registration_envelopes_bound_projected_entity_types_and_affordances():
    registration = parse_plugin_registration(
        {
            "schema_version": "mission-control.plugin/v2",
            "id": "landscape",
            "name": "Landscape",
            "version": "1",
            "plugin_api": ">=1 <2",
            "capabilities": ["agenda", "commands"],
            "configuration": {
                "document_version": "mission-control.landscape.config/v1",
                "schema_resource": "config.schema.json",
                "defaults_resource": "config.defaults.json",
                "presentation_resource": "config.presentation.json",
            },
            "entity_types": {
                "initiative": {"capabilities": []},
                "task": {"capabilities": ["lifecycle.complete"]},
                "visit": {"capabilities": []},
            },
        }
    )
    document = contribution_document()
    action = document["entries"][1]  # type: ignore[index]
    action["revision"] = "1"
    action["affordances"] = [
        {"capability": "lifecycle.complete", "command": "complete"}
    ]
    contribution = parse_agenda_contribution(document)

    validate_agenda_capabilities(registration, contribution)

    registration_without_task = parse_plugin_registration(
        {
            **registration_to_dict(registration),
            "entity_types": {
                "initiative": {"capabilities": []},
                "visit": {"capabilities": []},
            },
        }
    )
    with pytest.raises(AgendaCapabilityError, match="entity type 'task'"):
        validate_agenda_capabilities(registration_without_task, contribution)

    registration_without_complete = parse_plugin_registration(
        {
            **registration_to_dict(registration),
            "entity_types": {
                "initiative": {"capabilities": []},
                "task": {"capabilities": []},
                "visit": {"capabilities": []},
            },
        }
    )
    with pytest.raises(AgendaCapabilityError, match="exceeds the registered"):
        validate_agenda_capabilities(registration_without_complete, contribution)


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


def test_multi_day_all_day_event_preserves_exclusive_end_date():
    document = contribution_document()
    event = document["entries"][2]  # type: ignore[index]
    event["timing"] = {  # type: ignore[index]
        "kind": "all-day",
        "occurs_on": "2026-08-14",
        "ends_before": "2026-08-23",
    }

    contribution = parse_agenda_contribution(document)
    serialized = agenda_to_list(aggregate_agenda((contribution,)))

    assert serialized[0]["timing"] == event["timing"]
    event["timing"]["ends_before"] = "2026-08-14"  # type: ignore[index]
    with pytest.raises(AgendaContributionError, match="all-day event must end after"):
        parse_agenda_contribution(document)


def test_timed_entries_sort_by_instant_across_utc_offsets():
    document = contribution_document()
    document["entries"] = [  # type: ignore[index]
        {
            "id": "new-york",
            "source": {
                "plugin_id": "landscape",
                "entity_type": "visit",
                "entity_id": "new-york",
            },
            "title": "New York later",
            "attribution": {"principal_ids": []},
            "kind": "event",
            "timing": {
                "kind": "timed",
                "starts_at": "2026-08-14T08:00:00-04:00",
                "ends_at": "2026-08-14T09:00:00-04:00",
            },
        },
        {
            "id": "zurich",
            "source": {
                "plugin_id": "landscape",
                "entity_type": "visit",
                "entity_id": "zurich",
            },
            "title": "Zürich earlier",
            "attribution": {"principal_ids": []},
            "kind": "event",
            "timing": {
                "kind": "timed",
                "starts_at": "2026-08-14T09:00:00+02:00",
                "ends_at": "2026-08-14T10:00:00+02:00",
            },
        },
    ]

    contribution = parse_agenda_contribution(document)

    assert [entry.entry_id for entry in aggregate_agenda((contribution,)).entries] == [
        "zurich",
        "new-york",
    ]


def test_provider_ownership_and_duplicate_ids_are_enforced():
    document = contribution_document()
    document["entries"][0]["source"]["plugin_id"] = "other"  # type: ignore[index]
    with pytest.raises(AgendaContributionError, match="must match provider"):
        parse_agenda_contribution(document)

    document = contribution_document()
    document["entries"][1]["id"] = "access-plan"  # type: ignore[index]
    with pytest.raises(AgendaContributionError, match="duplicate agenda id"):
        parse_agenda_contribution(document)


def test_attribution_is_typed_scoped_and_independent_of_authoritative_source():
    first = contribution_document("google-calendar")
    first_entry = first["entries"][0]  # type: ignore[index]
    first_entry["attribution"] = {
        "principal_ids": ["patrik", "family"],
        "integration": {
            "connection": {"id": "personal", "label": "Personal Google"},
            "collection": {"id": "shared", "kind": "calendar", "label": "Family"},
        },
    }
    second = contribution_document("google-calendar")
    second_entry = second["entries"][0]  # type: ignore[index]
    second_entry["attribution"] = {
        "principal_ids": [],
        "integration": {
            "connection": {"id": "household", "label": "Household Google"},
            "collection": {"id": "shared", "kind": "calendar", "label": "Family"},
        },
    }

    first_parsed = parse_agenda_contribution(first).entries[0]
    second_parsed = parse_agenda_contribution(second).entries[0]

    assert first_parsed.source == second_parsed.source
    assert first_parsed.attribution.integration is not None
    assert second_parsed.attribution.integration is not None
    assert (
        first_parsed.attribution.integration.collection
        != second_parsed.attribution.integration.collection
    )
    assert [item.principal_id for item in first_parsed.attribution.principals] == [
        "patrik",
        "family",
    ]

    third = contribution_document("outlook-calendar")
    third_entry = third["entries"][0]  # type: ignore[index]
    third_entry["attribution"] = {
        "principal_ids": [],
        "integration": {
            "connection": {"id": "personal", "label": "Personal Outlook"},
            "collection": {"id": "shared", "kind": "calendar", "label": "Family"},
        },
    }
    third_parsed = parse_agenda_contribution(third).entries[0]
    assert third_parsed.attribution.integration is not None
    assert (
        first_parsed.attribution.integration.collection
        != third_parsed.attribution.integration.collection
    )


def test_attribution_rejects_duplicates_unknown_principals_and_display_escape_hatches():
    document = contribution_document()
    document["entries"][0]["attribution"] = {  # type: ignore[index]
        "principal_ids": ["patrik", "patrik"]
    }
    with pytest.raises(AgendaContributionError, match="must be unique"):
        parse_agenda_contribution(document)

    document = contribution_document()
    document["entries"][0]["attribution"] = {  # type: ignore[index]
        "principal_ids": ["missing"]
    }
    contribution = parse_agenda_contribution(document)
    with pytest.raises(AttributionCatalogError, match="unknown workspace principals"):
        validate_agenda_attribution(contribution, AttributionCatalog())

    document = contribution_document()
    document["entries"][0]["attribution"] = {  # type: ignore[index]
        "principal_ids": [], "color": "red"
    }
    with pytest.raises(AgendaContributionError, match="not valid under any"):
        parse_agenda_contribution(document)

    for integration in (
        {"connection": {"id": "home", "label": "   "}},
        {
            "connection": {"id": "home", "label": "Home"},
            "collection": {"id": "family", "kind": "calendar", "label": "\t"},
        },
    ):
        document = contribution_document()
        document["entries"][0]["attribution"] = {  # type: ignore[index]
            "principal_ids": [], "integration": integration
        }
        with pytest.raises(AgendaContributionError, match="not valid under any"):
            parse_agenda_contribution(document)


@pytest.mark.parametrize(
    "version", ("mission-control.agenda/v1", "mission-control.agenda/v3")
)
def test_agenda_v2_rejects_other_contract_versions(version):
    document = contribution_document()
    document["schema_version"] = version
    with pytest.raises(AgendaContributionError, match="was expected"):
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
