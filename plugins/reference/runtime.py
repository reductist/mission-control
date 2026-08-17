"""Minimal external-style runtime using only Mission Control's public adapter."""

from __future__ import annotations

from datetime import UTC, datetime

from mission_control.plugin_api import (
    CapabilityRouter,
    PluginContext,
    PluginSetupContext,
)


def activate(context: PluginContext) -> CapabilityRouter:
    message = str(context.configuration["message"])

    def health(_inputs):
        return {
            "schema_version": "mission-control.plugin-health/v2",
            "plugin_id": context.plugin_id,
            "state": "ready",
            "code": "reference-ready",
            "detail": message,
            "checked_at": datetime.now(UTC).isoformat(),
            "components": [],
        }

    return CapabilityRouter(context.plugin_id, {"health.get": health})


def activate_setup(context: PluginSetupContext) -> CapabilityRouter:
    """Prove a third-party plugin can expose setup through the public adapter."""

    def transition(draft, *, complete: bool):
        return {
            "schema_version": "mission-control.setup-transition/v1",
            "plugin_id": context.plugin_id,
            "draft": draft,
            "step": {
                "id": "complete" if complete else "message",
                "title": "Reference plugin is ready" if complete else "Choose a message",
                "fields": []
                if complete
                else [
                    {
                        "id": "message",
                        "label": "Health message",
                        "widget": "text",
                        "required": True,
                    }
                ],
                "actions": []
                if complete
                else [
                    {
                        "id": "save",
                        "label": "Use this message",
                        "style": "primary",
                        "intent": "commit",
                    }
                ],
            },
            "complete": complete,
        }

    def describe(inputs):
        return transition(dict(inputs["draft"]), complete=False)

    def save(inputs):
        draft = {
            "settings": dict(inputs["draft"]["settings"]),
            "credentials": dict(inputs["draft"]["credentials"]),
        }
        draft["settings"]["message"] = inputs["values"]["message"]
        return transition(draft, complete=True)

    return CapabilityRouter(
        context.plugin_id,
        {"setup.describe": describe, "setup.action": save},
    )
