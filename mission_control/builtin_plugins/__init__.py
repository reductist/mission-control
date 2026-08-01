"""Explicit loaders for bundled plugins selected by the operator."""

from __future__ import annotations

import json
from collections.abc import Iterable
from importlib.resources import files

from ..agenda import AgendaContribution, parse_agenda_contribution
from ..plugins import Capability, parse_plugin_registration


class BuiltinPluginError(ValueError):
    """A requested bundled plugin cannot provide a valid contribution."""


BUILTIN_AGENDA_PLUGIN_IDS = ("landscape",)


def _document(plugin_id: str, name: str) -> object:
    resource = files(__package__).joinpath(plugin_id, name)
    return json.loads(resource.read_text(encoding="utf-8"))


def _load_agenda_contribution(plugin_id: str) -> AgendaContribution:
    registration = parse_plugin_registration(_document(plugin_id, "registration.json"))
    if registration.plugin_id.value != plugin_id:
        raise BuiltinPluginError(
            f"bundled plugin directory and registration ids must match: {plugin_id}"
        )
    if Capability.AGENDA not in registration.capabilities:
        raise BuiltinPluginError(
            f"bundled plugin {plugin_id!r} must declare the agenda capability"
        )

    contribution = parse_agenda_contribution(_document(plugin_id, "agenda.json"))
    if registration.plugin_id != contribution.provider.plugin_id:
        raise BuiltinPluginError(
            f"bundled plugin {plugin_id!r} registration and provider ids must match"
        )
    return contribution


def load_builtin_agenda_contributions(
    plugin_ids: Iterable[str],
) -> tuple[AgendaContribution, ...]:
    """Load validated agenda snapshots for explicitly selected built-ins."""

    contributions: list[AgendaContribution] = []
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
        contributions.append(_load_agenda_contribution(plugin_id))
    return tuple(contributions)
