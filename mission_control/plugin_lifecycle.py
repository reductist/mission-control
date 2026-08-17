"""Neutral manifest-to-runtime lifecycle for selected plugins."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
from collections.abc import Callable, Iterable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from importlib import util as importlib_util
from importlib import import_module
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Iterator, Protocol

from mission_control.agenda import (
    AgendaContribution,
    AgendaContributionError,
    contribution_to_dict,
    parse_agenda_contribution,
    validate_agenda_capabilities,
)
from mission_control.commands import CommandOwner
from mission_control.database import Database
from mission_control.migrations import MigrationRunner
from mission_control.plugin_adapter import (
    DocumentPluginProvider,
    validate_runtime_capability_adapters,
)
from mission_control.plugin_api import (
    PluginCallContractError,
    PluginCallRejected,
    PluginContext,
    PluginSetupContext,
)
from mission_control.plugins import (
    Capability,
    PluginCompatibilityError,
    PluginConfiguration,
    PluginConfigurationError,
    PluginId,
    PluginRegistration,
    PluginRegistrationError,
    Permission,
    ensure_plugin_api_compatible,
    load_plugin_configuration_bundle,
    parse_plugin_registration,
    validate_plugin_configuration,
)
from mission_control.setup import DocumentPluginSetup, SetupSession


class PluginLifecycleError(ValueError):
    """A selected plugin cannot safely complete its declared lifecycle."""


class PluginProvider(Protocol):
    plugin_id: PluginId
    command_owner: CommandOwner | None

    def contribution(self, *, generated_at: datetime) -> AgendaContribution: ...


@dataclass(frozen=True, slots=True)
class PluginResourceSource:
    root: Traversable
    label: str

    def document(self, name: str) -> object:
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name) is None:
            raise PluginLifecycleError(f"unsafe plugin resource name: {name!r}")
        resource = self.root.joinpath(name)
        if isinstance(self.root, Path):
            root = self.root.resolve()
            path = Path(resource)
            if path.is_symlink() or path.resolve().parent != root:
                raise PluginLifecycleError(f"unsafe plugin resource: {name}")
        return json.loads(resource.read_text(encoding="utf-8"))


@dataclass(frozen=True, slots=True)
class PreparedPlugin:
    registration: PluginRegistration
    source: PluginResourceSource
    seed: AgendaContribution | None
    configuration: PluginConfiguration
    credentials: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class PreparedPluginSetup:
    """One setup entrypoint whose manifest and config bundle passed preflight."""

    registration: PluginRegistration
    source: PluginResourceSource


@dataclass(frozen=True, slots=True)
class PluginActivationFailure:
    plugin_id: PluginId
    code: str = "activation-failed"
    detail: str = "Plugin activation failed; its contributions are unavailable."


@dataclass(frozen=True, slots=True)
class PluginActivation:
    plugin: PreparedPlugin
    provider: PluginProvider | None
    failure: PluginActivationFailure | None


LOGGER = logging.getLogger(__name__)


_TABLE_ACTIONS = {
    sqlite3.SQLITE_CREATE_INDEX,
    sqlite3.SQLITE_CREATE_TABLE,
    sqlite3.SQLITE_CREATE_TEMP_INDEX,
    sqlite3.SQLITE_CREATE_TEMP_TABLE,
    sqlite3.SQLITE_CREATE_TEMP_TRIGGER,
    sqlite3.SQLITE_CREATE_TRIGGER,
    sqlite3.SQLITE_CREATE_VIEW,
    sqlite3.SQLITE_CREATE_VTABLE,
    sqlite3.SQLITE_DELETE,
    sqlite3.SQLITE_DROP_INDEX,
    sqlite3.SQLITE_DROP_TABLE,
    sqlite3.SQLITE_DROP_TEMP_INDEX,
    sqlite3.SQLITE_DROP_TEMP_TABLE,
    sqlite3.SQLITE_DROP_TEMP_TRIGGER,
    sqlite3.SQLITE_DROP_TRIGGER,
    sqlite3.SQLITE_DROP_VIEW,
    sqlite3.SQLITE_DROP_VTABLE,
    sqlite3.SQLITE_INSERT,
    sqlite3.SQLITE_READ,
    sqlite3.SQLITE_REINDEX,
    sqlite3.SQLITE_ANALYZE,
    sqlite3.SQLITE_ALTER_TABLE,
    sqlite3.SQLITE_UPDATE,
}


class PluginDatabase:
    """SQLite access restricted to one plugin's declared table namespace."""

    def __init__(
        self, database: Database, plugin_id: PluginId, *, enabled: bool
    ) -> None:
        self._database = database
        self._prefix = plugin_sql_prefix(plugin_id)
        self._enabled = enabled

    @property
    def namespace(self) -> str:
        return self._prefix

    def table_name(self, local_name: str) -> str:
        if re.fullmatch(r"[a-z][a-z0-9_]*", local_name) is None:
            raise ValueError("plugin-local table name is not a safe SQL identifier")
        return f"{self._prefix}{local_name}"

    def _authorize(
        self,
        action: int,
        argument1: str | None,
        argument2: str | None,
        _database_name: str | None,
        _trigger_name: str | None,
    ) -> int:
        if action in {sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH}:
            return sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_PRAGMA:
            allowed_pragma = argument1 == "foreign_keys" or (
                argument1 == "quick_check"
                and argument2 is not None
                and argument2.startswith(self._prefix)
            )
            return sqlite3.SQLITE_OK if allowed_pragma else sqlite3.SQLITE_DENY
        if action not in _TABLE_ACTIONS:
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_ALTER_TABLE:
            names = tuple(name for name in (argument2,) if name)
        else:
            names = (
                tuple(name for name in (argument1,) if name)
                if action
                in {
                    sqlite3.SQLITE_DELETE,
                    sqlite3.SQLITE_INSERT,
                    sqlite3.SQLITE_READ,
                    sqlite3.SQLITE_REINDEX,
                    sqlite3.SQLITE_ANALYZE,
                    sqlite3.SQLITE_UPDATE,
                    sqlite3.SQLITE_CREATE_TABLE,
                    sqlite3.SQLITE_CREATE_TEMP_TABLE,
                    sqlite3.SQLITE_CREATE_VIEW,
                    sqlite3.SQLITE_CREATE_VTABLE,
                    sqlite3.SQLITE_DROP_TABLE,
                    sqlite3.SQLITE_DROP_TEMP_TABLE,
                    sqlite3.SQLITE_DROP_VIEW,
                    sqlite3.SQLITE_DROP_VTABLE,
                }
                else tuple(name for name in (argument1, argument2) if name)
            )
        if (
            action == sqlite3.SQLITE_CREATE_INDEX
            and argument1 is not None
            and argument1.startswith("sqlite_autoindex_")
            and argument2 is not None
        ):
            names = (argument2,)
        allowed = self._enabled and bool(names) and all(
            name.startswith(self._prefix)
            or name == "sqlite_master"
            or (
                action == sqlite3.SQLITE_READ
                and name in {"sqlite_sequence", "pragma_quick_check"}
            )
            for name in names
        )
        return sqlite3.SQLITE_OK if allowed else sqlite3.SQLITE_DENY

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        with self._database.connect() as connection:
            connection.set_authorizer(self._authorize)
            yield connection


