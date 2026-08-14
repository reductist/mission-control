from __future__ import annotations

import threading

from mission_control.plugin_runtime import PluginJob, PluginJobSupervisor
from mission_control.plugins import PluginId


def test_plugin_job_supervisor_starts_once_and_stops_cleanly():
    called = threading.Event()
    count = 0
    lock = threading.Lock()

    def operation() -> None:
        nonlocal count
        with lock:
            count += 1
        called.set()

    supervisor = PluginJobSupervisor(
        (PluginJob(PluginId("example"), "refresh", 60, operation),)
    )
    supervisor.start()
    supervisor.start()
    assert called.wait(1)
    supervisor.stop()
    assert count == 1


def test_plugin_job_supervisor_reports_unexpected_failure():
    reported = threading.Event()

    def fail() -> None:
        raise RuntimeError("must not escape the job boundary")

    supervisor = PluginJobSupervisor(
        (
            PluginJob(
                PluginId("example"),
                "refresh",
                60,
                fail,
                reported.set,
            ),
        )
    )
    supervisor.start()
    assert reported.wait(1)
    supervisor.stop()


def test_plugin_job_supervisor_does_not_overlap_after_incomplete_stop():
    started = threading.Event()
    release = threading.Event()
    count = 0

    def blocked() -> None:
        nonlocal count
        count += 1
        started.set()
        release.wait(2)

    supervisor = PluginJobSupervisor(
        (PluginJob(PluginId("example"), "refresh", 60, blocked),)
    )
    supervisor.start()
    assert started.wait(1)
    supervisor.stop(timeout=0.01)
    supervisor.start()
    assert count == 1
    release.set()
    supervisor.stop(timeout=1)
