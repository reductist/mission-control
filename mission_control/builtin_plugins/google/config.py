"""Validated Google plugin runtime configuration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path


@dataclass(frozen=True, slots=True)
class GoogleConfig:
    mode: str
    demo_anchor_date: date | None
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
        configuration: Mapping[str, object],
        credentials: Mapping[str, str],
    ) -> GoogleConfig:
        mode = str(configuration["mode"])
        credential = Path(credentials["oauth"]) if "oauth" in credentials else None
        anchor_value = configuration.get("demo_anchor_date")
        return cls(
            mode=mode,
            demo_anchor_date=(
                date.fromisoformat(str(anchor_value))
                if anchor_value is not None
                else None
            ),
            calendar_ids=tuple(str(item) for item in configuration["calendar_ids"]),
            task_list_ids=tuple(str(item) for item in configuration["task_list_ids"]),
            lookback_days=int(configuration["lookback_days"]),
            lookahead_days=int(configuration["lookahead_days"]),
            sync_interval_seconds=int(configuration["sync_interval_seconds"]),
            request_timeout_seconds=int(configuration["request_timeout_seconds"]),
            oauth_credential=credential,
        )
