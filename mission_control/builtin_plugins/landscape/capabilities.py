"""Landscape's state-dependent projections of registered entity capabilities."""

from __future__ import annotations

from mission_control.builtin_plugins.landscape.domain import (
    LandscapeAction,
    LandscapeActionState,
)
from mission_control.plugins import (
    EntityAffordance,
    EntityCapability,
    StandardEntityCapability,
)

COMPLETE = EntityAffordance(
    EntityCapability(StandardEntityCapability.LIFECYCLE_COMPLETE.value),
    "complete",
)
REOPEN = EntityAffordance(
    EntityCapability(StandardEntityCapability.LIFECYCLE_REOPEN.value),
    "reopen",
)
ANNOTATE = EntityAffordance(
    EntityCapability(StandardEntityCapability.ENTITY_ANNOTATE.value),
    "add-note",
)


def action_affordances(action: LandscapeAction) -> tuple[EntityAffordance, ...]:
    """Expose exactly the lifecycle operation legal in the current state."""

    if action.state is LandscapeActionState.DONE:
        return (ANNOTATE, REOPEN)
    return (ANNOTATE, COMPLETE)
