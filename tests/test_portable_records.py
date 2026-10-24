from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from mission_control.portable_records import (
    DEPENDENCY_RELATION,
    PortableRecordError,
    PortableSnapshotError,
    canonical_record_bytes,
    parse_portable_record,
    parse_portable_snapshot,
    project_task_record,
)


FIXTURES = Path(__file__).parents[1] / "schema" / "examples"


def fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_synthetic_snapshot_contains_eight_tasks_and_two_contacts():
    snapshot = parse_portable_snapshot(fixture("valid-portable-snapshot.json"))

    assert len(snapshot["records"]) == 10
    assert sum(record["kind"] == "task" for record in snapshot["records"]) == 8
    assert sum(record["kind"] == "contact" for record in snapshot["records"]) == 2


def test_open_standard_payload_round_trips_unknown_properties_exactly():
    document = fixture("valid-portable-task.json")

    encoded = canonical_record_bytes(document)
    decoded = parse_portable_record(json.loads(encoded))

    assert decoded == document
    assert decoded["record"]["futureProperty"] == {  # type: ignore[index]
        "nested": ["kept", 7, True]
    }
    assert decoded["record"]["example.com:labColor"] == "violet"  # type: ignore[index]


def test_envelope_source_and_standard_identifiers_remain_distinct():
    projection = project_task_record(fixture("valid-portable-task.json"))

    assert projection.record_id == "synthetic-task-record-01"
    assert projection.source_entity_id == "provider-task-01"
    assert projection.standard_uid == "urn:uuid:10000000-0000-4000-8000-000000000001"
    assert len({projection.record_id, projection.source_entity_id, projection.standard_uid}) == 3


def test_parent_and_dependency_relations_project_separately():
    snapshot = parse_portable_snapshot(fixture("valid-portable-snapshot.json"))
    by_id = {record["record_id"]: record for record in snapshot["records"]}

    child = project_task_record(by_id["synthetic-task-inspect"])
    dependent = project_task_record(by_id["synthetic-task-clean"])

    assert child.parent_uids == (
        "urn:uuid:20000000-0000-4000-8000-000000000001",
    )
    assert child.dependency_uids == ()
    assert dependent.parent_uids == ()
    assert dependent.dependency_uids == (
        "urn:uuid:20000000-0000-4000-8000-000000000002",
    )


def test_relation_cannot_be_both_parent_and_dependency():
    document = fixture("valid-portable-task.json")
    document["record"]["relatedTo"] = {  # type: ignore[index]
        "urn:uuid:target": {
            "@type": "Relation",
            "relation": {"parent": True, DEPENDENCY_RELATION: True},
        }
    }

    with pytest.raises(PortableRecordError, match="both parent and dependency"):
        parse_portable_record(document)


@pytest.mark.parametrize(
    ("progress", "workflow_state"),
    [
        ("in-process", "in-progress"),
        ("completed", "done"),
        ("cancelled", "canceled"),
    ],
)
def test_exact_status_mappings_are_loss_free(progress: str, workflow_state: str):
    document = fixture("valid-portable-task.json")
    document["record"]["progress"] = progress  # type: ignore[index]
    document["mc"]["workflow"]["state"] = workflow_state  # type: ignore[index]

    projection = project_task_record(document)

    assert projection.workflow_state == workflow_state
    assert not [notice for notice in projection.notices if notice.outcome == "ambiguous"]


def test_needs_action_without_mc_workflow_reports_ambiguity():
    document = fixture("valid-portable-task.json")
    document["record"]["progress"] = "needs-action"  # type: ignore[index]
    document["mc"].pop("workflow")  # type: ignore[union-attr]

    projection = project_task_record(document)

    assert projection.workflow_state is None
    assert any(
        notice.pointer == "/record/progress" and notice.outcome == "ambiguous"
        for notice in projection.notices
    )


def test_failed_progress_is_reported_even_when_mc_workflow_is_retained():
    document = fixture("valid-portable-task.json")
    document["record"]["progress"] = "failed"  # type: ignore[index]
    document["mc"]["workflow"]["state"] = "backlog"  # type: ignore[index]

    projection = project_task_record(document)

    assert projection.workflow_state == "backlog"
    assert any(
        notice.pointer == "/record/progress" and notice.outcome == "unsupported"
        for notice in projection.notices
    )