def _validate_permissions(registration: PluginRegistration) -> None:
    runtime = registration.runtime
    if runtime is not None and runtime.migration_set is not None:
        if Permission.DATABASE not in registration.permissions:
            raise ValueError("a declared migration set requires database permission")


def _document(source: PluginResourceSource | str, name: str) -> object:
    """Read one resource; the string form is retained for focused contract tests."""

    if isinstance(source, str):
        source = next(
            item for item in bundled_plugin_sources() if item.root.name == source
        )
    return source.document(name)


def bundled_plugin_sources() -> tuple[PluginResourceSource, ...]:
    """Discover packaged manifests without maintaining a second ID registry."""

    root = files("mission_control.builtin_plugins")
    return tuple(
        PluginResourceSource(child, f"bundled:{child.name}")
        for child in sorted(root.iterdir(), key=lambda item: item.name)
        if child.is_dir() and child.joinpath("registration.json").is_file()
    )


def filesystem_plugin_sources(
    roots: Iterable[str | Path],
) -> tuple[PluginResourceSource, ...]:
    """Discover manifests and resources below explicit operator roots."""

    discovered: dict[str, Path] = {}
    for configured in roots:
        root = Path(configured).expanduser().resolve()
        if not root.exists():
            raise PluginLifecycleError(f"plugin root does not exist: {root}")
        candidates = (root,) if (root / "registration.json").is_file() else ()
        if root.is_dir() and not candidates:
            candidates = tuple(
                child
                for child in sorted(root.iterdir(), key=lambda item: item.name)
                if child.is_dir()
                and not child.is_symlink()
                and child.resolve().parent == root
                and (child / "registration.json").is_file()
            )
        for candidate in candidates:
            discovered[str(candidate)] = candidate
    return tuple(
        PluginResourceSource(path, str(path))
        for path in (discovered[key] for key in sorted(discovered))
    )


