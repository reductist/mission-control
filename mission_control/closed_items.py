"""Immutable cross-provider projections for currently closed entities."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from functools import lru_cache
from importlib.resources import files
from typing import Any, cast

from jsonschema import Draft202012Validator

from mission_control.agenda import ProviderRef, SourceRef
from mission_control.plugins import (
    EntityAffordance,
    EntityCapability,
    PluginId,
    PluginRegistration,
    StandardEntityCapability,
    entity_type_registration,
)
from mission_control.tasks import Task


class ClosedItemsContributionError(ValueError):
    """Untrusted closed-item data cannot enter the public read model."""


class ClosedItemsAggregationError(ValueError):
    """Closed-item provider snapshots cannot be combined unambiguously."""


class ClosedItemsCapabilityError(ClosedItemsContributionError):
    """A closed-item projection exceeds its entity capability envelope."""


class ClosedItemsSchemaVersion(StrEnum):
    V1 = "mission-control.closed-items/v1"


@dataclass(frozen=True, slots=True)
class ClosedItem:
    item_id: str
    source: SourceRef
    title: str
    state: str
    closed_at: datetime
    context: str | None = None
    detail: str | None = None
    revision: str | None = None
    affordances: tuple[EntityAffordance, ...] = ()


@dataclass(frozen=True, slots=True)
class ClosedItemsContribution:
    schema_version: ClosedItemsSchemaVersion
    provider: ProviderRef
    revision: str
    generated_at: datetime
    items: tuple[ClosedItem, ...]


@dataclass(frozen=True, slots=True)
class AggregatedClosedItems:
    contributions: tuple[ClosedItemsContribution, ...]
    items: tuple[ClosedItem, ...]


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    schema_path = files("mission_control").joinpath(
        "schemas", "closed-items-contribution.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _assert_json_input(value: object, path: str = "$") -> None:
    if value is None or isinstance(value, (bool, int, str)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ClosedItemsContributionError(
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
                raise ClosedItemsContributionError(
                    f"{path}: JSON object keys must be strings"
                )
            _assert_json_input(item, f"{path}.{key}")
        return
    raise ClosedItemsContributionError(
        f"{path}: closed-item contribution must contain only JSON values; "
        f"got {type(value).__name__}"
    )


def _validated_document(document: object) -> dict[str, Any]:
    _assert_json_input(document)
    detached = json.loads(json.dumps(document, sort_keys=True, allow_nan=False))
    if not isinstance(detached, dict):
        raise ClosedItemsContributionError(
            "$: closed-item contribution must be a JSON object"
        )
    errors = sorted(
        _validator().iter_errors(detached),
        key=lambda error: (
            tuple(str(part) for part in error.absolute_path),
            error.message,
        ),
    )
    if errors:
        error = errors[0]
        path = ".".join(str(part) for part in error.absolute_path) or "$"
        raise ClosedItemsContributionError(f"{path}: {error.message}")
    return cast(dict[str, Any], detached)


def _parse_datetime(value: str, path: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ClosedItemsContributionError(f"{path}: invalid ISO date-time") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ClosedItemsContributionError(
            f"{path}: date-time must include a UTC offset"
        )
    return parsed


def _parse_affordances(
    raw: list[Mapping[str, Any]], *, index: int, revision: str | None
) -> tuple[EntityAffordance, ...]:
    if raw and revision is None:
        raise ClosedItemsContributionError(
            f"items.{index}.affordances: mutable affordances require an opaque revision"
        )
    affordances: list[EntityAffordance] = []
    capabilities: set[str] = set()
    commands: set[str] = set()
    for affordance_index, item in enumerate(raw):
        capability = item["capability"]
        command = item["command"]
        path = f"items.{index}.affordances.{affordance_index}"
        if capability in capabilities:
            raise ClosedItemsContributionError(
                f"{path}.capability: capability {capability!r} is advertised more than once"
            )
        if command in commands:
            raise ClosedItemsContributionError(
                f"{path}.command: command {command!r} is advertised more than once"
            )
        capabilities.add(capability)
        commands.add(command)
        affordances.append(EntityAffordance(EntityCapability(capability), command))
    return tuple(affordances)


def parse_closed_items_contribution(document: object) -> ClosedItemsContribution:
    """Parse untrusted JSON-shaped data into an immutable provider snapshot."""

    raw = _validated_document(document)
    provider = ProviderRef(raw_plugin_id := PluginId(raw["provider"]["plugin_id"]))
    items: list[ClosedItem] = []
    seen: set[str] = set()
    for index, item in enumerate(raw["items"]):
        source = SourceRef(
            PluginId(item["source"]["plugin_id"]),
            item["source"]["entity_type"],
            item["source"]["entity_id"],
        )
        if source.plugin_id != raw_plugin_id:
            raise ClosedItemsContributionError(
                f"item {item['id']!r}: source plugin_id must match provider"
            )
        if item["id"] in seen:
            raise ClosedItemsContributionError(
                f"provider {raw_plugin_id.value!r} contributed duplicate closed-item id "
                f"{item['id']!r}"
            )
        seen.add(item["id"])
        revision = item.get("revision")
        items.append(
            ClosedItem(
                item_id=item["id"],
                source=source,
                title=item["title"],
                state=item["state"],
                closed_at=_parse_datetime(item["closed_at"], f"items.{index}.closed_at"),
                context=item.get("context"),
                detail=item.get("detail"),
                revision=revision,
                affordances=_parse_affordances(
                    item.get("affordances", []), index=index, revision=revision
                ),
            )
        )
    return ClosedItemsContribution(
        schema_version=ClosedItemsSchemaVersion(raw["schema_version"]),
        provider=provider,
        revision=raw["revision"],
        generated_at=_parse_datetime(raw["generated_at"], "generated_at"),
        items=tuple(items),
    )
def validate_closed_items_capabilities(
    registration: PluginRegistration, contribution: ClosedItemsContribution
) -> None:
    """Reject closed entities and affordances outside registration's envelope."""

    if contribution.provider.plugin_id != registration.plugin_id:
        raise ClosedItemsCapabilityError(
            "closed-item provider does not match the plugin registration"
        )
    for item in contribution.items:
        declared = entity_type_registration(
            registration, item.source.entity_type
        )
        if declared is None:
            raise ClosedItemsCapabilityError(
                f"item {item.item_id!r}: entity type {item.source.entity_type!r} "
                f"is not declared by plugin {registration.plugin_id.value!r}"
            )
        envelope = {capability.value for capability in declared.capabilities}
        for affordance in item.affordances:
            if affordance.capability.value not in envelope:
                raise ClosedItemsCapabilityError(
                    f"item {item.item_id!r}: affordance "
                    f"{affordance.capability.value!r} exceeds the registered "
                    f"capability envelope for {item.source.entity_type!r}"
                )


