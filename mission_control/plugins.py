"""Immutable plugin registration parsing and discovery catalog construction."""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from typing import Any, ClassVar, TypeAlias, cast

from jsonschema import Draft202012Validator


class PluginRegistrationError(ValueError):
    """A plugin registration document cannot be parsed into the domain model."""


class PluginDiscoveryError(ValueError):
    """Configured plugin roots cannot be scanned deterministically."""


class PluginSchemaVersion(StrEnum):
    V1 = "mission-control.plugin/v1"


class Capability(StrEnum):
    CLI = "cli"
    HTTP = "http"
    JOBS = "jobs"
    EVENTS = "events"
    UI = "ui"
    HEALTH = "health"


class ArgumentType(StrEnum):
    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    ARRAY = "array"
    OBJECT = "object"


class CatalogState(StrEnum):
    AVAILABLE = "available"
    REJECTED = "rejected"
    CONFLICTED = "conflicted"


@dataclass(frozen=True, slots=True, order=True)
class PluginId:
    value: str


JsonScalar: TypeAlias = None | bool | int | float | str


@dataclass(frozen=True, slots=True)
class JsonArray:
    values: tuple[JsonValue, ...]


@dataclass(frozen=True, slots=True)
class JsonObject:
    values: tuple[tuple[str, JsonValue], ...]


JsonValue: TypeAlias = JsonScalar | JsonArray | JsonObject


@dataclass(frozen=True, slots=True)
class ArgumentMetadata:
    required: bool = False
    description: str | None = None


@dataclass(frozen=True, slots=True)
class StringArgument:
    kind: ClassVar[ArgumentType] = ArgumentType.STRING
    metadata: ArgumentMetadata
    default: str | None = None
    enum: tuple[str, ...] | None = None
    pattern: str | None = None
    min_length: int | None = None
    max_length: int | None = None


@dataclass(frozen=True, slots=True)
class IntegerArgument:
    kind: ClassVar[ArgumentType] = ArgumentType.INTEGER
    metadata: ArgumentMetadata
    default: int | None = None
    enum: tuple[int, ...] | None = None
    minimum: int | None = None
    maximum: int | None = None


@dataclass(frozen=True, slots=True)
class NumberArgument:
    kind: ClassVar[ArgumentType] = ArgumentType.NUMBER
    metadata: ArgumentMetadata
    default: int | float | None = None
    enum: tuple[int | float, ...] | None = None
    minimum: int | float | None = None
    maximum: int | float | None = None


@dataclass(frozen=True, slots=True)
class BooleanArgument:
    kind: ClassVar[ArgumentType] = ArgumentType.BOOLEAN
    metadata: ArgumentMetadata
    default: bool | None = None


@dataclass(frozen=True, slots=True)
class ArrayArgument:
    kind: ClassVar[ArgumentType] = ArgumentType.ARRAY
    metadata: ArgumentMetadata
    items: ArgumentDefinition
    default: JsonArray | None = None
    min_items: int | None = None
    max_items: int | None = None


@dataclass(frozen=True, slots=True)
class ObjectArgument:
    kind: ClassVar[ArgumentType] = ArgumentType.OBJECT
    metadata: ArgumentMetadata
    properties: tuple[PluginArgument, ...] = ()
    additional_properties: bool = False
    default: JsonObject | None = None


ArgumentDefinition: TypeAlias = (
    StringArgument
    | IntegerArgument
    | NumberArgument
    | BooleanArgument
    | ArrayArgument
    | ObjectArgument
)


@dataclass(frozen=True, slots=True)
class PluginArgument:
    name: str
    definition: ArgumentDefinition


@dataclass(frozen=True, slots=True)
class PluginRegistration:
    schema_version: PluginSchemaVersion
    plugin_id: PluginId
    name: str
    version: str
    plugin_api: str
    capabilities: tuple[Capability, ...]
    arguments: tuple[PluginArgument, ...] = ()


@dataclass(frozen=True, slots=True, order=True)
class PluginSource:
    registration_path: Path


@dataclass(frozen=True, slots=True)
class RegistrationFailure:
    summary: str


@dataclass(frozen=True, slots=True)
class ParsedRegistrationCandidate:
    source: PluginSource
    registration: PluginRegistration


@dataclass(frozen=True, slots=True)
class RejectedRegistrationCandidate:
    source: PluginSource
    failure: RegistrationFailure