def bundled_plugin_ids() -> tuple[str, ...]:
    return tuple(
        sorted(
            parse_plugin_registration(
                source.document("registration.json")
            ).plugin_id.value
            for source in bundled_plugin_sources()
        )
    )


def _selected_sources(
    plugin_ids: Iterable[str], roots: Iterable[str | Path]
) -> tuple[tuple[str, PluginResourceSource], ...]:
    selected = tuple(plugin_ids)
    duplicate = next((item for item in selected if selected.count(item) > 1), None)
    if duplicate is not None:
        raise PluginLifecycleError(f"plugin selected more than once: {duplicate}")

    indexed: dict[str, list[PluginResourceSource]] = {}
    for source in bundled_plugin_sources():
        try:
            registration = parse_plugin_registration(
                source.document("registration.json")
            )
        except (OSError, json.JSONDecodeError, PluginRegistrationError) as error:
            raise PluginLifecycleError(f"{source.label}: {error}") from error
        existing = indexed.setdefault(registration.plugin_id.value, [])
        duplicate_path = any(
            isinstance(item.root, Path)
            and isinstance(source.root, Path)
            and item.root.resolve() == source.root.resolve()
            for item in existing
        )
        if not duplicate_path:
            existing.append(source)
    selected_ids = set(selected)
    for source in filesystem_plugin_sources(roots):
        document: object | None = None
        try:
            document = _document(source, "registration.json")
            registration = parse_plugin_registration(document)
        except (OSError, json.JSONDecodeError, PluginRegistrationError) as error:
            candidate_id = (
                document.get("id")
                if isinstance(document, Mapping)
                else source.root.name
            )
            if candidate_id in selected_ids:
                raise PluginLifecycleError(f"{source.label}: {error}") from error
            continue
        existing = indexed.setdefault(registration.plugin_id.value, [])
        duplicate_path = any(
            isinstance(item.root, Path)
            and isinstance(source.root, Path)
            and item.root.resolve() == source.root.resolve()
            for item in existing
        )
        if not duplicate_path:
            existing.append(source)

    result: list[tuple[str, PluginResourceSource]] = []
    for plugin_id in selected:
        matches = indexed.get(plugin_id, [])
        if not matches:
            available = ", ".join(sorted(indexed))
            raise PluginLifecycleError(
                f"unknown agenda plugin {plugin_id!r}; available: {available}"
            )
        if len(matches) != 1:
            locations = ", ".join(source.label for source in matches)
            raise PluginLifecycleError(
                f"conflicting manifests for plugin {plugin_id!r}: {locations}"
            )
        result.append((plugin_id, matches[0]))
    return tuple(result)


