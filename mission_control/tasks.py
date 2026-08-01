"""Task write and query operations."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final
from uuid import uuid4

from .database import Database

TASK_STATES: Final[tuple[str, ...]] = ("backlog", "ready", "in-progress", "done")
_UNSET: Final = object()


class StaleTaskRevisionError(ValueError):
    """A task changed after the caller read its projection."""

    def __init__(self, current_revision: str) -> None:
        super().__init__("task revision is stale")
        self.current_revision = current_revision


@dataclass(frozen=True)
class Task:
    id: str
    title: str
    description: str
    state: str
    blocked: bool
    waiting_on: str | None
    review_after: str | None
    created_at: str
    updated_at: str


class TaskRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create(self, title: str, description: str = "") -> Task:
        title = self._normalize_title(title)
        if not isinstance(description, str):
            raise TypeError("task description must be a string")

        now = datetime.now(UTC).isoformat()
        task_id = str(uuid4())
        event_id = str(uuid4())
        payload = {
            "title": title,
            "description": description,
            "state": "backlog",
            "blocked": False,
            "waiting_on": None,
            "review_after": None,
        }

        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO tasks(id, title, description, state, blocked, created_at, updated_at)
                VALUES (?, ?, ?, 'backlog', 0, ?, ?)
                """,
                (task_id, title, description, now, now),
            )
            connection.execute(
                """
                INSERT INTO task_events(event_id, task_id, event_type, payload_json, occurred_at)
                VALUES (?, ?, 'task.created', ?, ?)
                """,
                (event_id, task_id, json.dumps(payload, sort_keys=True), now),
            )
        return self.get(task_id)

    def update(
        self,
        task_id: str,
        *,
        title: str | object = _UNSET,
        description: str | object = _UNSET,
        state: str | object = _UNSET,
        blocked: bool | object = _UNSET,
        waiting_on: str | None | object = _UNSET,
        review_after: str | None | object = _UNSET,
        expected_revision: str | object = _UNSET,
    ) -> Task:
        """Update a task and append one event for material changes.

        ``None`` clears nullable fields; the private sentinel distinguishes clearing a
        field from leaving it untouched.
        """

        with self.database.connect() as connection:
            row = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if row is None:
                raise KeyError(task_id)
            current = self._task_from_row(row)

            if expected_revision is not _UNSET:
                if not isinstance(expected_revision, str):
                    raise TypeError("expected task revision must be a string")
                if expected_revision != current.updated_at:
                    raise StaleTaskRevisionError(current.updated_at)

            next_values: dict[str, object] = {
                "title": current.title,
                "description": current.description,
                "state": current.state,
                "blocked": current.blocked,
                "waiting_on": current.waiting_on,
                "review_after": current.review_after,
            }

            if title is not _UNSET:
                if not isinstance(title, str):
                    raise TypeError("task title must be a string")
                next_values["title"] = self._normalize_title(title)

            if description is not _UNSET:
                if not isinstance(description, str):
                    raise TypeError("task description must be a string")
                next_values["description"] = description

            if state is not _UNSET:
                if not isinstance(state, str):
                    raise TypeError("task state must be a string")
                if state not in TASK_STATES:
                    raise ValueError(f"unsupported task state: {state}")
                next_values["state"] = state

            if blocked is not _UNSET:
                if not isinstance(blocked, bool):
                    raise TypeError("task blocked status must be a boolean")
                next_values["blocked"] = blocked

            if waiting_on is not _UNSET:
                next_values["waiting_on"] = self._normalize_optional_text(
                    waiting_on, "waiting_on"
                )

            if review_after is not _UNSET:
                next_values["review_after"] = self._normalize_optional_text(
                    review_after, "review_after"
                )

            changes = {
                field: {"from": getattr(current, field), "to": value}
                for field, value in next_values.items()
                if getattr(current, field) != value
            }
            if not changes:
                return current

            now = datetime.now(UTC).isoformat()
            connection.execute(
                """
                UPDATE tasks
                SET title = ?, description = ?, state = ?, blocked = ?,
                    waiting_on = ?, review_after = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    next_values["title"],
                    next_values["description"],
                    next_values["state"],
                    int(bool(next_values["blocked"])),
                    next_values["waiting_on"],
                    next_values["review_after"],
                    now,
                    task_id,
                ),
            )
            connection.execute(
                """
                INSERT INTO task_events(event_id, task_id, event_type, payload_json, occurred_at)
                VALUES (?, ?, 'task.updated', ?, ?)
                """,
                (str(uuid4()), task_id, json.dumps({"changes": changes}, sort_keys=True), now),
            )

            updated_row = connection.execute(
                "SELECT * FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
            assert updated_row is not None
            updated = self._task_from_row(updated_row)

        return updated

    def get(self, task_id: str) -> Task:
        with self.database.connect() as connection:
            row = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            raise KeyError(task_id)
        return self._task_from_row(row)

    def list(self) -> list[Task]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM tasks ORDER BY created_at, id"
            ).fetchall()
        return [self._task_from_row(row) for row in rows]

    def history(self, task_id: str) -> list[dict[str, object]]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT sequence, event_id, event_type, payload_json, occurred_at "
                "FROM task_events WHERE task_id = ? ORDER BY sequence",
                (task_id,),
            ).fetchall()
        return [
            {
                "sequence": row["sequence"],
                "event_id": row["event_id"],
                "event_type": row["event_type"],
                "payload": json.loads(row["payload_json"]),
                "occurred_at": row["occurred_at"],
            }
            for row in rows
        ]

    @staticmethod
    def _normalize_title(title: str) -> str:
        if not isinstance(title, str):
            raise TypeError("task title must be a string")
        title = title.strip()
        if not title:
            raise ValueError("task title must not be empty")
        return title

    @staticmethod
    def _normalize_optional_text(value: str | None | object, field: str) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise TypeError(f"task {field} must be a string or null")
        return value.strip() or None

    @staticmethod
    def _task_from_row(row) -> Task:
        return Task(
            id=row["id"],
            title=row["title"],
            description=row["description"],
            state=row["state"],
            blocked=bool(row["blocked"]),
            waiting_on=row["waiting_on"],
            review_after=row["review_after"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
