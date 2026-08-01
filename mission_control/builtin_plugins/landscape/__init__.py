"""Landscape activation after registration and seed validation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ...agenda import AgendaContribution
from ...database import Database
from .repository import (
    LandscapeMigrationRunner,
    LandscapeRepository,
    SQLiteLandscapeRepository,
)


@dataclass(frozen=True, slots=True)
class LandscapeAgendaProvider:
    repository: LandscapeRepository

    def contribution(self, *, generated_at: datetime) -> AgendaContribution:
        return self.repository.agenda_contribution(generated_at=generated_at)


def activate(database: Database, seed: AgendaContribution) -> LandscapeAgendaProvider:
    """Apply Landscape-owned migrations and import its initial data once."""

    LandscapeMigrationRunner(database).apply()
    repository = SQLiteLandscapeRepository(database)
    repository.import_agenda_seed(seed)
    return LandscapeAgendaProvider(repository)
