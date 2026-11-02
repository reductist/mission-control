"""Family rewards plugin using standard agenda, detail, and command contracts."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, time
from typing import cast
from zoneinfo import ZoneInfo

from mission_control.builtin_plugins.family_rewards.repository import (
    ACCOUNT_ID,
    RewardsError,
    RewardsRepository,
)
from mission_control.plugin_api import CapabilityRouter, PluginContext

PLUGIN_ID = "family-rewards"
ACCOUNT_SOURCE = {"plugin_id": PLUGIN_ID, "entity_type": "account", "entity_id": ACCOUNT_ID}
AFFORDANCES = [
    {"capability": "entity.annotate", "command": "add-note"},
    {"capability": "family-rewards.task.award", "command": "award-task"},
    {"capability": "family-rewards.ledger.reverse", "command": "reverse-entry"},
    {"capability": "family-rewards.credit.spend", "command": "spend-credit"},
    {"capability": "family-rewards.settings.update", "command": "update-settings"},
    {"capability": "family-rewards.override.set", "command": "set-date-override"},
    {"capability": "family-rewards.override.remove", "command": "remove-date-override"},
]


def activate(context: PluginContext) -> CapabilityRouter:
    if context.plugin_id != PLUGIN_ID or context.credentials or context.agenda_seed is not None:
        raise ValueError("Family rewards received unsupported activation resources")
    repository = RewardsRepository(context.storage, context.configuration)

    def agenda_snapshot(inputs: Mapping[str, object]) -> object:
        generated_at = datetime.fromisoformat(cast(str, inputs["generated_at"]))
        snapshot = repository.snapshot(repository.local_today(generated_at))
        entries: list[dict[str, object]] = [{
            "id": ACCOUNT_ID, "source": ACCOUNT_SOURCE, "kind": "initiative",
            "title": "Family play credit", "state": "open",
            "context": f"{snapshot['balance_minutes']} minutes available",
            "detail": "Parent-operated rewards; earned credit carries over without expiry or debt.",
            "revision": snapshot["revision"], "affordances": AFFORDANCES,
            "attribution": {"principal_ids": []},
        }]
        for task in cast(list[dict[str, object]], snapshot["tasks"]):
            task_id = cast(str, task["id"])
            entries.append({
                "id": f"morning:{snapshot['local_date']}:{task_id}",
                "source": {"plugin_id": PLUGIN_ID, "entity_type": "routine-task", "entity_id": f"morning:{snapshot['local_date']}:{task_id}"},
                "kind": "action", "title": task["label"], "state": "ready",
                "timing": {"kind": "due-on", "due_on": snapshot["local_date"]},
                "context": "Checked" if task["completed"] else "Morning routine",
                "detail": f"{task['minutes']} minutes earned independently; reminders and parent support count.",
                "revision": snapshot["revision"], "affordances": [], "attribution": {"principal_ids": []},
            })
        timezone = ZoneInfo(cast(str, cast(dict[str, object], snapshot["settings"])["timezone"]))
        local_day = datetime.fromisoformat(cast(str, snapshot["local_date"]))
        for window in cast(list[dict[str, object]], cast(dict[str, object], snapshot["effective_day"])["windows"]):
            start = datetime.combine(local_day.date(), time.fromisoformat(cast(str, window["starts_at"])), timezone)
            end = datetime.combine(local_day.date(), time.fromisoformat(cast(str, window["ends_at"])), timezone)
            entries.append({
                "id": f"window:{snapshot['local_date']}:{window['id']}",
                "source": {"plugin_id": PLUGIN_ID, "entity_type": "play-window", "entity_id": f"window:{snapshot['local_date']}:{window['id']}"},
                "kind": "event", "title": window["label"],
                "timing": {"kind": "timed", "starts_at": start.isoformat(), "ends_at": end.isoformat()},
                "context": "Eligible play window", "detail": "Availability only; this first slice does not enforce devices or run a timer.",
                "revision": snapshot["revision"], "affordances": [], "attribution": {"principal_ids": []},
            })
        return {"schema_version": "mission-control.agenda/v2", "provider": {"plugin_id": PLUGIN_ID}, "revision": cast(str, snapshot["revision"]), "generated_at": generated_at.isoformat(), "entries": entries}

    def command_state(inputs: Mapping[str, object]) -> object:
        target = cast(Mapping[str, str], inputs["target"])
        if dict(target) != ACCOUNT_SOURCE:
            return None
        return {"schema_version": "mission-control.command-state/v1", "target": ACCOUNT_SOURCE, "revision": repository.revision(), "affordances": AFFORDANCES}

    def command_execute(inputs: Mapping[str, object]) -> object:
        command = cast(Mapping[str, object], inputs["command"])
        try:
            return repository.execute(command, cast(str, inputs["actor"]))
        except RewardsError as error:
            common = {"schema_version": "mission-control.command-result/v1", "command_id": command["command_id"], "target": command["target"]}
            if error.code == "stale-revision":
                return {**common, "status": "stale", "current_revision": error.detail, "error": {"code": error.code, "detail": "Family rewards changed after this view loaded; refresh before retrying."}}
            return {**common, "status": "rejected", "error": {"code": error.code, "detail": error.detail}}

    def command_lookup(inputs: Mapping[str, object]) -> object:
        return repository.lookup(cast(Mapping[str, object], inputs["command"]))

    def entity_details(inputs: Mapping[str, object]) -> object:
        target = cast(Mapping[str, str], inputs["target"])
        if target["plugin_id"] == PLUGIN_ID and target["entity_type"] == "routine-task":
            parts = target["entity_id"].split(":", 2)
            if len(parts) != 3 or parts[0] != "morning":
                return None
            try:
                day = datetime.fromisoformat(parts[1]).date()
            except ValueError:
                return None
            task = next((item for item in cast(list[dict[str, object]], repository.snapshot(day)["tasks"]) if item["id"] == parts[2]), None)
            if task is None:
                return None
            return {
                "schema_version": "mission-control.entity-detail/v1", "source": dict(target),
                "title": task["label"], "description": "One independently earnable morning task. Parent support and reminders count.",
                "state": "checked" if task["completed"] else "not-checked", "revision": repository.revision(),
                "affordances": [], "attributes": [
                    {"key": "local-date", "label": "Family date", "value": parts[1]},
                    {"key": "minutes", "label": "Earns", "value": f"{task['minutes']} minutes"},
                    {"key": "award-entry-id", "label": "Award entry", "value": task["award_entry_id"] or "none"},
                ], "activity": [],
            }
        if dict(target) != ACCOUNT_SOURCE:
            return None
        snapshot = repository.snapshot()
        activity = []
        for entry in reversed(cast(list[dict[str, object]], snapshot["ledger"])):
            minutes = cast(int, entry["amount_minutes"])
            label = {"earn": "Credit earned", "spend": "Credit redeemed", "reversal": "Earning corrected", "refund": "Redemption refunded"}[cast(str, entry["kind"])]
            activity.append({
                "activity_id": f"ledger:{entry['entry_id']}", "kind": "event", "activity_type": f"family-rewards.{entry['kind']}",
                "summary": f"{label}: {'+' if minutes > 0 else ''}{minutes} minutes",
                "body": "\n".join(filter(None, (
                    f"Date: {entry['local_date']}",
                    f"Task: {entry['task_id']}" if entry["task_id"] else None,
                    f"Reverses entry: {entry['reverses_entry_id']}" if entry["reverses_entry_id"] else None,
                    f"Note: {entry['note']}" if entry["note"] else None,
                ))),
                "actor": entry["actor"], "occurred_at": entry["occurred_at"],
            })
        reference_snapshot = {key: value for key, value in snapshot.items() if key not in {"settings", "overrides", "ledger"}}
        return {
            "schema_version": "mission-control.entity-detail/v1", "source": ACCOUNT_SOURCE,
            "title": "Family play credit", "description": "Parent-operated record of earned and redeemed play credit. Morning tasks are independent; there are no streaks, expiry, debt, or punitive deductions.",
            "state": "active", "revision": snapshot["revision"], "affordances": AFFORDANCES,
            "attributes": [
                {"key": "balance-minutes", "label": "Available credit", "value": f"{snapshot['balance_minutes']} minutes"},
                {"key": "local-date", "label": "Family date", "value": snapshot["local_date"]},
                {"key": "timezone", "label": "Timezone", "value": cast(dict[str, object], snapshot["settings"])["timezone"]},
                {"key": "rewards-snapshot", "label": "Reference-client snapshot", "value": json.dumps(reference_snapshot, sort_keys=True)},
                {"key": "rewards-settings", "label": "Reward settings", "value": json.dumps(snapshot["settings"], sort_keys=True)},
                {"key": "rewards-overrides", "label": "Date overrides", "value": json.dumps(snapshot["overrides"], sort_keys=True)},
            ],
            "activity": activity,
        }

    return CapabilityRouter(context.plugin_id, {"agenda.snapshot": agenda_snapshot, "commands.state": command_state, "commands.execute": command_execute, "commands.lookup": command_lookup, "entity-details.get": entity_details})
