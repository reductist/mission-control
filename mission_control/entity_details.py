"""Entity-focused read models composed from plugin state and shared activity."""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from functools import lru_cache
from importlib.resources import files
from typing import Any, Protocol, cast

from jsonschema import Draft202012Validator

from mission_control.agenda import SourceRef
from mission_control.annotations import EntityNote
from mission_control.plugins import (
    Capability,
    EntityAffordance,
    EntityCapability,
    PluginId,
    PluginRegistration,
    StandardEntityCapability,
    entity_type_registration,
)


class EntityDetailContractError(ValueError):
    """An entity detail document violates the public contract."""


class EntityDetailSchemaVersion(StrEnum):
    V1 = "mission-control.entity-detail/v1"


class ActivityKind(StrEnum):
    EVENT = "event"
    NOTE = "note"


@dataclass(frozen=True, slots=True)
class DetailAttribute:
    key: str
    label: str
    value: str


@dataclass(frozen=True, slots=True)
class ActivityEntry:
    activity_id: str
    kind: ActivityKind
    activity_type: str
    summary: str
    occurred_at: datetime
    body: str | None = None
    actor: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ActivityKind):
            raise TypeError("activity kind must be an ActivityKind")
        if not isinstance(self.occurred_at, datetime):
            raise TypeError("activity occurred_at must be a datetime")
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("activity occurred_at must be timezone-aware")
        if self.kind is ActivityKind.NOTE and (
            not isinstance(self.body, str)
            or not self.body.strip()
            or not isinstance(self.actor, str)
            or not self.actor.strip()
        ):
            raise ValueError("note activity requires a nonblank body and actor")


@dataclass(frozen=True, slots=True)
class EntityDetail:
    schema_version: EntityDetailSchemaVersion
    source: SourceRef
    title: str
    attributes: tuple[DetailAttribute, ...]
    affordances: tuple[EntityAffordance, ...]
    activity: tuple[ActivityEntry, ...]
    description: str | None = None
    state: str | None = None
    revision: str | None = None


class EntityDetailProvider(Protocol):
    plugin_id: PluginId

    def entity_detail(self, target: SourceRef) -> EntityDetail | None: ...


