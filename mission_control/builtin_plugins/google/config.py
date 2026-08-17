"""Validated Google Calendar plugin runtime configuration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import cast


@dataclass(frozen=True, slots=True)
class ResourceSelection:
    mode: str
    ids: tuple[str, ...] = ()

    def includes(
        self,
        external_id: str,
        *,
        default_selected: bool,
    ) -> bool:
        if self.mode == "disabled":
            return False
        if self.mode == "all":
            return True
        if self.mode == "defaults":
            return default_selected
        return external_id in self.ids


@dataclass(frozen=True, slots=True)
class GoogleConnectionConfig:
    connection_id: str
    label: str
    mode: str
    demo_anchor_date: date | None
    calendars: ResourceSelection
    tasks: ResourceSelection
    calendar_principals: tuple[tuple[str, tuple[str, ...]], ...]
    task_list_principals: tuple[tuple[str, tuple[str, ...]], ...]
    oauth_credential: Path | None

    def principals_for(self, kind: str, external_id: str) -> tuple[str, ...]:
        profiles = (
            self.calendar_principals if kind == "calendar" else self.task_list_principals
        )
        return dict(profiles).get(external_id, ())


@dataclass(frozen=True, slots=True)
class GoogleConfig:
    connections: tuple[GoogleConnectionConfig, ...]
    lookback_days: int
    lookahead_days: int
    sync_interval_seconds: int
    request_timeout_seconds: int

    @classmethod
    def from_runtime(
        cls,
        configuration: Mapping[str, object],
        credentials: Mapping[str, str],
    ) -> GoogleConfig:
        raw_connections = cast(Mapping[str, object], configuration["connections"])
        connections = tuple(
            _connection(connection_id, cast(Mapping[str, object], raw), credentials)
            for connection_id, raw in sorted(raw_connections.items())
        )
        return cls(
            connections=connections,
            lookback_days=int(configuration["lookback_days"]),
            lookahead_days=int(configuration["lookahead_days"]),
            sync_interval_seconds=int(configuration["sync_interval_seconds"]),
            request_timeout_seconds=int(configuration["request_timeout_seconds"]),
        )


def _selection(value: object) -> ResourceSelection:
    raw = cast(Mapping[str, object], value)
    return ResourceSelection(
        str(raw["mode"]), tuple(str(item) for item in cast(list[object], raw.get("ids", [])))
    )


def _profiles(value: object, key: str) -> tuple[tuple[str, tuple[str, ...]], ...]:
    attribution = cast(Mapping[str, object], value or {})
    profiles = cast(Mapping[str, object], attribution.get(key, {}))
    return tuple(
        (
            external_id,
            tuple(
                str(item)
                for item in cast(Mapping[str, list[object]], profile)["principal_ids"]
            ),
        )
        for external_id, profile in sorted(profiles.items())
    )


def _connection(
    connection_id: str,
    raw: Mapping[str, object],
    credentials: Mapping[str, str],
) -> GoogleConnectionConfig:
    mode = str(raw["mode"])
    anchor = raw.get("demo_anchor_date")
    credential_name = raw.get("credential")
    return GoogleConnectionConfig(
        connection_id=connection_id,
        label=str(raw["label"]),
        mode=mode,
        demo_anchor_date=date.fromisoformat(str(anchor)) if anchor is not None else None,
        calendars=_selection(raw["calendars"]),
        tasks=_selection(raw["tasks"]),
        calendar_principals=_profiles(raw.get("attribution"), "calendars"),
        task_list_principals=_profiles(raw.get("attribution"), "task_lists"),
        oauth_credential=(
            Path(credentials[str(credential_name)])
            if credential_name is not None
            else None
        ),
    )