def prepare_plugins(
    plugin_ids: Iterable[str],
    *,
    roots: Iterable[str | Path] = (),
    configurations: Mapping[str, object] | None = None,
    credentials: Mapping[str, Mapping[str, str]] | None = None,
    reference_catalogs: Mapping[str, frozenset[str]] | None = None,
) -> tuple[PreparedPlugin, ...]:
    """Validate selected plugin bundles without importing implementation code."""

    prepared: list[PreparedPlugin] = []
    for plugin_id, source in _selected_sources(plugin_ids, roots):
        try:
            registration = parse_plugin_registration(
                _document(source, "registration.json")
            )
            if registration.plugin_id.value != plugin_id:
                raise ValueError("selected and registration ids must match")
            ensure_plugin_api_compatible(registration)
            _validate_permissions(registration)
            validate_runtime_capability_adapters(registration)

            seed = None
            runtime = registration.runtime
            if runtime is not None and runtime.agenda_seed is not None:
                seed = parse_agenda_contribution(
                    _document(source, runtime.agenda_seed)
                )
                if registration.plugin_id != seed.provider.plugin_id:
                    raise ValueError("registration and agenda provider ids must match")
                validate_agenda_capabilities(registration, seed)
            validated_configuration = validate_plugin_configuration(
                registration,
                source.document,
                (configurations or {}).get(plugin_id, {}),
                (credentials or {}).get(plugin_id, {}),
                reference_catalogs=reference_catalogs,
            )
            if (
                validated_configuration.credentials
                and Permission.CREDENTIALS not in registration.permissions
            ):
                raise ValueError("configured credentials require credentials permission")
            prepared.append(
                PreparedPlugin(
                    registration,
                    source,
                    seed,
                    validated_configuration.settings,
                    validated_configuration.credentials,
                )
            )
        except (
            OSError,
            json.JSONDecodeError,
            PluginConfigurationError,
            PluginCallContractError,
            PluginCompatibilityError,
            PluginRegistrationError,
            AgendaContributionError,
            ValueError,
        ) as error:
            raise PluginLifecycleError(f"{plugin_id}: {error}") from error
    return tuple(prepared)


def prepare_plugin_setup(
    plugin_id: str, *, roots: Iterable[str | Path] = ()
) -> PreparedPluginSetup:
    """Preflight a setup provider without requiring final settings or opening a DB."""

    selected = _selected_sources((plugin_id,), roots)
    _, source = selected[0]
    try:
        registration = parse_plugin_registration(
            _document(source, "registration.json")
        )
        if registration.plugin_id.value != plugin_id:
            raise ValueError("selected and registration ids must match")
        ensure_plugin_api_compatible(registration)
        _validate_permissions(registration)
        validate_runtime_capability_adapters(registration)
        if registration.setup is None:
            raise ValueError("plugin does not declare a setup entrypoint")
        load_plugin_configuration_bundle(registration, source.document)
    except (
        OSError,
        json.JSONDecodeError,
        PluginConfigurationError,
        PluginCallContractError,
        PluginCompatibilityError,
        PluginRegistrationError,
        ValueError,
    ) as error:
        raise PluginLifecycleError(f"{plugin_id}: {error}") from error
    return PreparedPluginSetup(registration, source)


def prepare_agenda_plugins(
    plugin_ids: Iterable[str],
    *,
    roots: Iterable[str | Path] = (),
    configurations: Mapping[str, object] | None = None,
    credentials: Mapping[str, Mapping[str, str]] | None = None,
    reference_catalogs: Mapping[str, frozenset[str]] | None = None,
) -> tuple[PreparedPlugin, ...]:
    """Prepare plugins for the current in-process Agenda runtime."""

    prepared = prepare_plugins(
        plugin_ids,
        roots=roots,
        configurations=configurations,
        credentials=credentials,
        reference_catalogs=reference_catalogs,
    )
    return require_agenda_plugins(prepared)


def require_agenda_plugins(
    plugins: Iterable[PreparedPlugin],
) -> tuple[PreparedPlugin, ...]:
    """Require already-prepared plugins to fit the current Agenda adapter."""

    prepared = tuple(plugins)
    for plugin in prepared:
        plugin_id = plugin.registration.plugin_id.value
        if Capability.AGENDA not in plugin.registration.capabilities:
            raise PluginLifecycleError(
                f"{plugin_id}: registration must declare the agenda capability"
            )
        if plugin.registration.runtime is None:
            raise PluginLifecycleError(
                f"{plugin_id}: registration must declare a runtime entrypoint"
            )
    return prepared


