from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

import mission_control.plugin_lifecycle as builtin_plugins
from mission_control.builtin_plugins import (
    BuiltinPluginError,
    activate_builtin_agenda_plugins,
    prepare_builtin_agenda_plugins,
)
from mission_control.builtin_plugins.google.client import GoogleApiError
from mission_control.builtin_plugins.google.config import GoogleConfig
from mission_control.builtin_plugins.google.config import ResourceSelection
from mission_control.builtin_plugins.google.domain import (
    GoogleCollection,
    calendar_event,
    google_task,
)
from mission_control.builtin_plugins.google.fixture import FixtureGoogleClient
from mission_control.builtin_plugins.google.repository import (
    GoogleMigrationRunner,
    GoogleSynchronizer,
    SQLiteGoogleRepository,
    plugin_health,
)
from mission_control.database import Database
from mission_control.attribution import AttributionCatalog
from mission_control.migrations import MigrationRunner
from mission_control.plugins import Capability, StandardEntityCapability
from mission_control.server import MissionControlApplication


def google_plugins():
    return prepare_builtin_agenda_plugins(
        ("google-calendar",),
        configurations={"google-calendar": demo_settings()},
    )


def _two_connection_settings() -> dict[str, object]:
    settings = demo_settings("pat", label="Pat's Google")
    connections = settings["connections"]
    assert isinstance(connections, dict)
    connections["elizabeth"] = {
        "label": "Elizabeth's Google",
        "mode": "demo",
        "demo_anchor_date": "2026-08-14",
        "calendars": {"mode": "defaults"},
        "tasks": {"mode": "all"},
    }
    connections["pat"]["attribution"] = {
        "calendars": {
            "primary@example.invalid": {"principal_ids": ["pat"]},
        }
    }
    connections["elizabeth"]["attribution"] = {
        "calendars": {
            "primary@example.invalid": {"principal_ids": ["elizabeth"]},
        }
    }
    return settings


def demo_settings(
    connection_id: str = "demo", *, label: str = "Google demo"
) -> dict[str, object]:
    return {
        "connections": {
            connection_id: {
                "label": label,
                "mode": "demo",
                "demo_anchor_date": "2026-08-14",
                "calendars": {"mode": "defaults"},
                "tasks": {"mode": "all"},
            }
        }
    }


def test_google_registration_and_configuration_validate_before_import(monkeypatch):
    def unexpected_import(_name: str):
        raise AssertionError("plugin implementation imported during preparation")

    monkeypatch.setattr(builtin_plugins, "import_module", unexpected_import)
    (prepared,) = google_plugins()

    assert prepared.registration.capabilities == (
        Capability.AGENDA,
        Capability.ENTITY_DETAILS,
        Capability.JOBS,
        Capability.HEALTH,
    )
    assert {
        item.entity_type: tuple(capability.value for capability in item.capabilities)
        for item in prepared.registration.entity_types
    } == {
        "calendar-event": (
            StandardEntityCapability.ENTITY_ANNOTATE.value,
            StandardEntityCapability.ACTIVITY_READ.value,
        ),
        "task": (
            StandardEntityCapability.ENTITY_ANNOTATE.value,
            StandardEntityCapability.ACTIVITY_READ.value,
        ),
    }
    assert prepared.configuration.to_dict()["sync_interval_seconds"] == 300
    assert prepared.seed is None
    assert prepared.registration.runtime is not None
    assert (
        prepared.registration.runtime.entrypoint
        == "mission_control.builtin_plugins.google:activate"
    )


