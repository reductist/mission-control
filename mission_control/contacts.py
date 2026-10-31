"""Core persistence for standards-native JSContact cards."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from typing import Any, Mapping
from uuid import uuid4

from mission_control.database import Database
from mission_control.portable_records import parse_portable_record


class StaleContactRevisionError(ValueError):
    """The stored contact changed after the caller loaded it."""


def _utc_now() -> str:
    value = datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    head, fraction = value[:-1].split(".", 1)
    fraction = fraction.rstrip("0")
    return f"{head}.{fraction}Z" if fraction else f"{head}Z"


class ContactRepository:
    """Persist complete portable contact envelopes without flattening JSContact."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def list(self) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT record_json FROM contacts ORDER BY updated_at DESC, id"
            ).fetchall()
        return [json.loads(row["record_json"]) for row in rows]

    def get(self, contact_id: str) -> dict[str, Any]:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT record_json FROM contacts WHERE id = ?", (contact_id,)
            ).fetchone()
        if row is None:
            raise KeyError(contact_id)
        return json.loads(row["record_json"])

    def create(self, card: Mapping[str, Any]) -> dict[str, Any]:
        contact_id = str(uuid4())
        standard_uid = f"urn:uuid:{uuid4()}"
        now = _utc_now()
        detached = json.loads(json.dumps(card, allow_nan=False))
        detached.setdefault("@type", "Card")
        detached.setdefault("version", "2.0")
        detached.setdefault("uid", standard_uid)
        detached.setdefault("created", now)
        detached["updated"] = now
        envelope = self._envelope(contact_id, detached, revision=1, observed_at=now)
        with self.database.connect() as connection:
            connection.execute(
                "INSERT INTO contacts(id, record_json, revision, created_at, updated_at) "
                "VALUES (?, ?, 1, ?, ?)",
                (contact_id, self._encode(envelope), now, now),
            )
        return envelope

    def update(
        self,
        contact_id: str,
        card: Mapping[str, Any],
        *,
        expected_revision: str,
    ) -> dict[str, Any]:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT record_json, revision, created_at FROM contacts WHERE id = ?",
                (contact_id,),
            ).fetchone()
            if row is None:
                raise KeyError(contact_id)
            current = json.loads(row["record_json"])
            revision = int(row["revision"])
            if expected_revision != str(revision):
                raise StaleContactRevisionError("contact revision is stale")

            detached = json.loads(json.dumps(card, allow_nan=False))
            detached.setdefault("@type", "Card")
            detached.setdefault("version", "2.0")
            previous_card = current["record"]
            if detached.get("uid") != previous_card.get("uid"):
                raise ValueError("record.uid cannot be changed")
            if detached.get("created") != previous_card.get("created"):
                raise ValueError("record.created cannot be changed")
            now = _utc_now()
            detached["updated"] = now
            next_revision = revision + 1
            envelope = self._envelope(
                contact_id,
                detached,
                revision=next_revision,
                observed_at=now,
            )
            changed = connection.execute(
                "UPDATE contacts SET record_json = ?, revision = ?, updated_at = ? "
                "WHERE id = ? AND revision = ?",
                (
                    self._encode(envelope),
                    next_revision,
                    now,
                    contact_id,
                    revision,
                ),
            ).rowcount
            if changed != 1:
                raise StaleContactRevisionError("contact revision is stale")
        return envelope

    @staticmethod
    def _envelope(
        contact_id: str,
        card: Mapping[str, Any],
        *,
        revision: int,
        observed_at: str,
    ) -> dict[str, Any]:
        return parse_portable_record(
            {
                "schema_version": "mission-control.portable-record/v1",
                "record_id": f"contact-{contact_id}",
                "kind": "contact",
                "standard": {
                    "name": "jscontact",
                    "version": "2.0",
                    "profile": "mission-control.jscontact/v1",
                },
                "source": {
                    "plugin_id": "core",
                    "entity_type": "contact",
                    "entity_id": contact_id,
                },
                "revision": str(revision),
                "observed_at": observed_at,
                "record": dict(card),
                "mc": {},
            }
        )

    @staticmethod
    def _encode(envelope: Mapping[str, Any]) -> str:
        return json.dumps(
            envelope,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
