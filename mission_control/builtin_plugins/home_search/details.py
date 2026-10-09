"""Entity-detail projections for the search and each discovered candidate."""

from __future__ import annotations

import json

from mission_control.agenda import SourceRef
from mission_control.builtin_plugins.home_search.capabilities import (
    ANNOTATE,
    IMPORT_SNAPSHOT,
    SET_REVIEW_STATUS,
)
from mission_control.builtin_plugins.home_search.repository import (
    PLUGIN_ID,
    SEARCH_ID,
    HomeSearchEvent,
    SQLiteHomeSearchRepository,
)
from mission_control.entity_details import (
    ActivityEntry,
    ActivityKind,
    DetailAttribute,
    EntityDetail,
    EntityDetailSchemaVersion,
)


def entity_detail(
    repository: SQLiteHomeSearchRepository, target: SourceRef
) -> EntityDetail | None:
    if target.plugin_id != PLUGIN_ID:
        return None
    if target.entity_type == "search" and target.entity_id == SEARCH_ID:
        return _search_detail(repository, target)
    if target.entity_type != "candidate":
        return None
    try:
        candidate = repository.get_candidate(target.entity_id)
    except KeyError:
        return None
    item = candidate.candidate
    attributes = (
        DetailAttribute("verification", "Verification", item.verification_status),
        DetailAttribute("review-status", "Review status", candidate.review_status.value),
        DetailAttribute("location", "Location", item.location),
        DetailAttribute(
            "usable-indoor-space",
            "Usable indoor space",
            f"{item.indoor_sqft:,} sq ft reported indoor area; comparability to current usable area unverified"
            if item.indoor_sqft is not None
            else "Not confirmed by the source",
        ),
        DetailAttribute("listing-status", "Listing status", item.listing_status),
        DetailAttribute(
            "list-price",
            "List price",
            f"${item.list_price:,}" if item.list_price is not None else "Not provided",
        ),
        DetailAttribute(
            "estimated-all-in",
            "Estimated all-in cost",
            f"${item.estimated_all_in.amount:,} {item.estimated_all_in.currency}"
            if item.estimated_all_in.amount is not None
            else "Not yet estimated",
        ),
        DetailAttribute(
            "cost-confidence",
            "Estimate confidence",
            item.estimated_all_in.confidence,
        ),
        DetailAttribute(
            "cost-assumptions",
            "All-in assumptions",
            _list_value(item.estimated_all_in.assumptions),
        ),
        DetailAttribute("why-fit", "Why it fits", _list_value(item.why_fit)),
        DetailAttribute("tradeoffs", "Tradeoffs", _list_value(item.tradeoffs)),
        DetailAttribute("unknowns", "Unknowns", _list_value(item.unknowns)),
        DetailAttribute("source-url", "Source", item.source_url),
        DetailAttribute(
            "last-checked",
            "Source last checked",
            candidate.last_seen_checked_at.isoformat(),
        ),
    )
    return EntityDetail(
        schema_version=EntityDetailSchemaVersion.V1,
        source=target,
        title=item.address,
        description=(
            "A discovered Reading candidate. Source facts and estimates require "
            "independent verification before a purchase decision."
        ),
        state=(
            candidate.review_status.value
            if candidate.current
            else f"archived · {candidate.review_status.value}"
        ),
        revision=candidate.revision,
        attributes=attributes,
        affordances=(ANNOTATE, SET_REVIEW_STATUS) if candidate.current else (ANNOTATE,),
        activity=_activity(repository.history("candidate", item.candidate_id)),
    )


def _search_detail(
    repository: SQLiteHomeSearchRepository, target: SourceRef
) -> EntityDetail:
    state = repository.get_state()
    candidates = repository.list_candidates()
    verified = sum(
        item.candidate.verification_status == "verified" for item in candidates
    )
    snapshot_sources = ()
    if state.snapshot_json is not None:
        snapshot_sources = tuple(json.loads(state.snapshot_json)["sources"])
    attributes = (
        DetailAttribute("location", "Location", "Strictly Reading, MA 01867"),
        DetailAttribute(
            "space",
            "Indoor-space preference",
            "Prefer a meaningful usable-space upgrade from the current roughly 1,800 sq ft; finished walkout-basement space is context, not a hard numeric cutoff",
        ),
        DetailAttribute(
            "current-layout",
            "Current layout baseline",
            "2 upstairs bedrooms; downstairs office/guest room and playroom",
        ),
        DetailAttribute(
            "construction",
            "Construction and rooms",
            "Prefer newer solid construction, quieter floors/sound isolation, and higher, open rooms",
        ),
        DetailAttribute(
            "living",
            "Living priorities",
            "Frequent family guest stays; usable yard, nature, privacy, and off busy main roads",
        ),
        DetailAttribute(
            "systems",
            "Systems preferences",
            "FiOS, central AC, and gas or heat pump; upgrades are acceptable when included in total cost",
        ),
        DetailAttribute(
            "budget",
            "Purchase budget",
            "Provisional and unset pending mortgage reconciliation and previous pricing analysis",
        ),
        DetailAttribute(
            "sale-contingency",
            "Current home",
            "Sale of the current house is needed before purchase",
        ),
        DetailAttribute(
            "watcher",
            "Daily watcher",
            "Not active. Daily checks are approved after budget finalization; alert only for worthwhile matches",
        ),
        DetailAttribute(
            "freshness",
            "Actual source freshness",
            state.last_checked_at.isoformat()
            if state.last_checked_at is not None
            else "No verified search snapshot imported yet",
        ),
        DetailAttribute(
            "candidate-counts",
            "Current imported candidates",
            f"{len(candidates)} total; {verified} source-verified",
        ),
        DetailAttribute(
            "source-urls",
            "Research sources",
            " • ".join(snapshot_sources) if snapshot_sources else "No snapshot sources",
        ),
    )
    return EntityDetail(
        schema_version=EntityDetailSchemaVersion.V1,
        source=target,
        title="Reading home purchase search",
        description=(
            "Ready for the right home, without an invented affordability cap or an "
            "implied active listing feed."
        ),
        state=(
            "active" if state.last_checked_at is not None else "awaiting verified import"
        ),
        revision=state.revision,
        attributes=attributes,
        affordances=(IMPORT_SNAPSHOT,),
        activity=_activity(repository.history("search", SEARCH_ID)),
    )


def _list_value(items: tuple[str, ...]) -> str:
    return " • ".join(items) if items else "None recorded"


def _activity(events: tuple[HomeSearchEvent, ...]) -> tuple[ActivityEntry, ...]:
    return tuple(
        ActivityEntry(
            activity_id=f"home-search:{event.event_id}",
            kind=ActivityKind.EVENT,
            activity_type=event.event_type,
            summary=_summary(event),
            occurred_at=event.occurred_at,
        )
        for event in events
    )


def _summary(event: HomeSearchEvent) -> str:
    if event.event_type == "home-search.snapshot-imported":
        return (
            f"Imported source revision {event.payload.get('source_revision')} with "
            f"{event.payload.get('candidate_count')} candidates"
        )
    if event.event_type == "home-search.review-status-changed":
        return (
            f"Review status changed from {event.payload.get('from')} "
            f"to {event.payload.get('to')}"
        )
    if event.event_type == "home-search.candidate-discovered":
        return "Candidate discovered in an imported snapshot"
    if event.event_type == "home-search.candidate-updated":
        return "Candidate source details refreshed"
    return event.event_type
