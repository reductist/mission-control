from __future__ import annotations

import pytest

from mission_control.agenda import (
    AgendaContributionError,
    parse_agenda_contribution,
    parse_agenda_query,
)


def valid_contribution() -> dict[str, object]:
    return {
        "schema_version": "mission-control.agenda/v1",
        "provider": {"plugin_id": "landscape"},
        "revision": "1",
        "generated_at": "2026-07-29T13:00:00-04:00",
        "entries": [
            {
                "id": "measure-dropoff",
                "source": {
                    "plugin_id": "landscape",
                    "entity_type": "task",
                    "entity_id": "measure-dropoff",
                },
                "title": "Measure driveway drop-off",
                "kind": "action",
                "state": "ready",
                "timing": {"kind": "anytime"},
            }
        ],
    }


def test_packaged_contribution_schema_rejects_unknown_keys():
    document = valid_contribution()
    document["entries"][0]["status"] = "ready"  # type: ignore[index]

    with pytest.raises(AgendaContributionError, match="not valid under"):
        parse_agenda_contribution(document)


def test_packaged_contribution_schema_rejects_impossible_timing_shape():
    document = valid_contribution()
    document["entries"][0]["timing"] = {  # type: ignore[index]
        "kind": "anytime",
        "due_on": "2026-08-01",
    }

    with pytest.raises(AgendaContributionError, match="not valid under"):
        parse_agenda_contribution(document)


def test_packaged_query_schema_rejects_unknown_window_keys():
    with pytest.raises(AgendaContributionError, match="Additional properties"):
        parse_agenda_query(
            {
                "schema_version": "mission-control.agenda-query/v1",
                "window": {
                    "starts_at": "2026-07-29T00:00:00-04:00",
                    "ends_at": "2026-10-31T23:59:59-04:00",
                    "timezone": "America/New_York",
                },
                "include_unscheduled": True,
                "include_initiatives": True,
            }
        )


def test_runtime_requires_timezone_aware_datetimes():
    document = valid_contribution()
    document["generated_at"] = "2026-07-29T13:00:00"

    with pytest.raises(AgendaContributionError, match="must include a UTC offset"):
        parse_agenda_contribution(document)