def load_agenda_contributions(
    plugin_ids: Iterable[str], *, roots: Iterable[str | Path] = ()
) -> tuple[AgendaContribution, ...]:
    return tuple(
        plugin.seed
        for plugin in prepare_agenda_plugins(plugin_ids, roots=roots)
        if plugin.seed is not None
    )


def _apply_declared_migrations(
    database: Database, plugin: PreparedPlugin
) -> None:
    runtime = plugin.registration.runtime
    assert runtime is not None
    if runtime.migration_set is None:
        return
    if re.fullmatch(r"[a-z][a-z0-9_]*", runtime.migration_set) is None:
        raise PluginLifecycleError("migration set is not a safe SQL identifier")
    migration_root = plugin.source.root.joinpath("migrations")
    if isinstance(plugin.source.root, Path):
        plugin_root = plugin.source.root.resolve()
        migration_path = Path(migration_root)
        if migration_path.is_symlink() or not migration_path.resolve().is_relative_to(
            plugin_root
        ):
            raise PluginLifecycleError("unsafe plugin migration directory")
    if not migration_root.is_dir():
        raise PluginLifecycleError(
            f"declared migration set {runtime.migration_set!r} is unavailable"
        )
    plugin_id = plugin.registration.plugin_id.value
    with database.connect() as connection:
        for migration in sorted(migration_root.iterdir(), key=lambda item: item.name):
            if not migration.is_file() or not migration.name.endswith(".sql"):
                continue
            if isinstance(migration, Path) and (
                migration.is_symlink()
                or migration.resolve().parent != Path(migration_root).resolve()
            ):
                raise PluginLifecycleError(
                    f"unsafe plugin migration resource: {migration.name}"
                )
            try:
                version = int(migration.name.split("_", 1)[0])
            except ValueError as error:
                raise PluginLifecycleError(
                    f"invalid migration filename: {migration.name}"
                ) from error
            script = migration.read_text(encoding="utf-8")
            checksum = hashlib.sha256(script.encode()).hexdigest()
            existing = connection.execute(
                "SELECT checksum FROM plugin_schema_migrations "
                "WHERE plugin_id = ? AND migration_set = ? AND version = ?",
                (plugin_id, runtime.migration_set, version),
            ).fetchone()
            if existing is None:
                legacy_table = (
                    f"{plugin_sql_prefix(plugin.registration.plugin_id)}"
                    "schema_migrations"
                )
                legacy_exists = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                    (legacy_table,),
                ).fetchone()
                legacy_version = (
                    connection.execute(
                        f"SELECT 1 FROM {legacy_table} WHERE version = ?", (version,)
                    ).fetchone()
                    if legacy_exists is not None
                    else None
                )
                if legacy_version is not None:
                    connection.execute(
                        "INSERT INTO plugin_schema_migrations"
                        "(plugin_id, migration_set, version, checksum) VALUES (?, ?, ?, ?)",
                        (plugin_id, runtime.migration_set, version, checksum),
                    )
                    connection.commit()
                    continue
            if existing is not None:
                if existing["checksum"] != checksum:
                    raise PluginLifecycleError(
                        f"migration {migration.name} changed after it was applied"
                    )
                continue
            if "plugin_schema_migrations" in script.lower():
                raise PluginLifecycleError(
                    f"migration {migration.name} references the core migration ledger"
                )
            scoped = PluginDatabase(
                database,
                plugin.registration.plugin_id,
                enabled=Permission.DATABASE in plugin.registration.permissions,
            )
            connection.execute("BEGIN IMMEDIATE")
            connection.set_authorizer(scoped._authorize)
            try:
                _execute_migration_script(connection, script)
            finally:
                connection.set_authorizer(None)
            connection.execute(
                "INSERT INTO plugin_schema_migrations"
                "(plugin_id, migration_set, version, checksum) VALUES (?, ?, ?, ?)",
                (plugin_id, runtime.migration_set, version, checksum),
            )
            connection.commit()


def _execute_migration_script(connection: sqlite3.Connection, script: str) -> None:
    statement = ""
    for character in script:
        statement += character
        if character == ";" and sqlite3.complete_statement(statement):
            connection.execute(statement)
            statement = ""
    if statement.strip():
        raise PluginLifecycleError("migration contains an incomplete SQL statement")