def test_demo_sync_projects_events_tasks_details_and_independent_migration(tmp_path):
    database = Database(tmp_path / "mission-control.db")
    application = MissionControlApplication(database, builtin_plugins=google_plugins())
    dashboard = application.dashboard()
    google = [
        item for item in dashboard["agenda"] if item["source"]["plugin_id"] == "google-calendar"
    ]

    assert {item["title"] for item in google} >= {
        "Switzerland trip",
        "Flight to Zürich",
        "Download offline maps",
        "Check travel documents",
        "Museum appointment",
    }
    trip = next(item for item in google if item["title"] == "Switzerland trip")
    assert trip["timing"] == {
        "kind": "all-day",
        "occurs_on": "2026-08-14",
        "ends_before": "2026-08-23",
    }
    task = next(item for item in google if item["title"] == "Download offline maps")
    assert task["timing"] == {"kind": "due-on", "due_on": "2026-08-15"}
    detail = application.entity_detail(
        "google-calendar", task["source"]["entity_type"], task["source"]["entity_id"]
    )
    assert detail["title"] == "Download offline maps"
    assert detail["affordances"] == [
        {"capability": "entity.annotate", "command": "add-note"}
    ]
    assert application.health()["plugins"][0]["state"] == "ready"

    with database.connect() as connection:
        assert [
            row[0]
            for row in connection.execute(
                "SELECT version FROM plugin__15__google_calendar__schema_migrations"
            ).fetchall()
        ] == [1, 2, 3]
        assert (
            connection.execute(
                "SELECT count(*) FROM plugin__15__google_calendar__entries"
            ).fetchone()[0]
            == 8
        )

    restarted = MissionControlApplication(database, builtin_plugins=google_plugins())
    assert len(
        [
            item
            for item in restarted.dashboard()["agenda"]
            if item["source"]["plugin_id"] == "google-calendar"
        ]
    ) == 8


def test_two_connections_with_overlapping_remote_ids_remain_distinct(tmp_path) -> None:
    catalog = AttributionCatalog.from_workspace(
        {
            "principals": {
                "pat": {"label": "Pat", "kind": "person"},
                "elizabeth": {"label": "Elizabeth", "kind": "person"},
            },
            "accents": [],
        }
    )
    plugins = prepare_builtin_agenda_plugins(
        ("google-calendar",),
        configurations={"google-calendar": _two_connection_settings()},
        reference_catalogs={"workspace-principal": catalog.principal_ids},
    )
    application = MissionControlApplication(
        Database(tmp_path / "mission-control.db"),
        builtin_plugins=plugins,
        attribution_catalog=catalog,
    )

    google = [
        item
        for item in application.dashboard()["agenda"]
        if item["source"]["plugin_id"] == "google-calendar"
    ]
    assert len(google) == 16
    assert len({item["source"]["entity_id"] for item in google}) == 16
    trips = [item for item in google if item["title"] == "Language practice"]
    assert {
        item["attribution"]["integration"]["connection"]["id"] for item in trips
    } == {"pat", "elizabeth"}
    assert {
        item["attribution"]["integration"]["connection"]["id"]: item[
            "attribution"
        ]["integration"]["connection"]["label"]
        for item in trips
    } == {
        "pat": "Pat's Google",
        "elizabeth": "Elizabeth's Google",
    }
    assert {
        item["attribution"]["integration"]["collection"]["id"] for item in trips
    } == {"calendar:primary@example.invalid"}
    assert {tuple(item["attribution"]["principal_ids"]) for item in trips} == {
        ("pat",),
        ("elizabeth",),
    }
    components = application.health()["plugins"][0]["components"]
    assert {(item["id"], item["state"]) for item in components} == {
        ("pat", "ready"),
        ("elizabeth", "ready"),
    }


def test_generic_lifecycle_adopts_deployed_google_migrations(tmp_path):
    database = Database(tmp_path / "mission-control.db")
    MigrationRunner(database).apply()
    assert GoogleMigrationRunner(database).apply() == [1, 2, 3]

    (provider,) = activate_builtin_agenda_plugins(database, google_plugins())

    assert provider.plugin_id.value == "google-calendar"
    with database.connect() as connection:
        adopted = connection.execute(
            "SELECT version FROM plugin_schema_migrations "
            "WHERE plugin_id = 'google-calendar' ORDER BY version"
        ).fetchall()
    assert [row["version"] for row in adopted] == [1, 2, 3]


