"""Executable Google-resource to Mission Control agenda mapping contract."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any, Literal, cast

from mission_control.agenda import (
    Action,
    ActionState,
    AllDayTiming,
    AnytimeTiming,
    DueOnTiming,
    Event,
    SourceRef,
    TimedTiming,
    agenda_entry_to_dict,
)
from mission_control.builtin_plugins.google.domain import (
    GoogleCollection,
    GoogleEntry,
    GoogleResourceError,
    calendar_collection,
    calendar_event,
    google_task,
    task_list_collection,
)
from mission_control.plugins import (
    EntityAffordance,
    EntityCapability,
    PluginId,
    StandardEntityCapability,
)

MAPPING_SCHEMA_VERSION = "mission-control.google-mapping/v1"
PLUGIN_ID = PluginId("google-calendar")
ANNOTATE = EntityAffordance(
    EntityCapability(StandardEntityCapability.ENTITY_ANNOTATE.value), "add-note"
)

ResourceKind = Literal["calendar-event", "task"]


def agenda_entry(item: GoogleEntry) -> Event | Action:
    """Project one validated Google cache entry onto the public agenda contract."""

    source = SourceRef(PLUGIN_ID, item.entity_type, item.entity_id)
    common = {
        "entry_id": item.entity_id,
        "source": source,
        "title": item.title,
        "context": item.context,
        "detail": item.detail or item.location,
        "revision": item.revision,
        "affordances": (ANNOTATE,),
    }
    if item.entity_type == "calendar-event":
        timing = (
            AllDayTiming(item.occurs_on, item.ends_before)
            if item.timing_kind == "all-day" and item.occurs_on is not None
            else TimedTiming(_required(item.starts_at), _required(item.ends_at))
        )
        return Event(timing=timing, **common)
    timing = DueOnTiming(item.due_on) if item.due_on is not None else AnytimeTiming()
    return Action(state=ActionState.READY, timing=timing, **common)


def mapping_outcome(
    resource_kind: ResourceKind,
    collection_document: Mapping[str, Any],
    resource_document: Mapping[str, Any],
) -> dict[str, object]:
    """Return the stable, secret-free outcome used by mapping conformance cases.

    The input documents are the mapper-consumed projection of Google resources,
    not a claim to model every field that the Google APIs may return.
    """

    try:
        if resource_kind == "calendar-event":
            collection = calendar_collection(collection_document)
            item = calendar_event(collection, resource_document)
            filtered_reason = _calendar_filter_reason(resource_document)
        else:
            collection = task_list_collection(collection_document)
            item = google_task(collection, resource_document)
            filtered_reason = _task_filter_reason(resource_document)
    except GoogleResourceError:
        return {
            "schema_version": MAPPING_SCHEMA_VERSION,
            "status": "rejected",
            "code": "invalid-upstream-resource",
        }

    if item is None:
        if filtered_reason is None:  # Defensive: every production filter is named.
            raise AssertionError("Google mapper filtered a resource without a reason")
        return {
            "schema_version": MAPPING_SCHEMA_VERSION,
            "status": "filtered",
            "reason": filtered_reason,
        }

    return {
        "schema_version": MAPPING_SCHEMA_VERSION,
        "status": "mapped",
        "entry": agenda_entry_to_dict(agenda_entry(item)),
    }


def _calendar_filter_reason(document: Mapping[str, Any]) -> str | None:
    if document.get("status") == "cancelled":
        return "cancelled"
    attendees = document.get("attendees")
    if isinstance(attendees, list) and any(
        isinstance(attendee, Mapping)
        and attendee.get("self") is True
        and attendee.get("responseStatus") == "declined"
        for attendee in attendees
    ):
        return "self-declined"
    return None


def _task_filter_reason(document: Mapping[str, Any]) -> str | None:
    if document.get("deleted") is True:
        return "deleted"
    if document.get("status") == "completed":
        return "completed"
    return None


def _required(value: datetime | None) -> datetime:
    assert value is not None
    return cast(datetime, value)