@lru_cache(maxsize=1)
def _entity_detail_validator() -> Draft202012Validator:
    path = files("mission_control").joinpath(
        "schemas", "entity-detail.schema.json"
    )
    schema = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _assert_json_input(value: object, path: str = "$") -> None:
    if value is None or isinstance(value, (bool, int, str)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise EntityDetailContractError(
                f"{path}: non-finite numbers are not JSON values"
            )
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _assert_json_input(item, f"{path}.{index}")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise EntityDetailContractError(
                    f"{path}: JSON object keys must be strings"
                )
            _assert_json_input(item, f"{path}.{key}")
        return
    raise EntityDetailContractError(
        f"{path}: entity detail must contain only JSON values; "
        f"got {type(value).__name__}"
    )


def _validated_document(document: object) -> dict[str, Any]:
    _assert_json_input(document)
    detached = json.loads(json.dumps(document, sort_keys=True, allow_nan=False))
    if not isinstance(detached, dict):
        raise EntityDetailContractError("$: entity detail must be a JSON object")
    errors = sorted(
        _entity_detail_validator().iter_errors(detached),
        key=lambda error: (
            tuple(str(part) for part in error.absolute_path),
            error.message,
        ),
    )
    if errors:
        error = errors[0]
        path = ".".join(str(part) for part in error.absolute_path) or "$"
        raise EntityDetailContractError(f"{path}: {error.message}")
    return cast(dict[str, Any], detached)


def parse_entity_detail(document: object) -> EntityDetail:
    """Parse an untrusted entity detail document into immutable values."""

    raw = _validated_document(document)
    source = raw["source"]
    attributes = tuple(
        DetailAttribute(item["key"], item["label"], item["value"])
        for item in raw["attributes"]
    )
    affordances = tuple(
        EntityAffordance(EntityCapability(item["capability"]), item["command"])
        for item in raw["affordances"]
    )
    try:
        activity = tuple(
            ActivityEntry(
                item["activity_id"],
                ActivityKind(item["kind"]),
                item["activity_type"],
                item["summary"],
                datetime.fromisoformat(item["occurred_at"]),
                item.get("body"),
                item.get("actor"),
            )
            for item in raw["activity"]
        )
    except (TypeError, ValueError) as error:
        raise EntityDetailContractError(f"activity: {error}") from error
    detail = EntityDetail(
        EntityDetailSchemaVersion(raw["schema_version"]),
        SourceRef(
            PluginId(source["plugin_id"]),
            source["entity_type"],
            source["entity_id"],
        ),
        raw["title"],
        attributes,
        affordances,
        activity,
        raw.get("description"),
        raw.get("state"),
        raw.get("revision"),
    )
    _validate_detail_semantics(detail)
    return detail


def entity_detail_to_dict(detail: EntityDetail) -> dict[str, object]:
    """Serialize and self-validate a composed entity detail read model."""

    try:
        _validate_detail_semantics(detail)
    except EntityDetailContractError as error:
        raise AssertionError(f"invalid internal entity detail: {error}") from error
    document: dict[str, object] = {
        "schema_version": detail.schema_version.value,
        "source": {
            "plugin_id": detail.source.plugin_id.value,
            "entity_type": detail.source.entity_type,
            "entity_id": detail.source.entity_id,
        },
        "title": detail.title,
        "attributes": [
            {"key": item.key, "label": item.label, "value": item.value}
            for item in detail.attributes
        ],
        "affordances": [
            {
                "capability": item.capability.value,
                "command": item.command,
            }
            for item in detail.affordances
        ],
        "activity": [activity_entry_to_dict(item) for item in detail.activity],
    }
    if detail.description is not None:
        document["description"] = detail.description
    if detail.state is not None:
        document["state"] = detail.state
    if detail.revision is not None:
        document["revision"] = detail.revision
    try:
        return _validated_document(document)
    except EntityDetailContractError as error:
        raise AssertionError(f"invalid internal entity detail: {error}") from error


def _validate_detail_semantics(detail: EntityDetail) -> None:
    if len({item.key for item in detail.attributes}) != len(detail.attributes):
        raise EntityDetailContractError("attributes: duplicate attribute key")
    capabilities = [item.capability.value for item in detail.affordances]
    commands = [item.command for item in detail.affordances]
    if len(set(capabilities)) != len(capabilities):
        raise EntityDetailContractError("affordances: duplicate capability")
    if len(set(commands)) != len(commands):
        raise EntityDetailContractError("affordances: duplicate command")
    if len({item.activity_id for item in detail.activity}) != len(detail.activity):
        raise EntityDetailContractError("activity: duplicate activity id")
    ordered = sorted(
        detail.activity,
        key=lambda item: (item.occurred_at, item.activity_id),
    )
    if list(detail.activity) != ordered:
        raise EntityDetailContractError("activity: entries must be chronological")


def activity_entry_to_dict(entry: ActivityEntry) -> dict[str, object]:
    document: dict[str, object] = {
        "activity_id": entry.activity_id,
        "kind": entry.kind.value,
        "activity_type": entry.activity_type,
        "summary": entry.summary,
        "occurred_at": entry.occurred_at.isoformat(),
    }
    if entry.body is not None:
        document["body"] = entry.body
    if entry.actor is not None:
        document["actor"] = entry.actor
    return document


def compose_entity_detail(
    detail: EntityDetail, notes: Iterable[EntityNote]
) -> EntityDetail:
    """Merge shared immutable notes into plugin-owned activity at read time."""

    activity = [*detail.activity]
    activity.extend(
        ActivityEntry(
            activity_id=f"note:{note.note_id}",
            kind=ActivityKind.NOTE,
            activity_type="core.note-added",
            summary="Note added",
            body=note.body,
            actor=note.actor,
            occurred_at=note.occurred_at,
        )
        for note in notes
    )
    activity.sort(key=lambda item: (item.occurred_at, item.activity_id))
    return replace(detail, activity=tuple(activity))


def validate_entity_detail_capabilities(
    registration: PluginRegistration, detail: EntityDetail
) -> None:
    """Enforce the registration envelope around one detail projection."""

    if Capability.ENTITY_DETAILS not in registration.capabilities:
        raise ValueError("plugin did not declare the entity-details capability")
    if registration.plugin_id != detail.source.plugin_id:
        raise ValueError("entity detail provider does not match plugin registration")
    declared = entity_type_registration(registration, detail.source.entity_type)
    if declared is None:
        raise ValueError("entity detail uses an undeclared entity type")
    envelope = {item.value for item in declared.capabilities}
    seen_capabilities: set[str] = set()
    seen_commands: set[str] = set()
    for affordance in detail.affordances:
        if (
            affordance.capability.value not in envelope
            or affordance.capability.value in seen_capabilities
            or affordance.command in seen_commands
        ):
            raise ValueError(
                "entity detail affordances violate the registered capability envelope"
            )
        seen_capabilities.add(affordance.capability.value)
        seen_commands.add(affordance.command)
    if detail.activity and StandardEntityCapability.ACTIVITY_READ.value not in envelope:
        raise ValueError("entity detail exposed activity without activity.read")