def test_core_migrates_populated_v2_google_cache_through_scoped_authorizer(
    tmp_path,
) -> None:
    database = Database(tmp_path / "mission-control.db")
    MigrationRunner(database).apply()
    migration_root = (
        Path(__file__).parents[1]
        / "mission_control"
        / "builtin_plugins"
        / "google"
        / "migrations"
    )
    with database.connect() as connection:
        for name in ("0001_initial.sql", "0002_cache_source.sql"):
            connection.executescript(
                (migration_root / name).read_text(encoding="utf-8")
            )
        connection.execute(
            "UPDATE plugin__15__google_calendar__sync_status "
            "SET source_mode = 'demo', source_fingerprint = 'legacy-source', "
            "last_success_at = '2026-08-14T12:00:00+00:00' WHERE singleton = 1"
        )
        connection.execute(
            "INSERT INTO plugin__15__google_calendar__collections("
            "collection_key, kind, external_id, label, access_role"
            ") VALUES ('legacy-calendar', 'calendar', 'primary', "
            "'Legacy calendar', 'owner')"
        )
        connection.execute(
            "INSERT INTO plugin__15__google_calendar__entries("
            "entity_id, collection_key, remote_id, entity_type, title, context, "
            "timing_kind, occurs_on, status, revision, updated_at"
            ") VALUES ('legacy-event', 'legacy-calendar', 'remote-event', "
            "'calendar-event', 'Legacy event', 'Legacy calendar', 'all-day', "
            "'2026-08-14', 'confirmed', 'legacy-revision', "
            "'2026-08-14T12:00:00+00:00')"
        )

    (prepared,) = google_plugins()
    builtin_plugins._apply_declared_migrations(database, prepared)

    with database.connect() as connection:
        status = connection.execute(
            "SELECT connection_id, source_fingerprint FROM "
            "plugin__15__google_calendar__connections"
        ).fetchone()
        collection = connection.execute(
            "SELECT connection_id, external_id, principal_ids_json FROM "
            "plugin__15__google_calendar__collections"
        ).fetchone()
        entry = connection.execute(
            "SELECT entity_id, collection_key FROM "
            "plugin__15__google_calendar__entries"
        ).fetchone()
        applied = connection.execute(
            "SELECT version FROM plugin_schema_migrations "
            "WHERE plugin_id = 'google-calendar' ORDER BY version"
        ).fetchall()

    assert tuple(status) == ("default", "legacy-source")
    assert tuple(collection) == ("default", "primary", "[]")
    assert tuple(entry) == ("legacy-event", "legacy-calendar")
    assert [row[0] for row in applied] == [1, 2, 3]


def test_google_cache_is_quarantined_when_source_changes(tmp_path):
    database = Database(tmp_path / "mission-control.db")
    GoogleMigrationRunner(database).apply()
    repository = SQLiteGoogleRepository(database)
    repository.prepare_source("demo", "Google demo", "demo", "fixture-one")
    (prepared,) = google_plugins()
    config = GoogleConfig.from_runtime(prepared.configuration.to_dict(), {})
    connection = config.connections[0]
    GoogleSynchronizer(
        repository,
        FixtureGoogleClient.load(connection.demo_anchor_date),
        config,
        connection,
    ).sync_once()
    assert repository.list_entries()
    assert (
        repository.prepare_source("demo", "Google demo", "demo", "fixture-one")
        is False
    )
    assert repository.list_entries()

    assert (
        repository.prepare_source(
            "demo", "Google demo", "live", "different-authorization"
        )
        is True
    )

    assert repository.list_entries() == ()
    status = repository.status("demo")
    assert status.source_mode == "live"
    assert status.source_fingerprint == "different-authorization"
    assert status.last_success_at is None


