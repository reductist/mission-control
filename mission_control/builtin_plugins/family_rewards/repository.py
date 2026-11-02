"""Durable, parent-operated family rewards ledger."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import UTC, date, datetime, time
from typing import Any, Mapping, cast
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from mission_control.plugin_api import PluginStorage

PREFIX = "plugin__14__family_rewards__"
ACCOUNT_ID = "family-credit"


class RewardsError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _revision(row: sqlite3.Row) -> str:
    return f"r{row['revision']}"


def _parse_date(value: object) -> date:
    if not isinstance(value, str):
        raise RewardsError("invalid-date", "Local date must use YYYY-MM-DD.")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise RewardsError("invalid-date", "Local date must use YYYY-MM-DD.") from error
    if parsed.isoformat() != value:
        raise RewardsError("invalid-date", "Local date must use YYYY-MM-DD.")
    return parsed


def _validate_settings(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise RewardsError("invalid-settings", "Settings must be an object.")
    required = {
        "timezone", "school_day_cap_minutes", "non_school_day_cap_minutes",
        "tasks", "windows",
    }
    if set(value) != required:
        raise RewardsError("invalid-settings", "Settings contain missing or unsupported fields.")
    timezone = value["timezone"]
    if not isinstance(timezone, str) or not timezone or len(timezone) > 64:
        raise RewardsError("invalid-timezone", "Timezone must be a valid IANA timezone name.")
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError as error:
        raise RewardsError("invalid-timezone", "Timezone must be a valid IANA timezone name.") from error
    caps = (value["school_day_cap_minutes"], value["non_school_day_cap_minutes"])
    if any(type(item) is not int or not 0 <= item <= 1440 for item in caps):
        raise RewardsError("invalid-cap", "Daily caps must be whole minutes from 0 to 1440.")
    raw_tasks = value["tasks"]
    if not isinstance(raw_tasks, list) or len(raw_tasks) != 4:
        raise RewardsError("invalid-tasks", "Exactly four morning tasks are required.")
    tasks: list[dict[str, object]] = []
    for raw in raw_tasks:
        if not isinstance(raw, Mapping) or set(raw) != {"id", "label", "minutes"}:
            raise RewardsError("invalid-tasks", "Each task requires id, label, and minutes.")
        task_id, label, minutes = raw["id"], raw["label"], raw["minutes"]
        if not isinstance(task_id, str) or re.fullmatch(r"[a-z][a-z0-9-]*", task_id) is None:
            raise RewardsError("invalid-tasks", "Task ids may contain letters, numbers, and hyphens.")
        if not isinstance(label, str) or not label.strip() or len(label) > 160:
            raise RewardsError("invalid-tasks", "Task labels must be 1 to 160 characters.")
        if type(minutes) is not int or not 1 <= minutes <= 240:
            raise RewardsError("invalid-tasks", "Task values must be 1 to 240 minutes.")
        tasks.append({"id": task_id, "label": label.strip(), "minutes": minutes})
    if len({item["id"] for item in tasks}) != 4:
        raise RewardsError("invalid-tasks", "Task ids must be unique.")
    raw_windows = value["windows"]
    if not isinstance(raw_windows, list) or len(raw_windows) > 16:
        raise RewardsError("invalid-windows", "At most 16 recurring play windows are supported.")
    windows: list[dict[str, object]] = []
    for raw in raw_windows:
        if not isinstance(raw, Mapping) or set(raw) != {"id", "label", "weekdays", "starts_at", "ends_at"}:
            raise RewardsError("invalid-windows", "Each play window requires id, label, weekdays, start, and end.")
        window_id, label = raw["id"], raw["label"]
        weekdays, starts_at, ends_at = raw["weekdays"], raw["starts_at"], raw["ends_at"]
        if not isinstance(window_id, str) or re.fullmatch(r"[a-z][a-z0-9-]*", window_id) is None:
            raise RewardsError("invalid-windows", "Play-window ids may contain letters, numbers, and hyphens.")
        if not isinstance(label, str) or not label.strip() or len(label) > 80:
            raise RewardsError("invalid-windows", "Play-window labels must be 1 to 80 characters.")
        if not isinstance(weekdays, list) or not weekdays or len(set(weekdays)) != len(weekdays) or any(type(day) is not int or not 1 <= day <= 7 for day in weekdays):
            raise RewardsError("invalid-windows", "Play-window weekdays must be unique values from 1 to 7.")
        try:
            start = time.fromisoformat(cast(str, starts_at))
            end = time.fromisoformat(cast(str, ends_at))
        except (TypeError, ValueError) as error:
            raise RewardsError("invalid-windows", "Play-window times must use HH:MM.") from error
        if start >= end or len(cast(str, starts_at)) != 5 or len(cast(str, ends_at)) != 5:
            raise RewardsError("invalid-windows", "Play-window end must be after its start.")
        windows.append({"id": window_id, "label": label.strip(), "weekdays": sorted(weekdays), "starts_at": starts_at, "ends_at": ends_at})
    if len({item["id"] for item in windows}) != len(windows):
        raise RewardsError("invalid-windows", "Play-window ids must be unique.")
    return {"timezone": timezone, "school_day_cap_minutes": caps[0], "non_school_day_cap_minutes": caps[1], "tasks": tasks, "windows": windows}


class RewardsRepository:
    def __init__(self, storage: PluginStorage, initial_settings: Mapping[str, object]) -> None:
        self.storage = storage
        settings = _validate_settings(initial_settings)
        with self.storage.connect() as connection:
            row = connection.execute(f"SELECT 1 FROM {PREFIX}state WHERE singleton = 1").fetchone()
            if row is None:
                connection.execute(
                    f"INSERT INTO {PREFIX}state(singleton, revision, timezone, school_day_cap_minutes, non_school_day_cap_minutes, tasks_json, windows_json, updated_at) VALUES (1, 1, ?, ?, ?, ?, ?, ?)",
                    (settings["timezone"], settings["school_day_cap_minutes"], settings["non_school_day_cap_minutes"], _canonical(settings["tasks"]), _canonical(settings["windows"]), _now()),
                )

    def _state(self, connection: sqlite3.Connection) -> sqlite3.Row:
        row = connection.execute(f"SELECT * FROM {PREFIX}state WHERE singleton = 1").fetchone()
        if row is None:
            raise RuntimeError("family rewards state is unavailable")
        return row

    def revision(self) -> str:
        with self.storage.connect() as connection:
            return _revision(self._state(connection))

    def _settings(self, row: sqlite3.Row) -> dict[str, object]:
        return {"timezone": row["timezone"], "school_day_cap_minutes": row["school_day_cap_minutes"], "non_school_day_cap_minutes": row["non_school_day_cap_minutes"], "tasks": json.loads(row["tasks_json"]), "windows": json.loads(row["windows_json"])}

    def local_today(self, generated_at: datetime | None = None) -> date:
        with self.storage.connect() as connection:
            timezone = ZoneInfo(self._state(connection)["timezone"])
        instant = generated_at or datetime.now(UTC)
        return instant.astimezone(timezone).date()

    def _balance(self, connection: sqlite3.Connection) -> int:
        return int(connection.execute(f"SELECT COALESCE(SUM(amount_minutes), 0) FROM {PREFIX}ledger").fetchone()[0])

    def _effective_day(self, connection: sqlite3.Connection, local_day: date, settings: Mapping[str, object]) -> dict[str, object]:
        override = connection.execute(f"SELECT * FROM {PREFIX}overrides WHERE local_date = ?", (local_day.isoformat(),)).fetchone()
        school_day = local_day.isoweekday() <= 5
        if override is not None and override["school_day"] is not None:
            school_day = bool(override["school_day"])
        cap = cast(int, settings["school_day_cap_minutes"] if school_day else settings["non_school_day_cap_minutes"])
        if override is not None:
            windows = ([{"id": f"override-{local_day.isoformat()}", "label": override["note"] or "Date override", "weekdays": [local_day.isoweekday()], "starts_at": override["starts_at"], "ends_at": override["ends_at"]}] if override["eligible"] else [])
        else:
            windows = [item for item in cast(list[dict[str, object]], settings["windows"]) if local_day.isoweekday() in cast(list[int], item["weekdays"])]
        spent = -int(connection.execute(f"SELECT COALESCE(SUM(amount_minutes), 0) FROM {PREFIX}ledger WHERE local_date = ? AND kind IN ('spend', 'refund')", (local_day.isoformat(),)).fetchone()[0])
        return {"school_day": school_day, "cap_minutes": cap, "spent_minutes": spent, "remaining_cap_minutes": max(0, cap - spent), "windows": windows}

    def snapshot(self, local_day: date | None = None) -> dict[str, object]:
        with self.storage.connect() as connection:
            row = self._state(connection)
            settings = self._settings(row)
            day = local_day or datetime.now(UTC).astimezone(ZoneInfo(cast(str, settings["timezone"]))).date()
            completions = {item["task_id"]: item["active_award_entry_id"] for item in connection.execute(f"SELECT task_id, active_award_entry_id FROM {PREFIX}completions WHERE local_date = ?", (day.isoformat(),)).fetchall()}
            tasks = [{**task, "completed": completions.get(task["id"]) is not None, "award_entry_id": completions.get(task["id"])} for task in cast(list[dict[str, object]], settings["tasks"])]
            overrides = [dict(item) for item in connection.execute(f"SELECT * FROM {PREFIX}overrides ORDER BY local_date").fetchall()]
            ledger = [dict(item) for item in connection.execute(f"SELECT entry_id, local_date, kind, amount_minutes, task_id, reverses_entry_id, note, actor, occurred_at FROM {PREFIX}ledger ORDER BY occurred_at DESC, entry_id DESC LIMIT 100").fetchall()]
            return {"schema_version": "mission-control.family-rewards-snapshot/v1", "revision": _revision(row), "local_date": day.isoformat(), "balance_minutes": self._balance(connection), "settings": settings, "tasks": tasks, "effective_day": self._effective_day(connection, day, settings), "overrides": overrides, "ledger": ledger}

    def execute(self, command: Mapping[str, object], actor: str) -> dict[str, object]:
        fingerprint = hashlib.sha256(_canonical(command).encode()).hexdigest()
        command_id = cast(str, command["command_id"])
        with self.storage.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            receipt = connection.execute(f"SELECT command_fingerprint, result_json FROM {PREFIX}command_receipts WHERE command_id = ?", (command_id,)).fetchone()
            if receipt is not None:
                if receipt["command_fingerprint"] != fingerprint:
                    raise RewardsError("command-id-conflict", "That command id was already used for a different request.")
                return cast(dict[str, object], json.loads(receipt["result_json"]))
            state = self._state(connection)
            if command["expected_revision"] != _revision(state):
                raise RewardsError("stale-revision", _revision(state))
            arguments = command.get("arguments")
            if not isinstance(arguments, Mapping):
                raise RewardsError("invalid-arguments", "Command arguments must be an object.")
            operation = command["command"]
            if operation == "award-task":
                result = self._award(connection, command_id, arguments, actor, state)
            elif operation == "reverse-entry":
                result = self._reverse(connection, command_id, arguments, actor, state)
            elif operation == "spend-credit":
                result = self._spend(connection, command_id, arguments, actor, state)
            elif operation == "update-settings":
                result = self._update_settings(connection, arguments, state)
            elif operation == "set-date-override":
                result = self._set_override(connection, arguments, state)
            elif operation == "remove-date-override":
                result = self._remove_override(connection, arguments, state)
            else:
                raise RewardsError("unknown-command", "Family rewards does not support that command.")
            new_revision = f"r{state['revision'] + 1}"
            outcome = {"schema_version": "mission-control.command-result/v1", "command_id": command_id, "target": command["target"], "status": "accepted", "revision": new_revision, "result": result}
            connection.execute(f"INSERT INTO {PREFIX}command_receipts(command_id, command_fingerprint, result_json, created_at) VALUES (?, ?, ?, ?)", (command_id, fingerprint, _canonical(outcome), _now()))
            return outcome

    def lookup(self, command: Mapping[str, object]) -> dict[str, object] | None:
        """Look up an exact committed request without applying it again."""

        fingerprint = hashlib.sha256(_canonical(command).encode()).hexdigest()
        with self.storage.connect() as connection:
            receipt = connection.execute(
                f"SELECT command_fingerprint, result_json FROM {PREFIX}command_receipts WHERE command_id = ?",
                (command["command_id"],),
            ).fetchone()
        if receipt is None:
            return None
        if receipt["command_fingerprint"] != fingerprint:
            return {
                "schema_version": "mission-control.command-result/v1",
                "command_id": command["command_id"],
                "target": command["target"],
                "status": "rejected",
                "error": {
                    "code": "command-id-conflict",
                    "detail": "That command id was already used for a different request.",
                },
            }
        return cast(dict[str, object], json.loads(receipt["result_json"]))

    def _bump(self, connection: sqlite3.Connection, state: sqlite3.Row) -> None:
        changed = connection.execute(f"UPDATE {PREFIX}state SET revision = revision + 1, updated_at = ? WHERE singleton = 1 AND revision = ?", (_now(), state["revision"]))
        if changed.rowcount != 1:
            raise RewardsError("stale-revision", self.revision())

    def _award(self, connection: sqlite3.Connection, command_id: str, arguments: Mapping[str, object], actor: str, state: sqlite3.Row) -> dict[str, object]:
        if set(arguments) != {"local_date", "task_id"}:
            raise RewardsError("invalid-arguments", "award-task requires local_date and task_id.")
        day = _parse_date(arguments["local_date"])
        settings = self._settings(state)
        task = next((item for item in cast(list[dict[str, object]], settings["tasks"]) if item["id"] == arguments["task_id"]), None)
        if task is None:
            raise RewardsError("unknown-task", "Morning task not found.")
        existing = connection.execute(f"SELECT active_award_entry_id FROM {PREFIX}completions WHERE local_date = ? AND task_id = ?", (day.isoformat(), task["id"])).fetchone()
        if existing is not None and existing[0] is not None:
            raise RewardsError("already-awarded", "That task is already checked for this date.")
        entry_id = f"entry-{uuid4()}"
        connection.execute(f"INSERT INTO {PREFIX}ledger(entry_id, command_id, local_date, kind, amount_minutes, task_id, note, actor, occurred_at) VALUES (?, ?, ?, 'earn', ?, ?, ?, ?, ?)", (entry_id, command_id, day.isoformat(), task["minutes"], task["id"], cast(str, task["label"]), actor, _now()))
        connection.execute(f"INSERT INTO {PREFIX}completions(local_date, task_id, active_award_entry_id) VALUES (?, ?, ?) ON CONFLICT(local_date, task_id) DO UPDATE SET active_award_entry_id = excluded.active_award_entry_id", (day.isoformat(), task["id"], entry_id))
        self._bump(connection, state)
        return {"entry_id": entry_id, "balance_minutes": self._balance(connection)}

    def _spend(self, connection: sqlite3.Connection, command_id: str, arguments: Mapping[str, object], actor: str, state: sqlite3.Row) -> dict[str, object]:
        if set(arguments) != {"local_date", "minutes", "note"}:
            raise RewardsError("invalid-arguments", "spend-credit requires local_date, minutes, and note.")
        day = _parse_date(arguments["local_date"])
        minutes, note = arguments["minutes"], arguments["note"]
        if type(minutes) is not int or not 1 <= minutes <= 1440 or not isinstance(note, str) or len(note) > 240:
            raise RewardsError("invalid-spend", "Spend minutes must be 1 to 1440 and note at most 240 characters.")
        balance = self._balance(connection)
        if minutes > balance:
            raise RewardsError("insufficient-balance", "There is not enough earned credit for that redemption.")
        effective = self._effective_day(connection, day, self._settings(state))
        if not effective["windows"]:
            raise RewardsError("date-not-eligible", "That date has no eligible play window.")
        if minutes > effective["remaining_cap_minutes"]:
            raise RewardsError("daily-cap-exceeded", "That redemption would exceed the effective daily play cap.")
        entry_id = f"entry-{uuid4()}"
        connection.execute(f"INSERT INTO {PREFIX}ledger(entry_id, command_id, local_date, kind, amount_minutes, note, actor, occurred_at) VALUES (?, ?, ?, 'spend', ?, ?, ?, ?)", (entry_id, command_id, day.isoformat(), -minutes, note.strip(), actor, _now()))
        self._bump(connection, state)
        return {"entry_id": entry_id, "balance_minutes": self._balance(connection)}

    def _reverse(self, connection: sqlite3.Connection, command_id: str, arguments: Mapping[str, object], actor: str, state: sqlite3.Row) -> dict[str, object]:
        if set(arguments) != {"entry_id", "note"} or not isinstance(arguments["entry_id"], str) or not isinstance(arguments["note"], str) or len(arguments["note"]) > 240:
            raise RewardsError("invalid-arguments", "reverse-entry requires entry_id and note.")
        original = connection.execute(f"SELECT * FROM {PREFIX}ledger WHERE entry_id = ?", (arguments["entry_id"],)).fetchone()
        if original is None or original["kind"] not in {"earn", "spend"}:
            raise RewardsError("entry-not-reversible", "Only an original earning or redemption can be reversed.")
        if connection.execute(f"SELECT 1 FROM {PREFIX}ledger WHERE reverses_entry_id = ?", (original["entry_id"],)).fetchone() is not None:
            raise RewardsError("already-reversed", "That ledger entry already has a reversal.")
        amount = -original["amount_minutes"]
        if self._balance(connection) + amount < 0:
            raise RewardsError("negative-balance", "This correction would create debt; refund spending first.")
        kind = "reversal" if original["kind"] == "earn" else "refund"
        entry_id = f"entry-{uuid4()}"
        connection.execute(f"INSERT INTO {PREFIX}ledger(entry_id, command_id, local_date, kind, amount_minutes, reverses_entry_id, note, actor, occurred_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (entry_id, command_id, original["local_date"], kind, amount, original["entry_id"], cast(str, arguments["note"]).strip(), actor, _now()))
        if original["kind"] == "earn":
            connection.execute(f"UPDATE {PREFIX}completions SET active_award_entry_id = NULL WHERE local_date = ? AND task_id = ? AND active_award_entry_id = ?", (original["local_date"], original["task_id"], original["entry_id"]))
        self._bump(connection, state)
        return {"entry_id": entry_id, "balance_minutes": self._balance(connection)}

    def _update_settings(self, connection: sqlite3.Connection, arguments: Mapping[str, object], state: sqlite3.Row) -> dict[str, object]:
        if set(arguments) != {"settings"}:
            raise RewardsError("invalid-arguments", "update-settings requires one settings object.")
        settings = _validate_settings(arguments["settings"])
        connection.execute(f"UPDATE {PREFIX}state SET timezone = ?, school_day_cap_minutes = ?, non_school_day_cap_minutes = ?, tasks_json = ?, windows_json = ? WHERE singleton = 1", (settings["timezone"], settings["school_day_cap_minutes"], settings["non_school_day_cap_minutes"], _canonical(settings["tasks"]), _canonical(settings["windows"])))
        self._bump(connection, state)
        return {"updated": True}

    def _set_override(self, connection: sqlite3.Connection, arguments: Mapping[str, object], state: sqlite3.Row) -> dict[str, object]:
        if set(arguments) != {"local_date", "school_day", "eligible", "starts_at", "ends_at", "note"}:
            raise RewardsError("invalid-arguments", "set-date-override requires the complete override object.")
        day = _parse_date(arguments["local_date"])
        school_day, eligible = arguments["school_day"], arguments["eligible"]
        starts_at, ends_at, note = arguments["starts_at"], arguments["ends_at"], arguments["note"]
        if school_day is not None and type(school_day) is not bool or type(eligible) is not bool or not isinstance(note, str) or len(note) > 160:
            raise RewardsError("invalid-override", "Override values are invalid.")
        if eligible:
            try:
                start, end = time.fromisoformat(cast(str, starts_at)), time.fromisoformat(cast(str, ends_at))
            except (TypeError, ValueError) as error:
                raise RewardsError("invalid-override", "Eligible overrides require HH:MM start and end times.") from error
            if start >= end:
                raise RewardsError("invalid-override", "Override end must be after its start.")
        else:
            starts_at = ends_at = None
        exists = connection.execute(
            f"SELECT 1 FROM {PREFIX}overrides WHERE local_date = ?",
            (day.isoformat(),),
        ).fetchone()
        count = connection.execute(f"SELECT COUNT(*) FROM {PREFIX}overrides").fetchone()[0]
        if exists is None and count >= 16:
            raise RewardsError(
                "override-limit",
                "At most 16 date overrides are retained; remove an old override first.",
            )
        connection.execute(f"INSERT INTO {PREFIX}overrides(local_date, school_day, eligible, starts_at, ends_at, note) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(local_date) DO UPDATE SET school_day=excluded.school_day, eligible=excluded.eligible, starts_at=excluded.starts_at, ends_at=excluded.ends_at, note=excluded.note", (day.isoformat(), school_day, eligible, starts_at, ends_at, note.strip()))
        self._bump(connection, state)
        return {"local_date": day.isoformat()}

    def _remove_override(self, connection: sqlite3.Connection, arguments: Mapping[str, object], state: sqlite3.Row) -> dict[str, object]:
        if set(arguments) != {"local_date"}:
            raise RewardsError("invalid-arguments", "remove-date-override requires local_date.")
        day = _parse_date(arguments["local_date"])
        if connection.execute(f"DELETE FROM {PREFIX}overrides WHERE local_date = ?", (day.isoformat(),)).rowcount != 1:
            raise RewardsError("override-not-found", "Date override not found.")
        self._bump(connection, state)
        return {"local_date": day.isoformat()}