def plugin_sql_prefix(plugin_id: PluginId) -> str:
    """Return the injective, core-reserved SQLite namespace for a plugin."""

    return (
        f"plugin__{len(plugin_id.value)}__"
        f"{plugin_id.value.replace('-', '_')}__"
    )


def _activate_one(database: Database, plugin: PreparedPlugin) -> PluginProvider:
    runtime = plugin.registration.runtime
    assert runtime is not None
    _apply_declared_migrations(database, plugin)
    module_name, callable_name = runtime.entrypoint.split(":", 1)
    try:
        implementation = _import_plugin_module(plugin, module_name)
        activate = getattr(implementation, callable_name)
        handler = activate(
            PluginContext.create(
                plugin_id=plugin.registration.plugin_id.value,
                storage=PluginDatabase(
                    database,
                    plugin.registration.plugin_id,
                    enabled=Permission.DATABASE in plugin.registration.permissions,
                ),
                configuration=plugin.configuration.to_dict(),
                credentials=dict(plugin.credentials),
                agenda_seed=(
                    contribution_to_dict(plugin.seed)
                    if plugin.seed is not None
                    else None
                ),
            )
        )
    except Exception as error:
        raise PluginLifecycleError(
            f"{plugin.registration.plugin_id.value}: plugin activation failed "
            f"({type(error).__name__})"
        ) from error
    try:
        call = getattr(handler, "call", None)
    except Exception as error:
        raise PluginLifecycleError(
            f"{plugin.registration.plugin_id.value}: plugin activation failed "
            f"({type(error).__name__})"
        ) from error
    if not callable(call):
        raise TypeError("plugin entrypoint must return a JSON capability handler")
    try:
        provider = DocumentPluginProvider(plugin.registration, handler)
    except PluginCallRejected as error:
        raise PluginLifecycleError(
            f"{plugin.registration.plugin_id.value}: runtime description was rejected"
        ) from error
    except PluginCallContractError as error:
        raise PluginLifecycleError(
            f"{plugin.registration.plugin_id.value}: {error}"
        ) from error
    if provider.plugin_id != plugin.registration.plugin_id:
        raise ValueError("registration and activated provider ids must match")
    return provider


def _import_plugin_module(plugin: PreparedPlugin, module_name: str):
    """Load a simple local development module or an installed Python package."""

    return _import_plugin_module_from_source(
        plugin.source, plugin.registration.plugin_id, module_name
    )


def _import_plugin_module_from_source(
    source: PluginResourceSource, plugin_id: PluginId, module_name: str
):
    """Load one contained development module or an installed Python package."""

    if isinstance(source.root, Path):
        root = source.root.resolve()
        candidate = root.joinpath(*module_name.split(".")).with_suffix(".py")
        resolved = candidate.resolve()
        if candidate.is_file() or candidate.is_symlink():
            if not candidate.is_file() or not resolved.is_relative_to(root):
                raise PluginLifecycleError(
                    f"unsafe plugin runtime module: {module_name!r}"
                )
            qualified = (
                f"_mission_control_plugin_{plugin_id.value.replace('-', '_')}"
            )
            spec = importlib_util.spec_from_file_location(qualified, resolved)
            if spec is None or spec.loader is None:
                raise ImportError(f"cannot load plugin runtime module {module_name!r}")
            implementation = importlib_util.module_from_spec(spec)
            spec.loader.exec_module(implementation)
            return implementation
    return import_module(module_name)


