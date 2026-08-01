"""Immutable Landscape domain values."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import ClassVar, TypeAlias


class LandscapeEntityKind(StrEnum):
    INITIATIVE = "initiative"
    ACTION = "action"


class LandscapeInitiativeState(StrEnum):
    OPEN = "open"
    BLOCKED = "blocked"
    WAITING = "waiting"
    COMPLETED = "completed"


class LandscapeActionState(StrEnum):
    READY = "ready"
    BLOCKED = "blocked"
    WAITING = "waiting"
    DONE = "done"


class LandscapeTimingKind(StrEnum):
    ANYTIME = "anytime"
    DUE_ON = "due-on"
    DUE_AT = "due-at"
    WINDOW = "window"


@dataclass(frozen=True, slots=True)
class LandscapeAnytime:
    kind: ClassVar[LandscapeTimingKind] = LandscapeTimingKind.ANYTIME


@dataclass(frozen=True, slots=True)
class LandscapeDueOn:
    due_on: date
    kind: ClassVar[LandscapeTimingKind] = LandscapeTimingKind.DUE_ON


@dataclass(frozen=True, slots=True)
class LandscapeDueAt:
    due_at: datetime
    kind: ClassVar[LandscapeTimingKind] = LandscapeTimingKind.DUE_AT


@dataclass(frozen=True, slots=True)
class LandscapeWindow:
    starts_at: datetime
    ends_at: datetime
    kind: ClassVar[LandscapeTimingKind] = LandscapeTimingKind.WINDOW


LandscapeTiming: TypeAlias = (
    LandscapeAnytime | LandscapeDueOn | LandscapeDueAt | LandscapeWindow
)


@dataclass(frozen=True, slots=True)
class LandscapeInitiative:
    initiative_id: str
    title: str
    state: LandscapeInitiativeState
    context: str | None
    detail: str | None
    version: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class LandscapeAction:
    action_id: str
    title: str
    state: LandscapeActionState
    timing: LandscapeTiming
    context: str | None
    detail: str | None
    version: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class LandscapeEvent:
    sequence: int
    event_id: str
    entity_kind: LandscapeEntityKind
    entity_id: str
    event_type: str
    payload_json: str
    occurred_at: datetime
