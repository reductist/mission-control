"""Immutable plugin registration parsing and discovery catalog construction."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from typing import Any, ClassVar, Protocol, TypeAlias, cast
from urllib.parse import unquote

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError
from referencing.exceptions import Unresolvable


class PluginRegistrationError(ValueError):
    """A plugin registration document cannot be parsed into the domain model."""


class PluginConfigurationError(ValueError):
    """A plugin configuration does not satisfy its CUE-generated contract."""


class PluginCompatibilityError(ValueError):
    """A plugin does not support the host's public plugin API version."""


class PluginDiscoveryError(ValueError):
    """Configured plugin roots cannot be scanned deterministically."""


class PluginSchemaVersion(StrEnum):
    V2 = "mission-control.plugin/v2"


class Capability(StrEnum):
    AGENDA = "agenda"
    CLOSED_ITEMS = "closed-items"
    COMMANDS = "commands"
    ENTITY_DETAILS = "entity-details"
    CLI = "cli"
    HTTP = "http"
    JOBS = "jobs"
    EVENTS = "events"
    UI = "ui"
    HEALTH = "health"


class Permission(StrEnum):
    DATABASE = "database"
    NETWORK = "network"
    CREDENTIALS = "credentials"


class StandardEntityCapability(StrEnum):
    ENTITY_ANNOTATE = "entity.annotate"
    ENTITY_ATTACH = "entity.attach"
    ACTIVITY_READ = "activity.read"
    LIFECYCLE_COMPLETE = "lifecycle.complete"
    LIFECYCLE_REOPEN = "lifecycle.reopen"
    LIFECYCLE_ACKNOWLEDGE = "lifecycle.acknowledge"
    LIFECYCLE_DISMISS = "lifecycle.dismiss"
    ENTITY_EDIT = "entity.edit"
    ENTITY_DELETE = "entity.delete"


class CatalogState(StrEnum):
    AVAILABLE = "available"
    REJECTED = "rejected"
    CONFLICTED = "conflicted"


@dataclass(frozen=True, slots=True, order=True)
class PluginId:
    value: str


@dataclass(frozen=True, slots=True, order=True)
class EntityCapability:
    value: str


@dataclass(frozen=True, slots=True)
class EntityTypeRegistration:
    entity_type: str
    capabilities: tuple[EntityCapability, ...]


@dataclass(frozen=True, slots=True)
class EntityAffordance:
    capability: EntityCapability
    command: str


JsonScalar: TypeAlias = None | bool | int | float | str


@dataclass(frozen=True, slots=True)
class JsonArray:
    values: tuple[JsonValue, ...]


@dataclass(frozen=True, slots=True)
class JsonObject:
    values: tuple[tuple[str, JsonValue], ...]


JsonValue: TypeAlias = JsonScalar | JsonArray | JsonObject


@dataclass(frozen=True, slots=True)
class PluginRuntime:
    entrypoint: str
    migration_set: str | None = None
    agenda_seed: str | None = None


@dataclass(frozen=True, slots=True)
class PluginConfigurationContract:
    document_version: str
    schema_resource: str
    defaults_resource: str
    presentation_resource: str


@dataclass(frozen=True, slots=True)
class PluginRegistration:
    schema_version: PluginSchemaVersion
    plugin_id: PluginId
    name: str
    version: str
    plugin_api: str
    capabilities: tuple[Capability, ...]
    configuration: PluginConfigurationContract
    runtime: PluginRuntime | None = None
    permissions: tuple[Permission, ...] = ()
    entity_types: tuple[EntityTypeRegistration, ...] = ()


@dataclass(frozen=True, slots=True)
class PluginConfiguration:
    """One detached, validated, namespaced plugin configuration."""

    values: tuple[tuple[str, JsonValue], ...]

    def to_dict(self) -> dict[str, Any]:
        return {key: _thaw_json(value) for key, value in self.values}


@dataclass(frozen=True, slots=True)
class ValidatedPluginConfiguration:
    settings: PluginConfiguration
    credentials: tuple[tuple[str, str], ...]


class PluginResourceReader(Protocol):
    def __call__(self, name: str) -> object: ...


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


