from __future__ import annotations

import json
import threading
from datetime import UTC, datetime

from mission_control.builtin_plugins import prepare_builtin_agenda_plugins
from mission_control.database import Database
from mission_control.server import MissionControlApplication


def application(tmp_path):
    prepared = prepare_builtin_agenda_plugins(("family-rewards",))
    return MissionControlApplication(
        Database(tmp_path / "mission-control.db"),
        builtin_plugins=prepared,
        write_token="test-token",
    )


def snapshot(app):
    detail = app.entity_detail("family-rewards", "account", "family-credit")
    attributes = {item["key"]: item["value"] for item in detail["attributes"]}
    result = json.loads(attributes["rewards-snapshot"])
    result["settings"] = json.loads(attributes["rewards-settings"])
    result["overrides"] = json.loads(attributes["rewards-overrides"])
    return result


def ledger(app):
    with app.repository.database.connect() as connection:
        return [
            dict(item)
            for item in connection.execute(
                "SELECT * FROM plugin__14__family_rewards__ledger ORDER BY occurred_at, entry_id"
            ).fetchall()
        ]


def command(app, command_id, operation, arguments, *, revision=None):
    status, result = app.execute_command(
        {
            "schema_version": "mission-control.command/v1",
            "command_id": command_id,
            "target": {
                "plugin_id": "family-rewards",
                "entity_type": "account",
                "entity_id": "family-credit",
            },
            "expected_revision": revision or snapshot(app)["revision"],
            "command": operation,
            "arguments": arguments,
        },
        authorized=True,
    )
    return status, result