def test_google_resource_mapping_handles_privacy_dates_html_and_declines():
    collection = GoogleCollection("calendar", "one", "Private", "freeBusyReader")
    entry = calendar_event(
        collection,
        {
            "id": "event-1",
            "summary": "Secret title",
            "description": "<b>formatted</b><script>not executable</script>",
            "location": "Hidden place",
            "htmlLink": "https://calendar.google.com/example",
            "status": "confirmed",
            "start": {"date": "2026-08-14"},
            "end": {"date": "2026-08-16"},
            "etag": "one",
            "updated": "2026-08-14T00:00:00Z",
        },
    )
    assert entry is not None
    assert entry.title == "Busy"
    assert entry.detail is None
    assert entry.location is None
    assert entry.source_url is None
    assert entry.occurs_on.isoformat() == "2026-08-14"
    assert entry.ends_before.isoformat() == "2026-08-16"

    declined = calendar_event(
        GoogleCollection("calendar", "two", "Shared"),
        {
            "id": "declined",
            "status": "confirmed",
            "attendees": [{"self": True, "responseStatus": "declined"}],
            "start": {"dateTime": "2026-08-14T10:00:00+02:00"},
            "end": {"dateTime": "2026-08-14T11:00:00+02:00"},
        },
    )
    assert declined is None


def test_demo_fixture_rebases_its_showcase_dates():
    fixture = FixtureGoogleClient.load(date(2030, 1, 10))
    events = fixture.events(
        "travel@example.invalid",
        starts_at=datetime(2030, 1, 1, tzinfo=UTC),
        ends_at=datetime(2030, 2, 1, tzinfo=UTC),
    )
    trip = next(item for item in events if item["id"] == "travel-days")
    flight = next(item for item in events if item["id"] == "flight-zurich")

    assert trip["start"]["date"] == "2030-01-10"
    assert trip["end"]["date"] == "2030-01-19"
    assert flight["start"]["dateTime"].startswith("2030-01-10T20:30:00")


def test_google_task_due_timestamp_is_intentionally_date_only():
    task = google_task(
        GoogleCollection("task-list", "list", "Reminders"),
        {
            "id": "task",
            "title": "Remember this",
            "status": "needsAction",
            "due": "2026-08-14T23:59:59.000-07:00",
            "updated": "2026-08-14T00:00:00Z",
        },
    )
    assert task is not None
    assert task.timing_kind == "due-on"
    assert task.due_on.isoformat() == "2026-08-14"


def test_google_titles_fit_the_shared_entity_detail_contract():
    task = google_task(
        GoogleCollection("task-list", "list", "Tasks"),
        {
            "id": "long-task",
            "title": "T" * 257,
            "status": "needsAction",
            "updated": "2026-08-14T00:00:00Z",
        },
    )

    assert task is not None
    assert len(task.title) == 256
    assert task.title.endswith("…")


def test_partial_refresh_retains_last_good_collection_and_reports_degraded(tmp_path):
    database = Database(tmp_path / "mission-control.db")
    GoogleMigrationRunner(database).apply()
    repository = SQLiteGoogleRepository(database)
    (prepared,) = google_plugins()
    config = GoogleConfig.from_runtime(prepared.configuration.to_dict(), {})
    connection = config.connections[0]
    fixture = FixtureGoogleClient.load()
    repository.prepare_source(
        connection.connection_id, connection.label, connection.mode, "test-fixture"
    )
    GoogleSynchronizer(repository, fixture, config, connection).sync_once()
    before = {item.title for item in repository.list_entries()}

    class PartiallyFailingClient:
        def calendars(self):
            return fixture.calendars()

        def events(self, calendar_id, *, starts_at, ends_at):
            if calendar_id == "travel@example.invalid":
                raise GoogleApiError("upstream-unavailable", "Google could not be reached.")
            return fixture.events(calendar_id, starts_at=starts_at, ends_at=ends_at)

        def task_lists(self):
            return fixture.task_lists()

        def tasks(self, task_list_id):
            return fixture.tasks(task_list_id)

    GoogleSynchronizer(
        repository, PartiallyFailingClient(), config, connection
    ).sync_once()
    after = {item.title for item in repository.list_entries()}

    assert "Flight to Zürich" in before & after
    health = plugin_health(repository)
    assert health.state.value == "degraded"
    assert health.code == "connection-degraded"
    assert "Google demo" in health.detail


