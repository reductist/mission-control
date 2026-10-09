"""Plugin-owned durable state and projections for home-search research."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final
from uuid import uuid4

from mission_control.agenda import (
    Action,
    ActionState,
    AgendaContribution,
    AgendaSchemaVersion,
    AnytimeTiming,
    Initiative,
    InitiativeState,
    ProviderRef,
    SourceRef,
)
from mission_control.builtin_plugins.home_search.capabilities import (
    IMPORT_SNAPSHOT,
    SET_REVIEW_STATUS,
)
from mission_control.builtin_plugins.home_search.domain import (
    Candidate,
    ReviewStatus,
    SearchSnapshot,
    parse_snapshot,
)
from mission_control.plugin_api import PluginStorage
from mission_control.plugins import PluginId

PLUGIN_ID: Final = PluginId("home-search")
SEARCH_ID: Final = "reading-ma-01867"


class StaleHomeSearchRevisionError(ValueError):
    def __init__(self, current_revision: str) -> None:
        self.current_revision = current_revision
        super().__init__("Home-search revision is stale")


class SnapshotRevisionConflictError(ValueError):
    """One source revision was reused for different snapshot contents."""


class SnapshotFreshnessRegressionError(ValueError):
    """A new source revision claims an older check than the current snapshot."""


@dataclass(frozen=True, slots=True)
class SearchState:
    version: int
    source_revision: str | None
    snapshot_json: str | None
    last_checked_at: datetime | None
    imported_at: datetime | None

    @property
    def revision(self) -> str:
        return str(self.version)


@dataclass(frozen=True, slots=True)
class CandidateRecord:
    candidate: Candidate
    review_status: ReviewStatus
    current: bool
    last_seen_checked_at: datetime
    version: int
    first_seen_at: datetime
    updated_at: datetime

    @property
    def revision(self) -> str:
        return str(self.version)


@dataclass(frozen=True, slots=True)
class HomeSearchEvent:
    sequence: int
    event_id: str
    entity_type: str
    entity_id: str
    event_type: str
    payload: dict[str, object]
    occurred_at: datetime


class SQLiteHomeSearchRepository:
    def __init__(self, storage: PluginStorage) -> None:
        self.storage = storage
        self.state_table = storage.table_name("state")
        self.candidate_table = storage.table_name("candidates")
        self.event_table = storage.table_name("events")
        self.import_table = storage.table_name("imports")

    def get_state(self) -> SearchState:
        with self.storage.connect() as connection:
            row = connection.execute(
                f"SELECT * FROM {self.state_table} WHERE singleton_id = 1"
            ).fetchone()
        if row is None:
            raise RuntimeError("home-search state row is missing")
        return self._state(row)

    def list_candidates(self, *, current_only: bool = True) -> tuple[CandidateRecord, ...]:
        where = "WHERE current = 1" if current_only else ""
        with self.storage.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM {self.candidate_table} {where} "
                "ORDER BY CASE review_status "
                "WHEN 'shortlisted' THEN 0 WHEN 'unreviewed' THEN 1 ELSE 2 END, "
                "updated_at DESC, candidate_id"
            ).fetchall()
        return tuple(self._candidate(row) for row in rows)

    def get_candidate(self, candidate_id: str) -> CandidateRecord:
        with self.storage.connect() as connection:
            row = connection.execute(
                f"SELECT * FROM {self.candidate_table} WHERE candidate_id = ?",
                (candidate_id,),
            ).fetchone()
        if row is None:
            raise KeyError(candidate_id)
        return self._candidate(row)

    def import_snapshot(
        self,
        snapshot: SearchSnapshot,
        *,
        expected_revision: str,
    ) -> tuple[SearchState, bool]:
        """Atomically replace the current result set, preserving review decisions."""

        snapshot_json = json.dumps(
            snapshot.to_dict(), sort_keys=True, separators=(",", ":")
        )
        snapshot_hash = hashlib.sha256(snapshot_json.encode()).hexdigest()
        imported_at = datetime.now(UTC)
        with self.storage.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                f"SELECT * FROM {self.state_table} WHERE singleton_id = 1"
            ).fetchone()
            state = self._state(row)
            if state.revision != expected_revision:
                raise StaleHomeSearchRevisionError(state.revision)
            imported = connection.execute(
                f"SELECT snapshot_hash FROM {self.import_table} "
                "WHERE source_revision = ?",
                (snapshot.revision,),
            ).fetchone()
            if imported is not None:
                if imported["snapshot_hash"] == snapshot_hash:
                    return state, False
                raise SnapshotRevisionConflictError(
                    "snapshot revision already identifies different contents"
                )
            if (
                state.last_checked_at is not None
                and snapshot.checked_at < state.last_checked_at
            ):
                raise SnapshotFreshnessRegressionError(
                    "snapshot checked_at precedes the current source check"
                )

            candidate_ids = [candidate.candidate_id for candidate in snapshot.candidates]
            if candidate_ids:
                placeholders = ",".join("?" for _ in candidate_ids)
                connection.execute(
                    f"UPDATE {self.candidate_table} SET current = 0, "
                    "version = version + 1, updated_at = ? WHERE current = 1 "
                    f"AND candidate_id NOT IN ({placeholders})",
                    (imported_at.isoformat(), *candidate_ids),
                )
            else:
                connection.execute(
                    f"UPDATE {self.candidate_table} SET current = 0, "
                    "version = version + 1, updated_at = ? WHERE current = 1",
                    (imported_at.isoformat(),),
                )
            for candidate in snapshot.candidates:
                self._upsert_candidate(
                    connection, candidate, snapshot.checked_at, imported_at
                )
            connection.execute(
                f"UPDATE {self.state_table} SET version = version + 1, "
                "source_revision = ?, snapshot_json = ?, last_checked_at = ?, "
                "imported_at = ? WHERE singleton_id = 1",
                (
                    snapshot.revision,
                    snapshot_json,
                    snapshot.checked_at.isoformat(),
                    imported_at.isoformat(),
                ),
            )
            self._insert_event(
                connection,
                "search",
                SEARCH_ID,
                "home-search.snapshot-imported",
                {
                    "source_revision": snapshot.revision,
                    "candidate_count": len(snapshot.candidates),
                    "checked_at": snapshot.checked_at.isoformat(),
                },
                imported_at,
            )
            connection.execute(
                f"INSERT INTO {self.import_table}(source_revision, snapshot_hash, "
                "checked_at, imported_at) VALUES (?, ?, ?, ?)",
                (
                    snapshot.revision,
                    snapshot_hash,
                    snapshot.checked_at.isoformat(),
                    imported_at.isoformat(),
                ),
            )
            updated = connection.execute(
                f"SELECT * FROM {self.state_table} WHERE singleton_id = 1"
            ).fetchone()
        return self._state(updated), True

    def set_review_status(
        self,
        candidate_id: str,
        status: ReviewStatus,
        *,
        expected_revision: str,
    ) -> CandidateRecord:
        occurred_at = datetime.now(UTC)
        with self.storage.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                f"SELECT * FROM {self.candidate_table} WHERE candidate_id = ?",
                (candidate_id,),
            ).fetchone()
            if row is None:
                raise KeyError(candidate_id)
            current = self._candidate(row)
            if current.revision != expected_revision:
                raise StaleHomeSearchRevisionError(current.revision)
            if current.review_status is status:
                return current
            connection.execute(
                f"UPDATE {self.candidate_table} SET review_status = ?, "
                "version = version + 1, updated_at = ? WHERE candidate_id = ?",
                (status.value, occurred_at.isoformat(), candidate_id),
            )
            connection.execute(
                f"UPDATE {self.state_table} SET version = version + 1 "
                "WHERE singleton_id = 1"
            )
            self._insert_event(
                connection,
                "candidate",
                candidate_id,
                "home-search.review-status-changed",
                {"from": current.review_status.value, "to": status.value},
                occurred_at,
            )
            updated = connection.execute(
                f"SELECT * FROM {self.candidate_table} WHERE candidate_id = ?",
                (candidate_id,),
            ).fetchone()
        return self._candidate(updated)

    def history(self, entity_type: str, entity_id: str) -> tuple[HomeSearchEvent, ...]:
        with self.storage.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM {self.event_table} "
                "WHERE entity_type = ? AND entity_id = ? ORDER BY sequence",
                (entity_type, entity_id),
            ).fetchall()
        return tuple(
            HomeSearchEvent(
                sequence=row["sequence"],
                event_id=row["event_id"],
                entity_type=row["entity_type"],
                entity_id=row["entity_id"],
                event_type=row["event_type"],
                payload=json.loads(row["payload_json"]),
                occurred_at=datetime.fromisoformat(row["occurred_at"]),
            )
            for row in rows
        )

    def agenda_contribution(self, *, generated_at: datetime) -> AgendaContribution:
        state = self.get_state()
        candidates = self.list_candidates()
        if state.last_checked_at is None:
            detail = (
                "No research snapshot has been imported. Budget is provisional and unset "
                "pending mortgage reconciliation; the daily watcher is not active."
            )
        else:
            verified = sum(
                item.candidate.verification_status == "verified" for item in candidates
            )
            detail = (
                f"{len(candidates)} current candidates ({verified} verified). "
                f"Sources last checked {state.last_checked_at.isoformat()}. Budget remains "
                "unset and the daily watcher remains inactive."
            )
        entries: list[Initiative | Action] = [
            Initiative(
                entry_id=SEARCH_ID,
                source=SourceRef(PLUGIN_ID, "search", SEARCH_ID),
                title="Reading home purchase search",
                state=(
                    InitiativeState.OPEN
                    if state.last_checked_at is not None
                    else InitiativeState.WAITING
                ),
                context="Reading, MA 01867 · purchase budget not set",
                detail=detail,
                revision=state.revision,
                affordances=(IMPORT_SNAPSHOT,),
            )
        ]
        entries.extend(self._candidate_action(item) for item in candidates)
        digest = hashlib.sha256(
            "|".join(
                [state.revision, *(item.revision for item in candidates)]
            ).encode()
        ).hexdigest()[:16]
        return AgendaContribution(
            AgendaSchemaVersion.V2,
            ProviderRef(PLUGIN_ID),
            f"home-search-{digest}",
            generated_at,
            tuple(entries),
        )

    @staticmethod
    def _candidate_action(item: CandidateRecord) -> Action:
        candidate = item.candidate
        state = {
            ReviewStatus.UNREVIEWED: ActionState.WAITING,
            ReviewStatus.SHORTLISTED: ActionState.READY,
            ReviewStatus.REJECTED: ActionState.BLOCKED,
        }[item.review_status]
        cost = (
            f"${candidate.estimated_all_in.amount:,} estimated all-in"
            if candidate.estimated_all_in.amount is not None
            else "all-in cost not yet estimated"
        )
        return Action(
            entry_id=candidate.candidate_id,
            source=SourceRef(PLUGIN_ID, "candidate", candidate.candidate_id),
            title=candidate.address,
            state=state,
            timing=AnytimeTiming(),
            context=(
                f"{item.review_status.value} · {candidate.verification_status} · "
                f"{candidate.listing_status}"
            ),
            detail=f"{cost}. {candidate.why_fit[0]}",
            revision=item.revision,
            affordances=(SET_REVIEW_STATUS,),
        )

    def _upsert_candidate(
        self,
        connection: sqlite3.Connection,
        candidate: Candidate,
        checked_at: datetime,
        occurred_at: datetime,
    ) -> None:
        document_json = json.dumps(
            candidate.to_dict(), sort_keys=True, separators=(",", ":")
        )
        existing = connection.execute(
            f"SELECT * FROM {self.candidate_table} WHERE candidate_id = ?",
            (candidate.candidate_id,),
        ).fetchone()
        if existing is None:
            connection.execute(
                f"INSERT INTO {self.candidate_table}(candidate_id, document_json, "
                "review_status, current, last_seen_checked_at, version, first_seen_at, "
                "updated_at) VALUES (?, ?, 'unreviewed', 1, ?, 1, ?, ?)",
                (
                    candidate.candidate_id,
                    document_json,
                    checked_at.isoformat(),
                    occurred_at.isoformat(),
                    occurred_at.isoformat(),
                ),
            )
            event_type = "home-search.candidate-discovered"
        else:
            connection.execute(
                f"UPDATE {self.candidate_table} SET document_json = ?, current = 1, "
                "last_seen_checked_at = ?, version = version + 1, updated_at = ? "
                "WHERE candidate_id = ?",
                (
                    document_json,
                    checked_at.isoformat(),
                    occurred_at.isoformat(),
                    candidate.candidate_id,
                ),
            )
            event_type = "home-search.candidate-updated"
        self._insert_event(
            connection,
            "candidate",
            candidate.candidate_id,
            event_type,
            {"source_url": candidate.source_url},
            occurred_at,
        )

    def _insert_event(
        self,
        connection: sqlite3.Connection,
        entity_type: str,
        entity_id: str,
        event_type: str,
        payload: dict[str, object],
        occurred_at: datetime,
    ) -> None:
        connection.execute(
            f"INSERT INTO {self.event_table}(event_id, entity_type, entity_id, "
            "event_type, payload_json, occurred_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                uuid4().hex,
                entity_type,
                entity_id,
                event_type,
                json.dumps(payload, sort_keys=True, separators=(",", ":")),
                occurred_at.isoformat(),
            ),
        )

    @staticmethod
    def _state(row: sqlite3.Row) -> SearchState:
        return SearchState(
            version=row["version"],
            source_revision=row["source_revision"],
            snapshot_json=row["snapshot_json"],
            last_checked_at=(
                datetime.fromisoformat(row["last_checked_at"])
                if row["last_checked_at"] is not None
                else None
            ),
            imported_at=(
                datetime.fromisoformat(row["imported_at"])
                if row["imported_at"] is not None
                else None
            ),
        )

    @staticmethod
    def _candidate(row: sqlite3.Row) -> CandidateRecord:
        return CandidateRecord(
            candidate=parse_snapshot(
                {
                    "schema_version": "mission-control.home-search-snapshot/v1",
                    "revision": "persisted-candidate",
                    "checked_at": "2000-01-01T00:00:00+00:00",
                    "sources": [json.loads(row["document_json"])["source_url"]],
                    "candidates": [json.loads(row["document_json"])],
                }
            ).candidates[0],
            review_status=ReviewStatus(row["review_status"]),
            current=bool(row["current"]),
            last_seen_checked_at=datetime.fromisoformat(row["last_seen_checked_at"]),
            version=row["version"],
            first_seen_at=datetime.fromisoformat(row["first_seen_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
