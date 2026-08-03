"""Rich renderables for the human-facing CLI presentation shell."""

from __future__ import annotations

from collections.abc import Iterable
from typing import assert_never

from rich import box
from rich.table import Table
from rich.text import Text

from mission_control.agenda import (
    Action,
    AgendaEntry,
    AggregatedAgenda,
    AllDayTiming,
    AnytimeTiming,
    DueAtTiming,
    DueOnTiming,
    Event,
    Initiative,
    TimedTiming,
    WindowTiming,
)
from mission_control.plugins import (
    AvailablePlugin,
    ConflictedPlugin,
    PluginCatalog,
    PluginCatalogEntry,
    RejectedPlugin,
)
from mission_control.tasks import Task


def _text(value: object | None, *, style: str | None = None) -> Text:
    """Render external values as literal text rather than Rich markup."""

    return Text("" if value is None else str(value), style=style)


def task_table(tasks: Iterable[Task]) -> Table:
    """Build a responsive task table without performing console I/O."""

    rows = tuple(tasks)
    table = Table(
        title="Tasks",
        box=box.SIMPLE_HEAD,
        expand=True,
        header_style="bold",
        show_edge=False,
    )
    table.add_column("State", no_wrap=True)
    table.add_column("Title", ratio=3, overflow="fold")
    table.add_column("Blocked", justify="center", no_wrap=True)
    table.add_column("Waiting on", ratio=2, overflow="fold")
    table.add_column("Review after", overflow="fold")
    table.add_column("ID", ratio=2, overflow="fold")

    if not rows:
        table.add_row("", _text("No tasks."), "", "", "", "")
        return table

    for task in rows:
        state_style = "bold" if task.state == "in-progress" else None
        table.add_row(
            _text(task.state, style=state_style),
            _text(task.title),
            _text("yes" if task.blocked else ""),
            _text(task.waiting_on),
            _text(task.review_after),
            _text(task.id),
        )
    return table


def _plugin_row(entry: PluginCatalogEntry) -> tuple[Text, Text, Text, Text, Text]:
    match entry:
        case AvailablePlugin():
            registration = entry.registration
            return (
                _text(entry.state.value),
                _text(registration.plugin_id.value),
                _text(registration.name),
                _text(registration.version),
                _text(entry.source.registration_path),
            )
        case RejectedPlugin():
            return (
                _text(entry.state.value, style="bold"),
                _text(""),
                _text("Invalid registration"),
                _text(""),
                _text(f"{entry.source.registration_path}\n{entry.failure.summary}"),
            )
        case ConflictedPlugin():
            sources = "\n".join(str(source.registration_path) for source in entry.sources)
            return (
                _text(entry.state.value, style="bold"),
                _text(entry.plugin_id.value),
                _text("Duplicate plugin ID"),
                _text(""),
                _text(sources),
            )
        case _:
            assert_never(entry)


def plugin_catalog_table(catalog: PluginCatalog) -> Table:
    """Build a responsive plugin catalog table without performing console I/O."""

    table = Table(
        title="Plugin Catalog",
        box=box.SIMPLE_HEAD,
        expand=True,
        header_style="bold",
        show_edge=False,
    )
    table.add_column("State", no_wrap=True)
    table.add_column("ID", no_wrap=True, overflow="ellipsis")
    table.add_column("Name", ratio=2, overflow="fold")
    table.add_column("Version", no_wrap=True)
    table.add_column("Source / detail", ratio=4, overflow="fold")

    if not catalog.entries:
        table.add_row("", "", _text("No plugins found."), "", "")
        return table

    for entry in catalog:
        table.add_row(*_plugin_row(entry))
    return table


def _agenda_when(entry: AgendaEntry) -> str:
    if isinstance(entry, Initiative):
        return "Anytime"
    timing = entry.timing
    if isinstance(timing, AnytimeTiming):
        return "Anytime"
    if isinstance(timing, DueOnTiming):
        return timing.due_on.isoformat()
    if isinstance(timing, DueAtTiming):
        return timing.due_at.isoformat(timespec="minutes")
    if isinstance(timing, WindowTiming):
        return (
            f"{timing.starts_at.isoformat(timespec='minutes')} → "
            f"{timing.ends_at.isoformat(timespec='minutes')}"
        )
    if isinstance(timing, AllDayTiming):
        return timing.occurs_on.isoformat()
    if isinstance(timing, TimedTiming):
        return timing.starts_at.isoformat(timespec="minutes")
    raise AssertionError(f"unhandled agenda timing: {timing!r}")


def _agenda_state(entry: AgendaEntry) -> str:
    if isinstance(entry, (Initiative, Action)):
        return entry.state.value
    if isinstance(entry, Event):
        return ""
    raise AssertionError(f"unhandled agenda entry: {entry!r}")


def agenda_table(agenda: AggregatedAgenda) -> Table:
    """Build a read-only aggregate agenda table without performing I/O."""

    table = Table(
        title="Agenda",
        box=box.SIMPLE_HEAD,
        expand=True,
        header_style="bold",
        show_edge=False,
    )
    table.add_column("When", no_wrap=True, overflow="ellipsis")
    table.add_column("Kind", no_wrap=True)
    table.add_column("State", no_wrap=True)
    table.add_column("Title", ratio=3, overflow="fold")
    table.add_column("Context", ratio=2, overflow="fold")
    table.add_column("Owner", no_wrap=True, overflow="ellipsis")

    if not agenda.entries:
        table.add_row("", "", "", _text("No agenda entries."), "", "")
        return table

    for entry in agenda.entries:
        table.add_row(
            _text(_agenda_when(entry)),
            _text(entry.kind.value),
            _text(_agenda_state(entry)),
            _text(entry.title),
            _text(entry.context),
            _text(entry.source.plugin_id.value),
        )
    return table
