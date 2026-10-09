from __future__ import annotations

from copy import deepcopy

from mission_control.builtin_plugins import prepare_builtin_agenda_plugins
from mission_control.database import Database
from mission_control.server import MissionControlApplication


def snapshot(
    revision: str = "research-1",
    *,
    checked_at: str = "2026-10-09T11:30:00Z",
    candidates: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "schema_version": "mission-control.home-search-snapshot/v1",
        "revision": revision,
        "checked_at": checked_at,
        "sources": ["https://search.example/reading-ma-01867"],
        "candidates": [candidate()] if candidates is None else candidates,
    }


def candidate(candidate_id: str = "reading-12-oak") -> dict[str, object]:
    return {
        "id": candidate_id,
        "address": "12 Oak Street, Reading, MA 01867",
        "location": "Reading, MA 01867",
        "verification_status": "verified",
        "listing_status": "active",
        "source_url": "https://listings.example/reading-12-oak",
        "source_label": "Example listing source",
        "indoor_sqft": 2350,
        "list_price": 875000,
        "why_fit": ["Larger usable interior and a quiet side-street setting"],
        "tradeoffs": ["Central AC condition needs inspection"],
        "unknowns": ["FiOS availability must be confirmed at the address"],
        "estimated_all_in": {
            "amount": 912500,
            "currency": "USD",
            "confidence": "low",
            "assumptions": [
                "List price plus estimated closing costs",
                "Includes a provisional HVAC allowance",
            ],
        },
    }


def application(tmp_path, database: Database | None = None) -> MissionControlApplication:
    return MissionControlApplication(
        database or Database(tmp_path / "mission-control.db"),
        builtin_plugins=prepare_builtin_agenda_plugins(("home-search",)),
    )


def search_entry(app: MissionControlApplication) -> dict[str, object]:
    return next(
        item
        for item in app.dashboard()["agenda"]
        if item["source"] == {
            "plugin_id": "home-search",
            "entity_type": "search",
            "entity_id": "reading-ma-01867",
        }
    )


def import_snapshot(
    app: MissionControlApplication,
    document: object,
    *,
    revision: str | None = None,
    command_id: str = "import-1",
) -> tuple[int, dict[str, object]]:
    entry = search_entry(app)
    return app.execute_command(
        {
            "schema_version": "mission-control.command/v1",
            "command_id": command_id,
            "target": entry["source"],
            "expected_revision": revision or entry["revision"],
            "command": "import-snapshot",
            "arguments": {"snapshot": document},
        },
        authorized=True,
    )


def test_initial_state_is_honest_and_contains_no_demo_listings(tmp_path) -> None:
    app = application(tmp_path)

    agenda = app.dashboard()["agenda"]
    assert [item["id"] for item in agenda] == ["reading-ma-01867"]
    initiative = agenda[0]
    assert "Budget is provisional and unset" in initiative["detail"]
    assert "daily watcher is not active" in initiative["detail"]
    assert "$" not in initiative["detail"]

    detail = app.entity_detail("home-search", "search", "reading-ma-01867")
    attributes = {item["key"]: item["value"] for item in detail["attributes"]}
    assert attributes["location"] == "Strictly Reading, MA 01867"
    assert "not a hard numeric cutoff" in attributes["space"]
    assert "Provisional and unset" in attributes["budget"]
    assert attributes["freshness"] == "No verified search snapshot imported yet"
    assert attributes["watcher"].startswith("Not active.")


def test_valid_import_duplicate_and_conflict_preserve_last_good_snapshot(tmp_path) -> None:
    app = application(tmp_path)
    status, result = import_snapshot(app, snapshot())
    assert status == 200
    assert result["result"] == {
        "candidate_count": 1,
        "imported": True,
        "source_revision": "research-1",
    }
    candidate_before = app.entity_detail(
        "home-search", "candidate", "reading-12-oak"
    )

    status, duplicate = import_snapshot(
        app, snapshot(), command_id="duplicate-1"
    )
    assert status == 200
    assert duplicate["result"]["imported"] is False
    assert duplicate["revision"] == search_entry(app)["revision"]

    conflicting = snapshot()
    conflicting["candidates"][0]["listing_status"] = "pending"  # type: ignore[index]
    status, rejected = import_snapshot(
        app, conflicting, command_id="conflicting-revision-1"
    )
    assert status == 400
    assert rejected["error"]["code"] == "snapshot-revision-conflict"
    assert app.entity_detail(
        "home-search", "candidate", "reading-12-oak"
    ) == candidate_before

    invalid = deepcopy(snapshot("research-2"))
    invalid["candidates"][0]["location"] = "Wakefield, MA"  # type: ignore[index]
    status, rejected = import_snapshot(app, invalid, command_id="invalid-1")
    assert status == 400
    assert rejected["error"]["code"] == "invalid-snapshot"
    assert app.entity_detail(
        "home-search", "candidate", "reading-12-oak"
    ) == candidate_before


