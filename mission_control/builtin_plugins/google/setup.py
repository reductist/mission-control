"""Database-free, renderer-neutral setup flow for Google Calendar."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from typing import cast

from mission_control.builtin_plugins.google.client import (
    AuthorizedUserCredentials,
    GoogleApiError,
    GoogleClient,
    GoogleHttpClient,
)
from mission_control.builtin_plugins.google.fixture import FixtureGoogleClient
from mission_control.plugin_api import (
    CapabilityRouter,
    PluginCallRejected,
    PluginSetupContext,
)


PLUGIN_ID = "google-calendar"


def activate(context: PluginSetupContext) -> CapabilityRouter:
    """Create one transient setup handler with no application storage access."""

    flow = GoogleCalendarSetup(context)
    return CapabilityRouter(
        PLUGIN_ID,
        {
            "setup.describe": flow.describe,
            "setup.action": flow.action,
        },
    )


class GoogleCalendarSetup:
    def __init__(self, context: PluginSetupContext) -> None:
        if context.plugin_id != PLUGIN_ID:
            raise ValueError("Google setup context belongs to another plugin")
        self.context = context
        self._client: GoogleClient | None = None
        self._calendars: tuple[tuple[str, str, bool], ...] = ()
        self._task_lists: tuple[tuple[str, str], ...] = ()
        self._attribution_fields: dict[str, tuple[str, str]] = {}

    def describe(self, inputs: Mapping[str, object]) -> dict[str, object]:
        draft = cast(Mapping[str, object], inputs["draft"])
        return self._connection_state(draft)

    def action(self, inputs: Mapping[str, object]) -> dict[str, object]:
        action_id = cast(str, inputs["action_id"])
        draft = _draft(inputs["draft"])
        values = cast(Mapping[str, object], inputs["values"])
        principals = cast(list[Mapping[str, str]], inputs["principals"])

        if action_id == "start":
            return self._start(draft, values)
        if action_id == "connect":
            return self._connect(draft, values)
        if action_id == "select":
            return self._select(draft, values, principals)
        if action_id == "assign":
            return self._assign(draft, values)
        if action_id == "finish":
            return self._complete_state(draft)
        raise PluginCallRejected(
            "unknown-setup-action", "That setup action is not available."
        )

    def _state(
        self,
        draft: Mapping[str, object],
        *,
        step_id: str,
        title: str,
        description: str,
        fields: list[dict[str, object]],
        actions: list[dict[str, str]],
        complete: bool = False,
        notice: dict[str, str] | None = None,
    ) -> dict[str, object]:
        state: dict[str, object] = {
            "schema_version": "mission-control.setup-transition/v1",
            "plugin_id": PLUGIN_ID,
            "draft": _draft(draft),
            "step": {
                "id": step_id,
                "title": title,
                "description": description,
                "fields": fields,
                "actions": actions,
            },
            "complete": complete,
        }
        if notice is not None:
            state["notice"] = notice
        return state

    def _connection_state(self, draft: Mapping[str, object]) -> dict[str, object]:
        return self._state(
            draft,
            step_id="connection",
            title="Add a Google Calendar connection",
            description=(
                "Give this connection a stable ID and a familiar name. "
                "Demo mode uses packaged sample data and needs no account."
            ),
            fields=[
                _field("connection_id", "Connection ID", "text", required=True),
                _field("label", "Display name", "text", required=True),
                _field(
                    "mode",
                    "Connection type",
                    "select",
                    required=True,
                    options=(
                        ("live", "Connect a Google account"),
                        ("demo", "Try sample data"),
                    ),
                ),
            ],
            actions=[_action("start", "Continue")],
        )

    def _start(
        self, draft: dict[str, object], values: Mapping[str, object]
    ) -> dict[str, object]:
        connection_id = cast(str, values["connection_id"]).strip()
        label = cast(str, values["label"]).strip()
        mode = cast(str, values["mode"])
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]*", connection_id) is None or not label:
            raise PluginCallRejected(
                "invalid-connection",
                "Use a simple connection ID and provide a display name.",
            )
        connection: dict[str, object] = {
            "label": label,
            "mode": mode,
            "calendars": {"mode": "disabled"},
            "tasks": {"mode": "disabled"},
        }
        settings = cast(dict[str, object], draft["settings"])
        connections = cast(dict[str, object], settings.setdefault("connections", {}))
        if connection_id in connections:
            raise PluginCallRejected(
                "connection-exists",
                "That connection ID already exists. Choose another ID.",
            )
        connections[connection_id] = connection
        settings["setup_connection_id"] = connection_id
        if mode == "demo":
            self._client = FixtureGoogleClient.load(None)
            self._discover()
            return self._resources_state(draft)
        return self._state(
            draft,
            step_id="credential",
            title="Connect your Google account",
            description=(
                "Choose an authorized-user OAuth JSON file. Mission Control stores "
                "it separately and the plugin receives only a temporary handle here."
            ),
            fields=[
                _field(
                    "credential",
                    "Google authorization file",
                    "credential-file",
                    required=True,
                )
            ],
            actions=[_action("connect", "Test and discover", "authorize")],
        )

    def _connect(
        self, draft: dict[str, object], values: Mapping[str, object]
    ) -> dict[str, object]:
        handle = cast(str, values["credential"])
        connection_id, connection = _active_connection(draft)
        credential_name = "oauth-" + hashlib.sha256(
            connection_id.encode("utf-8")
        ).hexdigest()[:12]
        cast(dict[str, object], draft["credentials"])[credential_name] = {
            "handle": handle
        }
        connection["credential"] = credential_name
        try:
            authorized = AuthorizedUserCredentials.load(
                self.context.resolve_credential(handle)
            )
            self._client = GoogleHttpClient(authorized)
            self._discover()
        except GoogleApiError as error:
            raise PluginCallRejected(error.code, error.detail) from error
        except OSError as error:
            raise PluginCallRejected(
                "credential-unavailable",
                "The selected Google authorization file could not be read.",
            ) from error
        return self._resources_state(draft)

    def _discover(self) -> None:
        assert self._client is not None
        try:
            self._calendars = tuple(
                (
                    collection.external_id,
                    collection.label,
                    raw.get("primary") is True or raw.get("selected") is True,
                )
                for collection, raw in self._client.calendars()
            )
            self._task_lists = tuple(
                (collection.external_id, collection.label)
                for collection in self._client.task_lists()
            )
        except GoogleApiError as error:
            raise PluginCallRejected(error.code, error.detail) from error

    def _resources_state(self, draft: Mapping[str, object]) -> dict[str, object]:
        return self._state(
            draft,
            step_id="resources",
            title="Choose what appears in Mission Control",
            description=(
                "Select a policy for calendars and task lists. Explicit selections "
                "remain stable even when Google adds another collection later."
            ),
            fields=[
                _field(
                    "calendar_mode",
                    "Calendars",
                    "select",
                    required=True,
                    options=(
                        ("defaults", "Google-selected calendars"),
                        ("all", "All calendars"),
                        ("selected", "Only selected calendars"),
                        ("disabled", "No calendars"),
                    ),
                    value="defaults",
                ),
                _field(
                    "calendar_ids",
                    "Selected calendars",
                    "multi-select",
                    required=False,
                    options=tuple((item[0], item[1]) for item in self._calendars),
                ),
                _field(
                    "task_mode",
                    "Google Tasks",
                    "select",
                    required=True,
                    options=(
                        ("all", "All task lists"),
                        ("selected", "Only selected task lists"),
                        ("disabled", "No task lists"),
                    ),
                    value="disabled",
                ),
                _field(
                    "task_ids",
                    "Selected task lists",
                    "multi-select",
                    required=False,
                    options=self._task_lists,
                ),
            ],
            actions=[_action("select", "Continue")],
            notice={
                "kind": "success",
                "detail": (
                    f"Found {len(self._calendars)} calendars and "
                    f"{len(self._task_lists)} task lists."
                ),
            },
        )

    def _select(
        self,
        draft: dict[str, object],
        values: Mapping[str, object],
        principals: list[Mapping[str, str]],
    ) -> dict[str, object]:
        _connection_id, connection = _active_connection(draft)
        calendar_mode = cast(str, values["calendar_mode"])
        task_mode = cast(str, values["task_mode"])
        calendar_ids = tuple(cast(list[str], values.get("calendar_ids", [])))
        task_ids = tuple(cast(list[str], values.get("task_ids", [])))
        if calendar_mode == "selected" and not calendar_ids:
            raise PluginCallRejected(
                "selection-required", "Choose at least one calendar."
            )
        if task_mode == "selected" and not task_ids:
            raise PluginCallRejected(
                "selection-required", "Choose at least one task list."
            )
        connection["calendars"] = _selection(calendar_mode, calendar_ids)
        connection["tasks"] = _selection(task_mode, task_ids)

        selected_calendars = _selected_calendars(
            calendar_mode, calendar_ids, self._calendars
        )
        selected_tasks = _selected_resources(task_mode, task_ids, self._task_lists)
        principal_options = tuple(
            (principal["id"], principal["label"]) for principal in principals
        )
        fields: list[dict[str, object]] = []
        self._attribution_fields = {}
        for kind, resources in (
            ("calendar", selected_calendars),
            ("task_list", selected_tasks),
        ):
            for external_id, label in resources:
                field_id = "owners." + hashlib.sha256(
                    f"{kind}\0{external_id}".encode("utf-8")
                ).hexdigest()[:16]
                self._attribution_fields[field_id] = (kind, external_id)
                fields.append(
                    _field(
                        field_id,
                        f"Who owns {label}?",
                        "multi-select",
                        required=False,
                        options=principal_options,
                    )
                )
        if not fields:
            return self._review_state(draft)
        notice = None
        if not principal_options:
            notice = {
                "kind": "info",
                "detail": (
                    "No people are defined in the workspace yet. You can assign "
                    "ownership later without changing the Google connection."
                ),
            }
        return self._state(
            draft,
            step_id="attribution",
            title="Make ownership clear",
            description=(
                "A calendar or task list may belong to nobody, one person, or "
                "several people. Color remains a workspace presentation choice."
            ),
            fields=fields,
            actions=[_action("assign", "Review", "review")],
            notice=notice,
        )

    def _assign(
        self, draft: dict[str, object], values: Mapping[str, object]
    ) -> dict[str, object]:
        _connection_id, connection = _active_connection(draft)
        attribution: dict[str, dict[str, object]] = {
            "calendars": {},
            "task_lists": {},
        }
        for field_id, (kind, external_id) in self._attribution_fields.items():
            principal_ids = cast(list[str], values.get(field_id, []))
            if principal_ids:
                bucket = "calendars" if kind == "calendar" else "task_lists"
                attribution[bucket][external_id] = {
                    "principal_ids": principal_ids
                }
        if any(attribution.values()):
            connection["attribution"] = {
                key: value for key, value in attribution.items() if value
            }
        return self._review_state(draft)

    def _review_state(self, draft: Mapping[str, object]) -> dict[str, object]:
        _connection_id, connection = _active_connection(draft)
        calendars = cast(Mapping[str, object], connection["calendars"])["mode"]
        tasks = cast(Mapping[str, object], connection["tasks"])["mode"]
        return self._state(
            draft,
            step_id="review",
            title="Review this connection",
            description=(
                f"{connection['label']} will use {calendars} calendar selection "
                f"and {tasks} task-list selection. Nothing is written until the "
                "setup host commits this validated draft."
            ),
            fields=[],
            actions=[_action("finish", "Finish setup", "commit")],
        )

    def _complete_state(self, draft: dict[str, object]) -> dict[str, object]:
        settings = cast(dict[str, object], draft["settings"])
        settings.pop("setup_connection_id", None)
        return self._state(
            draft,
            step_id="complete",
            title="Google Calendar is ready",
            description="The configuration passed the plugin setup flow.",
            fields=[],
            actions=[],
            complete=True,
            notice={
                "kind": "success",
                "detail": "Review and save the configuration in the setup host.",
            },
        )


def _draft(value: object) -> dict[str, object]:
    source = cast(Mapping[str, object], value)
    settings = cast(Mapping[str, object], source["settings"])
    credentials = cast(Mapping[str, object], source["credentials"])
    return {
        "settings": _copy(settings),
        "credentials": _copy(credentials),
    }


def _copy(value: object) -> object:
    import json

    return json.loads(json.dumps(value, sort_keys=True, allow_nan=False))


def _active_connection(
    draft: Mapping[str, object],
) -> tuple[str, dict[str, object]]:
    settings = cast(dict[str, object], draft["settings"])
    connection_id = cast(str, settings["setup_connection_id"])
    connections = cast(dict[str, object], settings["connections"])
    return connection_id, cast(dict[str, object], connections[connection_id])


def _selection(mode: str, ids: tuple[str, ...]) -> dict[str, object]:
    return {"mode": mode, **({"ids": list(ids)} if mode == "selected" else {})}


def _selected_calendars(
    mode: str,
    selected_ids: tuple[str, ...],
    resources: tuple[tuple[str, str, bool], ...],
) -> tuple[tuple[str, str], ...]:
    if mode == "disabled":
        return ()
    if mode == "selected":
        selected = set(selected_ids)
        return tuple((item[0], item[1]) for item in resources if item[0] in selected)
    if mode == "defaults":
        return tuple((item[0], item[1]) for item in resources if item[2])
    return tuple((item[0], item[1]) for item in resources)


def _selected_resources(
    mode: str,
    selected_ids: tuple[str, ...],
    resources: tuple[tuple[str, str], ...],
) -> tuple[tuple[str, str], ...]:
    if mode == "disabled":
        return ()
    if mode == "selected":
        selected = set(selected_ids)
        return tuple(item for item in resources if item[0] in selected)
    return resources


def _field(
    field_id: str,
    label: str,
    widget: str,
    *,
    required: bool,
    options: tuple[tuple[str, str], ...] = (),
    value: object | None = None,
) -> dict[str, object]:
    field: dict[str, object] = {
        "id": field_id,
        "label": label,
        "widget": widget,
        "required": required,
    }
    if widget in {"select", "multi-select"}:
        field["options"] = [
            {"id": option_id, "label": option_label}
            for option_id, option_label in options
        ]
    if value is not None:
        field["value"] = value
    return field


def _action(
    action_id: str, label: str, intent: str = "continue"
) -> dict[str, str]:
    return {
        "id": action_id,
        "label": label,
        "style": "primary",
        "intent": intent,
    }
