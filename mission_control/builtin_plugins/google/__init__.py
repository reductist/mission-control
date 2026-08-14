"""Read-only Google Calendar and Tasks plugin activation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar

from mission_control.agenda import AgendaContribution, SourceRef
from mission_control.builtin_plugins.google.client import (
    AuthorizedUserCredentials,
    GoogleHttpClient,
)
from mission_control.builtin_plugins.google.config import GoogleConfig
from mission_control.builtin_plugins.google.fixture import FixtureGoogleClient
from mission_control.builtin_plugins.google.repository import (
    PLUGIN_ID,
    GoogleMigrationRunner,
    GoogleSynchronizer,
    SQLiteGoogleRepository,
    plugin_health,
)
from mission_control.database import Database
from mission_control.entity_details import EntityDetail
from mission_control.plugin_runtime import PluginHealth, PluginJob
from mission_control.plugins import PluginConfiguration, PluginId


@dataclass(frozen=True, slots=True)
class GoogleAgendaProvider:
    repository: SQLiteGoogleRepository
    synchronizer: GoogleSynchronizer
    interval_seconds: int
    plugin_id: ClassVar[PluginId] = PLUGIN_ID
    command_owner: ClassVar[None] = None

    def contribution(self, *, generated_at: datetime) -> AgendaContribution:
        return self.repository.contribution(generated_at=generated_at)

    def entity_detail(self, target: SourceRef) -> EntityDetail | None:
        return self.repository.entity_detail(target)

    def jobs(self) -> tuple[PluginJob, ...]:
        return (
            PluginJob(
                self.plugin_id,
                "refresh",
                self.interval_seconds,
                self.synchronizer.sync_once,
                self.synchronizer.record_unexpected_failure,
            ),
        )

    def health(self) -> PluginHealth:
        return plugin_health(
            self.repository,
            runtime_failure_at=self.synchronizer.runtime_failure_at,
        )


def activate(
    database: Database,
    seed: AgendaContribution,
    configuration: PluginConfiguration,
    credentials: dict[str, str],
) -> GoogleAgendaProvider:
    """Migrate the cache and prepare sync without persisting OAuth secrets."""

    if seed.provider.plugin_id != PLUGIN_ID or seed.entries:
        raise ValueError("Google's packaged agenda seed must be empty and provider-owned")
    config = GoogleConfig.from_runtime(configuration, credentials)
    GoogleMigrationRunner(database).apply()
    repository = SQLiteGoogleRepository(database)
    if config.mode == "demo":
        client = FixtureGoogleClient.load()
    else:
        assert config.oauth_credential is not None
        authorized = AuthorizedUserCredentials.load(config.oauth_credential)
        client = GoogleHttpClient(
            authorized, timeout_seconds=config.request_timeout_seconds
        )
    synchronizer = GoogleSynchronizer(repository, client, config)
    provider = GoogleAgendaProvider(
        repository, synchronizer, config.sync_interval_seconds
    )
    if config.mode == "demo":
        synchronizer.sync_once()
    return provider
