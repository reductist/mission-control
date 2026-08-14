"""Small public runtime values for plugin jobs, health, and shutdown."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from mission_control.plugins import PluginId


class PluginHealthState(StrEnum):
    STARTING = "starting"
    READY = "ready"
    DEGRADED = "degraded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class PluginHealth:
    plugin_id: PluginId
    state: PluginHealthState
    code: str
    detail: str
    checked_at: datetime
    last_success_at: datetime | None = None

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "plugin_id": self.plugin_id.value,
            "state": self.state.value,
            "code": self.code,
            "detail": self.detail,
            "checked_at": self.checked_at.isoformat(),
        }
        if self.last_success_at is not None:
            result["last_success_at"] = self.last_success_at.isoformat()
        return result


@dataclass(frozen=True, slots=True)
class PluginJob:
    plugin_id: PluginId
    job_id: str
    interval_seconds: int
    operation: Callable[[], None]
    failure_operation: Callable[[], None] | None = None


class PluginJobSupervisor:
    """Run independent periodic jobs without overlapping or blocking HTTP reads."""

    def __init__(self, jobs: Iterable[PluginJob]) -> None:
        self.jobs = tuple(jobs)
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        self._threads = [thread for thread in self._threads if thread.is_alive()]
        if self._threads:
            return
        self._stop.clear()
        for job in self.jobs:
            thread = threading.Thread(
                target=self._run,
                args=(job,),
                name=f"mission-control:{job.plugin_id.value}:{job.job_id}",
                daemon=True,
            )
            thread.start()
            self._threads.append(thread)

    def stop(self, *, timeout: float = 5.0) -> None:
        self._stop.set()
        for thread in reversed(self._threads):
            thread.join(timeout)
        self._threads = [thread for thread in self._threads if thread.is_alive()]

    def _run(self, job: PluginJob) -> None:
        while not self._stop.is_set():
            try:
                job.operation()
            except Exception:
                # Providers report safe health details. This final containment
                # boundary keeps one failed job from terminating the daemon.
                if job.failure_operation is not None:
                    try:
                        job.failure_operation()
                    except Exception:
                        pass
            if self._stop.wait(job.interval_seconds):
                return