def test_awards_are_durable_duplicate_safe_and_concurrency_safe(tmp_path):
    app = application(tmp_path)
    day = "2026-11-02"
    revision = snapshot(app)["revision"]
    document = {
        "local_date": day,
        "task_id": "get-dressed",
    }

    first_status, first = command(
        app, "award-once", "award-task", document, revision=revision
    )
    replay_status, replay = command(
        app, "award-once", "award-task", document, revision=revision
    )

    assert first_status == replay_status == 200
    assert first == replay
    assert snapshot(app)["balance_minutes"] == 10
    assert len(ledger(app)) == 1

    current = snapshot(app)["revision"]
    barrier = threading.Barrier(3)
    outcomes = []

    def award(command_id):
        barrier.wait()
        outcomes.append(
            command(
                app,
                command_id,
                "award-task",
                {"local_date": day, "task_id": "breakfast"},
                revision=current,
            )[1]
        )

    threads = [threading.Thread(target=award, args=(f"concurrent-{index}",)) for index in range(2)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join()

    assert [item["status"] for item in outcomes].count("accepted") == 1
    assert snapshot(app)["balance_minutes"] == 20
    assert len([item for item in ledger(app) if item["task_id"] == "breakfast"]) == 1


def test_reversal_is_explicit_and_historical_earning_value_is_stable(tmp_path):
    app = application(tmp_path)
    day = "2026-11-02"
    _, earned = command(
        app,
        "earn-ten",
        "award-task",
        {"local_date": day, "task_id": "brush-teeth"},
    )
    original_entry = earned["result"]["entry_id"]

    settings = snapshot(app)["settings"]
    settings["tasks"] = [
        {**task, "minutes": 20 if task["id"] == "brush-teeth" else task["minutes"]}
        for task in settings["tasks"]
    ]
    assert command(app, "change-value", "update-settings", {"settings": settings})[1]["status"] == "accepted"
    assert command(
        app,
        "correct-award",
        "reverse-entry",
        {"entry_id": original_entry, "note": "Checked in error"},
    )[1]["status"] == "accepted"
    assert command(
        app,
        "earn-twenty",
        "award-task",
        {"local_date": day, "task_id": "brush-teeth"},
    )[1]["status"] == "accepted"

    state = snapshot(app)
    assert state["balance_minutes"] == 20
    entries = ledger(app)
    assert sorted(item["amount_minutes"] for item in entries) == [-10, 10, 20]
    assert next(item for item in entries if item["kind"] == "reversal")["reverses_entry_id"] == original_entry


def test_spending_never_creates_debt_and_refunds_are_ledger_entries(tmp_path):
    app = application(tmp_path)
    day = "2026-11-02"
    for index, task_id in enumerate(("get-dressed", "breakfast", "brush-teeth", "pack-up")):
        command(app, f"earn-{index}", "award-task", {"local_date": day, "task_id": task_id})

    status, spent = command(
        app,
        "spend-thirty",
        "spend-credit",
        {"local_date": day, "minutes": 30, "note": "Parent-recorded play"},
    )
    assert status == 200
    assert snapshot(app)["balance_minutes"] == 10

    rejected_status, rejected = command(
        app,
        "overspend",
        "spend-credit",
        {"local_date": day, "minutes": 20, "note": "Too much"},
    )
    assert rejected_status == 400
    assert rejected["error"]["code"] == "insufficient-balance"
    assert snapshot(app)["balance_minutes"] == 10

    command(
        app,
        "refund",
        "reverse-entry",
        {"entry_id": spent["result"]["entry_id"], "note": "Session canceled"},
    )
    state = snapshot(app)
    assert state["balance_minutes"] == 40
    assert next(item for item in ledger(app) if item["kind"] == "refund")["amount_minutes"] == 30


def test_date_overrides_replace_recurring_eligibility_and_classification(tmp_path):
    app = application(tmp_path)
    holiday = "2026-11-03"
    assert command(
        app,
        "holiday-closed",
        "set-date-override",
        {"local_date": holiday, "school_day": False, "eligible": False, "starts_at": None, "ends_at": None, "note": "No play planned"},
    )[1]["status"] == "accepted"
    override = next(item for item in snapshot(app)["overrides"] if item["local_date"] == holiday)
    assert override["school_day"] == 0
    assert override["eligible"] == 0
    command(app, "holiday-earn", "award-task", {"local_date": holiday, "task_id": "get-dressed"})
    blocked_status, blocked = command(
        app,
        "holiday-spend-blocked",
        "spend-credit",
        {"local_date": holiday, "minutes": 5, "note": "Should be blocked"},
    )
    assert blocked_status == 400
    assert blocked["error"]["code"] == "date-not-eligible"

    assert command(
        app,
        "holiday-window",
        "set-date-override",
        {"local_date": holiday, "school_day": False, "eligible": True, "starts_at": "11:00", "ends_at": "13:00", "note": "Holiday window"},
    )[1]["status"] == "accepted"
    updated = next(item for item in snapshot(app)["overrides"] if item["local_date"] == holiday)
    assert (updated["starts_at"], updated["ends_at"]) == ("11:00", "13:00")
    assert command(
        app,
        "holiday-spend-allowed",
        "spend-credit",
        {"local_date": holiday, "minutes": 5, "note": "Holiday play"},
    )[1]["status"] == "accepted"

    assert command(app, "remove-holiday", "remove-date-override", {"local_date": holiday})[1]["status"] == "accepted"
    assert not snapshot(app)["overrides"]


def test_agenda_uses_configured_new_york_date_at_utc_boundary(tmp_path, monkeypatch):
    app = application(tmp_path)
    monkeypatch.setattr(
        app,
        "_agenda_contributions",
        lambda generated_at: tuple(
            provider.contribution(generated_at=datetime(2026, 11, 2, 2, tzinfo=UTC))
            for provider in app.agenda_providers
        ),
    )
    entries = [
        item
        for item in app.dashboard()["agenda"]
        if item["source"]["plugin_id"] == "family-rewards"
        and item["source"]["entity_type"] == "routine-task"
    ]
    assert {item["timing"]["due_on"] for item in entries} == {"2026-11-01"}
