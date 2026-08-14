from __future__ import annotations

import pytest

import mission_control.builtin_plugins as builtin_plugins
from mission_control.builtin_plugins import (
    BuiltinPluginError,
    prepare_builtin_agenda_plugins,
)
from mission_control.builtin_plugins.google.client import GoogleApiError
from mission_control.builtin_plugins.google.config import GoogleConfig
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
from mission_control.plugins import Capability, StandardEntityCapability
from mission_control.server import MissionControlApplication


def google_plugins():
    return prepare_builtin_agenda_plugins(
        ("google",), configurations={"google": {"mode": "demo"}}
    )


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


def test_demo_sync_projects_events_tasks_details_and_independent_migration(tmp_path):
    database = Database(tmp_path / "mission-control.db")
    application = MissionControlApplication(database, builtin_plugins=google_plugins())
    dashboard = application.dashboard()
    google = [
        item for item in dashboard["agenda"] if item["source"]["plugin_id"] == "google"
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
        "google", task["source"]["entity_type"], task["source"]["entity_id"]
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
                "SELECT version FROM google_schema_migrations"
            ).fetchall()
        ] == [1]
        assert connection.execute("SELECT count(*) FROM google_entries").fetchone()[0] == 8

    restarted = MissionControlApplication(database, builtin_plugins=google_plugins())
    assert len(
        [
            item
            for item in restarted.dashboard()["agenda"]
            if item["source"]["plugin_id"] == "google"
        ]
    ) == 8


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
    config = GoogleConfig.from_runtime(prepared.configuration, {})
    fixture = FixtureGoogleClient.load()
    GoogleSynchronizer(repository, fixture, config).sync_once()
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

    GoogleSynchronizer(repository, PartiallyFailingClient(), config).sync_once()
    after = {item.title for item in repository.list_entries()}

    assert "Flight to Zürich" in before & after
    health = plugin_health(repository)
    assert health.state.value == "degraded"
    assert health.code == "partial-sync"
    assert "Google source" in health.detail


def test_live_google_requires_named_oauth_credential(tmp_path):
    prepared = prepare_builtin_agenda_plugins(("google",))
    with pytest.raises(BuiltinPluginError, match="named 'oauth' credential"):
        MissionControlApplication(
            Database(tmp_path / "mission-control.db"), builtin_plugins=prepared
        )


def test_reconnect_required_is_actionable_and_erases_private_cache(tmp_path):
    database = Database(tmp_path / "mission-control.db")
    GoogleMigrationRunner(database).apply()
    repository = SQLiteGoogleRepository(database)
    (prepared,) = google_plugins()
    config = GoogleConfig.from_runtime(prepared.configuration, {})
    GoogleSynchronizer(repository, FixtureGoogleClient.load(), config).sync_once()
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

    GoogleSynchronizer(repository, RevokedClient(), config).sync_once()

    assert repository.list_entries() == ()
    health = plugin_health(repository)
    assert health.state.value == "degraded"
    assert health.code == "reconnect-required"
    assert health.detail == "Google authorization must be reconnected."
