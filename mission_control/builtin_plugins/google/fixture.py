"""Credential-free Google-shaped fixture transport for demos and tests."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from importlib.resources import files
from typing import Any, cast

from mission_control.builtin_plugins.google.domain import (
    GoogleCollection,
    calendar_collection,
    task_list_collection,
)


class FixtureGoogleClient:
    def __init__(self, document: Mapping[str, Any]) -> None:
        self.document = document

    @classmethod
    def load(cls) -> FixtureGoogleClient:
        raw = json.loads(files(__package__).joinpath("demo.json").read_text("utf-8"))
        if not isinstance(raw, Mapping):
            raise ValueError("Google demo fixture must be a JSON object")
        return cls(cast(Mapping[str, Any], raw))

    def calendars(self) -> tuple[tuple[GoogleCollection, Mapping[str, Any]], ...]:
        items = self._items(self.document.get("calendarList"), "calendarList")
        return tuple((calendar_collection(item), item) for item in items)

    def events(
        self, calendar_id: str, *, starts_at: datetime, ends_at: datetime
    ) -> tuple[Mapping[str, Any], ...]:
        del starts_at, ends_at
        resources = self.document.get("events")
        if not isinstance(resources, Mapping):
            raise ValueError("Google demo events must be an object")
        return self._items(resources.get(calendar_id), f"events.{calendar_id}")

    def task_lists(self) -> tuple[GoogleCollection, ...]:
        return tuple(
            task_list_collection(item)
            for item in self._items(self.document.get("tasklists"), "tasklists")
        )

    def tasks(self, task_list_id: str) -> tuple[Mapping[str, Any], ...]:
        resources = self.document.get("tasks")
        if not isinstance(resources, Mapping):
            raise ValueError("Google demo tasks must be an object")
        return self._items(resources.get(task_list_id), f"tasks.{task_list_id}")

    @staticmethod
    def _items(value: object, path: str) -> tuple[Mapping[str, Any], ...]:
        if not isinstance(value, Mapping) or not isinstance(value.get("items"), list):
            raise ValueError(f"Google demo {path} must contain an item list")
        result = []
        for item in value["items"]:
            if not isinstance(item, Mapping):
                raise ValueError(f"Google demo {path} contains a non-object item")
            result.append(cast(Mapping[str, Any], item))
        return tuple(result)
