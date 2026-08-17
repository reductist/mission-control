from __future__ import annotations

import json
from pathlib import Path

from mission_control.builtin_plugins.google.mapping import mapping_outcome


def test_google_mapping_cases_match_the_production_projection() -> None:
    statuses: set[str] = set()
    resource_kinds: set[str] = set()
    examples = Path(__file__).parents[1] / "schema" / "google" / "examples"
    for path in (
        examples / "valid-mapping-cases.json",
        examples / "valid-mapping-additive-fields.json",
    ):
        document = json.loads(path.read_text(encoding="utf-8"))
        for case in document["cases"]:
            resource_kind = case["resource_kind"]
            outcome = mapping_outcome(
                resource_kind,
                case["input"]["collection"],
                case["input"]["resource"],
            )
            assert outcome == case["outcome"], case["name"]
            statuses.add(outcome["status"])
            resource_kinds.add(resource_kind)

    assert statuses == {"mapped", "filtered", "rejected"}
    assert resource_kinds == {"calendar-event", "task"}


def test_calendar_and_task_list_ids_use_distinct_public_namespaces() -> None:
    calendar = mapping_outcome(
        "calendar-event",
        {"id": "shared", "summary": "Calendar", "accessRole": "owner"},
        {
            "id": "event",
            "summary": "Event",
            "status": "confirmed",
            "start": {"date": "2026-08-14"},
            "end": {"date": "2026-08-15"},
            "updated": "2026-08-14T12:00:00Z",
            "etag": "event-v1",
        },
    )
    task = mapping_outcome(
        "task",
        {"id": "shared", "title": "Tasks"},
        {
            "id": "task",
            "title": "Task",
            "status": "needsAction",
            "updated": "2026-08-14T12:00:00Z",
            "etag": "task-v1",
        },
    )

    calendar_id = calendar["entry"]["attribution"]["integration"]["collection"]["id"]
    task_id = task["entry"]["attribution"]["integration"]["collection"]["id"]
    assert calendar_id == "calendar:shared"
    assert task_id == "task-list:shared"
