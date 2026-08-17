"""Read-only Google Calendar and Tasks plugin activation."""

from __future__ import annotations

from datetime import UTC, datetime
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
    repository.reconcile_configured_connections(
        connection.connection_id for connection in config.connections
    )
    synchronizers: dict[str, GoogleSynchronizer] = {}
    for connection in config.connections:
        if connection.mode == "demo":
            client = FixtureGoogleClient.load(connection.demo_anchor_date)
            source_fingerprint = (
                "packaged-fixture-v1:"
                + (
                    connection.demo_anchor_date.isoformat()
                    if connection.demo_anchor_date is not None
                    else "default"
                )
            )
        else:
            try:
                assert connection.oauth_credential is not None
                authorized = AuthorizedUserCredentials.load(
                    connection.oauth_credential
                )
                source_fingerprint = authorized.source_fingerprint()
                client = GoogleHttpClient(
                    authorized, timeout_seconds=config.request_timeout_seconds
                )
            except (OSError, ValueError):
                repository.prepare_source(
                    connection.connection_id,
                    connection.label,
                    connection.mode,
                    "connection-unavailable",
                )
                repository.record_failure(
                    connection.connection_id,
                    datetime.now(UTC),
                    code="connection-unavailable",
                    detail="Google authorization or connection setup is unavailable.",
                )
                continue
        repository.prepare_source(
            connection.connection_id,
            connection.label,
            connection.mode,
            source_fingerprint,
        )
        synchronizer = GoogleSynchronizer(repository, client, config, connection)
        synchronizers[connection.connection_id] = synchronizer
        if connection.mode == "demo":
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
                    "job_id": f"refresh:{connection_id}",
                    "interval_seconds": config.sync_interval_seconds,
                }
                for connection_id in sorted(synchronizers)
            ],
        }

    def jobs_run(inputs):
        job_id = cast(str, inputs["job_id"])
        if not job_id.startswith("refresh:") or job_id[8:] not in synchronizers:
            raise ValueError("unknown Google job")
        synchronizers[job_id[8:]].sync_once()
        return {}

    def jobs_failure(inputs):
        job_id = cast(str, inputs["job_id"])
        if not job_id.startswith("refresh:") or job_id[8:] not in synchronizers:
            raise ValueError("unknown Google job")
        synchronizers[job_id[8:]].record_unexpected_failure()
        return {}

    def health(_inputs):
        document = plugin_health(
            repository,
            runtime_failures={
                connection_id: synchronizer.runtime_failure_at
                for connection_id, synchronizer in synchronizers.items()
                if synchronizer.runtime_failure_at is not None
            },
        ).to_dict()
        return {"schema_version": "mission-control.plugin-health/v2", **document}

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