def aggregate_closed_items(
    contributions: Iterable[ClosedItemsContribution],
) -> AggregatedClosedItems:
    """Combine immutable provider snapshots into one deterministic read model."""

    snapshots = tuple(contributions)
    providers = set()
    identities = set()
    items: list[ClosedItem] = []
    for contribution in snapshots:
        provider_id = contribution.provider.plugin_id
        if provider_id in providers:
            raise ClosedItemsAggregationError(
                f"multiple closed-item snapshots supplied for provider {provider_id.value!r}"
            )
        providers.add(provider_id)
        for item in contribution.items:
            if item.source.plugin_id != provider_id:
                raise ClosedItemsAggregationError(
                    f"item {item.item_id!r} does not belong to provider {provider_id.value!r}"
                )
            identity = (provider_id, item.item_id)
            if identity in identities:
                raise ClosedItemsAggregationError(
                    f"duplicate closed-item identity {provider_id.value}:{item.item_id}"
                )
            identities.add(identity)
            items.append(item)
    return AggregatedClosedItems(
        contributions=tuple(
            sorted(snapshots, key=lambda item: item.provider.plugin_id.value)
        ),
        items=tuple(
            sorted(
                items,
                key=lambda item: (
                    -item.closed_at.timestamp(),
                    item.title.casefold(),
                    item.source.plugin_id.value,
                    item.item_id,
                ),
            )
        ),
    )


def closed_item_to_dict(item: ClosedItem) -> dict[str, object]:
    result: dict[str, object] = {
        "id": item.item_id,
        "source": {
            "plugin_id": item.source.plugin_id.value,
            "entity_type": item.source.entity_type,
            "entity_id": item.source.entity_id,
        },
        "title": item.title,
        "state": item.state,
        "closed_at": item.closed_at.isoformat(),
    }
    if item.context is not None:
        result["context"] = item.context
    if item.detail is not None:
        result["detail"] = item.detail
    if item.revision is not None:
        result["revision"] = item.revision
    if item.affordances:
        result["affordances"] = [
            {
                "capability": affordance.capability.value,
                "command": affordance.command,
            }
            for affordance in item.affordances
        ]
    return result


def closed_items_to_list(aggregate: AggregatedClosedItems) -> list[dict[str, object]]:
    return [closed_item_to_dict(item) for item in aggregate.items]


def contribution_to_dict(
    contribution: ClosedItemsContribution,
) -> dict[str, object]:
    return {
        "schema_version": contribution.schema_version.value,
        "provider": {"plugin_id": contribution.provider.plugin_id.value},
        "revision": contribution.revision,
        "generated_at": contribution.generated_at.isoformat(),
        "items": [closed_item_to_dict(item) for item in contribution.items],
    }


def project_core_closed_items(
    tasks: Iterable[Task], *, generated_at: datetime
) -> ClosedItemsContribution:
    """Project completed transitional core tasks into the shared closed-item model."""

    provider = ProviderRef(PluginId("core"))
    serializable_tasks: list[dict[str, object]] = []
    items: list[ClosedItem] = []
    reopen = EntityAffordance(
        EntityCapability(StandardEntityCapability.LIFECYCLE_REOPEN.value),
        "set-state",
    )
    for task in tasks:
        if task.state != "done":
            continue
        serializable_tasks.append(
            {
                "id": task.id,
                "title": task.title,
                "description": task.description,
                "state": task.state,
                "updated_at": task.updated_at,
            }
        )
        items.append(
            ClosedItem(
                item_id=task.id,
                source=SourceRef(provider.plugin_id, "task", task.id),
                title=task.title,
                state=task.state,
                closed_at=_parse_datetime(task.updated_at, "task.updated_at"),
                context="Core tasks",
                detail=task.description or None,
                revision=task.updated_at,
                affordances=(reopen,),
            )
        )
    revision = hashlib.sha256(
        json.dumps(
            serializable_tasks, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    return ClosedItemsContribution(
        schema_version=ClosedItemsSchemaVersion.V1,
        provider=provider,
        revision=revision,
        generated_at=generated_at,
        items=tuple(items),
    )