def test_resource_selection_modes_are_explicit() -> None:
    assert not ResourceSelection("disabled").includes(
        "primary", default_selected=True
    )
    assert ResourceSelection("defaults").includes(
        "primary", default_selected=True
    )
    assert not ResourceSelection("defaults").includes(
        "shared", default_selected=False
    )
    assert ResourceSelection("all").includes("shared", default_selected=False)
    assert ResourceSelection("selected", ("chosen",)).includes(
        "chosen", default_selected=False
    )
    assert not ResourceSelection("selected", ("chosen",)).includes(
        "other", default_selected=True
    )


def test_live_google_requires_named_oauth_credential(tmp_path):
    with pytest.raises(BuiltinPluginError, match=r"unknown credential reference"):
        prepare_builtin_agenda_plugins(
            ("google-calendar",),
            configurations={
                "google-calendar": {
                    "connections": {
                        "personal": {
                            "label": "Personal Google",
                            "mode": "live",
                            "credential": "personal-oauth",
                            "calendars": {"mode": "defaults"},
                            "tasks": {"mode": "disabled"},
                        }
                    }
                }
            },
        )


def test_reconnect_required_is_actionable_and_erases_private_cache(tmp_path):
    database = Database(tmp_path / "mission-control.db")
    GoogleMigrationRunner(database).apply()
    repository = SQLiteGoogleRepository(database)
    (prepared,) = google_plugins()
    config = GoogleConfig.from_runtime(prepared.configuration.to_dict(), {})
    connection = config.connections[0]
    repository.prepare_source(
        connection.connection_id, connection.label, connection.mode, "test-fixture"
    )
    GoogleSynchronizer(
        repository, FixtureGoogleClient.load(), config, connection
    ).sync_once()
    assert repository.list_entries()

    class RevokedClient:
        def calendars(self):
            raise GoogleApiError(
                "reconnect-required", "Google authorization must be reconnected."
            )

        def events(self, calendar_id, *, starts_at, ends_at):
            raise AssertionError("event reads must not run after discovery fails")

        def task_lists(self):
            raise AssertionError("Tasks must not run after terminal authorization failure")

        def tasks(self, task_list_id):
            raise AssertionError("task reads must not run after discovery fails")

    GoogleSynchronizer(repository, RevokedClient(), config, connection).sync_once()

    assert repository.list_entries() == ()
    health = plugin_health(repository)
    assert health.state.value == "degraded"
    assert health.code == "connection-degraded"
    assert health.detail == "Google connection needs attention: Google demo"


def test_revocation_erases_only_the_affected_connection(tmp_path) -> None:
    database = Database(tmp_path / "mission-control.db")
    GoogleMigrationRunner(database).apply()
    repository = SQLiteGoogleRepository(database)
    (prepared,) = prepare_builtin_agenda_plugins(
        ("google-calendar",),
        configurations={"google-calendar": _two_connection_settings()},
        reference_catalogs={
            "workspace-principal": frozenset({"pat", "elizabeth"})
        },
    )
    config = GoogleConfig.from_runtime(prepared.configuration.to_dict(), {})
    repository.reconcile_configured_connections(
        item.connection_id for item in config.connections
    )
    for connection in config.connections:
        repository.prepare_source(
            connection.connection_id,
            connection.label,
            connection.mode,
            f"fixture:{connection.connection_id}",
        )
        GoogleSynchronizer(
            repository, FixtureGoogleClient.load(), config, connection
        ).sync_once()
    assert len(repository.list_entries()) == 16

    class RevokedClient:
        def calendars(self):
            raise GoogleApiError(
                "reconnect-required", "Google authorization must be reconnected."
            )

        def events(self, calendar_id, *, starts_at, ends_at):
            raise AssertionError("events must not run after revocation")

        def task_lists(self):
            raise AssertionError("tasks must not run after revocation")

        def tasks(self, task_list_id):
            raise AssertionError("tasks must not run after revocation")

    pat = next(item for item in config.connections if item.connection_id == "pat")
    GoogleSynchronizer(repository, RevokedClient(), config, pat).sync_once()

    remaining = repository.list_entries()
    assert len(remaining) == 8
    assert {item.connection_id for item in remaining} == {"elizabeth"}
    components = plugin_health(repository).components
    assert {(item.component_id, item.state.value) for item in components} == {
        ("pat", "degraded"),
        ("elizabeth", "ready"),
    }