def test_unprojected_extension_is_reported_as_retained_not_dropped():
    projection = project_task_record(fixture("valid-portable-task.json"))

    retained = {notice.pointer for notice in projection.notices if notice.outcome == "retained"}
    assert "/record/futureProperty" in retained
    assert "/record/example.com:labColor" in retained


def test_projection_reports_known_standard_relationship_and_mc_omissions():
    document = fixture("valid-portable-task.json")
    document["record"]["start"] = "2026-10-31T09:00:00"  # type: ignore[index]
    document["record"]["relatedTo"] = {  # type: ignore[index]
        "urn:uuid:child": {
            "@type": "Relation",
            "relation": {"child": True},
        }
    }
    document["mc"]["workflow"].update(  # type: ignore[index]
        {"waiting_on": "Synthetic review", "review_after": "2026-10-30"}
    )

    projection = project_task_record(document)
    retained = {notice.pointer for notice in projection.notices if notice.outcome == "retained"}

    assert "/record/updated" in retained
    assert "/record/start" in retained
    assert "/record/relatedTo/urn:uuid:child/relation/child" in retained
    assert "/mc/workflow/blocked" in retained
    assert "/mc/workflow/waiting_on" in retained
    assert "/mc/workflow/review_after" in retained
    assert "/mc/planning" in retained


def test_jscontact_2_card_without_uid_is_valid_and_preserved():
    document = fixture("valid-portable-contact.json")

    parsed = parse_portable_record(document)

    assert "uid" not in parsed["record"]
    assert json.loads(canonical_record_bytes(parsed)) == document


def test_uidless_card_cannot_be_related_to_another_card():
    document = fixture("valid-portable-contact.json")
    document["record"]["relatedTo"] = {  # type: ignore[index]
        "urn:uuid:other": {"relation": {"contact": True}}
    }

    with pytest.raises(PortableRecordError, match="without uid"):
        parse_portable_record(document)


def test_uid_bearing_card_rejects_malformed_relation_without_crashing():
    document = fixture("valid-portable-contact.json")
    document["record"]["uid"] = "urn:uuid:30000000-0000-4000-8000-000000000099"  # type: ignore[index]
    document["record"]["relatedTo"] = {"urn:uuid:other": 7}  # type: ignore[index]

    with pytest.raises(PortableRecordError):
        parse_portable_record(document)


@pytest.mark.parametrize(
    "name",
    [
        "invalid-portable-record-key.json",
        "invalid-portable-task-missing-uid.json",
        "invalid-portable-task-offset-due.json",
        "invalid-portable-mc-key.json",
    ],
)
def test_negative_schema_fixtures_are_rejected(name: str):
    with pytest.raises(PortableRecordError):
        parse_portable_record(fixture(name))


def test_invalid_iana_timezone_is_rejected_by_semantic_profile():
    document = fixture("valid-portable-task.json")
    document["record"]["timeZone"] = "Mars/Olympus"  # type: ignore[index]

    with pytest.raises(PortableRecordError, match="IANA time zone"):
        parse_portable_record(document)


def test_date_like_profile_requires_local_midnight():
    document = fixture("valid-portable-task.json")
    document["record"]["showWithoutTime"] = True  # type: ignore[index]

    with pytest.raises(PortableRecordError, match="local midnight"):
        parse_portable_record(document)


def test_planning_target_is_not_repurposed_as_standard_due():
    snapshot = parse_portable_snapshot(fixture("valid-portable-snapshot.json"))
    target = next(
        record
        for record in snapshot["records"]
        if record["record_id"] == "synthetic-task-date-like"
    )

    assert "due" not in target["record"]
    assert target["mc"]["planning"] == {
        "intent": "planning-target",
        "target": "2026-11-07T00:00:00",
        "time_zone": None,
        "show_without_time": True,
    }

    target["record"]["due"] = "2026-11-07T00:00:00"
    with pytest.raises(PortableRecordError, match="must not repurpose"):
        parse_portable_record(target)


