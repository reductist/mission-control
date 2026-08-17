"""Read-only Google Calendar and Tasks plugin activation."""

from __future__ import annotations

from datetime import datetime
from typing import cast

from mission_control.agenda import SourceRef, contribution_to_dict
from mission_control.builtin_plugins.google.client import (
    AuthorizedUserCredentials,
    GoogleHttpClient,
)
from mission_control.builtin_plugins.google.config import GoogleConfig
from mission_control.builtin_plugins.google.fixture import FixtureGoogleClient
from mission_control.builtin_plugins.google.repository import (
    PLUGIN_ID,
    GoogleSynchronizer,
    SQLiteGoogleRepository,
    plugin_health,
)
from mission_control.entity_details import entity_detail_to_dict
from mission_control.plugin_api import CapabilityRouter, PluginContext
from mission_control.plugins import PluginId


def activate(context: PluginContext) -> CapabilityRouter:
    """Prepare Google-owned state and expose only JSON capability operations."""

    if context.agenda_seed is not None:
        raise ValueError("Google does not declare an agenda seed resource")
    config = GoogleConfig.from_runtime(context.configuration, context.credentials)
    repository = SQLiteGoogleRepository(context.storage)
    if config.mode == "demo":
        client = FixtureGoogleClient.load(config.demo_anchor_date)
        source_fingerprint = "packaged-fixture-v1"
    else:
        assert config.oauth_credential is not None
        authorized = AuthorizedUserCredentials.load(config.oauth_credential)
        source_fingerprint = authorized.source_fingerprint()
        client = GoogleHttpClient(
            authorized, timeout_seconds=config.request_timeout_seconds
        )
    repository.prepare_source(config.mode, source_fingerprint)
    synchronizer = GoogleSynchronizer(repository, client, config)
    if config.mode == "demo":
        synchronizer.sync_once()

    def agenda_snapshot(inputs):
        generated_at = datetime.fromisoformat(cast(str, inputs["generated_at"]))
        return contribution_to_dict(
            repository.contribution(generated_at=generated_at)
        )

    def entity_details(inputs):
        target = _source(cast(dict[str, str], inputs["target"]))
        detail = repository.entity_detail(target)
        return entity_detail_to_dict(detail) if detail is not None else None

    def jobs_list(_inputs):
        return {
            "schema_version": "mission-control.plugin-jobs/v1",
            "plugin_id": PLUGIN_ID.value,
            "jobs": [
                {
                    "job_id": "refresh",
                    "interval_seconds": config.sync_interval_seconds,
                }
            ],
        }

    def jobs_run(inputs):
        if inputs["job_id"] != "refresh":
            raise ValueError("unknown Google job")
        synchronizer.sync_once()
        return {}

    def jobs_failure(inputs):
        if inputs["job_id"] != "refresh":
            raise ValueError("unknown Google job")
        synchronizer.record_unexpected_failure()
        return {}

    def health(_inputs):
        document = plugin_health(
            repository,
            source_mode=config.mode,
            runtime_failure_at=synchronizer.runtime_failure_at,
        ).to_dict()
        return {"schema_version": "mission-control.plugin-health/v1", **document}

    return CapabilityRouter(
        context.plugin_id,
        {
            "agenda.snapshot": agenda_snapshot,
            "entity-details.get": entity_details,
            "health.get": health,
            "jobs.failure": jobs_failure,
            "jobs.list": jobs_list,
            "jobs.run": jobs_run,
        },
    )


def _source(document: dict[str, str]) -> SourceRef:
    return SourceRef(
        PluginId(document["plugin_id"]),
        document["entity_type"],
        document["entity_id"],
    )
