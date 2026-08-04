"""Immutable Landscape domain values."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from datetime import date, datetime
from enum import StrEnum
from typing import ClassVar, Final, TypeAlias

LANDSCAPE_ID_MAX_LENGTH: Final = 128
LANDSCAPE_TITLE_MAX_LENGTH: Final = 256
LANDSCAPE_CONTEXT_MAX_LENGTH: Final = 128
LANDSCAPE_DETAIL_MAX_LENGTH: Final = 4096

_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]*")
_EVENT_TYPE = re.compile(r"landscape\.[a-z][a-z0-9-]*")


class LandscapeInvariantError(ValueError):
    """An authoritative Landscape value or transition is invalid."""

    def __init__(self, code: str, field: str, detail: str) -> None:
        self.code = code
        self.field = field
        self.detail = detail
        super().__init__(f"{field}: {detail}")


def _invalid(field: str, detail: str, *, code: str = "invalid-value") -> None:
    raise LandscapeInvariantError(code, field, detail)


def _require_text(
    value: object,
    field: str,
    *,
    maximum: int,
    pattern: re.Pattern[str] | None = None,
) -> None:
    if not isinstance(value, str):
        _invalid(field, "must be a string")
    if not value.strip():
        _invalid(field, "must not be blank")
    if len(value) > maximum:
        _invalid(field, f"must contain at most {maximum} characters")
    if pattern is not None and pattern.fullmatch(value) is None:
        _invalid(field, "contains unsupported characters")


def _require_optional_text(value: object, field: str, *, maximum: int) -> None:
    if value is not None:
        _require_text(value, field, maximum=maximum)


def _require_aware(value: object, field: str) -> None:
    if not isinstance(value, datetime):
        _invalid(field, "must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        _invalid(field, "must be timezone-aware")


def _require_version(value: object, field: str = "version") -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        _invalid(field, "must be a positive integer")


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON value {value}")


def _require_entity_fields(
    *,
    entity_id: object,
    id_field: str,
    title: object,
    context: object,
    detail: object,
    version: object,
    created_at: object,
    updated_at: object,
) -> None:
    _require_text(
        entity_id,
        id_field,
        maximum=LANDSCAPE_ID_MAX_LENGTH,
        pattern=_IDENTIFIER,
    )
    _require_text(title, "title", maximum=LANDSCAPE_TITLE_MAX_LENGTH)
    _require_optional_text(context, "context", maximum=LANDSCAPE_CONTEXT_MAX_LENGTH)
    _require_optional_text(detail, "detail", maximum=LANDSCAPE_DETAIL_MAX_LENGTH)
    _require_version(version)
    _require_aware(created_at, "created_at")
    _require_aware(updated_at, "updated_at")
    if updated_at < created_at:
        _invalid("updated_at", "must not precede created_at")


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

    def __post_init__(self) -> None:
        if not isinstance(self.due_on, date) or isinstance(self.due_on, datetime):
            _invalid("due_on", "must be a date")


@dataclass(frozen=True, slots=True)
class LandscapeDueAt:
    due_at: datetime
    kind: ClassVar[LandscapeTimingKind] = LandscapeTimingKind.DUE_AT

    def __post_init__(self) -> None:
        _require_aware(self.due_at, "due_at")


@dataclass(frozen=True, slots=True)
class LandscapeWindow:
    starts_at: datetime
    ends_at: datetime
    kind: ClassVar[LandscapeTimingKind] = LandscapeTimingKind.WINDOW

    def __post_init__(self) -> None:
        _require_aware(self.starts_at, "starts_at")
        _require_aware(self.ends_at, "ends_at")
        if self.ends_at <= self.starts_at:
            _invalid("ends_at", "must be later than starts_at")


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

    def __post_init__(self) -> None:
        if not isinstance(self.state, LandscapeInitiativeState):
            _invalid("state", "must be a LandscapeInitiativeState")
        _require_entity_fields(
            entity_id=self.initiative_id,
            id_field="initiative_id",
            title=self.title,
            context=self.context,
            detail=self.detail,
            version=self.version,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )

    @property
    def revision(self) -> str:
        """Return the opaque public concurrency token for this initiative."""

        return str(self.version)


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

    def __post_init__(self) -> None:
        if not isinstance(self.state, LandscapeActionState):
            _invalid("state", "must be a LandscapeActionState")
        if not isinstance(
            self.timing,
            (LandscapeAnytime, LandscapeDueOn, LandscapeDueAt, LandscapeWindow),
        ):
            _invalid("timing", "must be a Landscape timing value")
        _require_entity_fields(
            entity_id=self.action_id,
            id_field="action_id",
            title=self.title,
            context=self.context,
            detail=self.detail,
            version=self.version,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )

    @property
    def revision(self) -> str:
        """Return the opaque public concurrency token for this action."""

        return str(self.version)

    def complete(self, *, at: datetime) -> LandscapeAction:
        """Return the next immutable state for a legal completion."""

        if self.state is LandscapeActionState.DONE:
            _invalid(
                "state",
                "a completed Landscape action cannot be completed again",
                code="invalid-transition",
            )
        return self._transition(LandscapeActionState.DONE, at=at)

    def reopen(self, *, at: datetime) -> LandscapeAction:
        """Return the next immutable state for a legal reopening."""

        if self.state is not LandscapeActionState.DONE:
            _invalid(
                "state",
                "only a completed Landscape action can be reopened",
                code="invalid-transition",
            )
        return self._transition(LandscapeActionState.READY, at=at)

    def _transition(
        self, state: LandscapeActionState, *, at: datetime
    ) -> LandscapeAction:
        _require_aware(at, "updated_at")
        if at < self.updated_at:
            _invalid("updated_at", "must not precede the current updated_at")
        return replace(
            self,
            state=state,
            version=self.version + 1,
            updated_at=at,
        )


@dataclass(frozen=True, slots=True)
class LandscapeEvent:
    sequence: int
    event_id: str
    entity_kind: LandscapeEntityKind
    entity_id: str
    event_type: str
    payload_json: str
    occurred_at: datetime

    def __post_init__(self) -> None:
        _require_version(self.sequence, "sequence")
        _require_text(
            self.event_id,
            "event_id",
            maximum=LANDSCAPE_ID_MAX_LENGTH,
            pattern=_IDENTIFIER,
        )
        if not isinstance(self.entity_kind, LandscapeEntityKind):
            _invalid("entity_kind", "must be a LandscapeEntityKind")
        _require_text(
            self.entity_id,
            "entity_id",
            maximum=LANDSCAPE_ID_MAX_LENGTH,
            pattern=_IDENTIFIER,
        )
        _require_text(
            self.event_type,
            "event_type",
            maximum=LANDSCAPE_ID_MAX_LENGTH,
            pattern=_EVENT_TYPE,
        )
        if not isinstance(self.payload_json, str):
            _invalid("payload_json", "must be a JSON string")
        try:
            payload = json.loads(
                self.payload_json,
                parse_constant=_reject_json_constant,
            )
        except (TypeError, ValueError) as error:
            raise LandscapeInvariantError(
                "invalid-value", "payload_json", "must contain valid JSON"
            ) from error
        if not isinstance(payload, dict):
            _invalid("payload_json", "must contain a JSON object")
        _require_aware(self.occurred_at, "occurred_at")