def activate_plugin_setup(
    prepared: PreparedPluginSetup,
    *,
    credential_resolver: Callable[[str], str],
) -> DocumentPluginSetup:
    """Import one setup entrypoint with no database or normal runtime context."""

    setup = prepared.registration.setup
    assert setup is not None

    def reject_credential(_handle: str) -> str:
        raise ValueError("plugin does not declare credentials permission")

    approved_resolver = (
        credential_resolver
        if Permission.CREDENTIALS in prepared.registration.permissions
        else reject_credential
    )
    module_name, callable_name = setup.entrypoint.split(":", 1)
    try:
        implementation = _import_plugin_module_from_source(
            prepared.source, prepared.registration.plugin_id, module_name
        )
        activate = getattr(implementation, callable_name)
        handler = activate(
            PluginSetupContext.create(
                plugin_id=prepared.registration.plugin_id.value,
                credential_resolver=approved_resolver,
            )
        )
        call = getattr(handler, "call", None)
    except Exception as error:
        raise PluginLifecycleError(
            f"{prepared.registration.plugin_id.value}: plugin setup activation failed "
            f"({type(error).__name__})"
        ) from error
    if not callable(call):
        raise PluginLifecycleError(
            f"{prepared.registration.plugin_id.value}: setup entrypoint must return "
            "a JSON capability handler"
        )
    return DocumentPluginSetup(prepared.registration, handler)


def create_plugin_setup_session(
    prepared: PreparedPluginSetup,
    *,
    credential_paths: Mapping[str, str],
    settings: Mapping[str, object] | None = None,
    configured_credentials: Mapping[str, str] | None = None,
    principals: tuple[Mapping[str, str], ...] = (),
) -> SetupSession:
    """Build a setup session whose completed draft uses normal config validation."""

    def resolve(handle: str) -> str:
        try:
            return credential_paths[handle]
        except KeyError as error:
            raise ValueError("unknown credential handle") from error

    provider = activate_plugin_setup(prepared, credential_resolver=resolve)

    def validate_complete(draft: Mapping[str, object]):
        raw_credentials = draft.get("credentials", {})
        if not isinstance(raw_credentials, Mapping):
            raise PluginConfigurationError("setup draft credentials are invalid")
        credentials: dict[str, str] = {}
        for name, reference in raw_credentials.items():
            if not isinstance(reference, Mapping) or not isinstance(
                reference.get("handle"), str
            ):
                raise PluginConfigurationError("setup credential handle is invalid")
            credentials[str(name)] = resolve(str(reference["handle"]))
        principal_ids = frozenset(str(item["id"]) for item in principals)
        return validate_plugin_configuration(
            prepared.registration,
            prepared.source.document,
            draft.get("settings", {}),
            credentials,
            reference_catalogs={"workspace-principal": principal_ids},
        )

    return SetupSession(
        provider,
        settings=settings,
        credential_handles=configured_credentials,
        principals=principals,
        validate_complete=validate_complete,
    )


def activate_plugins(
    database: Database, plugins: Iterable[PreparedPlugin]
) -> tuple[PluginProvider, ...]:
    """Migrate then import each previously validated runtime entrypoint."""

    MigrationRunner(database).apply()
    providers: list[PluginProvider] = []
    for plugin in plugins:
        plugin_id = plugin.registration.plugin_id.value
        try:
            providers.append(_activate_one(database, plugin))
        except PluginLifecycleError:
            raise
        except (
            AttributeError,
            ImportError,
            OSError,
            TypeError,
            ValueError,
            sqlite3.Error,
        ) as error:
            raise PluginLifecycleError(f"{plugin_id}: {error}") from error
    return tuple(providers)


def activate_agenda_plugins(
    database: Database, plugins: Iterable[PreparedPlugin]
) -> tuple[PluginProvider, ...]:
    """Activate already-prepared plugins supported by the current Agenda shell."""

    prepared = require_agenda_plugins(plugins)
    return activate_plugins(database, prepared)


def activate_agenda_plugins_isolated(
    database: Database, plugins: Iterable[PreparedPlugin]
) -> tuple[PluginActivation, ...]:
    """Activate independently so one failed plugin cannot suppress unrelated work."""

    MigrationRunner(database).apply()
    activations: list[PluginActivation] = []
    for plugin in plugins:
        plugin_id = plugin.registration.plugin_id
        try:
            provider = _activate_one(database, plugin)
        except Exception as error:
            LOGGER.error(
                "plugin %s failed during activation (%s)",
                plugin_id.value,
                type(error).__name__,
            )
            activations.append(
                PluginActivation(
                    plugin,
                    None,
                    PluginActivationFailure(plugin_id),
                )
            )
        else:
            activations.append(PluginActivation(plugin, provider, None))
    return tuple(activations)