def test_snapshot_rejects_duplicate_record_and_source_identities():
    original = fixture("valid-portable-snapshot.json")
    duplicate_record = deepcopy(original)
    duplicate_record["records"][1]["record_id"] = duplicate_record["records"][0][  # type: ignore[index]
        "record_id"
    ]
    with pytest.raises(PortableSnapshotError, match="duplicate record_id"):
        parse_portable_snapshot(duplicate_record)

    duplicate_source = deepcopy(original)
    duplicate_source["records"][1]["source"] = deepcopy(  # type: ignore[index]
        duplicate_source["records"][0]["source"]  # type: ignore[index]
    )
    with pytest.raises(PortableSnapshotError, match="duplicate source identity"):
        parse_portable_snapshot(duplicate_source)


def test_snapshot_rejects_duplicate_task_uids():
    snapshot = fixture("valid-portable-snapshot.json")
    snapshot["records"][1]["record"]["uid"] = snapshot["records"][0]["record"][  # type: ignore[index]
        "uid"
    ]

    with pytest.raises(PortableSnapshotError, match="duplicate task uid"):
        parse_portable_snapshot(snapshot)


def test_snapshot_rejects_parent_cycle_without_treating_dependency_as_hierarchy():
    snapshot = fixture("valid-portable-snapshot.json")
    records = snapshot["records"]  # type: ignore[assignment]
    plan = records[0]  # type: ignore[index]
    plan["record"]["relatedTo"] = {  # type: ignore[index]
        "urn:uuid:20000000-0000-4000-8000-000000000002": {
            "@type": "Relation",
            "relation": {"parent": True},
        }
    }

    with pytest.raises(PortableSnapshotError, match="parent relationship cycle"):
        parse_portable_snapshot(snapshot)


def test_snapshot_rejects_record_observed_after_generation():
    snapshot = fixture("valid-portable-snapshot.json")
    snapshot["records"][0]["observed_at"] = "2026-10-24T10:06:00Z"  # type: ignore[index]

    with pytest.raises(PortableSnapshotError, match="cannot follow"):
        parse_portable_snapshot(snapshot)


def test_non_finite_numbers_are_not_portable_i_json():
    document = fixture("valid-portable-task.json")
    document["record"]["example.com:value"] = float("nan")  # type: ignore[index]

    with pytest.raises(PortableRecordError, match="I-JSON"):
        parse_portable_record(document)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("updated", "2026-10-24T09:00:00.0Z"),
        ("estimatedDuration", "Pbanana"),
    ],
)
def test_known_calendar_scalars_follow_rfc_8984_profile(field: str, value: str):
    document = fixture("valid-portable-task.json")
    document["record"][field] = value  # type: ignore[index]

    with pytest.raises(PortableRecordError):
        parse_portable_record(document)


def test_known_jscontact_nested_values_are_typed():
    document = fixture("valid-portable-contact.json")
    document["record"]["uid"] = "urn:uuid:30000000-0000-4000-8000-000000000098"  # type: ignore[index]
    document["record"]["emails"] = {  # type: ignore[index]
        "work": {"@type": "Phone", "address": "person@example.test", "pref": 101}
    }

    with pytest.raises(PortableRecordError):
        parse_portable_record(document)


def test_event_duration_is_optional_with_zero_default_in_rfc_profile():
    document = fixture("valid-portable-task.json")
    document["record_id"] = "synthetic-event-record"
    document["kind"] = "event"
    document["source"]["entity_type"] = "event"  # type: ignore[index]
    document["source"]["entity_id"] = "provider-event-01"  # type: ignore[index]
    document["record"] = {
        "@type": "Event",
        "uid": "urn:uuid:40000000-0000-4000-8000-000000000001",
        "updated": "2026-10-24T09:00:00Z",
        "start": "2026-11-01T09:00:00",
        "timeZone": "Europe/Zurich",
        "title": "Synthetic zero-duration event",
    }
    document["mc"] = {}

    assert "duration" not in parse_portable_record(document)["record"]
