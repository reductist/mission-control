"""Validation and narrow projections for standards-aligned portable records.

The standards-native JSON object is retained intact.  The projection helper is
intentionally lossy and reports material supported-profile ambiguities and
selected retained-but-unprojected fields; it is an experiment for later adapter
work, not a persistence migration or a complete implementation of either
standard.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from importlib.resources import files
import json
import math
from typing import Any, Literal, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from jsonschema import Draft202012Validator, FormatChecker


DEPENDENCY_RELATION = "mission-control.dev:depends-on"
_EXACT_PROGRESS_TO_WORKFLOW = {
    "in-process": "in-progress",
    "completed": "done",
    "cancelled": "canceled",
}
_PROJECTED_TASK_FIELDS = frozenset(
    {
        "@type",
        "uid",
        "title",
        "description",
        "due",
        "timeZone",
        "showWithoutTime",
        "progress",
        "relatedTo",
    }
)


class PortableRecordError(ValueError):
    """A portable record violates the supported Mission Control profile."""


class PortableSnapshotError(ValueError):
    """A portable snapshot is invalid or internally ambiguous."""


@dataclass(frozen=True, slots=True)
class MappingNotice:
    pointer: str
    outcome: Literal["retained", "normalized", "ambiguous", "unsupported"]
    explanation: str


@dataclass(frozen=True, slots=True)
class TaskProjection:
    record_id: str
    source_entity_id: str
    standard_uid: str
    title: str
    description: str
    due: str | None
    time_zone: str | None
    show_without_time: bool
    workflow_state: str | None
    parent_uids: tuple[str, ...]
    dependency_uids: tuple[str, ...]
    sibling_order: int | None
    notices: tuple[MappingNotice, ...]


@lru_cache(maxsize=2)
def _validator(schema_name: str) -> Draft202012Validator:
    schema_path = files("mission_control").joinpath("schemas", schema_name)
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _detached_json(document: object, *, error_type: type[ValueError]) -> dict[str, Any]:
    try:
        encoded = json.dumps(
            document,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        detached = json.loads(encoded)
    except (TypeError, ValueError) as error:
        raise error_type(f"document is not I-JSON compatible: {error}") from error
    if not isinstance(detached, dict):
        raise error_type("document must be a JSON object")
    return detached


def _validate_schema(
    document: dict[str, Any], schema_name: str, *, error_type: type[ValueError]
) -> None:
    errors = sorted(_validator(schema_name).iter_errors(document), key=lambda item: list(item.path))
    if errors:
        error = errors[0]
        pointer = "/" + "/".join(str(part) for part in error.absolute_path)
        raise error_type(f"{pointer or '/'}: {error.message}")


def _parse_utc(value: str, pointer: str, *, error_type: type[ValueError]) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise error_type(f"{pointer} must be a valid UTC date-time") from error
    if not value.endswith("Z") or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise error_type(f"{pointer} must use the UTC Z designator")
    return parsed


def _validate_local(value: str, pointer: str, *, error_type: type[ValueError]) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise error_type(f"{pointer} must be a valid local date-time") from error
    if parsed.tzinfo is not None:
        raise error_type(f"{pointer} must not contain a UTC offset")
    return parsed


def _validate_time_zone(value: object, pointer: str, *, error_type: type[ValueError]) -> None:
    if value is None:
        return
    try:
        ZoneInfo(str(value))
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise error_type(f"{pointer} must name an installed IANA time zone or be null") from error


def _semantic_record(document: dict[str, Any], *, error_type: type[ValueError]) -> None:
    kind = document["kind"]
    standard = document["standard"]
    record = document["record"]
    mc = document["mc"]
    expected = {
        "task": ("jscalendar", "Task"),
        "event": ("jscalendar", "Event"),
        "contact": ("jscontact", "Card"),
    }[kind]
    actual = (standard["name"], record["@type"])
    if actual != expected:
        raise error_type(
            f"/kind {kind!r} requires standard/type {expected!r}, got {actual!r}"
        )

    _parse_utc(document["observed_at"], "/observed_at", error_type=error_type)
    for key in ("created", "updated", "progressUpdated"):
        if key in record:
            _parse_utc(record[key], f"/record/{key}", error_type=error_type)
    for key in ("due", "start"):
        if key in record:
            parsed = _validate_local(record[key], f"/record/{key}", error_type=error_type)
            if record.get("showWithoutTime") and parsed.time().isoformat() != "00:00:00":
                raise error_type(
                    f"/record/{key} must be local midnight when showWithoutTime is true"
                )
    if "timeZone" in record:
        _validate_time_zone(record["timeZone"], "/record/timeZone", error_type=error_type)

    if kind == "contact" and "uid" not in record:
        if "members" in record or "relatedTo" in record:
            raise error_type(
                "a JSContact 2.0 Card without uid cannot use members or relatedTo"
            )

    workflow = mc.get("workflow")
    planning = mc.get("planning")
    if kind != "task" and any(key in mc for key in ("workflow", "planning", "sibling_order")):
        raise error_type("workflow, planning, and sibling_order metadata are task-only")
    if planning and planning["intent"] == "planning-target":
        if "due" in record:
            raise error_type(
                "planning-target intent must not repurpose /record/due as a soft target"
            )
        _validate_local(planning["target"], "/mc/planning/target", error_type=error_type)
        _validate_time_zone(
            planning["time_zone"], "/mc/planning/time_zone", error_type=error_type
        )
    if planning and planning["intent"] == "hard-deadline" and "due" not in record:
        raise error_type("hard-deadline intent requires /record/due")

    progress = record.get("progress")
    if workflow and progress in _EXACT_PROGRESS_TO_WORKFLOW:
        expected_state = _EXACT_PROGRESS_TO_WORKFLOW[progress]
        if workflow["state"] != expected_state:
            raise error_type(
                f"/mc/workflow/state must be {expected_state!r} for progress {progress!r}"
            )
    if workflow and progress == "needs-action" and workflow["state"] not in {
        "backlog",
        "ready",
    }:
        raise error_type("needs-action only maps to backlog or ready in this profile")

    for target, relation in record.get("relatedTo", {}).items():
        if not isinstance(relation, Mapping):
            raise error_type(f"/record/relatedTo/{target} must be an object")
        relation_types = relation.get("relation", {})
        if "parent" in relation_types and DEPENDENCY_RELATION in relation_types:
            raise error_type(
                f"/record/relatedTo/{target} cannot be both parent and dependency"
            )


def parse_portable_record(document: object) -> dict[str, Any]:
    """Validate and detach one portable record without normalizing its payload."""

    detached = _detached_json(document, error_type=PortableRecordError)
    _validate_schema(
        detached, "portable-record.schema.json", error_type=PortableRecordError
    )
    _semantic_record(detached, error_type=PortableRecordError)
    return detached


def canonical_record_bytes(document: object) -> bytes:
    """Return deterministic UTF-8 JSON while preserving all record properties."""

    parsed = parse_portable_record(document)
    return json.dumps(
        parsed,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def parse_portable_snapshot(document: object) -> dict[str, Any]:
    """Validate a snapshot and its cross-record identity/hierarchy invariants."""

    detached = _detached_json(document, error_type=PortableSnapshotError)
    _validate_schema(
        detached, "portable-snapshot.schema.json", error_type=PortableSnapshotError
    )
    generated_at = _parse_utc(
        detached["generated_at"], "/generated_at", error_type=PortableSnapshotError
    )
    window = detached["selection"].get("window")
    if window:
        starts_at = _parse_utc(
            window["starts_at"],
            "/selection/window/starts_at",
            error_type=PortableSnapshotError,
        )
        ends_at = _parse_utc(
            window["ends_at"],
            "/selection/window/ends_at",
            error_type=PortableSnapshotError,
        )
        if starts_at >= ends_at:
            raise PortableSnapshotError("selection window must end after it starts")

    record_ids: set[str] = set()
    source_ids: set[tuple[str, str, str]] = set()
    task_by_uid: dict[str, dict[str, Any]] = {}
    for index, record in enumerate(detached["records"]):
        try:
            _semantic_record(record, error_type=PortableSnapshotError)
        except PortableSnapshotError as error:
            raise PortableSnapshotError(f"/records/{index}: {error}") from error
        if record["record_id"] in record_ids:
            raise PortableSnapshotError(f"duplicate record_id: {record['record_id']}")
        record_ids.add(record["record_id"])
        source_key = (
            record["source"]["plugin_id"],
            record["source"]["entity_type"],
            record["source"]["entity_id"],
        )
        if source_key in source_ids:
            raise PortableSnapshotError(f"duplicate source identity: {source_key!r}")
        source_ids.add(source_key)
        observed_at = _parse_utc(
            record["observed_at"],
            f"/records/{index}/observed_at",
            error_type=PortableSnapshotError,
        )
        if observed_at > generated_at:
            raise PortableSnapshotError("record observed_at cannot follow snapshot generated_at")
        if record["kind"] == "task":
            uid = record["record"]["uid"]
            if uid in task_by_uid:
                raise PortableSnapshotError(f"duplicate task uid: {uid}")
            task_by_uid[uid] = record

    parent_edges: dict[str, str] = {}
    for uid, envelope in task_by_uid.items():
        for target, relation in envelope["record"].get("relatedTo", {}).items():
            if relation.get("relation", {}).get("parent") and target in task_by_uid:
                if uid in parent_edges:
                    raise PortableSnapshotError(f"task {uid!r} has more than one parent")
                parent_edges[uid] = target
    for uid in parent_edges:
        seen: set[str] = set()
        current = uid
        while current in parent_edges:
            if current in seen:
                raise PortableSnapshotError(f"parent relationship cycle includes {current!r}")
            seen.add(current)
            current = parent_edges[current]
    return detached


def project_task_record(document: object) -> TaskProjection:
    """Project the supported task subset and make non-projected data explicit."""

    parsed = parse_portable_record(document)
    if parsed["kind"] != "task":
        raise PortableRecordError("task projection requires kind 'task'")
    record = parsed["record"]
    mc = parsed["mc"]
    notices: list[MappingNotice] = []
    workflow = mc.get("workflow")
    workflow_state = workflow["state"] if workflow else None
    progress = record.get("progress")
    if workflow_state is None:
        if progress in _EXACT_PROGRESS_TO_WORKFLOW:
            workflow_state = _EXACT_PROGRESS_TO_WORKFLOW[progress]
        elif progress == "needs-action":
            notices.append(
                MappingNotice(
                    "/record/progress",
                    "ambiguous",
                    "needs-action does not distinguish Mission Control backlog from ready",
                )
            )
    if progress == "failed" or (
        isinstance(progress, str)
        and progress not in {*_EXACT_PROGRESS_TO_WORKFLOW, "needs-action"}
    ):
        notices.append(
            MappingNotice(
                "/record/progress",
                "unsupported",
                "Mission Control has no exact workflow state for this JSCalendar progress",
            )
        )

    parents: list[str] = []
    dependencies: list[str] = []
    for target, relation in record.get("relatedTo", {}).items():
        relation_types = relation.get("relation", {})
        if relation_types.get("parent"):
            parents.append(target)
        if relation_types.get(DEPENDENCY_RELATION):
            dependencies.append(target)
        for relation_type in sorted(relation_types):
            if relation_type not in {"parent", DEPENDENCY_RELATION}:
                notices.append(
                    MappingNotice(
                        f"/record/relatedTo/{target}/relation/{relation_type}",
                        "retained",
                        "relationship is preserved but not represented in the task projection",
                    )
                )

    if record.get("showWithoutTime") and record.get("due"):
        notices.append(
            MappingNotice(
                "/record/due",
                "normalized",
                "MC profile interprets local midnight plus showWithoutTime as date-like",
            )
        )
    for key in sorted(set(record) - _PROJECTED_TASK_FIELDS):
        notices.append(
            MappingNotice(
                f"/record/{key}",
                "retained",
                "not represented in the task projection; preserved in the portable record",
            )
        )
    for key in ("blocked", "waiting_on", "review_after"):
        if workflow and key in workflow:
            notices.append(
                MappingNotice(
                    f"/mc/workflow/{key}",
                    "retained",
                    "workflow detail is preserved but not represented in the task projection",
                )
            )
    if "planning" in mc and mc["planning"]["intent"] != "none":
        notices.append(
            MappingNotice(
                "/mc/planning",
                "retained",
                "planning intent is preserved but not represented in the task projection",
            )
        )

    return TaskProjection(
        record_id=parsed["record_id"],
        source_entity_id=parsed["source"]["entity_id"],
        standard_uid=record["uid"],
        title=record.get("title", ""),
        description=record.get("description", ""),
        due=record.get("due"),
        time_zone=record.get("timeZone"),
        show_without_time=record.get("showWithoutTime", False),
        workflow_state=workflow_state,
        parent_uids=tuple(sorted(parents)),
        dependency_uids=tuple(sorted(dependencies)),
        sibling_order=mc.get("sibling_order"),
        notices=tuple(notices),
    )