def test_stale_import_is_rejected_and_state_survives_restart(tmp_path) -> None:
    database = Database(tmp_path / "mission-control.db")
    app = application(tmp_path, database)
    initial_revision = search_entry(app)["revision"]
    assert import_snapshot(app, snapshot())[0] == 200

    status, stale = import_snapshot(
        app,
        snapshot(
            "research-2",
            checked_at="2026-10-09T12:30:00Z",
            candidates=[],
        ),
        revision=initial_revision,
        command_id="stale-import-1",
    )
    assert status == 409
    assert stale["status"] == "stale"

    restarted = application(tmp_path, database)
    persisted = restarted.entity_detail(
        "home-search", "candidate", "reading-12-oak"
    )
    attributes = {item["key"]: item["value"] for item in persisted["attributes"]}
    assert attributes["source-url"] == "https://listings.example/reading-12-oak"
    assert attributes["estimated-all-in"] == "$912,500 USD"
    assert "provisional HVAC allowance" in attributes["cost-assumptions"]
    assert attributes["last-checked"] == "2026-10-09T11:30:00+00:00"


def test_review_decision_survives_full_replacement_reimport(tmp_path) -> None:
    app = application(tmp_path)
    assert import_snapshot(app, snapshot())[0] == 200
    detail = app.entity_detail("home-search", "candidate", "reading-12-oak")
    status, reviewed = app.execute_command(
        {
            "schema_version": "mission-control.command/v1",
            "command_id": "shortlist-1",
            "target": detail["source"],
            "expected_revision": detail["revision"],
            "command": "set-review-status",
            "arguments": {"status": "shortlisted"},
        },
        authorized=True,
    )
    assert status == 200
    assert reviewed["result"] == {"review_status": "shortlisted"}

    refreshed_candidate = candidate()
    refreshed_candidate["listing_status"] = "price changed"
    assert import_snapshot(
        app,
        snapshot("research-2", candidates=[refreshed_candidate]),
        command_id="import-2",
    )[0] == 200
    refreshed = app.entity_detail(
        "home-search", "candidate", "reading-12-oak"
    )
    attributes = {item["key"]: item["value"] for item in refreshed["attributes"]}
    assert attributes["review-status"] == "shortlisted"
    assert attributes["listing-status"] == "price changed"
    assert [event["activity_type"] for event in refreshed["activity"]] == [
        "home-search.candidate-discovered",
        "home-search.review-status-changed",
        "home-search.candidate-updated",
    ]


def test_verified_empty_snapshot_reports_scope_without_implying_feed(tmp_path) -> None:
    app = application(tmp_path)
    status, _ = import_snapshot(app, snapshot(candidates=[]))
    assert status == 200
    initiative = search_entry(app)
    assert "0 current candidates" in initiative["detail"]
    assert "2026-10-09T11:30:00+00:00" in initiative["detail"]
    assert "watcher remains inactive" in initiative["detail"]
    assert len(app.dashboard()["agenda"]) == 1


