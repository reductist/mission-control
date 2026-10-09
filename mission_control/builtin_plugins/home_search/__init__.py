"""Home-search activation through the public JSON capability adapter."""

from __future__ import annotations

from datetime import datetime
from typing import cast

from mission_control.agenda import SourceRef, contribution_to_dict
from mission_control.builtin_plugins.home_search.commands import HomeSearchCommandOwner
from mission_control.builtin_plugins.home_search.details import entity_detail
from mission_control.builtin_plugins.home_search.repository import (
    SQLiteHomeSearchRepository,
)
from mission_control.commands import CommandContext, outcome_to_dict, parse_command
from mission_control.entity_details import entity_detail_to_dict
from mission_control.plugin_api import CapabilityRouter, PluginContext
from mission_control.plugins import PluginId


def activate(context: PluginContext) -> CapabilityRouter:
    if context.configuration or context.credentials:
        raise ValueError("Home Search does not accept configuration or credentials")
    repository = SQLiteHomeSearchRepository(context.storage)
    commands = HomeSearchCommandOwner(repository)

    def agenda_snapshot(inputs):
        generated_at = datetime.fromisoformat(cast(str, inputs["generated_at"]))
        return contribution_to_dict(
            repository.agenda_contribution(generated_at=generated_at)
        )

    def details(inputs):
        target = _source(cast(dict[str, str], inputs["target"]))
        detail = entity_detail(repository, target)
        return entity_detail_to_dict(detail) if detail is not None else None

    def command_state(inputs):
        target = _source(cast(dict[str, str], inputs["target"]))
        state = commands.command_state(target)
        if state is None:
            return None
        return {
            "schema_version": "mission-control.command-state/v1",
            "target": inputs["target"],
            "revision": state.revision,
            "affordances": [
                {
                    "capability": affordance.capability.value,
                    "command": affordance.command,
                }
                for affordance in state.affordances
            ],
        }

    def command_execute(inputs):
        command = parse_command(inputs["command"])
        outcome = commands.handle(
            command, CommandContext(actor=cast(str, inputs["actor"]))
        )
        return outcome_to_dict(outcome)

    return CapabilityRouter(
        context.plugin_id,
        {
            "agenda.snapshot": agenda_snapshot,
            "commands.execute": command_execute,
            "commands.state": command_state,
            "entity-details.get": details,
        },
    )


def _source(document: dict[str, str]) -> SourceRef:
    return SourceRef(
        PluginId(document["plugin_id"]),
        document["entity_type"],
        document["entity_id"],
    )
