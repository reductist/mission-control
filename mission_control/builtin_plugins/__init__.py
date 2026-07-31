"""Explicit loaders for bundled plugins selected by the operator."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Callable

from ..agenda import AgendaContribution
from .landscape import load_agenda_contribution as load_landscape_agenda


class BuiltinPluginError(ValueError):
    """A requested bundled plugin cannot provide a valid contribution."""


_AGENDA_LOADERS: dict[str, Callable[[], AgendaContribution]] = {
    "landscape": load_landscape_agenda,
}
BUILTIN_AGENDA_PLUGIN_IDS = tuple(sorted(_AGENDA_LOADERS))


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
        loader = _AGENDA_LOADERS.get(plugin_id)
        if loader is None:
            supported = ", ".join(BUILTIN_AGENDA_PLUGIN_IDS)
            raise BuiltinPluginError(
                f"unknown bundled agenda plugin {plugin_id!r}; available: {supported}"
            )
        contributions.append(loader())
    return tuple(contributions)
