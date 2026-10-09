"""State-dependent home-search command affordances."""

from mission_control.plugins import (
    EntityAffordance,
    EntityCapability,
    StandardEntityCapability,
)

IMPORT_SNAPSHOT = EntityAffordance(
    EntityCapability("home-search.snapshot.import"), "import-snapshot"
)
SET_REVIEW_STATUS = EntityAffordance(
    EntityCapability("home-search.review.set-status"), "set-review-status"
)
ANNOTATE = EntityAffordance(
    EntityCapability(StandardEntityCapability.ENTITY_ANNOTATE.value), "add-note"
)
