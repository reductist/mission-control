"""Google-owned cache, migrations, sync orchestration, and projections."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from importlib.resources import files

from mission_control.agenda import (
    AgendaContribution,
    AgendaSchemaVersion,
    ProviderRef,
    SourceRef,
)
from mission_control.builtin_plugins.google.client import GoogleApiError, GoogleClient
from mission_control.builtin_plugins.google.config import GoogleConfig
from mission_control.builtin_plugins.google.domain import (
    GoogleCollection,
    GoogleEntry,
    GoogleResourceError,
    calendar_event,
    google_task,
)
from mission_control.builtin_plugins.google.mapping import agenda_entry
from mission_control.database import Database
from mission_control.entity_details import (
    DetailAttribute,
    EntityDetail,
    EntityDetailSchemaVersion,
)
from mission_control.plugin_runtime import PluginHealth, PluginHealthState
from mission_control.plugins import (
    EntityAffordance,
    EntityCapability,
    PluginId,
    StandardEntityCapability,
)

PLUGIN_ID = PluginId("google-calendar")
ANNOTATE = EntityAffordance(
    EntityCapability(StandardEntityCapability.ENTITY_ANNOTATE.value), "add-note"
)


class GoogleMigrationRunner:
    def __init__(self, database: Database) -> None:
        self.database = database

    def apply(self) -> list[int]:
        applied: list[int] = []
        root = files(__package__).joinpath("migrations")
        with self.database.connect() as connection:
            existing = (
                {
                    row[0]
                    for row in connection.execute(
                        "SELECT version FROM plugin__15__google_calendar__schema_migrations"
                    ).fetchall()
                }
                if self._has_migration_table(connection)
                else set()
            )
            for migration in sorted(root.iterdir(), key=lambda path: path.name):
                if migration.suffix != ".sql":
                    continue
                version = int(migration.name.split("_", 1)[0])
                if version in existing:
                    continue
                connection.executescript(
                    f"BEGIN IMMEDIATE;\n{migration.read_text(encoding='utf-8')}\nCOMMIT;"
                )
                applied.append(version)
        return applied

    @staticmethod
    def _has_migration_table(connection: sqlite3.Connection) -> bool:
        return (
            connection.execute(
                "SELECT 1 FROM sqlite_master "
                "WHERE type = 'table' AND name = 'plugin__15__google_calendar__schema_migrations'"
            ).fetchone()
            is not None
        )


@dataclass(frozen=True, slots=True)
class GoogleSyncStatus:
    last_attempt_at: datetime | None
    last_success_at: datetime | None
    error_code: str | None
    error_detail: str | None
    source_mode: str | None
    source_fingerprint: str | None


class SQLiteGoogleRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def reconcile_collections(
        self, kind: str, collections: Iterable[GoogleCollection]
    ) -> None:
        snapshot = tuple(collections)
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for item in snapshot:
                connection.execute(
                    "INSERT INTO plugin__15__google_calendar__collections("
                    "collection_key, kind, external_id, label, access_role"
                    ") VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(collection_key) DO UPDATE SET "
                    "label = excluded.label, access_role = excluded.access_role",
                    (
                        item.collection_key,
                        item.kind,
                        item.external_id,
                        item.label,
                        item.access_role,
                    ),
                )
            keys = tuple(item.collection_key for item in snapshot)
            if keys:
                placeholders = ",".join("?" for _ in keys)
                connection.execute(
                    f"DELETE FROM plugin__15__google_calendar__collections WHERE kind = ? "
                    f"AND collection_key NOT IN ({placeholders})",
                    (kind, *keys),
                )
            else:
                connection.execute(
                    "DELETE FROM plugin__15__google_calendar__collections WHERE kind = ?", (kind,)
                )

    def prepare_source(self, mode: str, fingerprint: str) -> bool:
        """Quarantine cache rows when fixture mode or OAuth identity changes."""

        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT source_mode, source_fingerprint FROM plugin__15__google_calendar__sync_status "
                "WHERE singleton = 1"
            ).fetchone()
            assert row is not None
            if row["source_mode"] == mode and row["source_fingerprint"] == fingerprint:
                return False
            connection.execute("DELETE FROM plugin__15__google_calendar__collections")
            connection.execute(
                "UPDATE plugin__15__google_calendar__sync_status SET last_attempt_at = NULL, "
                "last_success_at = NULL, error_code = NULL, error_detail = NULL, "
                "source_mode = ?, source_fingerprint = ? WHERE singleton = 1",
                (mode, fingerprint),
            )
        return True

    def replace_collection(
        self,
        collection: GoogleCollection,
        entries: Iterable[GoogleEntry],
        *,
        synced_at: datetime,
    ) -> None:
        snapshot = tuple(entries)
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "DELETE FROM plugin__15__google_calendar__entries WHERE collection_key = ?",
                (collection.collection_key,),
            )
            for item in snapshot:
                connection.execute(
                    "INSERT INTO plugin__15__google_calendar__entries("
                    "entity_id, collection_key, remote_id, entity_type, title, context, "
                    "detail, timing_kind, occurs_on, ends_before, starts_at, ends_at, "
                    "due_on, status, location, source_url, revision, updated_at"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        item.entity_id,
                        item.collection_key,
                        item.remote_id,
                        item.entity_type,
                        item.title,
                        item.context,
                        item.detail,
                        item.timing_kind,
                        _date_text(item.occurs_on),
                        _date_text(item.ends_before),
                        _datetime_text(item.starts_at),
                        _datetime_text(item.ends_at),
                        _date_text(item.due_on),
                        item.status,
                        item.location,
                        item.source_url,
                        item.revision,
                        item.updated_at.isoformat(),
                    ),
                )
            connection.execute(
                "UPDATE plugin__15__google_calendar__collections SET last_attempt_at = ?, last_success_at = ?, "
                "error_code = NULL, error_detail = NULL WHERE collection_key = ?",
                (
                    synced_at.isoformat(),
                    synced_at.isoformat(),
                    collection.collection_key,
                ),
            )

    def mark_collection_failure(
        self,
        collection: GoogleCollection,
        *,
        attempted_at: datetime,
        code: str,
        detail: str,
    ) -> None:
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE plugin__15__google_calendar__collections SET last_attempt_at = ?, error_code = ?, "
                "error_detail = ? WHERE collection_key = ?",
                (attempted_at.isoformat(), code, detail, collection.collection_key),
            )

    def record_attempt(self, attempted_at: datetime) -> None:
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE plugin__15__google_calendar__sync_status SET last_attempt_at = ? WHERE singleton = 1",
                (attempted_at.isoformat(),),
            )

    def record_success(self, synced_at: datetime) -> None:
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE plugin__15__google_calendar__sync_status SET last_attempt_at = ?, last_success_at = ?, "
                "error_code = NULL, error_detail = NULL WHERE singleton = 1",
                (synced_at.isoformat(), synced_at.isoformat()),
            )

    def record_failure(
        self, attempted_at: datetime, *, code: str, detail: str
    ) -> None:
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE plugin__15__google_calendar__sync_status SET last_attempt_at = ?, error_code = ?, "
                "error_detail = ? WHERE singleton = 1",
                (attempted_at.isoformat(), code, detail),
            )

    def clear_cache(self) -> None:
        """Erase imported private data after terminal authorization failure."""

        with self.database.connect() as connection:
            connection.execute("DELETE FROM plugin__15__google_calendar__collections")

    def status(self) -> GoogleSyncStatus:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT last_attempt_at, last_success_at, error_code, error_detail, "
                "source_mode, source_fingerprint "
                "FROM plugin__15__google_calendar__sync_status WHERE singleton = 1"
            ).fetchone()
        assert row is not None
        return GoogleSyncStatus(
            _optional_datetime(row["last_attempt_at"]),
            _optional_datetime(row["last_success_at"]),
            row["error_code"],
            row["error_detail"],
            row["source_mode"],
            row["source_fingerprint"],
        )

    def list_entries(self) -> tuple[GoogleEntry, ...]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM plugin__15__google_calendar__entries ORDER BY entity_type, entity_id"
            ).fetchall()
        return tuple(self._entry(row) for row in rows)

    def get_entry(self, entity_id: str) -> GoogleEntry:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM plugin__15__google_calendar__entries WHERE entity_id = ?", (entity_id,)
            ).fetchone()
        if row is None:
            raise KeyError(entity_id)
        return self._entry(row)

    @staticmethod
    def _entry(row: sqlite3.Row) -> GoogleEntry:
        return GoogleEntry(
            entity_id=row["entity_id"],
            collection_key=row["collection_key"],
            remote_id=row["remote_id"],
            entity_type=row["entity_type"],
            title=row["title"],
            context=row["context"],
            detail=row["detail"],
            timing_kind=row["timing_kind"],
            occurs_on=_optional_date(row["occurs_on"]),
            ends_before=_optional_date(row["ends_before"]),
            starts_at=_optional_datetime(row["starts_at"]),
            ends_at=_optional_datetime(row["ends_at"]),
            due_on=_optional_date(row["due_on"]),
            status=row["status"],
            location=row["location"],
            source_url=row["source_url"],
            revision=row["revision"],
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def contribution(self, *, generated_at: datetime) -> AgendaContribution:
        cached = self.list_entries()
        entries = tuple(agenda_entry(item) for item in cached)
        revision = hashlib.sha256(
            json.dumps(
                [(item.entity_id, item.revision) for item in cached],
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return AgendaContribution(
            schema_version=AgendaSchemaVersion.V2,
            provider=ProviderRef(PLUGIN_ID),
            revision=revision,
            generated_at=generated_at,
            entries=entries,
        )

    def entity_detail(self, target: SourceRef) -> EntityDetail | None:
        if target.plugin_id != PLUGIN_ID or target.entity_type not in {
            "calendar-event",
            "task",
        }:
            return None
        try:
            item = self.get_entry(target.entity_id)
        except KeyError:
            return None
        if item.entity_type != target.entity_type:
            return None
        attributes = [
            DetailAttribute("source", "Source", item.context),
            DetailAttribute("when", "When", _timing_label(item)),
        ]
        if item.location:
            attributes.append(DetailAttribute("location", "Location", item.location))
        if item.source_url:
            attributes.append(DetailAttribute("google-link", "Google link", item.source_url))
        return EntityDetail(
            schema_version=EntityDetailSchemaVersion.V1,
            source=target,
            title=item.title,
            description=item.detail,
            state=item.status,
            revision=item.revision,
            attributes=tuple(attributes),
            affordances=(ANNOTATE,),
            activity=(),
        )


class GoogleSynchronizer:
    def __init__(
        self,
        repository: SQLiteGoogleRepository,
        client: GoogleClient,
        config: GoogleConfig,
    ) -> None:
        self.repository = repository
        self.client = client
        self.config = config
        self._runtime_failure_at: datetime | None = None

    @property
    def runtime_failure_at(self) -> datetime | None:
        return self._runtime_failure_at

    def record_unexpected_failure(self) -> None:
        failed_at = datetime.now(UTC)
        self._runtime_failure_at = failed_at
        try:
            self.repository.record_failure(
                failed_at,
                code="job-failed",
                detail="Google refresh failed unexpectedly; cached data was retained.",
            )
        except sqlite3.Error:
            pass

    def sync_once(self) -> None:
        attempted_at = datetime.now(UTC)
        self.repository.record_attempt(attempted_at)
        calendar_failures, calendar_discovery_error = self._sync_calendars(attempted_at)
        if (
            calendar_discovery_error is not None
            and calendar_discovery_error[0] == "reconnect-required"
        ):
            task_failures, task_discovery_error = 0, None
        else:
            task_failures, task_discovery_error = self._sync_tasks(attempted_at)
        failures = calendar_failures + task_failures
        discovery_errors = tuple(
            error
            for error in (calendar_discovery_error, task_discovery_error)
            if error is not None
        )
        reconnect = next(
            (error for error in discovery_errors if error[0] == "reconnect-required"),
            None,
        )
        if reconnect is not None:
            self.repository.clear_cache()
            self.repository.record_failure(
                attempted_at,
                code=reconnect[0],
                detail=reconnect[1],
            )
        if failures:
            if reconnect is None:
                self.repository.record_failure(
                    attempted_at,
                    code="partial-sync",
                    detail=f"{failures} Google source{'s' if failures != 1 else ''} could not refresh; healthy sources remain available.",
                )
        else:
            self.repository.record_success(attempted_at)
        self._runtime_failure_at = None

    def _sync_calendars(
        self, attempted_at: datetime
    ) -> tuple[int, tuple[str, str] | None]:
        try:
            discovered = self.client.calendars()
        except (GoogleApiError, GoogleResourceError, ValueError) as error:
            return 1, _safe_error(error)
        selected = []
        configured = set(self.config.calendar_ids)
        for collection, document in discovered:
            if configured:
                include = collection.external_id in configured
            else:
                include = document.get("primary") is True or document.get("selected") is True
            if include:
                selected.append(collection)
        missing = configured - {item.external_id for item in selected}
        self.repository.reconcile_collections("calendar", selected)
        failures = len(missing)
        starts_at = attempted_at - timedelta(days=self.config.lookback_days)
        ends_at = attempted_at + timedelta(days=self.config.lookahead_days)
        for collection in selected:
            try:
                resources = self.client.events(
                    collection.external_id, starts_at=starts_at, ends_at=ends_at
                )
                entries = tuple(
                    entry
                    for entry in (
                        calendar_event(collection, resource) for resource in resources
                    )
                    if entry is not None
                )
                self.repository.replace_collection(
                    collection, entries, synced_at=attempted_at
                )
            except (GoogleApiError, GoogleResourceError, ValueError) as error:
                failures += 1
                code, detail = _safe_error(error)
                self.repository.mark_collection_failure(
                    collection,
                    attempted_at=attempted_at,
                    code=code,
                    detail=detail,
                )
        return failures, None

    def _sync_tasks(
        self, attempted_at: datetime
    ) -> tuple[int, tuple[str, str] | None]:
        try:
            discovered = self.client.task_lists()
        except (GoogleApiError, GoogleResourceError, ValueError) as error:
            return 1, _safe_error(error)
        configured = set(self.config.task_list_ids)
        selected = [
            item
            for item in discovered
            if not configured or item.external_id in configured
        ]
        missing = configured - {item.external_id for item in selected}
        self.repository.reconcile_collections("task-list", selected)
        failures = len(missing)
        for collection in selected:
            try:
                entries = tuple(
                    entry
                    for entry in (
                        google_task(collection, resource)
                        for resource in self.client.tasks(collection.external_id)
                    )
                    if entry is not None
                )
                self.repository.replace_collection(
                    collection, entries, synced_at=attempted_at
                )
            except (GoogleApiError, GoogleResourceError, ValueError) as error:
                failures += 1
                code, detail = _safe_error(error)
                self.repository.mark_collection_failure(
                    collection,
                    attempted_at=attempted_at,
                    code=code,
                    detail=detail,
                )
        return failures, None


def plugin_health(
    repository: SQLiteGoogleRepository,
    *,
    source_mode: str = "live",
    runtime_failure_at: datetime | None = None,
) -> PluginHealth:
    now = datetime.now(UTC)
    status = repository.status()
    if runtime_failure_at is not None:
        state = PluginHealthState.FAILED
        code = "job-failed"
        detail = "Google refresh failed unexpectedly; cached data was retained."
    elif status.error_code is not None:
        state = PluginHealthState.DEGRADED
        code = status.error_code
        detail = status.error_detail or "Google refresh is degraded."
    elif status.last_success_at is None:
        state = PluginHealthState.STARTING
        code = "awaiting-first-sync"
        detail = "Waiting for the first Google refresh."
    else:
        state = PluginHealthState.READY
        code = "synchronized"
        detail = (
            "Synthetic Calendar and Tasks fixture is ready."
            if source_mode == "demo"
            else "Calendar and task cache is current."
        )
    return PluginHealth(PLUGIN_ID, state, code, detail, now, status.last_success_at)


def _timing_label(item: GoogleEntry) -> str:
    if item.timing_kind == "all-day":
        assert item.occurs_on is not None
        if item.ends_before is not None and item.ends_before > item.occurs_on + timedelta(days=1):
            last_day = item.ends_before - timedelta(days=1)
            return f"{item.occurs_on.isoformat()} through {last_day.isoformat()}"
        return item.occurs_on.isoformat()
    if item.timing_kind == "timed":
        return f"{_required(item.starts_at).isoformat()} to {_required(item.ends_at).isoformat()}"
    if item.due_on is not None:
        return f"Due {item.due_on.isoformat()}"
    return "Anytime"


def _safe_error(error: Exception) -> tuple[str, str]:
    if isinstance(error, GoogleApiError):
        return error.code, error.detail
    return "invalid-upstream-resource", "Google returned data that could not be imported."


def _date_text(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _datetime_text(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _optional_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value is not None else None


def _optional_datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value is not None else None


def _required(value: datetime | None) -> datetime:
    assert value is not None
    return value
