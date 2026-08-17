"""Small public Python adapter for versioned JSON plugin capability calls."""

from __future__ import annotations

import json
import math
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from types import MappingProxyType
from typing import Any, ContextManager, Protocol, cast

from jsonschema import Draft202012Validator, FormatChecker


class PluginCallContractError(ValueError):
    """A capability request or result violates the public JSON contract."""


class PluginCallRejected(RuntimeError):
    """A plugin deliberately rejects one otherwise valid capability call."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


class PluginStorage(Protocol):
    """Current in-process namespaced SQLite boundary supplied by core."""

    @property
    def namespace(self) -> str: ...

    def table_name(self, local_name: str) -> str: ...

    def connect(self) -> ContextManager[sqlite3.Connection]: ...


@dataclass(frozen=True, slots=True)
class PluginContext:
    """Activation context containing only one plugin's approved resources."""

    plugin_id: str
    storage: PluginStorage
    configuration: Mapping[str, object]
    credentials: Mapping[str, str]
    agenda_seed: object | None = None

    @classmethod
    def create(
        cls,
        *,
        plugin_id: str,
        storage: PluginStorage,
        configuration: Mapping[str, object],
        credentials: Mapping[str, str],
        agenda_seed: object | None = None,
    ) -> PluginContext:
        return cls(
            plugin_id,
            storage,
            MappingProxyType(_detached_object(configuration)),
            MappingProxyType(dict(credentials)),
            _detached_json(agenda_seed) if agenda_seed is not None else None,
        )


class PluginCallHandler(Protocol):
    def call(self, request: object) -> object: ...


CapabilityOperation = Callable[[Mapping[str, object]], object]


class CapabilityRouter:
    """Plugin-facing dispatcher that supplies consistent call result envelopes."""

    def __init__(
        self,
        plugin_id: str,
        operations: Mapping[str, CapabilityOperation],
    ) -> None:
        self.plugin_id = plugin_id
        self._operations = dict(operations)

    def call(self, request: object) -> object:
        raw = validate_plugin_call(request)
        operation = cast(str, raw["operation"])
        inputs = cast(dict[str, object], raw["input"])
        if operation == "runtime.describe":
            output: object = {
                "schema_version": "mission-control.plugin-runtime/v1",
                "plugin_id": self.plugin_id,
                "operations": sorted((*self._operations, "runtime.describe")),
            }
            return validate_plugin_call_result(_success(operation, output))
        callback = self._operations.get(operation)
        if callback is None:
            return validate_plugin_call_result(
                _failure(
                    operation,
                    "unsupported-operation",
                    "The plugin does not implement this declared operation.",
                )
            )
        try:
            output = callback(MappingProxyType(inputs))
        except PluginCallRejected as error:
            return validate_plugin_call_result(
                _failure(operation, error.code, error.detail)
            )
        return validate_plugin_call_result(_success(operation, output))


def call_plugin(
    handler: PluginCallHandler,
    operation: str,
    inputs: Mapping[str, object],
) -> object:
    """Validate both sides of one in-process capability call."""

    request = validate_plugin_call(
        {
            "schema_version": "mission-control.plugin-call/v1",
            "operation": operation,
            "input": dict(inputs),
        }
    )
    try:
        response = handler.call(request)
    except Exception as error:
        raise PluginCallContractError(
            f"{operation}: plugin operation failed ({type(error).__name__})"
        ) from error
    result = validate_plugin_call_result(response)
    if result["operation"] != operation:
        raise PluginCallContractError("plugin result operation does not match its call")
    if result["status"] == "error":
        error = cast(dict[str, str], result["error"])
        raise PluginCallRejected(error["code"], error["detail"])
    return _detached_json(result["output"])


def validate_plugin_call(document: object) -> dict[str, object]:
    return _validate_document(document, "plugin-call.schema.json", "plugin call")


def validate_plugin_call_result(document: object) -> dict[str, object]:
    return _validate_document(
        document, "plugin-call-result.schema.json", "plugin call result"
    )


def validate_capability_document(
    document: object, schema_name: str, label: str
) -> dict[str, object]:
    """Validate an operation-specific document returned through the call envelope."""

    return _validate_document(document, schema_name, label)


@lru_cache(maxsize=None)
def _validator(schema_name: str) -> Draft202012Validator:
    path = files("mission_control").joinpath("schemas", schema_name)
    schema = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _validate_document(
    document: object, schema_name: str, label: str
) -> dict[str, object]:
    _assert_json(document, label=label)
    detached = _detached_json(document)
    if not isinstance(detached, dict):
        raise PluginCallContractError(f"$: {label} must be a JSON object")
    errors = sorted(
        _validator(schema_name).iter_errors(detached),
        key=lambda error: (
            tuple(str(part) for part in error.absolute_path),
            error.message,
        ),
    )
    if errors:
        error = errors[0]
        path = "/" + "/".join(str(part) for part in error.absolute_path)
        raise PluginCallContractError(
            f"{path if path != '/' else '$'}: {label} violates its schema"
        )
    return cast(dict[str, object], detached)


def _success(operation: str, output: object) -> dict[str, object]:
    return {
        "schema_version": "mission-control.plugin-call-result/v1",
        "operation": operation,
        "status": "ok",
        "output": output,
    }


def _failure(operation: str, code: str, detail: str) -> dict[str, object]:
    return {
        "schema_version": "mission-control.plugin-call-result/v1",
        "operation": operation,
        "status": "error",
        "error": {"code": code, "detail": detail},
    }


def _assert_json(value: object, path: str = "$", *, label: str) -> None:
    if value is None or isinstance(value, (bool, int, str)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise PluginCallContractError(f"{path}: non-finite JSON number in {label}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _assert_json(item, f"{path}/{index}", label=label)
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise PluginCallContractError(f"{path}: non-string JSON key in {label}")
            _assert_json(item, f"{path}/{key}", label=label)
        return
    raise PluginCallContractError(
        f"{path}: {label} must contain only JSON values, got {type(value).__name__}"
    )


def _detached_json(value: object) -> object:
    return json.loads(json.dumps(value, sort_keys=True, allow_nan=False))


def _detached_object(value: Mapping[str, object]) -> dict[str, object]:
    detached = _detached_json(dict(value))
    assert isinstance(detached, dict)
    return cast(dict[str, object], detached)
