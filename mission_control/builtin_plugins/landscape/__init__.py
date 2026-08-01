"""Landscape activation after registration and seed validation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar

from ...agenda import AgendaContribution
from ...commands import CommandOwner
from ...database import Database
from ...plugins import PluginId
from .commands import LandscapeCommandOwner
from .repository import (
    PLUGIN_ID,
    LandscapeMigrationRunner,
    LandscapeRepository,
    SQLiteLandscapeRepository,
)


@dataclass(frozen=True, slots=True)
class LandscapeAgendaProvider:
    repository: LandscapeRepository
    command_owner: CommandOwner
    plugin_id: ClassVar[PluginId] = PLUGIN_ID

    def contribution(self, *, generated_at: datetime) -> AgendaContribution:
        return self.repository.agenda_contribution(generated_at=generated_at)


def activate(database: Database, seed: AgendaContribution) -> LandscapeAgendaProvider:
    """Apply Landscape-owned migrations and import its initial data once."""

    LandscapeMigrationRunner(database).apply()
    repository = SQLiteLandscapeRepository(database)
    repository.import_agenda_seed(seed)
    return LandscapeAgendaProvider(repository, LandscapeCommandOwner(repository))