@pytest.mark.parametrize("revoked_phase", ("events", "tasks"))
def test_revocation_during_collection_reads_erases_the_connection(
    tmp_path, revoked_phase
) -> None:
    database = Database(tmp_path / f"mission-control-{revoked_phase}.db")
    GoogleMigrationRunner(database).apply()
    repository = SQLiteGoogleRepository(database)
    (prepared,) = google_plugins()
    config = GoogleConfig.from_runtime(prepared.configuration.to_dict(), {})
    connection = config.connections[0]
    fixture = FixtureGoogleClient.load()
    repository.reconcile_configured_connections((connection.connection_id,))
    repository.prepare_source(
        connection.connection_id, connection.label, connection.mode, "test-fixture"
    )
    GoogleSynchronizer(repository, fixture, config, connection).sync_once()
    assert repository.list_entries()

    class RevokedDuringRead:
        def calendars(self):
            return fixture.calendars()

        def events(self, calendar_id, *, starts_at, ends_at):
            if revoked_phase == "events":
                raise GoogleApiError(
                    "reconnect-required", "Google authorization must be reconnected."
                )
            return fixture.events(calendar_id, starts_at=starts_at, ends_at=ends_at)

        def task_lists(self):
            if revoked_phase == "events":
                raise AssertionError("task reads must stop after calendar revocation")
            return fixture.task_lists()

        def tasks(self, task_list_id):
            raise GoogleApiError(
                "reconnect-required", "Google authorization must be reconnected."
            )

    GoogleSynchronizer(
        repository, RevokedDuringRead(), config, connection
    ).sync_once()

    assert repository.list_entries() == ()
    assert repository.status(connection.connection_id).error_code == "reconnect-required"


def test_one_invalid_connection_does_not_hide_a_healthy_connection(tmp_path) -> None:
    credential = tmp_path / "invalid-oauth.json"
    credential.write_text("{}", encoding="utf-8")
    credential.chmod(0o600)
    settings = demo_settings("demo", label="Demo Google")
    connections = settings["connections"]
    assert isinstance(connections, dict)
    connections["broken"] = {
        "label": "Broken Google",
        "mode": "live",
        "credential": "broken-oauth",
        "calendars": {"mode": "defaults"},
        "tasks": {"mode": "disabled"},
    }
    plugins = prepare_builtin_agenda_plugins(
        ("google-calendar",),
        configurations={"google-calendar": settings},
        credentials={"google-calendar": {"broken-oauth": str(credential)}},
    )

    application = MissionControlApplication(
        Database(tmp_path / "mission-control.db"), builtin_plugins=plugins
    )

    google = [
        item
        for item in application.dashboard()["agenda"]
        if item["source"]["plugin_id"] == "google-calendar"
    ]
    assert len(google) == 8
    health = application.health()["plugins"][0]
    assert health["state"] == "degraded"
    assert {(item["id"], item["state"]) for item in health["components"]} == {
        ("broken", "degraded"),
        ("demo", "ready"),
    }
