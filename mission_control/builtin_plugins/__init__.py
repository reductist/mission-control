"""Explicit loaders for bundled plugins selected by the operator."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from importlib import import_module
from importlib.resources import files
from typing import Protocol

from mission_control.agenda import (
    AgendaContribution,
    AgendaContributionError,
    parse_agenda_contribution,
    validate_agenda_capabilities,
)
from mission_control.commands import CommandOwner
from mission_control.database import Database
from mission_control.plugins import (
    Capability,
    PluginId,
    PluginRegistration,
    PluginRegistrationError,
    parse_plugin_registration,
)


class BuiltinPluginError(ValueError):
    """A requested bundled plugin cannot provide a valid contribution."""


BUILTIN_AGENDA_PLUGIN_IDS = ("landscape",)


class BuiltinAgendaProvider(Protocol):
    plugin_id: PluginId
    command_owner: CommandOwner | None

    def contribution(self, *, generated_at: datetime) -> AgendaContribution: ...


@dataclass(frozen=True, slots=True)
class PreparedBuiltinAgendaPlugin:
    registration: PluginRegistration
    seed: AgendaContribution


def _document(plugin_id: str, name: str) -> object:
    resource = files(__package__).joinpath(plugin_id, name)
    return json.loads(resource.read_text(encoding="utf-8"))


def _prepare_agenda_plugin(plugin_id: str) -> PreparedBuiltinAgendaPlugin:
    try:
        registration = parse_plugin_registration(
            _document(plugin_id, "registration.json")
        )
        if registration.plugin_id.value != plugin_id:
            raise ValueError("directory and registration ids must match")
        if Capability.AGENDA not in registration.capabilities:
            raise ValueError("registration must declare the agenda capability")

        contribution = parse_agenda_contribution(_document(plugin_id, "agenda.json"))
        if registration.plugin_id != contribution.provider.plugin_id:
            raise ValueError("registration and agenda provider ids must match")
        validate_agenda_capabilities(registration, contribution)
        return PreparedBuiltinAgendaPlugin(registration, contribution)
    except (
        OSError,
        json.JSONDecodeError,
        PluginRegistrationError,
        AgendaContributionError,
        ValueError,
    ) as error:
        raise BuiltinPluginError(f"{plugin_id}: {error}") from error


def load_builtin_agenda_contributions(
    plugin_ids: Iterable[str],
) -> tuple[AgendaContribution, ...]:
    """Load validated agenda snapshots for explicitly selected built-ins."""

    return tuple(plugin.seed for plugin in prepare_builtin_agenda_plugins(plugin_ids))


def prepare_builtin_agenda_plugins(
    plugin_ids: Iterable[str],
) -> tuple[PreparedBuiltinAgendaPlugin, ...]:
    """Validate selected built-ins without importing code or touching persistence."""

    prepared: list[PreparedBuiltinAgendaPlugin] = []
    selected: set[str] = set()
    for plugin_id in plugin_ids:
        if plugin_id in selected:
            raise BuiltinPluginError(f"plugin selected more than once: {plugin_id}")
        selected.add(plugin_id)
        if plugin_id not in BUILTIN_AGENDA_PLUGIN_IDS:
            supported = ", ".join(BUILTIN_AGENDA_PLUGIN_IDS)
            raise BuiltinPluginError(
                f"unknown bundled agenda plugin {plugin_id!r}; available: {supported}"
            )
        prepared.append(_prepare_agenda_plugin(plugin_id))
    return tuple(prepared)


def activate_builtin_agenda_plugins(
    database: Database,
    plugins: Iterable[PreparedBuiltinAgendaPlugin],
) -> tuple[BuiltinAgendaProvider, ...]:
    """Activate previously validated built-ins in their explicit bootstrap phase."""

    providers: list[BuiltinAgendaProvider] = []
    for plugin in plugins:
        plugin_id = plugin.registration.plugin_id.value
        try:
            implementation = import_module(f"{__package__}.{plugin_id}")
            provider = implementation.activate(database, plugin.seed)
            if provider.plugin_id != plugin.registration.plugin_id:
                raise ValueError("registration and activated provider ids must match")
            declares_commands = Capability.COMMANDS in plugin.registration.capabilities
            if (provider.command_owner is not None) is not declares_commands:
                raise ValueError(
                    "registration and activated command capability must match"
                )
            if declares_commands and not callable(
                getattr(provider.command_owner, "command_state", None)
            ):
                raise ValueError(
                    "registered command owner must expose current entity affordances"
                )
            declares_closed_items = (
                Capability.CLOSED_ITEMS in plugin.registration.capabilities
            )
            if callable(getattr(provider, "closed_items", None)) is not declares_closed_items:
                raise ValueError(
                    "registration and activated closed-items capability must match"
                )
            declares_entity_details = (
                Capability.ENTITY_DETAILS in plugin.registration.capabilities
            )
            exposes_entity_details = callable(
                getattr(provider, "entity_detail", None)
            )
            if exposes_entity_details is not declares_entity_details:
                raise ValueError(
                    "registration and activated entity-details capability must match"
                )
        except (
            AttributeError,
            ImportError,
            OSError,
            TypeError,
            ValueError,
            sqlite3.Error,
        ) as error:
            raise BuiltinPluginError(f"{plugin_id}: {error}") from error
        providers.append(provider)
    return tuple(providers)
