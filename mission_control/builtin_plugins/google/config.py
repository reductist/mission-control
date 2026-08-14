"""Validated Google plugin runtime configuration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mission_control.plugins import PluginConfiguration


@dataclass(frozen=True, slots=True)
class GoogleConfig:
    mode: str
    calendar_ids: tuple[str, ...]
    task_list_ids: tuple[str, ...]
    lookback_days: int
    lookahead_days: int
    sync_interval_seconds: int
    request_timeout_seconds: int
    oauth_credential: Path | None

    @classmethod
    def from_runtime(
        cls,
        configuration: PluginConfiguration,
        credentials: dict[str, str],
    ) -> GoogleConfig:
        values = configuration.to_dict()
        unknown_credentials = sorted(set(credentials) - {"oauth"})
        if unknown_credentials:
            raise ValueError(
                "Google received unknown credentials: "
                + ", ".join(unknown_credentials)
            )
        mode = str(values.get("mode", "live"))
        credential = Path(credentials["oauth"]) if "oauth" in credentials else None
        if mode == "live" and credential is None:
            raise ValueError("Google live mode requires the named 'oauth' credential")
        if mode == "demo" and credential is not None:
            raise ValueError("Google demo mode does not accept an OAuth credential")
        return cls(
            mode=mode,
            calendar_ids=tuple(str(item) for item in values.get("calendar_ids", [])),
            task_list_ids=tuple(str(item) for item in values.get("task_list_ids", [])),
            lookback_days=int(values.get("lookback_days", 1)),
            lookahead_days=int(values.get("lookahead_days", 30)),
            sync_interval_seconds=int(values.get("sync_interval_seconds", 300)),
            request_timeout_seconds=int(values.get("request_timeout_seconds", 15)),
            oauth_credential=credential,
        )
