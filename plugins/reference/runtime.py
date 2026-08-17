"""Minimal external-style runtime using only Mission Control's public adapter."""

from __future__ import annotations

from datetime import UTC, datetime

from mission_control.plugin_api import CapabilityRouter, PluginContext


def activate(context: PluginContext) -> CapabilityRouter:
    message = str(context.configuration["message"])

    def health(_inputs):
        return {
            "schema_version": "mission-control.plugin-health/v1",
            "plugin_id": context.plugin_id,
            "state": "ready",
            "code": "reference-ready",
            "detail": message,
            "checked_at": datetime.now(UTC).isoformat(),
        }

    return CapabilityRouter(context.plugin_id, {"health.get": health})
