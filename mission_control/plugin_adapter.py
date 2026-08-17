"""Core-side adapter from JSON capability calls to internal immutable models."""

from __future__ import annotations

from datetime import datetime
from typing import cast

from mission_control.agenda import (
    AgendaContribution,
    SourceRef,
    parse_agenda_contribution,
    validate_agenda_capabilities,
)
from mission_control.closed_items import (
    ClosedItemsContribution,
    parse_closed_items_contribution,
    validate_closed_items_capabilities,
)
from mission_control.commands import (
    CommandContext,
    CommandEnvelope,
    CommandOutcome,
    CommandTargetState,
    command_to_dict,
    parse_command_result,
)
from mission_control.entity_details import (
    EntityDetail,
    parse_entity_detail,
    validate_entity_detail_capabilities,
)
from mission_control.plugin_api import (
    PluginCallContractError,
    PluginCallHandler,
    call_plugin,
    validate_capability_document,
)
from mission_control.plugin_runtime import (
    PluginHealth,
    PluginHealthComponent,
    PluginHealthState,
    PluginJob,
)
from mission_control.plugins import (
    Capability,
    EntityAffordance,
    EntityCapability,
    PluginId,
    PluginRegistration,
)


_CAPABILITY_OPERATIONS = {
    Capability.AGENDA: frozenset({"agenda.snapshot"}),
    Capability.CLOSED_ITEMS: frozenset({"closed-items.snapshot"}),
    Capability.COMMANDS: frozenset({"commands.execute", "commands.state"}),
    Capability.ENTITY_DETAILS: frozenset({"entity-details.get"}),
    Capability.JOBS: frozenset({"jobs.failure", "jobs.list", "jobs.run"}),
    Capability.HEALTH: frozenset({"health.get"}),
}


def validate_runtime_capability_adapters(registration: PluginRegistration) -> None:
    """Reject executable capability claims core cannot yet call generically."""

    if registration.runtime is None:
        return
    unsupported = sorted(
        capability.value
        for capability in registration.capabilities
        if capability not in _CAPABILITY_OPERATIONS
    )
    if unsupported:
        raise PluginCallContractError(
            "plugin runtime declares capabilities without a public call adapter: "
            + ", ".join(unsupported)
        )


