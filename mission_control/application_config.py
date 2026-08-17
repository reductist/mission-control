"""Canonical, immutable Mission Control application configuration."""

from __future__ import annotations

import json
import math
import os
import re
import stat
import tomllib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


class ApplicationConfigError(ValueError):
    """The application configuration cannot be loaded or validated safely."""


@dataclass(frozen=True, slots=True)
class ConfigLayer:
    """One ordered configuration input and its diagnostic label."""

    label: str
    document: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class ConfigExplanation:
    """One effective configuration value and every source that assigned it."""

    path: str
    value: object
    sources: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ApplicationConfigSnapshot:
    """A validated configuration frozen as canonical JSON plus immutable provenance."""

    _document_json: str
    _provenance: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...]
    _source_order: tuple[str, ...]

    def to_dict(self, *, redacted: bool = False) -> dict[str, object]:
        document = json.loads(self._document_json)
        assert isinstance(document, dict)
        return _redact(document) if redacted else document

    @property
    def database_path(self) -> str:
        return str(self.to_dict()["database"]["path"])  # type: ignore[index]

    @property
    def host(self) -> str:
        return str(self.to_dict()["http"]["host"])  # type: ignore[index]

    @property
    def port(self) -> int:
        return int(self.to_dict()["http"]["port"])  # type: ignore[index]

    @property
    def demo(self) -> bool:
        return bool(self.to_dict()["demo"])

    @property
    def plugin_roots(self) -> tuple[str, ...]:
        roots = self.to_dict()["plugin_roots"]
        assert isinstance(roots, list)
        return tuple(str(root) for root in roots)

    @property
    def enabled_plugin_ids(self) -> tuple[str, ...]:
        plugins = self.to_dict()["plugins"]
        assert isinstance(plugins, dict)
        return tuple(
            plugin_id
            for plugin_id, block in sorted(plugins.items())
            if isinstance(block, dict) and block.get("enabled") is True
        )

    def plugin_settings(self) -> dict[str, object]:
        plugins = self.to_dict()["plugins"]
        assert isinstance(plugins, dict)
        return {
            plugin_id: dict(block.get("settings", {}))
            for plugin_id, block in plugins.items()
            if isinstance(block, dict) and block.get("enabled") is True
        }

    def plugin_credentials(self) -> dict[str, dict[str, str]]:
        plugins = self.to_dict()["plugins"]
        assert isinstance(plugins, dict)
        result: dict[str, dict[str, str]] = {}
        for plugin_id, block in plugins.items():
            if not isinstance(block, dict) or block.get("enabled") is not True:
                continue
            credentials = block.get("credentials", {})
            assert isinstance(credentials, dict)
            result[plugin_id] = {
                name: str(reference["file"])
                for name, reference in credentials.items()
                if isinstance(reference, dict)
            }
        return result

    def explain(self, pointer: str, *, redacted: bool = True) -> ConfigExplanation:
        if not pointer.startswith("/") or pointer == "/":
            raise ApplicationConfigError(
                "configuration key must be a non-empty JSON Pointer"
            )
        encoded_parts = pointer[1:].split("/")
        if any(re.search(r"~(?:[^01]|$)", part) for part in encoded_parts):
            raise ApplicationConfigError(
                f"invalid JSON Pointer escape in configuration key: {pointer}"
            )
        parts = tuple(
            part.replace("~1", "/").replace("~0", "~") for part in encoded_parts
        )
        value: object = self.to_dict()
        for part in parts:
            if isinstance(value, dict) and part in value:
                value = value[part]
                continue
            if isinstance(value, list) and re.fullmatch(r"0|[1-9][0-9]*", part):
                index = int(part)
                if index < len(value):
                    value = value[index]
                    continue
            raise ApplicationConfigError(
                f"unknown effective configuration key: {pointer}"
            )
        provenance = dict(self._provenance)
        sources = provenance.get(parts)
        ancestor = parts
        while sources is None and ancestor:
            ancestor = ancestor[:-1]
            sources = provenance.get(ancestor)
        if sources is None:
            descendants = {
                source
                for path, chain in self._provenance
                if path[: len(parts)] == parts
                for source in chain
            }
            sources = tuple(
                source for source in self._source_order if source in descendants
            )
        rendered = _redact_value(parts, value) if redacted else value
        return ConfigExplanation(pointer, rendered, tuple(sources))


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    schema_path = files("mission_control").joinpath(
        "schemas", "application-config.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


@lru_cache(maxsize=1)
def _defaults() -> dict[str, object]:
    defaults_path = files("mission_control").joinpath(
        "schemas", "application-config.defaults.json"
    )
    document = json.loads(defaults_path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise RuntimeError("packaged application defaults must be a JSON object")
    return document


def _value_kind(value: object) -> str:
    if isinstance(value, Mapping):
        return "object"
    if isinstance(value, list):
        return "array"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    return type(value).__name__


def _leaf_paths(value: object, prefix: tuple[str, ...]) -> Iterable[tuple[str, ...]]:
    if isinstance(value, Mapping):
        for key, child in value.items():
            yield from _leaf_paths(child, (*prefix, str(key)))
        return
    yield prefix


def _copy_json(value: object, *, path: str = "$") -> object:
    _assert_json_value(value, path)
    return json.loads(json.dumps(value, allow_nan=False))


def _assert_json_value(value: object, path: str = "$") -> None:
    if value is None or isinstance(value, (bool, str, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ApplicationConfigError(f"{path}: non-finite numbers are not valid JSON")
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _assert_json_value(child, f"{path}[{index}]")
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise ApplicationConfigError(f"{path}: object keys must be strings")
            _assert_json_value(child, f"{path}.{key}")
        return
    raise ApplicationConfigError(
        f"{path}: {type(value).__name__} is not a valid JSON configuration value"
    )


def _merge(
    target: dict[str, object],
    incoming: Mapping[str, object],
    *,
    source: str,
    provenance: dict[tuple[str, ...], list[str]],
    prefix: tuple[str, ...] = (),
) -> None:
    for key, raw_value in incoming.items():
        path = (*prefix, str(key))
        value = _copy_json(raw_value)
        if key not in target:
            target[key] = value
            for leaf in _leaf_paths(value, path):
                provenance[leaf] = [source]
            continue

        current = target[key]
        if isinstance(current, dict) and isinstance(value, dict):
            _merge(
                current,
                value,
                source=source,
                provenance=provenance,
                prefix=path,
            )
            continue

        current_kind = _value_kind(current)
        incoming_kind = _value_kind(value)
        if current_kind != incoming_kind:
            prior_sources = sorted(
                {
                    item
                    for leaf, chain in provenance.items()
                    if leaf[: len(path)] == path
                    for item in chain
                }
            )
            prior = ", ".join(prior_sources) or "an earlier layer"
            raise ApplicationConfigError(
                f"configuration type conflict at {'.'.join(path)}: "
                f"{current_kind} from {prior}; {incoming_kind} from {source}"
            )

        target[key] = value
        prior_chain = provenance.get(path, [])
        provenance[path] = [*prior_chain, source]


def _read_toml(path: Path) -> dict[str, object]:
    try:
        with path.open("rb") as source:
            document = tomllib.load(source)
    except tomllib.TOMLDecodeError as error:
        raise ApplicationConfigError(f"invalid TOML in {path}: {error}") from error
    except OSError as error:
        raise ApplicationConfigError(f"cannot read configuration {path}: {error}") from error
    _assert_json_value(document, str(path))
    return document


def _configured_layers(
    base_path: str | Path | None,
    fragment_dirs: Sequence[str | Path],
) -> tuple[ConfigLayer, ...]:
    layers: list[ConfigLayer] = []
    if base_path is not None:
        path = Path(base_path).expanduser().resolve()
        layers.append(ConfigLayer(str(path), _read_toml(path)))
    for configured in fragment_dirs:
        directory = Path(configured).expanduser().resolve()
        if not directory.is_dir():
            raise ApplicationConfigError(
                f"configuration fragment directory does not exist: {directory}"
            )
        for path in sorted(directory.glob("*.toml"), key=lambda item: item.name):
            layers.append(ConfigLayer(str(path), _read_toml(path)))
    return tuple(layers)


def _format_validation_error(error: Any) -> str:
    path = "$" + "".join(f".{part}" for part in error.absolute_path)
    return f"{path}: {error.message}"


def load_application_config(
    *,
    base_path: str | Path | None = None,
    fragment_dirs: Sequence[str | Path] = (),
    overrides: Mapping[str, object] | None = None,
) -> ApplicationConfigSnapshot:
    """Load, merge, validate, and freeze one effective application configuration."""

    document = _copy_json(_defaults())
    assert isinstance(document, dict)
    provenance: dict[tuple[str, ...], list[str]] = {
        path: ["defaults"] for path in _leaf_paths(document, ())
    }
    layers = list(_configured_layers(base_path, fragment_dirs))
    if overrides:
        layers.append(ConfigLayer("command line", overrides))
    for layer in layers:
        _merge(
            document,
            layer.document,
            source=layer.label,
            provenance=provenance,
        )

    errors = sorted(
        _validator().iter_errors(document),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        raise ApplicationConfigError(_format_validation_error(errors[0]))

    serialized = json.dumps(document, sort_keys=True, separators=(",", ":"))
    frozen_provenance = tuple(
        (path, tuple(chain)) for path, chain in sorted(provenance.items())
    )
    return ApplicationConfigSnapshot(
        serialized,
        frozen_provenance,
        ("defaults", *(layer.label for layer in layers)),
    )


_SENSITIVE_KEY = re.compile(r"(?:password|secret|token|credential)", re.IGNORECASE)


def _redact_value(path: tuple[str, ...], value: object) -> object:
    structural_credentials = (
        len(path) >= 3 and path[0] == "plugins" and path[2] == "credentials"
    )
    opaque_plugin_settings = (
        len(path) >= 3 and path[0] == "plugins" and path[2] == "settings"
    )
    credential_file = structural_credentials and path[-1:] == ("file",)
    sensitive_setting = not structural_credentials and any(
        _SENSITIVE_KEY.search(part) for part in path
    )
    if credential_file or opaque_plugin_settings or sensitive_setting:
        return "<redacted>"
    if isinstance(value, dict):
        return {
            key: _redact_value((*path, str(key)), child)
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [_redact_value(path, child) for child in value]
    return value


def _redact(document: dict[str, object]) -> dict[str, object]:
    rendered = _redact_value((), document)
    assert isinstance(rendered, dict)
    return rendered


def prepare_application_plugins(snapshot: ApplicationConfigSnapshot) -> tuple[Any, ...]:
    """Validate every enabled plugin and credential reference before side effects."""

    from mission_control.plugin_lifecycle import (  # Imported without plugin entrypoints.
        PluginLifecycleError,
        prepare_agenda_plugins,
    )

    try:
        prepared = prepare_agenda_plugins(
            snapshot.enabled_plugin_ids,
            roots=snapshot.plugin_roots,
            configurations=snapshot.plugin_settings(),
            credentials=snapshot.plugin_credentials(),
        )
    except (OSError, PluginLifecycleError, ValueError) as error:
        raise ApplicationConfigError(str(error)) from error

    for plugin_id, credentials in snapshot.plugin_credentials().items():
        for name, configured_path in credentials.items():
            path = Path(configured_path).expanduser()
            if not path.is_file():
                raise ApplicationConfigError(
                    f"{plugin_id}.{name}: credential file is unavailable: {path}"
                )
            if os.name == "posix":
                mode = stat.S_IMODE(path.stat().st_mode)
                if mode & (stat.S_IRWXG | stat.S_IRWXO):
                    raise ApplicationConfigError(
                        f"{plugin_id}.{name}: credential file must not be "
                        "accessible by group or other users"
                    )
            try:
                with path.open("rb"):
                    pass
            except OSError as error:
                raise ApplicationConfigError(
                    f"{plugin_id}.{name}: credential file is unreadable: {path}"
                ) from error
    return prepared
