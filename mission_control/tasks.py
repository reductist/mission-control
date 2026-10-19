"""Task write and query operations."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Final
from uuid import uuid4

from mission_control.database import Database
from mission_control.task_metadata import TASK_TAG_CATALOG, normalize_deadline, normalize_tags

TASK_STATES: Final[tuple[str, ...]] = (
    "backlog",
    "ready",
    "in-progress",
    "done",
    "canceled",
)
CLOSED_TASK_STATES: Final[frozenset[str]] = frozenset({"done", "canceled"})
_UNSET: Final = object()


class StaleTaskRevisionError(ValueError):
    """A task changed after the caller read its projection."""

    def __init__(self, current_revision: str) -> None:
        super().__init__("task revision is stale")
        self.current_revision = current_revision


class UnfinishedChildrenError(ValueError):
    """A parent was explicitly completed while it still has open children."""

    def __init__(self, child_ids: list[str]) -> None:
        super().__init__("parent task has unfinished children")
        self.child_ids = tuple(child_ids)


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
    deadline: dict[str, str] | None = None
    tags: list[str] = field(default_factory=list)
    parent_id: str | None = None
    sibling_order: int = 0


class TaskRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create(
        self,
        title: str,
        description: str = "",
        *,
        deadline: object = None,
        tags: object = _UNSET,
        parent_id: str | None = None,
    ) -> Task:
        title = self._normalize_title(title)
        if not isinstance(description, str):
            raise TypeError("task description must be a string")
        deadline = normalize_deadline(deadline)
        tags = normalize_tags([] if tags is _UNSET else tags)

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
            "deadline": deadline,
            "tags": tags,
            "parent_id": parent_id,
        }

        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._validate_parent(connection, task_id, parent_id, task_has_children=False)
            sibling_order = self._next_sibling_order(connection, parent_id)
            tags = self._canonicalize_tags(connection, tags)
            payload["tags"] = tags
            payload["sibling_order"] = sibling_order
            connection.execute(
                """
                INSERT INTO tasks(
                    id, title, description, state, blocked, created_at, updated_at,
                    deadline_json, tags_json, parent_id, sibling_order
                )
                VALUES (?, ?, ?, 'backlog', 0, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    title,
                    description,
                    now,
                    now,
                    json.dumps(deadline) if deadline is not None else None,
                    json.dumps(tags),
                    parent_id,
                    sibling_order,
                ),
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
        deadline: object = _UNSET,
        tags: object = _UNSET,
        parent_id: str | None | object = _UNSET,
        sibling_order: int | object = _UNSET,
    ) -> Task:
        """Update a task and append one event for material changes.

        ``None`` clears nullable fields; the private sentinel distinguishes clearing a
        field from leaving it untouched.
        """

        with self.database.connect() as connection:
            # Serialize the revision check and write: two editors must not both
            # accept the same revision after reading before either writes.
            connection.execute("BEGIN IMMEDIATE")
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
                "deadline": current.deadline,
                "tags": current.tags,
                "parent_id": current.parent_id,
                "sibling_order": current.sibling_order,
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

            if deadline is not _UNSET:
                next_values["deadline"] = normalize_deadline(deadline)
            if tags is not _UNSET:
                next_values["tags"] = self._canonicalize_tags(
                    connection, normalize_tags(tags)
                )

            target_parent = current.parent_id
            if parent_id is not _UNSET:
                if parent_id is not None and not isinstance(parent_id, str):
                    raise TypeError("task parent_id must be a string or null")
                target_parent = parent_id
                has_children = connection.execute(
                    "SELECT 1 FROM tasks WHERE parent_id = ? LIMIT 1", (task_id,)
                ).fetchone() is not None
                self._validate_parent(
                    connection,
                    task_id,
                    target_parent,
                    task_has_children=has_children,
                )
                next_values["parent_id"] = target_parent

            if sibling_order is not _UNSET:
                if not isinstance(sibling_order, int) or isinstance(sibling_order, bool):
                    raise TypeError("task sibling_order must be an integer")
                if sibling_order < 0:
                    raise ValueError("task sibling_order must not be negative")
                clause = "parent_id IS NULL" if target_parent is None else "parent_id = ?"
                parameters: tuple[object, ...] = () if target_parent is None else (target_parent,)
                count = connection.execute(
                    f"SELECT count(*) FROM tasks WHERE {clause} AND id <> ?",
                    (*parameters, task_id),
                ).fetchone()[0]
                next_values["sibling_order"] = min(sibling_order, count)
            elif target_parent != current.parent_id:
                next_values["sibling_order"] = self._next_sibling_order(
                    connection, target_parent, excluding=task_id
                )

            if next_values["state"] == "done" and current.state != "done":
                unfinished = [
                    row["id"]
                    for row in connection.execute(
                        "SELECT id FROM tasks WHERE parent_id = ? "
                        "AND state NOT IN ('done', 'canceled') ORDER BY sibling_order, id",
                        (task_id,),
                    ).fetchall()
                ]
                if unfinished:
                    raise UnfinishedChildrenError(unfinished)

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
                    waiting_on = ?, review_after = ?, updated_at = ?, deadline_json = ?,
                    tags_json = ?, parent_id = ?, sibling_order = ?
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
                    json.dumps(next_values["deadline"]) if next_values["deadline"] is not None else None,
                    json.dumps(next_values["tags"]),
                    next_values["parent_id"],
                    next_values["sibling_order"],
                    task_id,
                ),
            )
            if next_values["parent_id"] != current.parent_id:
                self._normalize_sibling_orders(
                    connection, current.parent_id, now=now, cause_task_id=task_id
                )
            if sibling_order is not _UNSET:
                self._place_at_order(
                    connection,
                    task_id,
                    next_values["parent_id"],
                    int(next_values["sibling_order"]),
                    now=now,
                )
            else:
                self._normalize_sibling_orders(
                    connection,
                    next_values["parent_id"],
                    now=now,
                    cause_task_id=task_id,
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
                "SELECT * FROM tasks ORDER BY parent_id IS NOT NULL, parent_id, sibling_order, created_at, id"
            ).fetchall()
        return [self._task_from_row(row) for row in rows]

    def progress(self, task_id: str) -> dict[str, int | bool]:
        """Return transport-neutral progress derived only from direct children."""

        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT state FROM tasks WHERE parent_id = ?", (task_id,)
            ).fetchall()
            parent = connection.execute(
                "SELECT state FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
        if parent is None:
            raise KeyError(task_id)
        total = len(rows)
        done = sum(row["state"] == "done" for row in rows)
        canceled = sum(row["state"] == "canceled" for row in rows)
        unfinished = total - done - canceled
        closed = done + canceled
        return {
            "total": total,
            "done": done,
            "canceled": canceled,
            "unfinished": unfinished,
            "closed": closed,
            "percent": round(closed * 100 / total) if total else 0,
            "ready_to_close": total > 0
            and unfinished == 0
            and parent["state"] not in CLOSED_TASK_STATES,
        }

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
    def _validate_parent(
        connection, task_id: str, parent_id: str | None, *, task_has_children: bool
    ) -> None:
        if parent_id is None:
            return
        if parent_id == task_id:
            raise ValueError("a task cannot be its own parent")
        parent = connection.execute(
            "SELECT parent_id FROM tasks WHERE id = ?", (parent_id,)
        ).fetchone()
        if parent is None:
            raise ValueError("task parent does not exist")
        if parent["parent_id"] is not None:
            raise ValueError("task hierarchy supports only two levels")
        if task_has_children:
            raise ValueError("a parent task cannot be attached beneath another task")

    @staticmethod
    def _next_sibling_order(connection, parent_id: str | None, *, excluding: str | None = None) -> int:
        clause = "parent_id IS NULL" if parent_id is None else "parent_id = ?"
        parameters: list[object] = [] if parent_id is None else [parent_id]
        if excluding is not None:
            clause += " AND id <> ?"
            parameters.append(excluding)
        row = connection.execute(
            f"SELECT coalesce(max(sibling_order), -1) + 1 AS next_order FROM tasks WHERE {clause}",
            parameters,
        ).fetchone()
        return int(row["next_order"])

    @staticmethod
    def _normalize_sibling_orders(
        connection,
        parent_id: str | None,
        *,
        now: str | None = None,
        cause_task_id: str | None = None,
    ) -> None:
        clause = "parent_id IS NULL" if parent_id is None else "parent_id = ?"
        parameters: tuple[object, ...] = () if parent_id is None else (parent_id,)
        rows = connection.execute(
            f"SELECT id, sibling_order FROM tasks WHERE {clause} "
            "ORDER BY sibling_order, created_at, id",
            parameters,
        ).fetchall()
        TaskRepository._write_sibling_orders(
            connection,
            [(row["id"], row["sibling_order"]) for row in rows],
            [row["id"] for row in rows],
            now=now,
            cause_task_id=cause_task_id,
        )

    @staticmethod
    def _canonicalize_tags(connection, tags: list[str]) -> list[str]:
        canonical: dict[str, str] = {}
        for item in TASK_TAG_CATALOG:
            identifier = str(item["id"])
            canonical[identifier.casefold()] = identifier
            canonical[str(item["label"]).casefold()] = identifier
        rows = connection.execute("SELECT tags_json FROM tasks ORDER BY created_at, id").fetchall()
        for row in rows:
            for label in json.loads(row["tags_json"]):
                canonical.setdefault(label.casefold(), label)
        values = [canonical.get(tag.casefold(), tag) for tag in tags]
        if len(values) != len(set(values)):
            raise ValueError("task tags must resolve to unique labels")
        return values

    @staticmethod
    def _place_at_order(
        connection,
        task_id: str,
        parent_id: str | None,
        requested: int,
        *,
        now: str,
    ) -> None:
        clause = "parent_id IS NULL" if parent_id is None else "parent_id = ?"
        parameters: tuple[object, ...] = () if parent_id is None else (parent_id,)
        rows = connection.execute(
            f"SELECT id, sibling_order FROM tasks WHERE {clause} AND id <> ? "
            "ORDER BY sibling_order, created_at, id",
            (*parameters, task_id),
        ).fetchall()
        identities = [row["id"] for row in rows]
        identities.insert(min(requested, len(identities)), task_id)
        current = [(row["id"], row["sibling_order"]) for row in rows]
        target = connection.execute(
            "SELECT sibling_order FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        assert target is not None
        current.append((task_id, target["sibling_order"]))
        TaskRepository._write_sibling_orders(
            connection,
            current,
            identities,
            now=now,
            cause_task_id=task_id,
        )

    @staticmethod
    def _write_sibling_orders(
        connection,
        current_rows: list[tuple[str, int]],
        ordered_ids: list[str],
        *,
        now: str | None,
        cause_task_id: str | None,
    ) -> None:
        current = dict(current_rows)
        for order, identity in enumerate(ordered_ids):
            previous = current[identity]
            if previous == order:
                continue
            if now is None or identity == cause_task_id:
                connection.execute(
                    "UPDATE tasks SET sibling_order = ? WHERE id = ?",
                    (order, identity),
                )
                continue
            connection.execute(
                "UPDATE tasks SET sibling_order = ?, updated_at = ? WHERE id = ?",
                (order, now, identity),
            )
            connection.execute(
                "INSERT INTO task_events(event_id, task_id, event_type, payload_json, occurred_at) "
                "VALUES (?, ?, 'task.reordered', ?, ?)",
                (
                    str(uuid4()),
                    identity,
                    json.dumps(
                        {
                            "changes": {
                                "sibling_order": {"from": previous, "to": order}
                            },
                            "cause_task_id": cause_task_id,
                        },
                        sort_keys=True,
                    ),
                    now,
                ),
            )

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
            deadline=json.loads(row["deadline_json"]) if row["deadline_json"] else None,
            tags=json.loads(row["tags_json"]),
            parent_id=row["parent_id"],
            sibling_order=row["sibling_order"],
        )
