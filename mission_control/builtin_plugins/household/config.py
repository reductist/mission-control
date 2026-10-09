"""Validated household plugin configuration values."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import cast


@dataclass(frozen=True, slots=True)
class HouseholdContact:
    name: str
    role: str | None
    company: str | None
    phone: str | None
    email: str | None
    website: str | None


@dataclass(frozen=True, slots=True)
class HouseholdLink:
    label: str
    kind: str
    url: str


@dataclass(frozen=True, slots=True)
class HouseholdAppointment:
    appointment_id: str
    title: str
    kind: str
    starts_at: datetime
    ends_at: datetime
    detail: str | None

    def __post_init__(self) -> None:
        if self.starts_at.tzinfo is None or self.starts_at.utcoffset() is None:
            raise ValueError("appointment starts_at must include a UTC offset")
        if self.ends_at.tzinfo is None or self.ends_at.utcoffset() is None:
            raise ValueError("appointment ends_at must include a UTC offset")
        if self.ends_at <= self.starts_at:
            raise ValueError("appointment ends_at must be later than starts_at")


@dataclass(frozen=True, slots=True)
class HouseholdCase:
    case_id: str
    title: str
    state: str
    summary: str
    area: str | None
    contacts: tuple[HouseholdContact, ...]
    links: tuple[HouseholdLink, ...]
    related_task_ids: tuple[str, ...]
    appointments: tuple[HouseholdAppointment, ...]


@dataclass(frozen=True, slots=True)
class HouseholdConfig:
    cases: tuple[HouseholdCase, ...]

    @classmethod
    def from_runtime(cls, configuration: Mapping[str, object]) -> HouseholdConfig:
        raw_cases = cast(Mapping[str, object], configuration["cases"])
        return cls(
            tuple(
                _case(case_id, cast(Mapping[str, object], value))
                for case_id, value in sorted(raw_cases.items())
            )
        )


def _optional_text(raw: Mapping[str, object], key: str) -> str | None:
    value = raw.get(key)
    return str(value) if value is not None else None


def _contact(raw: Mapping[str, object]) -> HouseholdContact:
    return HouseholdContact(
        name=str(raw["name"]),
        role=_optional_text(raw, "role"),
        company=_optional_text(raw, "company"),
        phone=_optional_text(raw, "phone"),
        email=_optional_text(raw, "email"),
        website=_optional_text(raw, "website"),
    )


def _link(raw: Mapping[str, object]) -> HouseholdLink:
    return HouseholdLink(str(raw["label"]), str(raw["kind"]), str(raw["url"]))


def _appointment(
    appointment_id: str, raw: Mapping[str, object]
) -> HouseholdAppointment:
    return HouseholdAppointment(
        appointment_id=appointment_id,
        title=str(raw["title"]),
        kind=str(raw["kind"]),
        starts_at=datetime.fromisoformat(str(raw["starts_at"]).replace("Z", "+00:00")),
        ends_at=datetime.fromisoformat(str(raw["ends_at"]).replace("Z", "+00:00")),
        detail=_optional_text(raw, "detail"),
    )


def _case(case_id: str, raw: Mapping[str, object]) -> HouseholdCase:
    appointments = cast(Mapping[str, object], raw.get("appointments", {}))
    return HouseholdCase(
        case_id=case_id,
        title=str(raw["title"]),
        state=str(raw["state"]),
        summary=str(raw["summary"]),
        area=_optional_text(raw, "area"),
        contacts=tuple(
            _contact(cast(Mapping[str, object], item))
            for item in cast(list[object], raw.get("contacts", []))
        ),
        links=tuple(
            _link(cast(Mapping[str, object], item))
            for item in cast(list[object], raw.get("links", []))
        ),
        related_task_ids=tuple(
            str(item) for item in cast(list[object], raw.get("related_task_ids", []))
        ),
        appointments=tuple(
            _appointment(appointment_id, cast(Mapping[str, object], item))
            for appointment_id, item in sorted(appointments.items())
        ),
    )
