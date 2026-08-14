"""Pure parsing and normalization of Google Calendar and Tasks resources."""

from __future__ import annotations

import hashlib
import html
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from html.parser import HTMLParser
from typing import Any


class GoogleResourceError(ValueError):
    """One upstream resource cannot be represented safely."""


@dataclass(frozen=True, slots=True)
class GoogleCollection:
    kind: str
    external_id: str
    label: str
    access_role: str | None = None

    @property
    def collection_key(self) -> str:
        return _stable_id(f"{self.kind}\0{self.external_id}", prefix="gsrc")


@dataclass(frozen=True, slots=True)
class GoogleEntry:
    entity_id: str
    collection_key: str
    remote_id: str
    entity_type: str
    title: str
    context: str
    detail: str | None
    timing_kind: str
    occurs_on: date | None
    ends_before: date | None
    starts_at: datetime | None
    ends_at: datetime | None
    due_on: date | None
    status: str
    location: str | None
    source_url: str | None
    revision: str
    updated_at: datetime


class _PlainTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def text(self) -> str:
        return " ".join(" ".join(self.parts).split())


def calendar_collection(document: Mapping[str, Any]) -> GoogleCollection:
    external_id = _required_text(document, "id", "calendar.id")
    label = _optional_text(document.get("summaryOverride")) or _optional_text(
        document.get("summary")
    )
    return GoogleCollection(
        "calendar",
        external_id,
        label or "Calendar",
        _optional_text(document.get("accessRole")),
    )


def task_list_collection(document: Mapping[str, Any]) -> GoogleCollection:
    return GoogleCollection(
        "task-list",
        _required_text(document, "id", "task-list.id"),
        _optional_text(document.get("title")) or "Tasks",
    )


def calendar_event(
    collection: GoogleCollection,
    document: Mapping[str, Any],
) -> GoogleEntry | None:
    if document.get("status") == "cancelled" or _self_declined(document):
        return None
    remote_id = _required_text(document, "id", "event.id")
    start = _mapping(document.get("start"), "event.start")
    end = _mapping(document.get("end"), "event.end")
    original = document.get("originalStartTime")
    occurrence = ""
    if isinstance(original, Mapping):
        occurrence = str(original.get("dateTime") or original.get("date") or "")
    identity = f"{collection.external_id}\0{remote_id}\0{occurrence}"
    free_busy_only = collection.access_role == "freeBusyReader"
    title = (
        "Busy" if free_busy_only else _optional_text(document.get("summary")) or "Busy"
    )
    description = None if free_busy_only else _html_text(document.get("description"))
    location = None if free_busy_only else _optional_text(document.get("location"))
    source_url = None if free_busy_only else _safe_url(document.get("htmlLink"))
    revision = _revision(document)
    updated_at = _updated_at(document)

    occurs_on: date | None = None
    ends_before: date | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    if isinstance(start.get("date"), str):
        occurs_on = _date(start["date"], "event.start.date")
        end_date = end.get("date")
        if not isinstance(end_date, str):
            raise GoogleResourceError("event.end.date: required for an all-day event")
        ends_before = _date(end_date, "event.end.date")
        if ends_before <= occurs_on:
            raise GoogleResourceError("event: all-day end must be after start")
        timing_kind = "all-day"
    else:
        starts_at = _datetime(start.get("dateTime"), "event.start.dateTime")
        ends_at = _datetime(end.get("dateTime"), "event.end.dateTime")
        if ends_at <= starts_at:
            raise GoogleResourceError("event: timed end must be after start")
        timing_kind = "timed"

    return GoogleEntry(
        entity_id=_stable_id(identity, prefix="gcal"),
        collection_key=collection.collection_key,
        remote_id=identity,
        entity_type="calendar-event",
        title=_bounded(title, 256),
        context=_bounded(collection.label, 512),
        detail=_bounded(description, 4096) if description else None,
        timing_kind=timing_kind,
        occurs_on=occurs_on,
        ends_before=ends_before,
        starts_at=starts_at,
        ends_at=ends_at,
        due_on=None,
        status=_optional_text(document.get("status")) or "confirmed",
        location=_bounded(location, 1024) if location else None,
        source_url=source_url,
        revision=revision,
        updated_at=updated_at,
    )


def google_task(
    collection: GoogleCollection,
    document: Mapping[str, Any],
) -> GoogleEntry | None:
    if document.get("deleted") is True or document.get("status") == "completed":
        return None
    remote_id = _required_text(document, "id", "task.id")
    due = document.get("due")
    due_on = _date(due[:10], "task.due") if isinstance(due, str) else None
    notes = _optional_text(document.get("notes"))
    return GoogleEntry(
        entity_id=_stable_id(
            f"{collection.external_id}\0{remote_id}", prefix="gtask"
        ),
        collection_key=collection.collection_key,
        remote_id=remote_id,
        entity_type="task",
        title=_bounded(_optional_text(document.get("title")) or "Untitled task", 256),
        context=_bounded(collection.label, 512),
        detail=_bounded(notes, 4096) if notes else None,
        timing_kind="due-on" if due_on is not None else "anytime",
        occurs_on=None,
        ends_before=None,
        starts_at=None,
        ends_at=None,
        due_on=due_on,
        status=_optional_text(document.get("status")) or "needsAction",
        location=None,
        source_url=_safe_url(document.get("webViewLink")),
        revision=_revision(document),
        updated_at=_updated_at(document),
    )


def _stable_id(value: str, *, prefix: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return f"{prefix}-{digest}"


def _revision(document: Mapping[str, Any]) -> str:
    explicit = _optional_text(document.get("etag")) or _optional_text(
        document.get("updated")
    )
    if explicit:
        return explicit
    payload = json.dumps(document, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _updated_at(document: Mapping[str, Any]) -> datetime:
    value = document.get("updated")
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
        else:
            if parsed.tzinfo is not None and parsed.utcoffset() is not None:
                return parsed
    return datetime.now(UTC)


def _self_declined(document: Mapping[str, Any]) -> bool:
    attendees = document.get("attendees")
    if not isinstance(attendees, list):
        return False
    return any(
        isinstance(item, Mapping)
        and item.get("self") is True
        and item.get("responseStatus") == "declined"
        for item in attendees
    )


def _mapping(value: object, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise GoogleResourceError(f"{path}: expected object")
    return value


def _required_text(document: Mapping[str, Any], key: str, path: str) -> str:
    value = _optional_text(document.get(key))
    if value is None:
        raise GoogleResourceError(f"{path}: required nonblank string")
    return value


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _html_text(value: object) -> str | None:
    text = _optional_text(value)
    if text is None:
        return None
    parser = _PlainTextParser()
    parser.feed(text)
    parser.close()
    return html.unescape(parser.text()) or None


def _safe_url(value: object) -> str | None:
    text = _optional_text(value)
    if text is None or not text.startswith("https://"):
        return None
    return _bounded(text, 2048)


def _date(value: object, path: str) -> date:
    if not isinstance(value, str):
        raise GoogleResourceError(f"{path}: expected date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise GoogleResourceError(f"{path}: invalid date") from error
    return parsed


def _datetime(value: object, path: str) -> datetime:
    if not isinstance(value, str):
        raise GoogleResourceError(f"{path}: expected date-time")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise GoogleResourceError(f"{path}: invalid date-time") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise GoogleResourceError(f"{path}: date-time must include an offset")
    return parsed


def _bounded(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[: limit - 1] + "…"