def _assert_json_input(
    value: object, path: str = "$", *, label: str = "plugin registration"
) -> None:
    if value is None or isinstance(value, (bool, int, str)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise PluginRegistrationError(f"{path}: non-finite numbers are not JSON values")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _assert_json_input(item, f"{path}.{index}", label=label)
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise PluginRegistrationError(f"{path}: JSON object keys must be strings")
            _assert_json_input(item, f"{path}.{key}", label=label)
        return
    raise PluginRegistrationError(
        f"{path}: {label} must contain only JSON values; "
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


def parse_plugin_registration(document: object) -> PluginRegistration:
    """Parse untrusted JSON-shaped data into an immutable registration value."""

    raw = _validated_document(document)
    plugin_id = PluginId(raw["id"])
    raw_configuration = raw["configuration"]
    configuration = PluginConfigurationContract(
        document_version=raw_configuration["document_version"],
        schema_resource=raw_configuration["schema_resource"],
        defaults_resource=raw_configuration["defaults_resource"],
        presentation_resource=raw_configuration["presentation_resource"],
    )
    raw_runtime = raw.get("runtime")
    runtime = (
        PluginRuntime(
            entrypoint=raw_runtime["entrypoint"],
            migration_set=raw_runtime.get("migration_set"),
            agenda_seed=raw_runtime.get("agenda_seed"),
        )
        if raw_runtime is not None
        else None
    )
    entity_types = tuple(
        EntityTypeRegistration(
            entity_type,
            _parse_entity_capabilities(
                definition["capabilities"],
                plugin_id=plugin_id,
                entity_type=entity_type,
            ),
        )
        for entity_type, definition in sorted(raw.get("entity_types", {}).items())
    )
    return PluginRegistration(
        schema_version=PluginSchemaVersion(raw["schema_version"]),
        plugin_id=plugin_id,
        name=raw["name"],
        version=raw["version"],
        plugin_api=raw["plugin_api"],
        capabilities=tuple(Capability(value) for value in raw["capabilities"]),
        configuration=configuration,
        runtime=runtime,
        permissions=tuple(Permission(value) for value in raw.get("permissions", [])),
        entity_types=entity_types,
    )


@lru_cache(maxsize=2)
def _configuration_artifact_validator(name: str) -> Draft202012Validator:
    schema_path = files("mission_control").joinpath("schemas", name)
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _configuration_document(value: object, *, label: str) -> dict[str, Any]:
    try:
        _assert_json_input(value, label="configuration")
    except PluginRegistrationError as error:
        raise PluginConfigurationError(f"{label}: {error}") from error
    detached = json.loads(json.dumps(value, sort_keys=True, allow_nan=False))
    if not isinstance(detached, dict):
        raise PluginConfigurationError(f"{label}: expected a JSON object")
    return cast(dict[str, Any], detached)


def _validate_artifact(
    document: dict[str, Any], *, schema_name: str, label: str
) -> None:
    errors = sorted(
        _configuration_artifact_validator(schema_name).iter_errors(document),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        raise PluginConfigurationError(
            f"{label}: invalid {errors[0].validator or 'document'}"
        )


def _fill_absent(defaults: object, configured: object) -> object:
    if not isinstance(defaults, dict) or not isinstance(configured, dict):
        return json.loads(json.dumps(configured, sort_keys=True))
    result = json.loads(json.dumps(defaults, sort_keys=True))
    assert isinstance(result, dict)
    for key, value in configured.items():
        result[key] = (
            _fill_absent(result[key], value)
            if key in result
            else json.loads(json.dumps(value, sort_keys=True))
        )
    return result


def _json_pointer_tokens(pointer: str) -> tuple[str, ...]:
    if not pointer:
        return ()
    return tuple(
        token.replace("~1", "/").replace("~0", "~")
        for token in pointer[1:].split("/")
    )


def _resolve_local_ref(root: Mapping[str, Any], reference: str) -> Mapping[str, Any] | None:
    if reference == "#":
        return root
    if not reference.startswith("#/"):
        return None
    current: object = root
    for token in _json_pointer_tokens(reference[1:]):
        token = unquote(token)
        if not isinstance(current, Mapping) or token not in current:
            return None
        current = current[token]
    return current if isinstance(current, Mapping) else None


def _schema_children(
    root: Mapping[str, Any],
    node: Mapping[str, Any],
    token: str,
    seen: set[int] | None = None,
) -> tuple[Mapping[str, Any], ...]:
    visited = seen if seen is not None else set()
    marker = id(node)
    if marker in visited:
        return ()
    visited.add(marker)

    children: list[Mapping[str, Any]] = []
    properties = node.get("properties")
    if isinstance(properties, Mapping):
        child = properties.get(token)
        if isinstance(child, Mapping):
            children.append(child)
    reference = node.get("$ref")
    if isinstance(reference, str):
        resolved = _resolve_local_ref(root, reference)
        if resolved is not None:
            children.extend(_schema_children(root, resolved, token, visited))
    for keyword in ("oneOf", "anyOf", "allOf"):
        branches = node.get(keyword, ())
        if isinstance(branches, list):
            for branch in branches:
                if isinstance(branch, Mapping):
                    children.extend(_schema_children(root, branch, token, visited))
    return tuple(children)


def _schema_has_pointer(schema: Mapping[str, Any], pointer: str) -> bool:
    nodes: tuple[Mapping[str, Any], ...] = (schema,)
    for token in _json_pointer_tokens(pointer):
        nodes = tuple(
            child
            for node in nodes
            for child in _schema_children(schema, node, token)
        )
        if not nodes:
            return False
    return True


def _reject_external_schema_references(value: object, *, root: bool = True) -> None:
    if isinstance(value, list):
        for item in value:
            _reject_external_schema_references(item, root=False)
        return
    if not isinstance(value, Mapping):
        return
    if not root and ("$id" in value or "$schema" in value):
        raise PluginConfigurationError(
            "configuration schema may declare identity and dialect only at its root"
        )
    for keyword in ("$ref", "$dynamicRef"):
        reference = value.get(keyword)
        if (
            isinstance(reference, str)
            and reference != "#"
            and not reference.startswith("#/")
        ):
            raise PluginConfigurationError(
                "configuration schema may use only local references"
            )
    for item in value.values():
        _reject_external_schema_references(item, root=False)


def _partial_configuration_schema(value: object) -> object:
    """Allow omitted operator values while retaining every declared value rule."""

    if not isinstance(value, Mapping):
        return value
    relaxed = dict(value)
    relaxed.pop("required", None)
    for keyword in (
        "additionalProperties",
        "contains",
        "contentSchema",
        "else",
        "if",
        "items",
        "not",
        "propertyNames",
        "then",
        "unevaluatedItems",
        "unevaluatedProperties",
    ):
        child = relaxed.get(keyword)
        if isinstance(child, Mapping):
            relaxed[keyword] = _partial_configuration_schema(child)
    for keyword in ("allOf", "anyOf", "oneOf", "prefixItems"):
        children = relaxed.get(keyword)
        if isinstance(children, list):
            relaxed[keyword] = [
                _partial_configuration_schema(child)
                if isinstance(child, Mapping)
                else child
                for child in children
            ]
    for keyword in ("$defs", "dependentSchemas", "patternProperties", "properties"):
        children = relaxed.get(keyword)
        if isinstance(children, Mapping):
            relaxed[keyword] = {
                name: _partial_configuration_schema(child)
                if isinstance(child, Mapping)
                else child
                for name, child in children.items()
            }
    return relaxed


def _configuration_leaf_errors(error: Any) -> tuple[Any, ...]:
    if not error.context:
        return (error,)
    return tuple(
        leaf for child in error.context for leaf in _configuration_leaf_errors(child)
    )


def _configuration_error(error: Any) -> str:
    path = "/" + "/".join(str(part) for part in error.absolute_path)
    path = path if path != "/" else "$"
    if error.validator == "required":
        match = re.match(r"^'([^']+)'", error.message)
        missing = match.group(1) if match else None
        return (
            f"{path}/{missing}: required field is missing"
            if missing
            else f"{path}: a required field is missing"
        )
    if error.validator == "additionalProperties":
        match = re.search(r"\('([^']+)' was unexpected\)", error.message)
        unknown = match.group(1) if match else None
        return (
            f"{path}/{unknown}: unknown field is present"
            if unknown
            else f"{path}: an unknown field is present"
        )
    if error.validator == "format":
        return f"{path}: expected {error.validator_value} format"
    if error.validator == "type":
        return f"{path}: expected {error.validator_value}"
    if error.validator in {"const", "enum"}:
        return f"{path}: expected an allowed value"
    return f"{path}: configuration violates {error.validator or 'schema'}"


def validate_plugin_configuration(
    registration: PluginRegistration,
    read_resource: PluginResourceReader,
    settings: object,
    credentials: Mapping[str, str],
) -> ValidatedPluginConfiguration:
    """Load one generated CUE bundle and validate the full plugin namespace."""

    contract = registration.configuration
    try:
        schema = _configuration_document(
            read_resource(contract.schema_resource), label=contract.schema_resource
        )
        if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
            raise PluginConfigurationError(
                f"{contract.schema_resource}: unsupported JSON Schema dialect"
            )
        if schema.get("$id") != contract.document_version:
            raise PluginConfigurationError(
                f"{contract.schema_resource}: configuration schema identity mismatch"
            )
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as error:
            raise PluginConfigurationError(
                f"{contract.schema_resource}: invalid JSON Schema"
            ) from error
        _reject_external_schema_references(schema)

        defaults = _configuration_document(
            read_resource(contract.defaults_resource), label=contract.defaults_resource
        )
        default_values = defaults.get("defaults")
        if (
            isinstance(default_values, Mapping)
            and default_values.get("credentials", {}) != {}
        ):
            raise PluginConfigurationError(
                f"{contract.defaults_resource}: credential references cannot have defaults"
            )
        _validate_artifact(
            defaults,
            schema_name="plugin-config-defaults.schema.json",
            label=contract.defaults_resource,
        )
        try:
            default_errors = tuple(
                Draft202012Validator(
                    _partial_configuration_schema(schema),
                    format_checker=FormatChecker(),
                ).iter_errors(defaults["defaults"])
            )
        except Unresolvable as error:
            raise PluginConfigurationError(
                f"{contract.schema_resource}: configuration schema reference is unavailable"
            ) from error
        if default_errors:
            raise PluginConfigurationError(
                f"{contract.defaults_resource}: declared defaults violate the configuration schema"
            )
        presentation = _configuration_document(
            read_resource(contract.presentation_resource),
            label=contract.presentation_resource,
        )
        _validate_artifact(
            presentation,
            schema_name="plugin-config-presentation.schema.json",
            label=contract.presentation_resource,
        )
    except (OSError, json.JSONDecodeError) as error:
        raise PluginConfigurationError(f"configuration resource unavailable: {error}") from error

    for label, artifact in (
        (contract.defaults_resource, defaults),
        (contract.presentation_resource, presentation),
    ):
        if artifact["configuration_schema"] != contract.document_version:
            raise PluginConfigurationError(f"{label}: configuration schema identity mismatch")
    for field in presentation["fields"]:
        if not _schema_has_pointer(schema, field["path"]):
            raise PluginConfigurationError(
                f"{contract.presentation_resource}: field path is absent from configuration schema"
            )
    credential_fields = tuple(
        field
        for field in presentation["fields"]
        if field.get("widget") == "credential-file"
    )
    if credential_fields and Permission.CREDENTIALS not in registration.permissions:
        raise PluginConfigurationError(
            f"{contract.presentation_resource}: credential fields require credentials permission"
        )

    raw = {
        "settings": _configuration_document(settings, label="settings"),
        "credentials": {
            name: {"file": path} for name, path in sorted(credentials.items())
        },
    }
    effective = _fill_absent(defaults["defaults"], raw)
    try:
        errors = sorted(
            Draft202012Validator(
                schema, format_checker=FormatChecker()
            ).iter_errors(effective),
            key=lambda error: (
                tuple(str(part) for part in error.absolute_path),
                str(error.validator),
            ),
        )
    except Unresolvable as error:
        raise PluginConfigurationError(
            f"{contract.schema_resource}: configuration schema reference is unavailable"
        ) from error
    if errors:
        messages = tuple(
            dict.fromkeys(
                _configuration_error(leaf)
                for leaf in _configuration_leaf_errors(errors[0])
            )
        )
        raise PluginConfigurationError("; ".join(messages))
    assert isinstance(effective, dict)
    effective_settings = effective["settings"]
    effective_credentials = effective["credentials"]
    assert isinstance(effective_settings, dict)
    assert isinstance(effective_credentials, dict)
    return ValidatedPluginConfiguration(
        PluginConfiguration(
            tuple(
                (key, _freeze_json(value))
                for key, value in sorted(effective_settings.items())
            )
        ),
        tuple(
            sorted(
                (name, str(reference["file"]))
                for name, reference in effective_credentials.items()
            )
        ),
    )


PLUGIN_API_VERSION = "1.0.0"
_VERSION_CLAUSE = re.compile(r"^(>=|<=|==|>|<)([0-9]+(?:\.[0-9]+){0,2})$")


def _version_tuple(value: str) -> tuple[int, int, int]:
    parts = value.split(".")
    if len(parts) > 3 or any(not part.isdigit() for part in parts):
        raise PluginCompatibilityError(f"invalid plugin API version {value!r}")
    padded = tuple(int(part) for part in parts) + (0,) * (3 - len(parts))
    return cast(tuple[int, int, int], padded)


def ensure_plugin_api_compatible(
    registration: PluginRegistration, *, host_version: str = PLUGIN_API_VERSION
) -> None:
    """Reject an incompatible implementation before any plugin code is imported."""

    host = _version_tuple(host_version)
    clauses = registration.plugin_api.split()
    if not clauses:
        raise PluginCompatibilityError("plugin_api compatibility range is empty")
    comparisons = {
        ">=": lambda left, right: left >= right,
        "<=": lambda left, right: left <= right,
        ">": lambda left, right: left > right,
        "<": lambda left, right: left < right,
        "==": lambda left, right: left == right,
    }
    for clause in clauses:
        match = _VERSION_CLAUSE.fullmatch(clause)
        if match is None:
            raise PluginCompatibilityError(
                f"invalid plugin_api compatibility clause {clause!r}"
            )
        operator, version = match.groups()
        if not comparisons[operator](host, _version_tuple(version)):
            raise PluginCompatibilityError(
                f"plugin requires API {registration.plugin_api!r}; host provides {host_version}"
            )


def _parse_entity_capabilities(
    values: list[str],
    *,
    plugin_id: PluginId,
    entity_type: str,
) -> tuple[EntityCapability, ...]:
    capabilities: list[EntityCapability] = []
    seen: set[str] = set()
    standard = {item.value for item in StandardEntityCapability}
    for index, value in enumerate(values):
        path = f"entity_types.{entity_type}.capabilities.{index}"
        if value in seen:
            raise PluginRegistrationError(f"{path}: duplicate entity capability {value!r}")
        if value not in standard and value.split(".", 1)[0] != plugin_id.value:
            raise PluginRegistrationError(
                f"{path}: plugin-specific capability must use namespace "
                f"{plugin_id.value!r}"
            )
        seen.add(value)
        capabilities.append(EntityCapability(value))
    return tuple(capabilities)


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


def registration_to_dict(registration: PluginRegistration) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema_version": registration.schema_version.value,
        "id": registration.plugin_id.value,
        "name": registration.name,
        "version": registration.version,
        "plugin_api": registration.plugin_api,
        "capabilities": [value.value for value in registration.capabilities],
        "configuration": {
            "document_version": registration.configuration.document_version,
            "schema_resource": registration.configuration.schema_resource,
            "defaults_resource": registration.configuration.defaults_resource,
            "presentation_resource": registration.configuration.presentation_resource,
        },
    }
    if registration.runtime is not None:
        result["runtime"] = {"entrypoint": registration.runtime.entrypoint}
        if registration.runtime.migration_set is not None:
            result["runtime"]["migration_set"] = registration.runtime.migration_set
        if registration.runtime.agenda_seed is not None:
            result["runtime"]["agenda_seed"] = registration.runtime.agenda_seed
    if registration.permissions:
        result["permissions"] = [item.value for item in registration.permissions]
    if registration.entity_types:
        result["entity_types"] = {
            entity.entity_type: {
                "capabilities": [
                    capability.value for capability in entity.capabilities
                ]
            }
            for entity in registration.entity_types
        }
    return result


def entity_type_registration(
    registration: PluginRegistration, entity_type: str
) -> EntityTypeRegistration | None:
    """Return one declared entity envelope without exposing mutable maps."""

    return next(
        (
            item
            for item in registration.entity_types
            if item.entity_type == entity_type
        ),
        None,
    )


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
