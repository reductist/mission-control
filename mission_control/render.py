"""Human-readable task rendering."""

from __future__ import annotations

from collections.abc import Iterable

from mission_control.tasks import TASK_STATES, Task

_STATE_HEADINGS = {
    "backlog": "Backlog",
    "ready": "Ready",
    "in-progress": "In Progress",
    "done": "Done",
}


def render_tasks_markdown(tasks: Iterable[Task]) -> str:
    """Render tasks as deterministic, portable Markdown."""

    grouped: dict[str, list[Task]] = {state: [] for state in TASK_STATES}
    for task in tasks:
        grouped[task.state].append(task)

    lines = ["# Mission Control Tasks", ""]
    if not any(grouped.values()):
        lines.extend(["_No tasks._", ""])
        return "\n".join(lines)

    for state in TASK_STATES:
        state_tasks = grouped[state]
        if not state_tasks:
            continue

        lines.extend([f"## {_STATE_HEADINGS[state]}", ""])
        for task in state_tasks:
            checkbox = "x" if task.state == "done" else " "
            lines.append(f"- [{checkbox}] {task.title} (`{task.id}`)")
            if task.description:
                description = " ".join(task.description.splitlines())
                lines.append(f"  - Description: {description}")
            if task.blocked:
                lines.append("  - Blocked: yes")
            if task.waiting_on:
                lines.append(f"  - Waiting on: {task.waiting_on}")
            if task.review_after:
                lines.append(f"  - Review after: {task.review_after}")
        lines.append("")

    return "\n".join(lines)