class DocumentPluginProvider:
    """Present validated JSON plugin calls through core's current provider API."""

    def __init__(
        self, registration: PluginRegistration, handler: PluginCallHandler
    ) -> None:
        self.registration = registration
        self.handler = handler
        self.plugin_id = registration.plugin_id
        self.command_owner = (
            self if Capability.COMMANDS in registration.capabilities else None
        )
        self._operations = self._validate_runtime_surface()

    @property
    def operations(self) -> tuple[str, ...]:
        return tuple(sorted(self._operations))

    def _validate_runtime_surface(self) -> frozenset[str]:
        validate_runtime_capability_adapters(self.registration)
        output = call_plugin(self.handler, "runtime.describe", {})
        raw = validate_capability_document(
            output, "plugin-runtime.schema.json", "plugin runtime description"
        )
        if raw["plugin_id"] != self.plugin_id.value:
            raise PluginCallContractError(
                "plugin runtime description belongs to a different plugin"
            )
        operations = cast(list[str], raw["operations"])
        if len(operations) != len(set(operations)):
            raise PluginCallContractError(
                "plugin runtime description contains duplicate operations"
            )
        expected = {"runtime.describe"}
        for capability in self.registration.capabilities:
            expected.update(_CAPABILITY_OPERATIONS.get(capability, ()))
        actual = set(operations)
        if actual - expected - {"runtime.stop"}:
            raise PluginCallContractError(
                "plugin runtime exposes operations outside its manifest capabilities"
            )
        if expected - actual:
            raise PluginCallContractError(
                "plugin runtime is missing operations required by its manifest capabilities"
            )
        return frozenset(actual)

    def contribution(self, *, generated_at: datetime) -> AgendaContribution:
        output = call_plugin(
            self.handler,
            "agenda.snapshot",
            {"generated_at": generated_at.isoformat()},
        )
        contribution = parse_agenda_contribution(output)
        validate_agenda_capabilities(self.registration, contribution)
        return contribution

    def closed_items(self, *, generated_at: datetime) -> ClosedItemsContribution:
        output = call_plugin(
            self.handler,
            "closed-items.snapshot",
            {"generated_at": generated_at.isoformat()},
        )
        contribution = parse_closed_items_contribution(output)
        validate_closed_items_capabilities(self.registration, contribution)
        return contribution

    def entity_detail(self, target: SourceRef) -> EntityDetail | None:
        output = call_plugin(
            self.handler,
            "entity-details.get",
            {"target": _source_to_dict(target)},
        )
        if output is None:
            return None
        detail = parse_entity_detail(output)
        validate_entity_detail_capabilities(
            self.registration, detail, expected_source=target
        )
        return detail

    def command_state(self, target: SourceRef) -> CommandTargetState | None:
        output = call_plugin(
            self.handler,
            "commands.state",
            {"target": _source_to_dict(target)},
        )
        if output is None:
            return None
        raw = validate_capability_document(
            output, "command-state.schema.json", "command target state"
        )
        if raw["target"] != _source_to_dict(target):
            raise PluginCallContractError(
                "command state belongs to a different target"
            )
        affordances = tuple(
            EntityAffordance(
                EntityCapability(item["capability"]), item["command"]
            )
            for item in cast(list[dict[str, str]], raw["affordances"])
        )
        return CommandTargetState(cast(str, raw["revision"]), affordances)

    def handle(
        self, command: CommandEnvelope, context: CommandContext
    ) -> CommandOutcome:
        output = call_plugin(
            self.handler,
            "commands.execute",
            {"command": command_to_dict(command), "actor": context.actor},
        )
        outcome = parse_command_result(output)
        if outcome.command_id != command.command_id or outcome.target != command.target:
            raise PluginCallContractError(
                "command result belongs to a different command"
            )
        return outcome

    def jobs(self) -> tuple[PluginJob, ...]:
        output = call_plugin(self.handler, "jobs.list", {})
        raw = validate_capability_document(
            output, "plugin-jobs.schema.json", "plugin jobs"
        )
        if raw["plugin_id"] != self.plugin_id.value:
            raise PluginCallContractError("plugin jobs belong to a different plugin")
        jobs = cast(list[dict[str, object]], raw["jobs"])
        job_ids = [cast(str, item["job_id"]) for item in jobs]
        if len(job_ids) != len(set(job_ids)):
            raise PluginCallContractError("plugin jobs contain duplicate job ids")
        return tuple(
            PluginJob(
                self.plugin_id,
                cast(str, item["job_id"]),
                cast(int, item["interval_seconds"]),
                lambda job_id=cast(str, item["job_id"]): call_plugin(
                    self.handler, "jobs.run", {"job_id": job_id}
                ),
                lambda job_id=cast(str, item["job_id"]): call_plugin(
                    self.handler, "jobs.failure", {"job_id": job_id}
                ),
            )
            for item in jobs
        )

    def health(self) -> PluginHealth:
        output = call_plugin(self.handler, "health.get", {})
        raw = validate_capability_document(
            output, "plugin-health.schema.json", "plugin health"
        )
        if raw["plugin_id"] != self.plugin_id.value:
            raise PluginCallContractError("plugin health belongs to a different plugin")
        checked_at = _timestamp(cast(str, raw["checked_at"]), "checked_at")
        last_success = raw.get("last_success_at")
        components = cast(list[dict[str, object]], raw["components"])
        return PluginHealth(
            self.plugin_id,
            PluginHealthState(cast(str, raw["state"])),
            cast(str, raw["code"]),
            cast(str, raw["detail"]),
            checked_at,
            _timestamp(cast(str, last_success), "last_success_at")
            if last_success is not None
            else None,
            tuple(
                PluginHealthComponent(
                    cast(str, component["id"]),
                    cast(str, component["label"]),
                    PluginHealthState(cast(str, component["state"])),
                    cast(str, component["code"]),
                    cast(str, component["detail"]),
                    _timestamp(
                        cast(str, component["last_success_at"]),
                        "components.last_success_at",
                    )
                    if component.get("last_success_at") is not None
                    else None,
                )
                for component in components
            ),
        )

    def stop(self) -> None:
        if "runtime.stop" in self._operations:
            call_plugin(self.handler, "runtime.stop", {})


def _source_to_dict(source: SourceRef) -> dict[str, str]:
    return {
        "plugin_id": source.plugin_id.value,
        "entity_type": source.entity_type,
        "entity_id": source.entity_id,
    }


def _timestamp(value: str, path: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise PluginCallContractError(f"{path}: invalid timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PluginCallContractError(f"{path}: timestamp must include a UTC offset")
    return parsed