def test_full_replacement_hides_omitted_candidate_without_deleting_history(tmp_path) -> None:
    app = application(tmp_path)
    assert import_snapshot(app, snapshot())[0] == 200
    assert import_snapshot(
        app,
        snapshot(
            "research-2",
            checked_at="2026-10-09T12:30:00Z",
            candidates=[],
        ),
        command_id="empty-replacement-1",
    )[0] == 200

    assert [item["id"] for item in app.dashboard()["agenda"]] == [
        "reading-ma-01867"
    ]
    historical = app.entity_detail(
        "home-search", "candidate", "reading-12-oak"
    )
    assert historical["title"] == "12 Oak Street, Reading, MA 01867"
    assert historical["state"] == "archived · unreviewed"
    assert historical["revision"] == "2"
    assert historical["affordances"] == [
        {"capability": "entity.annotate", "command": "add-note"}
    ]
    attributes = {item["key"]: item["value"] for item in historical["attributes"]}
    assert attributes["last-checked"] == "2026-10-09T11:30:00+00:00"
    assert historical["activity"][0]["activity_type"] == (
        "home-search.candidate-discovered"
    )

    status, stale = app.execute_command(
        {
            "schema_version": "mission-control.command/v1",
            "command_id": "review-archived-1",
            "target": historical["source"],
            "expected_revision": "1",
            "command": "set-review-status",
            "arguments": {"status": "shortlisted"},
        },
        authorized=True,
    )
    assert status == 409
    assert stale["status"] == "stale"


def test_unverified_candidate_stays_explicit_and_unsafe_source_is_rejected(tmp_path) -> None:
    app = application(tmp_path)
    unverified = candidate()
    unverified["verification_status"] = "unverified"
    assert import_snapshot(
        app, snapshot(candidates=[unverified]), command_id="unverified-1"
    )[0] == 200
    entry = next(
        item
        for item in app.dashboard()["agenda"]
        if item["source"]["entity_type"] == "candidate"
    )
    assert "unverified" in entry["context"]
    detail = app.entity_detail("home-search", "candidate", "reading-12-oak")
    attributes = {item["key"]: item["value"] for item in detail["attributes"]}
    assert attributes["verification"] == "unverified"

    unsafe = candidate("reading-unsafe")
    unsafe["source_url"] = "javascript:alert(1)"
    status, rejected = import_snapshot(
        app,
        snapshot("research-unsafe", candidates=[unsafe]),
        command_id="unsafe-source-1",
    )
    assert status == 400
    assert rejected["error"]["code"] == "invalid-snapshot"
    assert {item["id"] for item in app.dashboard()["agenda"]} == {
        "reading-ma-01867",
        "reading-12-oak",
    }


def test_revision_ledger_and_freshness_prevent_replay_or_regression(tmp_path) -> None:
    app = application(tmp_path)
    assert import_snapshot(app, snapshot())[0] == 200
    assert import_snapshot(
        app,
        snapshot(
            "research-2",
            checked_at="2026-10-09T12:30:00Z",
            candidates=[],
        ),
        command_id="newer-1",
    )[0] == 200
    current_revision = search_entry(app)["revision"]

    status, replay = import_snapshot(
        app, snapshot(), command_id="historical-replay-1"
    )
    assert status == 200
    assert replay["result"]["imported"] is False
    assert search_entry(app)["revision"] == current_revision

    changed_old = snapshot()
    changed_old["candidates"] = []
    status, conflict = import_snapshot(
        app, changed_old, command_id="historical-conflict-1"
    )
    assert status == 400
    assert conflict["error"]["code"] == "snapshot-revision-conflict"

    status, stale_source = import_snapshot(
        app,
        snapshot(
            "research-3",
            checked_at="2026-10-09T12:00:00Z",
            candidates=[],
        ),
        command_id="freshness-regression-1",
    )
    assert status == 400
    assert stale_source["error"]["code"] == "snapshot-freshness-regression"


def test_smaller_or_unknown_space_and_unknown_cost_remain_visible(tmp_path) -> None:
    app = application(tmp_path)
    incomplete = candidate()
    incomplete["indoor_sqft"] = 1700
    incomplete["estimated_all_in"] = {
        "amount": None,
        "currency": "USD",
        "confidence": "unknown",
        "assumptions": [
            "Closing and upgrade costs have not yet been reconciled"
        ],
    }
    status, _ = import_snapshot(
        app,
        snapshot("incomplete-research-1", candidates=[incomplete]),
        command_id="incomplete-research-1",
    )
    assert status == 200
    detail = app.entity_detail("home-search", "candidate", "reading-12-oak")
    attributes = {item["key"]: item["value"] for item in detail["attributes"]}
    assert attributes["usable-indoor-space"].startswith("1,700 sq ft reported")
    assert attributes["estimated-all-in"] == "Not yet estimated"
    assert attributes["cost-confidence"] == "unknown"
    assert "not yet been reconciled" in attributes["cost-assumptions"]