RegistrationCandidate: TypeAlias = ParsedRegistrationCandidate | RejectedRegistrationCandidate


@dataclass(frozen=True, slots=True)
class AvailablePlugin:
    state: ClassVar[CatalogState] = CatalogState.AVAILABLE
    source: PluginSource
    registration: PluginRegistration


@dataclass(frozen=True, slots=True)
class RejectedPlugin:
    state: ClassVar[CatalogState] = CatalogState.REJECTED
    source: PluginSource
    failure: RegistrationFailure


@dataclass(frozen=True, slots=True)
class ConflictedPlugin:
    state: ClassVar[CatalogState] = CatalogState.CONFLICTED
    plugin_id: PluginId
    sources: tuple[PluginSource, ...]


PluginCatalogEntry: TypeAlias = AvailablePlugin | RejectedPlugin | ConflictedPlugin


@dataclass(frozen=True, slots=True)
class PluginCatalog:
    entries: tuple[PluginCatalogEntry, ...]

    def __iter__(self) -> Iterator[PluginCatalogEntry]:
        return iter(self.entries)

    def __len__(self) -> int:
        return len(self.entries)


@lru_cache(maxsize=1)
def _registration_validator() -> Draft202012Validator:
    schema_path = files("mission_control").joinpath(
        "schemas", "plugin-registration.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _assert_json_input(value: object, path: str = "$") -> None:
    if value is None or isinstance(value, (bool, int, str)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise PluginRegistrationError(f"{path}: non-finite numbers are not JSON values")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _assert_json_input(item, f"{path}.{index}")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise PluginRegistrationError(f"{path}: JSON object keys must be strings")
            _assert_json_input(item, f"{path}.{key}")
        return
    raise PluginRegistrationError(
        f"{path}: plugin registration must contain only JSON values; "
        f"got {type(value).__name__}"
    )


def _validated_document(document: object) -> dict[str, Any]:
    _assert_json_input(document)
    detached = json.loads(json.dumps(document, sort_keys=True, allow_nan=False))
    if not isinstance(detached, dict):
        raise PluginRegistrationError("$: plugin registration must be a JSON object")

    errors = sorted(
        _registration_validator().iter_errors(detached),
        key=lambda error: (
            tuple(str(part) for part in error.absolute_path),
            error.message,
        ),
    )
    if errors:
        error = errors[0]
        path = ".".join(str(part) for part in error.absolute_path) or "$"
        raise PluginRegistrationError(f"{path}: {error.message}")
    return cast(dict[str, Any], detached)


def _freeze_json(value: Any) -> JsonValue:
    if isinstance(value, dict):
        return JsonObject(
            tuple((key, _freeze_json(item)) for key, item in sorted(value.items()))
        )
    if isinstance(value, list):
        return JsonArray(tuple(_freeze_json(item) for item in value))
    return cast(JsonScalar, value)


def _thaw_json(value: JsonValue) -> Any:
    if isinstance(value, JsonObject):
        return {key: _thaw_json(item) for key, item in value.values}
    if isinstance(value, JsonArray):
        return [_thaw_json(item) for item in value.values]
    return value


def _metadata(raw: Mapping[str, Any]) -> ArgumentMetadata:
    return ArgumentMetadata(
        required=raw.get("required", False),
        description=raw.get("description"),
    )


def _parse_argument(raw: Mapping[str, Any]) -> ArgumentDefinition:
    kind = ArgumentType(raw["type"])
    metadata = _metadata(raw)

    match kind:
        case ArgumentType.STRING:
            return StringArgument(
                metadata=metadata,
                default=raw.get("default"),
                enum=tuple(raw["enum"]) if "enum" in raw else None,
                pattern=raw.get("pattern"),
                min_length=raw.get("min_length"),
                max_length=raw.get("max_length"),
            )
        case ArgumentType.INTEGER:
            return IntegerArgument(
                metadata=metadata,
                default=raw.get("default"),
                enum=tuple(raw["enum"]) if "enum" in raw else None,
                minimum=raw.get("minimum"),
                maximum=raw.get("maximum"),
            )
        case ArgumentType.NUMBER:
            return NumberArgument(
                metadata=metadata,
                default=raw.get("default"),
                enum=tuple(raw["enum"]) if "enum" in raw else None,
                minimum=raw.get("minimum"),
                maximum=raw.get("maximum"),
            )
        case ArgumentType.BOOLEAN:
            return BooleanArgument(
                metadata=metadata,
                default=raw.get("default"),
            )
        case ArgumentType.ARRAY:
            default = _freeze_json(raw["default"]) if "default" in raw else None
            return ArrayArgument(
                metadata=metadata,
                items=_parse_argument(raw["items"]),
                default=cast(JsonArray | None, default),
                min_items=raw.get("min_items"),
                max_items=raw.get("max_items"),
            )
        case ArgumentType.OBJECT:
            properties = tuple(
                PluginArgument(name, _parse_argument(definition))
                for name, definition in sorted(raw.get("properties", {}).items())
            )
            default = _freeze_json(raw["default"]) if "default" in raw else None
            return ObjectArgument(
                metadata=metadata,
                properties=properties,
                additional_properties=raw.get("additional_properties", False),
                default=cast(JsonObject | None, default),
            )

    raise AssertionError(f"unhandled argument type: {kind}")


def parse_plugin_registration(document: object) -> PluginRegistration:
    """Parse untrusted JSON-shaped data into an immutable registration value."""

    raw = _validated_document(document)
    arguments = tuple(
        PluginArgument(name, _parse_argument(definition))
        for name, definition in sorted(raw.get("arguments", {}).items())
    )
    return PluginRegistration(
        schema_version=PluginSchemaVersion(raw["schema_version"]),
        plugin_id=PluginId(raw["id"]),
        name=raw["name"],
        version=raw["version"],
        plugin_api=raw["plugin_api"],
        capabilities=tuple(Capability(value) for value in raw["capabilities"]),
        arguments=arguments,
    )


def load_registration(path: str | Path) -> PluginRegistration:
    """Read and parse one registration document from the filesystem shell."""

    try:
        with Path(path).open(encoding="utf-8") as source:
            document = json.load(source)
    except json.JSONDecodeError as error:
        raise PluginRegistrationError(
            f"invalid JSON at line {error.lineno}, column {error.colno}: {error.msg}"
        ) from error
    return parse_plugin_registration(document)


def _metadata_to_dict(metadata: ArgumentMetadata) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if metadata.required:
        result["required"] = True
    if metadata.description is not None:
        result["description"] = metadata.description
    return result


def argument_to_dict(argument: ArgumentDefinition) -> dict[str, Any]:
    result = _metadata_to_dict(argument.metadata)
    result["type"] = argument.kind.value

    if isinstance(argument, StringArgument):
        if argument.default is not None:
            result["default"] = argument.default
        if argument.enum is not None:
            result["enum"] = list(argument.enum)
        if argument.pattern is not None:
            result["pattern"] = argument.pattern
        if argument.min_length is not None:
            result["min_length"] = argument.min_length
        if argument.max_length is not None:
            result["max_length"] = argument.max_length
    elif isinstance(argument, IntegerArgument):
        if argument.default is not None:
            result["default"] = argument.default
        if argument.enum is not None:
            result["enum"] = list(argument.enum)
        if argument.minimum is not None:
            result["minimum"] = argument.minimum
        if argument.maximum is not None:
            result["maximum"] = argument.maximum
    elif isinstance(argument, NumberArgument):
        if argument.default is not None:
            result["default"] = argument.default
        if argument.enum is not None:
            result["enum"] = list(argument.enum)
        if argument.minimum is not None:
            result["minimum"] = argument.minimum
        if argument.maximum is not None:
            result["maximum"] = argument.maximum
    elif isinstance(argument, BooleanArgument):
        if argument.default is not None:
            result["default"] = argument.default
    elif isinstance(argument, ArrayArgument):
        result["items"] = argument_to_dict(argument.items)
        if argument.default is not None:
            result["default"] = _thaw_json(argument.default)
        if argument.min_items is not None:
            result["min_items"] = argument.min_items
        if argument.max_items is not None:
            result["max_items"] = argument.max_items
    elif isinstance(argument, ObjectArgument):
        if argument.properties:
            result["properties"] = {
                item.name: argument_to_dict(item.definition)
                for item in argument.properties
            }
        if argument.additional_properties:
            result["additional_properties"] = True
        if argument.default is not None:
            result["default"] = _thaw_json(argument.default)
    else:
        raise AssertionError(f"unhandled argument definition: {argument!r}")

    return result


def registration_to_dict(registration: PluginRegistration) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema_version": registration.schema_version.value,
        "id": registration.plugin_id.value,
        "name": registration.name,
        "version": registration.version,
        "plugin_api": registration.plugin_api,
        "capabilities": [value.value for value in registration.capabilities],
    }
    if registration.arguments:
        result["arguments"] = {
            argument.name: argument_to_dict(argument.definition)
            for argument in registration.arguments
        }
    return result


def discover_registration_sources(
    roots: Iterable[str | Path],
) -> tuple[PluginSource, ...]:
    """Discover direct plugin registration files from explicitly configured roots."""

    configured = tuple(Path(root).expanduser().resolve() for root in roots)
    if not configured:
        raise PluginDiscoveryError("at least one plugin root is required")

    discovered: dict[str, PluginSource] = {}
    for root in configured:
        if not root.exists():
            raise PluginDiscoveryError(f"plugin root does not exist: {root}")
        if root.is_file():
            if root.name != "registration.json":
                raise PluginDiscoveryError(
                    f"plugin root file must be named registration.json: {root}"
                )
            discovered[str(root)] = PluginSource(root)
            continue
        if not root.is_dir():
            raise PluginDiscoveryError(f"plugin root is not a directory: {root}")

        direct = root / "registration.json"
        if direct.is_file():
            discovered[str(direct)] = PluginSource(direct)

        for child in sorted(root.iterdir(), key=lambda item: item.name):
            registration_path = child / "registration.json"
            if child.is_dir() and registration_path.is_file():
                discovered[str(registration_path)] = PluginSource(registration_path)

    return tuple(discovered[key] for key in sorted(discovered))


def read_registration_candidate(source: PluginSource) -> RegistrationCandidate:
    """Read one source at the imperative boundary and return an immutable result."""

    try:
        registration = load_registration(source.registration_path)
    except (OSError, PluginRegistrationError) as error:
        return RejectedRegistrationCandidate(source, RegistrationFailure(str(error)))
    return ParsedRegistrationCandidate(source, registration)


def build_plugin_catalog(candidates: Iterable[RegistrationCandidate]) -> PluginCatalog:
    """Purely build a deterministic catalog from immutable candidate results."""

    parsed: dict[PluginId, list[ParsedRegistrationCandidate]] = {}
    rejected: list[RejectedPlugin] = []

    for candidate in candidates:
        if isinstance(candidate, RejectedRegistrationCandidate):
            rejected.append(RejectedPlugin(candidate.source, candidate.failure))
            continue
        parsed.setdefault(candidate.registration.plugin_id, []).append(candidate)

    entries: list[PluginCatalogEntry] = list(rejected)
    for plugin_id in sorted(parsed):
        matches = sorted(
            parsed[plugin_id],
            key=lambda candidate: str(candidate.source.registration_path),
        )
        if len(matches) == 1:
            match = matches[0]
            entries.append(AvailablePlugin(match.source, match.registration))
        else:
            entries.append(
                ConflictedPlugin(
                    plugin_id,
                    tuple(candidate.source for candidate in matches),
                )
            )

    def sort_key(entry: PluginCatalogEntry) -> tuple[int, str, str]:
        if isinstance(entry, AvailablePlugin):
            return (0, entry.registration.plugin_id.value, str(entry.source.registration_path))
        if isinstance(entry, ConflictedPlugin):
            return (1, entry.plugin_id.value, "")
        return (2, "", str(entry.source.registration_path))

    return PluginCatalog(tuple(sorted(entries, key=sort_key)))


def scan_plugin_catalog(roots: Iterable[str | Path]) -> PluginCatalog:
    """Imperative shell: discover and read sources, then invoke the pure catalog core."""

    sources = discover_registration_sources(roots)
    return build_plugin_catalog(read_registration_candidate(source) for source in sources)


def catalog_entry_to_dict(entry: PluginCatalogEntry) -> dict[str, Any]:
    if isinstance(entry, AvailablePlugin):
        return {
            "state": entry.state.value,
            "id": entry.registration.plugin_id.value,
            "name": entry.registration.name,
            "version": entry.registration.version,
            "source": str(entry.source.registration_path),
        }
    if isinstance(entry, ConflictedPlugin):
        return {
            "state": entry.state.value,
            "id": entry.plugin_id.value,
            "sources": [str(source.registration_path) for source in entry.sources],
        }
    return {
        "state": entry.state.value,
        "source": str(entry.source.registration_path),
        "error": entry.failure.summary,
    }


def catalog_to_list(catalog: PluginCatalog) -> list[dict[str, Any]]:
    return [catalog_entry_to_dict(entry) for entry in catalog]
