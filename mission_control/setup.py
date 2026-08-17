"""Renderer-neutral orchestration for explicit plugin setup sessions."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from threading import RLock
from typing import cast

from mission_control.plugin_api import (
    PluginCallContractError,
    PluginCallHandler,
    call_plugin,
    validate_capability_document,
)
from mission_control.plugins import PluginRegistration


class PluginSetupError(ValueError):
    """A setup provider or caller violated the shared setup contract."""


class DocumentPluginSetup:
    """Typed adapter around one plugin-owned setup handler."""

    def __init__(
        self, registration: PluginRegistration, handler: PluginCallHandler
    ) -> None:
        self.registration = registration
        self.handler = handler

    def describe(
        self,
        draft: Mapping[str, object],
        principals: tuple[Mapping[str, str], ...],
    ) -> dict[str, object]:
        output = call_plugin(
            self.handler,
            "setup.describe",
            {"draft": dict(draft), "principals": [dict(item) for item in principals]},
        )
        return self._transition(output)

    def action(
        self,
        *,
        action_id: str,
        draft: Mapping[str, object],
        principals: tuple[Mapping[str, str], ...],
        values: Mapping[str, object],
    ) -> dict[str, object]:
        output = call_plugin(
            self.handler,
            "setup.action",
            {
                "action_id": action_id,
                "draft": dict(draft),
                "principals": [dict(item) for item in principals],
                "values": dict(values),
            },
        )
        return self._transition(output)

    def _transition(self, output: object) -> dict[str, object]:
        try:
            transition = validate_capability_document(
                output, "setup-transition.schema.json", "plugin setup transition"
            )
        except PluginCallContractError as error:
            raise PluginSetupError(str(error)) from error
        if transition["plugin_id"] != self.registration.plugin_id.value:
            raise PluginSetupError("plugin setup transition belongs to a different plugin")
        _validate_unique_ids(cast(Mapping[str, object], transition["step"]))
        return transition


class SetupSession:
    """Core-owned revision and input checks around one transient setup handler."""

    def __init__(
        self,
        provider: DocumentPluginSetup,
        *,
        settings: Mapping[str, object] | None = None,
        credential_handles: Mapping[str, str] | None = None,
        principals: tuple[Mapping[str, str], ...] = (),
        validate_complete: Callable[[Mapping[str, object]], object] | None = None,
    ) -> None:
        self.provider = provider
        self.principals = tuple(dict(item) for item in principals)
        self._initial_draft: dict[str, object] = {
            "settings": dict(settings or {}),
            "credentials": {
                name: {"handle": handle}
                for name, handle in sorted((credential_handles or {}).items())
            },
        }
        self._state: dict[str, object] | None = None
        self._revision = 0
        self._validate_complete = validate_complete
        self._validated_configuration: object | None = None
        self._lock = RLock()

    @property
    def validated_configuration(self) -> object | None:
        return self._validated_configuration

    @property
    def state(self) -> dict[str, object]:
        with self._lock:
            if self._state is None:
                self._state = self._accept(
                    self.provider.describe(self._initial_draft, self.principals),
                    revision=0,
                )
            return cast(dict[str, object], _detach(self._state))

    def act(
        self,
        action_id: str,
        values: Mapping[str, object],
        *,
        expected_revision: str,
    ) -> dict[str, object]:
        with self._lock:
            current = self.state
            if expected_revision != current["revision"]:
                raise PluginSetupError("setup state changed; refresh and try again")
            step = cast(Mapping[str, object], current["step"])
            actions = cast(list[Mapping[str, object]], step["actions"])
            action = next(
                (
                    item
                    for item in actions
                    if cast(str, item["id"]) == action_id
                ),
                None,
            )
            if action is None:
                raise PluginSetupError(
                    "setup action is not available in the current step"
                )
            normalized = _validate_values(
                step, values, action_intent=cast(str, action["intent"])
            )
            transition = self.provider.action(
                action_id=action_id,
                draft=cast(Mapping[str, object], current["draft"]),
                principals=self.principals,
                values=normalized,
            )
            next_revision = self._revision + 1
            candidate = self._accept(transition, revision=next_revision)
            validated: object | None = None
            if candidate["complete"]:
                if self._validate_complete is None:
                    raise PluginSetupError(
                        "completed setup state has no core configuration validator"
                    )
                validated = self._validate_complete(
                    cast(Mapping[str, object], candidate["draft"])
                )
            self._revision = next_revision
            self._state = candidate
            self._validated_configuration = validated
            return cast(dict[str, object], _detach(self._state))

    def _accept(
        self, transition: Mapping[str, object], *, revision: int
    ) -> dict[str, object]:
        state = {
            key: _detach(value)
            for key, value in transition.items()
            if key != "schema_version"
        }
        return {
            "schema_version": "mission-control.setup-state/v1",
            "revision": f"r{revision}",
            **state,
        }


def _validate_unique_ids(step: Mapping[str, object]) -> None:
    fields = cast(list[Mapping[str, object]], step["fields"])
    actions = cast(list[Mapping[str, object]], step["actions"])
    for label, documents in (("field", fields), ("action", actions)):
        ids = [cast(str, item["id"]) for item in documents]
        if len(ids) != len(set(ids)):
            raise PluginSetupError(f"setup step contains duplicate {label} ids")
    for field in fields:
        options = cast(list[Mapping[str, object]], field.get("options", []))
        ids = [cast(str, item["id"]) for item in options]
        if len(ids) != len(set(ids)):
            raise PluginSetupError("setup field contains duplicate option ids")


def _validate_values(
    step: Mapping[str, object],
    values: Mapping[str, object],
    *,
    action_intent: str,
) -> dict[str, object]:
    fields = {
        cast(str, field["id"]): field
        for field in cast(list[Mapping[str, object]], step["fields"])
    }
    unknown = sorted(set(values) - set(fields))
    if unknown:
        raise PluginSetupError(f"setup action supplied an unknown field: {unknown[0]}")
    normalized = dict(values)
    for field_id, field in fields.items():
        if (
            action_intent != "back"
            and field_id not in normalized
            and "value" in field
        ):
            normalized[field_id] = field["value"]
        if (
            action_intent != "back"
            and field.get("required")
            and field_id not in normalized
        ):
            raise PluginSetupError(f"setup field is required: {field_id}")
        if field_id not in normalized:
            continue
        value = normalized[field_id]
        widget = field["widget"]
        if widget == "checkbox" and not isinstance(value, bool):
            raise PluginSetupError(f"setup field expects a checkbox value: {field_id}")
        if widget in {"text", "select", "credential-file"} and not isinstance(
            value, str
        ):
            raise PluginSetupError(f"setup field expects text: {field_id}")
        if widget == "multi-select" and not (
            isinstance(value, list) and all(isinstance(item, str) for item in value)
        ):
            raise PluginSetupError(f"setup field expects a list: {field_id}")
        options = cast(list[Mapping[str, object]], field.get("options", []))
        allowed = {cast(str, option["id"]) for option in options}
        selected = value if isinstance(value, list) else [value]
        if allowed and any(item not in allowed for item in selected):
            raise PluginSetupError(f"setup field contains an unknown option: {field_id}")
    return normalized


def _detach(value: object) -> object:
    return json.loads(json.dumps(value, sort_keys=True, allow_nan=False))
