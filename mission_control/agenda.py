"""Immutable cross-provider agenda contracts and deterministic aggregation."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from functools import lru_cache
from importlib.resources import files
from typing import Any, ClassVar, TypeAlias, cast

from jsonschema import Draft202012Validator

from .plugins import PluginId
from .tasks import Task


class AgendaContributionError(ValueError):
    """Untrusted agenda data cannot be parsed into the public domain model."""


class AgendaAggregationError(ValueError):
    """Agenda provider snapshots cannot be combined without ambiguity."""


class AgendaSchemaVersion(StrEnum):
    V1 = "mission-control.agenda/v1"


class AgendaQuerySchemaVersion(StrEnum):
    V1 = "mission-control.agenda-query/v1"


class AgendaEntryKind(StrEnum):
    INITIATIVE = "initiative"
    ACTION = "action"
    EVENT = "event"


class InitiativeState(StrEnum):
    OPEN = "open"
    BLOCKED = "blocked"
    WAITING = "waiting"


class ActionState(StrEnum):
    READY = "ready"
    BLOCKED = "blocked"
    WAITING = "waiting"


class ActionTimingKind(StrEnum):
    ANYTIME = "anytime"
    DUE_ON = "due-on"
    DUE_AT = "due-at"
    WINDOW = "window"


class EventTimingKind(StrEnum):
    ALL_DAY = "all-day"
    TIMED = "timed"


@dataclass(frozen=True, slots=True, order=True)
class ProviderRef:
    plugin_id: PluginId


@dataclass(frozen=True, slots=True, order=True)
class SourceRef:
    plugin_id: PluginId
    entity_type: str
    entity_id: str


@dataclass(frozen=True, slots=True)
class AnytimeTiming:
    kind: ClassVar[ActionTimingKind] = ActionTimingKind.ANYTIME


@dataclass(frozen=True, slots=True)
class DueOnTiming:
    due_on: date
    kind: ClassVar[ActionTimingKind] = ActionTimingKind.DUE_ON


@dataclass(frozen=True, slots=True)
class DueAtTiming:
    due_at: datetime
    kind: ClassVar[ActionTimingKind] = ActionTimingKind.DUE_AT


@dataclass(frozen=True, slots=True)
class WindowTiming:
    starts_at: datetime
    ends_at: datetime
    kind: ClassVar[ActionTimingKind] = ActionTimingKind.WINDOW


ActionTiming: TypeAlias = AnytimeTiming | DueOnTiming | DueAtTiming | WindowTiming


@dataclass(frozen=True, slots=True)
class AllDayTiming:
    occurs_on: date
    kind: ClassVar[EventTimingKind] = EventTimingKind.ALL_DAY


@dataclass(frozen=True, slots=True)
class TimedTiming:
    starts_at: datetime
    ends_at: datetime
    kind: ClassVar[EventTimingKind] = EventTimingKind.TIMED


EventTiming: TypeAlias = AllDayTiming | TimedTiming


@dataclass(frozen=True, slots=True)
class Initiative:
    entry_id: str
    source: SourceRef
    title: str
    state: InitiativeState
    context: str | None = None
    detail: str | None = None
    kind: ClassVar[AgendaEntryKind] = AgendaEntryKind.INITIATIVE


@dataclass(frozen=True, slots=True)
class Action:
    entry_id: str
    source: SourceRef
    title: str
    state: ActionState
    timing: ActionTiming
    context: str | None = None
    detail: str | None = None
    kind: ClassVar[AgendaEntryKind] = AgendaEntryKind.ACTION


@dataclass(frozen=True, slots=True)
class Event:
    entry_id: str
    source: SourceRef
    title: str
    timing: EventTiming
    context: str | None = None
    detail: str | None = None
    kind: ClassVar[AgendaEntryKind] = AgendaEntryKind.EVENT


AgendaEntry: TypeAlias = Initiative | Action | Event


@dataclass(frozen=True, slots=True)
class AgendaContribution:
    schema_version: AgendaSchemaVersion
    provider: ProviderRef
    revision: str
    generated_at: datetime
    entries: tuple[AgendaEntry, ...]


@dataclass(frozen=True, slots=True)
class AgendaQuery:
    schema_version: AgendaQuerySchemaVersion
    starts_at: datetime
    ends_at: datetime
    include_unscheduled: bool
    include_initiatives: bool


@dataclass(frozen=True, slots=True)
class AggregatedAgenda:
    contributions: tuple[AgendaContribution, ...]
    entries: tuple[AgendaEntry, ...]


@lru_cache(maxsize=1)
def _agenda_query_validator() -> Draft202012Validator:
    schema_path = files("mission_control").joinpath(
        "schemas", "agenda-query.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


@lru_cache(maxsize=1)
def _agenda_validator() -> Draft202012Validator:
    schema_path = files("mission_control").joinpath(
        "schemas", "agenda-contribution.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _assert_json_input(value: object, path: str = "$") -> None:
    if value is None or isinstance(value, (bool, int, str)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise AgendaContributionError(f"{path}: non-finite numbers are not JSON values")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _assert_json_input(item, f"{path}.{index}")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise AgendaContributionError(f"{path}: JSON object keys must be strings")
            _assert_json_input(item, f"{path}.{key}")
        return
    raise AgendaContributionError(
        f"{path}: agenda contribution must contain only JSON values; "
        f"got {type(value).__name__}"
    )


def _validated_document(
    document: object, validator: Draft202012Validator | None = None
) -> dict[str, Any]:
    _assert_json_input(document)
    detached = json.loads(json.dumps(document, sort_keys=True, allow_nan=False))
    if not isinstance(detached, dict):
        raise AgendaContributionError("$: agenda contribution must be a JSON object")

    errors = sorted(
        (validator or _agenda_validator()).iter_errors(detached),
        key=lambda error: (
            tuple(str(part) for part in error.absolute_path),
            error.message,
        ),
    )
    if errors:
        error = errors[0]
        path = ".".join(str(part) for part in error.absolute_path) or "$"
        raise AgendaContributionError(f"{path}: {error.message}")
    return cast(dict[str, Any], detached)


def _parse_date(value: str, path: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise AgendaContributionError(f"{path}: invalid ISO date") from error
    if parsed.isoformat() != value:
        raise AgendaContributionError(f"{path}: date must use YYYY-MM-DD")
    return parsed


def _parse_datetime(value: str, path: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise AgendaContributionError(f"{path}: invalid ISO date-time") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AgendaContributionError(f"{path}: date-time must include a UTC offset")
    return parsed


def _parse_source(raw: Mapping[str, Any]) -> SourceRef:
    return SourceRef(
        plugin_id=PluginId(raw["plugin_id"]),
        entity_type=raw["entity_type"],
        entity_id=raw["entity_id"],
    )


def _parse_action_timing(raw: Mapping[str, Any], path: str) -> ActionTiming:
    kind = ActionTimingKind(raw["kind"])
    match kind:
        case ActionTimingKind.ANYTIME:
            return AnytimeTiming()
        case ActionTimingKind.DUE_ON:
            return DueOnTiming(_parse_date(raw["due_on"], f"{path}.due_on"))
        case ActionTimingKind.DUE_AT:
            return DueAtTiming(_parse_datetime(raw["due_at"], f"{path}.due_at"))
        case ActionTimingKind.WINDOW:
            starts_at = _parse_datetime(raw["starts_at"], f"{path}.starts_at")
            ends_at = _parse_datetime(raw["ends_at"], f"{path}.ends_at")
            if ends_at <= starts_at:
                raise AgendaContributionError(f"{path}: window must end after it starts")
            return WindowTiming(starts_at, ends_at)
    raise AssertionError(f"unhandled action timing: {kind}")


def _parse_event_timing(raw: Mapping[str, Any], path: str) -> EventTiming:
    kind = EventTimingKind(raw["kind"])
    match kind:
        case EventTimingKind.ALL_DAY:
            return AllDayTiming(_parse_date(raw["occurs_on"], f"{path}.occurs_on"))
        case EventTimingKind.TIMED:
            starts_at = _parse_datetime(raw["starts_at"], f"{path}.starts_at")
            ends_at = _parse_datetime(raw["ends_at"], f"{path}.ends_at")
            if ends_at <= starts_at:
                raise AgendaContributionError(f"{path}: event must end after it starts")
            return TimedTiming(starts_at, ends_at)
    raise AssertionError(f"unhandled event timing: {kind}")


def _parse_entry(raw: Mapping[str, Any], index: int) -> AgendaEntry:
    kind = AgendaEntryKind(raw["kind"])
    common = {
        "entry_id": raw["id"],
        "source": _parse_source(raw["source"]),
        "title": raw["title"],
        "context": raw.get("context"),
        "detail": raw.get("detail"),
    }
    match kind:
        case AgendaEntryKind.INITIATIVE:
            return Initiative(state=InitiativeState(raw["state"]), **common)
        case AgendaEntryKind.ACTION:
            return Action(
                state=ActionState(raw["state"]),
                timing=_parse_action_timing(raw["timing"], f"entries.{index}.timing"),
                **common,
            )
        case AgendaEntryKind.EVENT:
            return Event(
                timing=_parse_event_timing(raw["timing"], f"entries.{index}.timing"),
                **common,
            )
    raise AssertionError(f"unhandled agenda entry kind: {kind}")


def parse_agenda_query(document: object) -> AgendaQuery:
    """Parse a provider query horizon and unscheduled-item selection flags."""

    raw = _validated_document(document, _agenda_query_validator())
    starts_at = _parse_datetime(raw["window"]["starts_at"], "window.starts_at")
    ends_at = _parse_datetime(raw["window"]["ends_at"], "window.ends_at")
    if ends_at <= starts_at:
        raise AgendaContributionError("window: query must end after it starts")
    return AgendaQuery(
        schema_version=AgendaQuerySchemaVersion(raw["schema_version"]),
        starts_at=starts_at,
        ends_at=ends_at,
        include_unscheduled=raw["include_unscheduled"],
        include_initiatives=raw["include_initiatives"],
    )


def parse_agenda_contribution(document: object) -> AgendaContribution:
    """Parse untrusted JSON-shaped data into one immutable provider snapshot."""

    raw = _validated_document(document)
    provider = ProviderRef(PluginId(raw["provider"]["plugin_id"]))
    entries = tuple(_parse_entry(entry, index) for index, entry in enumerate(raw["entries"]))

    seen: set[str] = set()
    for entry in entries:
        if entry.source.plugin_id != provider.plugin_id:
            raise AgendaContributionError(
                f"entry {entry.entry_id!r}: source plugin_id must match provider"
            )
        if entry.entry_id in seen:
            raise AgendaContributionError(
                f"provider {provider.plugin_id.value!r} contributed duplicate agenda id "
                f"{entry.entry_id!r}"
            )
        seen.add(entry.entry_id)

    return AgendaContribution(
        schema_version=AgendaSchemaVersion(raw["schema_version"]),
        provider=provider,
        revision=raw["revision"],
        generated_at=_parse_datetime(raw["generated_at"], "generated_at"),
        entries=entries,
    )


def _datetime_text(value: datetime) -> str:
    return value.isoformat()


def _source_to_dict(source: SourceRef) -> dict[str, str]:
    return {
        "plugin_id": source.plugin_id.value,
        "entity_type": source.entity_type,
        "entity_id": source.entity_id,
    }


def _action_timing_to_dict(timing: ActionTiming) -> dict[str, object]:
    if isinstance(timing, AnytimeTiming):
        return {"kind": timing.kind.value}
    if isinstance(timing, DueOnTiming):
        return {"kind": timing.kind.value, "due_on": timing.due_on.isoformat()}
    if isinstance(timing, DueAtTiming):
        return {"kind": timing.kind.value, "due_at": _datetime_text(timing.due_at)}
    if isinstance(timing, WindowTiming):
        return {
            "kind": timing.kind.value,
            "starts_at": _datetime_text(timing.starts_at),
            "ends_at": _datetime_text(timing.ends_at),
        }
    raise AssertionError(f"unhandled action timing: {timing!r}")


def _event_timing_to_dict(timing: EventTiming) -> dict[str, object]:
    if isinstance(timing, AllDayTiming):
        return {"kind": timing.kind.value, "occurs_on": timing.occurs_on.isoformat()}
    if isinstance(timing, TimedTiming):
        return {
            "kind": timing.kind.value,
            "starts_at": _datetime_text(timing.starts_at),
            "ends_at": _datetime_text(timing.ends_at),
        }
    raise AssertionError(f"unhandled event timing: {timing!r}")


def agenda_entry_to_dict(entry: AgendaEntry) -> dict[str, object]:
    result: dict[str, object] = {
        "id": entry.entry_id,
        "kind": entry.kind.value,
        "source": _source_to_dict(entry.source),
        "title": entry.title,
    }
    if entry.context is not None:
        result["context"] = entry.context
    if entry.detail is not None:
        result["detail"] = entry.detail

    if isinstance(entry, Initiative):
        result["state"] = entry.state.value
    elif isinstance(entry, Action):
        result["state"] = entry.state.value
        result["timing"] = _action_timing_to_dict(entry.timing)
    elif isinstance(entry, Event):
        result["timing"] = _event_timing_to_dict(entry.timing)
    else:
        raise AssertionError(f"unhandled agenda entry: {entry!r}")
    return result


def contribution_to_dict(contribution: AgendaContribution) -> dict[str, object]:
    return {
        "schema_version": contribution.schema_version.value,
        "provider": {"plugin_id": contribution.provider.plugin_id.value},
        "revision": contribution.revision,
        "generated_at": _datetime_text(contribution.generated_at),
        "entries": [agenda_entry_to_dict(entry) for entry in contribution.entries],
    }


def _entry_sort_key(entry: AgendaEntry) -> tuple[str, str, str, str, str]:
    if isinstance(entry, Action):
        timing = entry.timing
        if isinstance(timing, DueOnTiming):
            when = f"0:{timing.due_on.isoformat()}"
        elif isinstance(timing, DueAtTiming):
            when = f"0:{_datetime_text(timing.due_at)}"
        elif isinstance(timing, WindowTiming):
            when = f"0:{_datetime_text(timing.starts_at)}"
        else:
            when = "1:"
    elif isinstance(entry, Event):
        timing = entry.timing
        when = (
            f"0:{timing.occurs_on.isoformat()}"
            if isinstance(timing, AllDayTiming)
            else f"0:{_datetime_text(timing.starts_at)}"
        )
    else:
        when = "2:"
    return (
        when,
        entry.kind.value,
        entry.title.casefold(),
        entry.source.plugin_id.value,
        entry.entry_id,
    )


def aggregate_agenda(contributions: Iterable[AgendaContribution]) -> AggregatedAgenda:
    """Combine immutable provider snapshots into one deterministic read model."""

    snapshots = tuple(contributions)
    providers: set[PluginId] = set()
    identities: set[tuple[PluginId, str]] = set()
    entries: list[AgendaEntry] = []

    for contribution in snapshots:
        provider_id = contribution.provider.plugin_id
        if provider_id in providers:
            raise AgendaAggregationError(
                f"multiple agenda snapshots supplied for provider {provider_id.value!r}"
            )
        providers.add(provider_id)
        for entry in contribution.entries:
            if entry.source.plugin_id != provider_id:
                raise AgendaAggregationError(
                    f"entry {entry.entry_id!r} does not belong to provider {provider_id.value!r}"
                )
            identity = (provider_id, entry.entry_id)
            if identity in identities:
                raise AgendaAggregationError(
                    f"duplicate agenda identity {provider_id.value}:{entry.entry_id}"
                )
            identities.add(identity)
            entries.append(entry)

    return AggregatedAgenda(
        contributions=tuple(sorted(snapshots, key=lambda item: item.provider.plugin_id.value)),
        entries=tuple(sorted(entries, key=_entry_sort_key)),
    )


def agenda_to_list(agenda: AggregatedAgenda) -> list[dict[str, object]]:
    return [agenda_entry_to_dict(entry) for entry in agenda.entries]


def project_core_tasks(
    tasks: Iterable[Task], *, generated_at: datetime
) -> AgendaContribution:
    """Project current core tasks through the same public agenda contract as plugins."""

    provider = ProviderRef(PluginId("core"))
    entries: list[AgendaEntry] = []
    serializable_tasks: list[dict[str, object]] = []

    for task in tasks:
        serializable_tasks.append(
            {
                "id": task.id,
                "title": task.title,
                "description": task.description,
                "state": task.state,
                "blocked": task.blocked,
                "waiting_on": task.waiting_on,
                "review_after": task.review_after,
                "updated_at": task.updated_at,
            }
        )
        if task.state == "done":
            continue

        if task.blocked:
            state = ActionState.BLOCKED
        elif task.waiting_on is not None:
            state = ActionState.WAITING
        else:
            state = ActionState.READY

        timing: ActionTiming = AnytimeTiming()
        if task.review_after is not None:
            try:
                timing = DueOnTiming(_parse_date(task.review_after, "task.review_after"))
            except AgendaContributionError:
                timing = AnytimeTiming()

        detail_parts = [part for part in (task.description, task.waiting_on) if part]
        entries.append(
            Action(
                entry_id=task.id,
                source=SourceRef(provider.plugin_id, "task", task.id),
                title=task.title,
                state=state,
                timing=timing,
                context="Core tasks",
                detail="; ".join(detail_parts) or None,
            )
        )

    revision = hashlib.sha256(
        json.dumps(serializable_tasks, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return AgendaContribution(
        schema_version=AgendaSchemaVersion.V1,
        provider=provider,
        revision=revision,
        generated_at=generated_at,
        entries=tuple(entries),
    )
