"""Landscape activation after registration and seed validation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar

from mission_control.agenda import AgendaContribution
from mission_control.builtin_plugins.landscape.commands import LandscapeCommandOwner
from mission_control.builtin_plugins.landscape.repository import (
    PLUGIN_ID,
    LandscapeMigrationRunner,
    LandscapeRepository,
    SQLiteLandscapeRepository,
)
from mission_control.commands import CommandOwner
from mission_control.closed_items import ClosedItemsContribution
from mission_control.database import Database
from mission_control.plugins import PluginId


@dataclass(frozen=True, slots=True)
class LandscapeAgendaProvider:
    repository: LandscapeRepository
    command_owner: CommandOwner
    plugin_id: ClassVar[PluginId] = PLUGIN_ID

    def contribution(self, *, generated_at: datetime) -> AgendaContribution:
        return self.repository.agenda_contribution(generated_at=generated_at)

    def closed_items(self, *, generated_at: datetime) -> ClosedItemsContribution:
        return self.repository.closed_items_contribution(generated_at=generated_at)


def activate(database: Database, seed: AgendaContribution) -> LandscapeAgendaProvider:
    """Apply Landscape-owned migrations and import its initial data once."""

    LandscapeMigrationRunner(database).apply()
    repository = SQLiteLandscapeRepository(database)
    repository.import_agenda_seed(seed)
    return LandscapeAgendaProvider(repository, LandscapeCommandOwner(repository))
