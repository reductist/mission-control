"""Versioned command contracts and single-owner dispatch."""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from enum import StrEnum
from functools import lru_cache
from importlib.resources import files
from typing import Any, Protocol, TypeAlias, cast

from jsonschema import Draft202012Validator

from mission_control.agenda import SourceRef
from mission_control.plugins import (
    EntityAffordance,
    EntityCapability,
    PluginId,
    PluginRegistration,
    entity_type_registration,
)
from mission_control.tasks import TASK_STATES, StaleTaskRevisionError, TaskRepository


class CommandContractError(ValueError):
    """An untrusted command document does not satisfy the public contract."""


class CommandSchemaVersion(StrEnum):
    V1 = "mission-control.command/v1"


class CommandResultSchemaVersion(StrEnum):
    V1 = "mission-control.command-result/v1"


class CommandStatus(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    CONFLICTED = "conflicted"
    STALE = "stale"
    UNAUTHORIZED = "unauthorized"
    FAILED = "failed"


JsonScalar: TypeAlias = None | bool | int | float | str


@dataclass(frozen=True, slots=True)
class JsonArray:
    values: tuple[JsonValue, ...]


@dataclass(frozen=True, slots=True)
class JsonObject:
    values: tuple[tuple[str, JsonValue], ...]


JsonValue: TypeAlias = JsonScalar | JsonArray | JsonObject


@dataclass(frozen=True, slots=True)
class CommandEnvelope:
    schema_version: CommandSchemaVersion
    command_id: str
    target: SourceRef
    expected_revision: str
    command: str
    arguments: JsonObject


@dataclass(frozen=True, slots=True)
class CommandError:
    code: str
    detail: str


@dataclass(frozen=True, slots=True)
class Accepted:
    command_id: str
    target: SourceRef
    revision: str
    result: JsonObject = JsonObject(())
    status: CommandStatus = CommandStatus.ACCEPTED


@dataclass(frozen=True, slots=True)
class Rejected:
    command_id: str
    target: SourceRef
    error: CommandError
    status: CommandStatus = CommandStatus.REJECTED


@dataclass(frozen=True, slots=True)
class Conflicted:
    command_id: str
    target: SourceRef
    current_revision: str
    error: CommandError
    status: CommandStatus = CommandStatus.CONFLICTED


@dataclass(frozen=True, slots=True)
class Stale:
    command_id: str
    target: SourceRef
    current_revision: str
    error: CommandError
    status: CommandStatus = CommandStatus.STALE


@dataclass(frozen=True, slots=True)
class Unauthorized:
    command_id: str
    target: SourceRef
    error: CommandError
    status: CommandStatus = CommandStatus.UNAUTHORIZED


@dataclass(frozen=True, slots=True)
class Failed:
    command_id: str
    target: SourceRef
    error: CommandError
    status: CommandStatus = CommandStatus.FAILED


CommandOutcome: TypeAlias = (
    Accepted | Rejected | Conflicted | Stale | Unauthorized | Failed
)


@dataclass(frozen=True, slots=True)
class CommandContext:
    actor: str


@dataclass(frozen=True, slots=True)
class CommandTargetState:
    revision: str
    affordances: tuple[EntityAffordance, ...]


class CommandOwner(Protocol):
    def handle(
        self, command: CommandEnvelope, context: CommandContext
    ) -> CommandOutcome: ...


@lru_cache(maxsize=1)
def _command_validator() -> Draft202012Validator:
    schema = _schema_document("command-envelope.schema.json")
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


@lru_cache(maxsize=1)
def _result_validator() -> Draft202012Validator:
    schema = _schema_document("command-result.schema.json")
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _schema_document(name: str) -> dict[str, Any]:
    path = files("mission_control").joinpath("schemas", name)
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise AssertionError(  # noqa: TRY004 - this is a packaged-data invariant
            f"packaged {name} must contain a JSON object"
        )
    return cast(dict[str, Any], document)


def _validated_document(
    document: object, validator: Draft202012Validator
) -> dict[str, Any]:
    _assert_json_input(document)
    detached = json.loads(json.dumps(document, sort_keys=True, allow_nan=False))
    if not isinstance(detached, dict):
        raise CommandContractError("$: command must be a JSON object")
    errors = sorted(
        validator.iter_errors(detached),
        key=lambda error: (
            tuple(str(part) for part in error.absolute_path),
            error.message,
        ),
    )
    if errors:
        error = errors[0]
        path = ".".join(str(part) for part in error.absolute_path) or "$"
        raise CommandContractError(f"{path}: {error.message}")
    return cast(dict[str, Any], detached)


def _assert_json_input(value: object, path: str = "$") -> None:
    if value is None or isinstance(value, (bool, int, str)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CommandContractError(
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
                raise CommandContractError(f"{path}: JSON object keys must be strings")
            _assert_json_input(item, f"{path}.{key}")
        return
    raise CommandContractError(
        f"{path}: command must contain only JSON values; got {type(value).__name__}"
    )


def _freeze_json(value: Any) -> JsonValue:
    if isinstance(value, dict):
        return JsonObject(
            tuple((key, _freeze_json(item)) for key, item in sorted(value.items()))
        )
    if isinstance(value, list):
        return JsonArray(tuple(_freeze_json(item) for item in value))
    return cast(JsonScalar, value)


def _thaw_json(value: JsonValue) -> object:
    if isinstance(value, JsonObject):
        return {key: _thaw_json(item) for key, item in value.values}
    if isinstance(value, JsonArray):
        return [_thaw_json(item) for item in value.values]
    return value


def freeze_json_object(value: Mapping[str, object]) -> JsonObject:
    """Freeze a trusted JSON-shaped result without exposing mutable containers."""

    _assert_json_input(value)
    return cast(JsonObject, _freeze_json(dict(value)))


def thaw_json_object(value: JsonObject) -> object:
    """Return a detached JSON object for a validated command handler."""

    return _thaw_json(value)


def parse_command(document: object) -> CommandEnvelope:
    """Parse an untrusted command into an immutable value."""

    raw = _validated_document(document, _command_validator())
    target = raw["target"]
    return CommandEnvelope(
        schema_version=CommandSchemaVersion(raw["schema_version"]),
        command_id=raw["command_id"],
        target=SourceRef(
            PluginId(target["plugin_id"]),
            target["entity_type"],
            target["entity_id"],
        ),
        expected_revision=raw["expected_revision"],
        command=raw["command"],
        arguments=cast(JsonObject, _freeze_json(raw["arguments"])),
    )


def outcome_to_dict(outcome: CommandOutcome) -> dict[str, object]:
    """Serialize and self-validate a structured command result."""

    result: dict[str, object] = {
        "schema_version": CommandResultSchemaVersion.V1.value,
        "command_id": outcome.command_id,
        "target": _source_to_dict(outcome.target),
        "status": outcome.status.value,
    }
    if isinstance(outcome, Accepted):
        result["revision"] = outcome.revision
        thawed = _thaw_json(outcome.result)
        if thawed:
            result["result"] = thawed
    else:
        result["error"] = asdict(outcome.error)
        if isinstance(outcome, (Conflicted, Stale)):
            result["current_revision"] = outcome.current_revision

    try:
        return _validated_document(result, _result_validator())
    except CommandContractError as error:
        raise AssertionError(f"invalid internal command outcome: {error}") from error


def _source_to_dict(source: SourceRef) -> dict[str, str]:
    return {
        "plugin_id": source.plugin_id.value,
        "entity_type": source.entity_type,
        "entity_id": source.entity_id,
    }


class CommandRouter:
    """Dispatch a validated command to exactly one registered owner."""

    def __init__(
        self,
        owners: Mapping[str, CommandOwner],
        *,
        registrations: Mapping[str, PluginRegistration] | None = None,
        capability_handlers: Mapping[str, CommandOwner] | None = None,
        entity_type_capabilities: Mapping[tuple[str, str], Iterable[EntityCapability]]
        | None = None,
    ) -> None:
        self._owners = dict(owners)
        self._registrations = dict(registrations or {})
        self._capability_handlers = dict(capability_handlers or {})
        self._entity_type_capabilities = {
            key: tuple(capabilities)
            for key, capabilities in (entity_type_capabilities or {}).items()
        }

    def dispatch(
        self,
        command: CommandEnvelope,
        *,
        context: CommandContext | None,
    ) -> CommandOutcome:
        if context is None:
            return Unauthorized(
                command.command_id,
                command.target,
                CommandError(
                    "write-token-required",
                    "A valid same-origin write token is required.",
                ),
            )

        owner = self._owners.get(command.target.plugin_id.value)
        if owner is None:
            return Rejected(
                command.command_id,
                command.target,
                CommandError(
                    "unknown-owner",
                    f"No command owner is registered for {command.target.plugin_id.value!r}.",
                ),
            )
        try:
            registration = self._registrations.get(command.target.plugin_id.value)
            capability: EntityCapability | None = None
            if registration is not None:
                policy_outcome, capability = self._enforce_entity_capabilities(
                    command, owner, registration
                )
                if policy_outcome is not None:
                    return policy_outcome
            else:
                envelope = self._entity_type_capabilities.get(
                    (
                        command.target.plugin_id.value,
                        command.target.entity_type,
                    )
                )
                if envelope is not None:
                    policy_outcome, capability = self._enforce_capability_envelope(
                        command,
                        owner,
                        envelope,
                        owner_label=command.target.plugin_id.value,
                    )
                    if policy_outcome is not None:
                        return policy_outcome
            handler = (
                self._capability_handlers.get(capability.value)
                if capability is not None
                else None
            )
            outcome = (handler or owner).handle(command, context)
            if not isinstance(
                outcome,
                (Accepted, Rejected, Conflicted, Stale, Unauthorized, Failed),
            ):
                raise TypeError("owner returned an unsupported command outcome")
            if (
                outcome.command_id != command.command_id
                or outcome.target != command.target
            ):
                raise ValueError("owner returned an outcome for a different command")
            return outcome
        except Exception:  # noqa: BLE001 - isolate arbitrary plugin owner failures
            return Failed(
                command.command_id,
                command.target,
                CommandError(
                    "owner-failed",
                    "The command owner failed without applying a successful outcome.",
                ),
            )

    @staticmethod
    def _enforce_entity_capabilities(
        command: CommandEnvelope,
        owner: CommandOwner,
        registration: PluginRegistration,
    ) -> tuple[CommandOutcome | None, EntityCapability | None]:
        declared = entity_type_registration(registration, command.target.entity_type)
        if declared is None:
            return _rejected(
                command,
                "undeclared-target",
                f"Plugin {registration.plugin_id.value!r} did not register entity type "
                f"{command.target.entity_type!r}.",
            ), None

        return CommandRouter._enforce_capability_envelope(
            command,
            owner,
            declared.capabilities,
            owner_label=registration.plugin_id.value,
        )

    @staticmethod
    def _enforce_capability_envelope(
        command: CommandEnvelope,
        owner: CommandOwner,
        declared_capabilities: Iterable[EntityCapability],
        *,
        owner_label: str,
    ) -> tuple[CommandOutcome | None, EntityCapability | None]:
        resolver = getattr(owner, "command_state", None)
        if not callable(resolver):
            raise TypeError("registered plugin owner does not expose command state")
        state = resolver(command.target)
        if state is None:
            return _rejected(
                command,
                "unknown-target",
                "No command state is available for this target.",
            ), None
        if not isinstance(state, CommandTargetState):
            raise TypeError("owner returned unsupported command state")

        envelope = {capability.value for capability in declared_capabilities}
        seen_capabilities: set[str] = set()
        seen_commands: set[str] = set()
        for affordance in state.affordances:
            if not isinstance(affordance, EntityAffordance):
                raise TypeError("owner returned an unsupported affordance")
            capability = affordance.capability.value
            if (
                capability not in envelope
                or capability in seen_capabilities
                or affordance.command in seen_commands
            ):
                return Failed(
                    command.command_id,
                    command.target,
                    CommandError(
                        "capability-contract-violation",
                        f"Owner {owner_label!r} exposed command behavior outside its "
                        "registered entity capability envelope.",
                    ),
                ), None
            seen_capabilities.add(capability)
            seen_commands.add(affordance.command)

        if command.expected_revision != state.revision:
            return Stale(
                command.command_id,
                command.target,
                state.revision,
                CommandError(
                    "stale-revision",
                    "The target changed after this view was loaded; refresh before "
                    "retrying.",
                ),
            ), None

        matching = next(
            (
                affordance
                for affordance in state.affordances
                if affordance.command == command.command
            ),
            None,
        )
        if matching is None:
            return _rejected(
                command,
                "unavailable-command",
                f"Command {command.command!r} is not currently available for this "
                "target.",
            ), None
        return None, matching.capability


class EntityTypeCommandOwner:
    """Route one owner namespace to handlers for disjoint entity types."""

    def __init__(self, owners: Mapping[str, CommandOwner]) -> None:
        self._owners = dict(owners)

    def command_state(self, target: SourceRef) -> CommandTargetState | None:
        owner = self._owners.get(target.entity_type)
        resolver = getattr(owner, "command_state", None)
        if not callable(resolver):
            return None
        state = resolver(target)
        return state if isinstance(state, CommandTargetState) else None

    def handle(
        self, command: CommandEnvelope, context: CommandContext
    ) -> CommandOutcome:
        owner = self._owners.get(command.target.entity_type)
        if owner is None:
            return _rejected(
                command,
                "unknown-target",
                f"No core command owner is registered for entity type "
                f"{command.target.entity_type!r}.",
            )
        return owner.handle(command, context)


class CoreTaskCommandOwner:
    """Authoritative command handler for the transitional core task domain."""

    def __init__(self, repository: TaskRepository) -> None:
        self.repository = repository

    def handle(
        self, command: CommandEnvelope, context: CommandContext
    ) -> CommandOutcome:
        del context  # Actor-aware events follow when the event envelope lands.
        if command.target.entity_type != "task":
            return _rejected(command, "unknown-target", "Core owns only task targets.")
        if command.command != "set-state":
            return _rejected(
                command,
                "unknown-command",
                f"Core tasks do not support command {command.command!r}.",
            )

        arguments = cast(dict[str, object], _thaw_json(command.arguments))
        if set(arguments) != {"state"}:
            return _rejected(
                command,
                "invalid-arguments",
                "set-state requires exactly one state argument.",
            )
        state = arguments["state"]
        if not isinstance(state, str) or state not in TASK_STATES:
            return _rejected(
                command,
                "invalid-state",
                f"state must be one of: {', '.join(TASK_STATES)}",
            )

        try:
            task = self.repository.update(
                command.target.entity_id,
                state=state,
                expected_revision=command.expected_revision,
            )
        except KeyError:
            return _rejected(command, "task-not-found", "Task not found.")
        except StaleTaskRevisionError as error:
            return Stale(
                command.command_id,
                command.target,
                error.current_revision,
                CommandError(
                    "stale-revision",
                    "The task changed after this view was loaded; refresh before retrying.",
                ),
            )
        except (TypeError, ValueError) as error:
            return _rejected(command, "invalid-task", str(error))

        return Accepted(
            command.command_id,
            command.target,
            task.updated_at,
            freeze_json_object({"task": asdict(task)}),
        )


def _rejected(command: CommandEnvelope, code: str, detail: str) -> Rejected:
    return Rejected(command.command_id, command.target, CommandError(code, detail))
