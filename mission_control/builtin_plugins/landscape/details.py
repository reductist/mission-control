"""Landscape-owned entity details and domain activity projection."""

from __future__ import annotations

import json

from mission_control.agenda import SourceRef
from mission_control.builtin_plugins.landscape.capabilities import action_affordances
from mission_control.builtin_plugins.landscape.domain import (
    LandscapeAction,
    LandscapeAnytime,
    LandscapeDueAt,
    LandscapeDueOn,
    LandscapeEntityKind,
    LandscapeEvent,
    LandscapeInitiative,
    LandscapeWindow,
)
from mission_control.builtin_plugins.landscape.repository import (
    PLUGIN_ID,
    LandscapeRepository,
)
from mission_control.entity_details import (
    ActivityEntry,
    ActivityKind,
    DetailAttribute,
    EntityDetail,
    EntityDetailSchemaVersion,
)


def entity_detail(
    repository: LandscapeRepository, target: SourceRef
) -> EntityDetail | None:
    """Project one current Landscape entity without copying its state into core."""

    if target.plugin_id != PLUGIN_ID:
        return None
    try:
        if target.entity_type == LandscapeEntityKind.ACTION.value:
            entity = repository.get_action(target.entity_id)
            return _action_detail(repository, target, entity)
        if target.entity_type == LandscapeEntityKind.INITIATIVE.value:
            entity = repository.get_initiative(target.entity_id)
            return _initiative_detail(repository, target, entity)
    except KeyError:
        return None
    return None


def _action_detail(
    repository: LandscapeRepository,
    target: SourceRef,
    action: LandscapeAction,
) -> EntityDetail:
    attributes = [
        DetailAttribute("timing", "Timing", _timing_label(action)),
    ]
    if action.context is not None:
        attributes.append(DetailAttribute("context", "Context", action.context))
    return EntityDetail(
        schema_version=EntityDetailSchemaVersion.V1,
        source=target,
        title=action.title,
        description=action.detail,
        state=action.state.value,
        revision=action.revision,
        attributes=tuple(attributes),
        affordances=action_affordances(action),
        activity=_activity(
            repository.history(LandscapeEntityKind.ACTION, action.action_id)
        ),
    )


def _initiative_detail(
    repository: LandscapeRepository,
    target: SourceRef,
    initiative: LandscapeInitiative,
) -> EntityDetail:
    attributes = ()
    if initiative.context is not None:
        attributes = (DetailAttribute("context", "Context", initiative.context),)
    return EntityDetail(
        schema_version=EntityDetailSchemaVersion.V1,
        source=target,
        title=initiative.title,
        description=initiative.detail,
        state=initiative.state.value,
        revision=initiative.revision,
        attributes=attributes,
        affordances=(),
        activity=_activity(
            repository.history(
                LandscapeEntityKind.INITIATIVE, initiative.initiative_id
            )
        ),
    )


def _activity(events: tuple[LandscapeEvent, ...]) -> tuple[ActivityEntry, ...]:
    return tuple(_activity_entry(event) for event in events)


def _activity_entry(event: LandscapeEvent) -> ActivityEntry:
    payload = json.loads(event.payload_json)
    if event.event_type.endswith("-imported"):
        state = payload.get("state", "initial state")
        summary = f"Imported in {state} state"
    elif event.event_type == "landscape.action-state-changed":
        before = payload.get("from")
        after = payload.get("to")
        summary = (
            f"State changed from {before} to {after}"
            if isinstance(before, str) and isinstance(after, str)
            else event.event_type
        )
    else:
        summary = event.event_type
    return ActivityEntry(
        activity_id=f"landscape:{event.event_id}",
        kind=ActivityKind.EVENT,
        activity_type=event.event_type,
        summary=summary,
        occurred_at=event.occurred_at,
    )


def _timing_label(action: LandscapeAction) -> str:
    timing = action.timing
    if isinstance(timing, LandscapeAnytime):
        return "Anytime"
    if isinstance(timing, LandscapeDueOn):
        return f"Due {timing.due_on.isoformat()}"
    if isinstance(timing, LandscapeDueAt):
        return f"Due {timing.due_at.isoformat()}"
    if isinstance(timing, LandscapeWindow):
        return (
            f"{timing.starts_at.date().isoformat()} to "
            f"{timing.ends_at.date().isoformat()}"
        )
    raise AssertionError(f"unsupported Landscape timing: {timing!r}")
