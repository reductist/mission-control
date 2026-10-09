"""Validated immutable values for imported home-search research."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from functools import lru_cache
from importlib.resources import files
from typing import Any, cast
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator, FormatChecker


class HomeSearchSnapshotError(ValueError):
    """An imported research snapshot is unsafe or incomplete."""


class ReviewStatus(StrEnum):
    UNREVIEWED = "unreviewed"
    SHORTLISTED = "shortlisted"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class AllInEstimate:
    amount: int | None
    currency: str
    confidence: str
    assumptions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Candidate:
    candidate_id: str
    address: str
    location: str
    verification_status: str
    listing_status: str
    source_url: str
    source_label: str | None
    indoor_sqft: int | None
    list_price: int | None
    why_fit: tuple[str, ...]
    tradeoffs: tuple[str, ...]
    unknowns: tuple[str, ...]
    estimated_all_in: AllInEstimate

    def to_dict(self) -> dict[str, object]:
        document: dict[str, object] = {
            "id": self.candidate_id,
            "address": self.address,
            "location": self.location,
            "verification_status": self.verification_status,
            "listing_status": self.listing_status,
            "source_url": self.source_url,
            "indoor_sqft": self.indoor_sqft,
            "list_price": self.list_price,
            "why_fit": list(self.why_fit),
            "tradeoffs": list(self.tradeoffs),
            "unknowns": list(self.unknowns),
            "estimated_all_in": {
                "amount": self.estimated_all_in.amount,
                "currency": self.estimated_all_in.currency,
                "confidence": self.estimated_all_in.confidence,
                "assumptions": list(self.estimated_all_in.assumptions),
            },
        }
        if self.source_label is not None:
            document["source_label"] = self.source_label
        return document


@dataclass(frozen=True, slots=True)
class SearchSnapshot:
    revision: str
    checked_at: datetime
    sources: tuple[str, ...]
    candidates: tuple[Candidate, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "mission-control.home-search-snapshot/v1",
            "revision": self.revision,
            "checked_at": self.checked_at.isoformat(),
            "sources": list(self.sources),
            "candidates": [candidate.to_dict() for candidate in self.candidates],
        }


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    path = files(__package__).joinpath("snapshot.schema.json")
    schema = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def parse_snapshot(document: object) -> SearchSnapshot:
    """Validate and detach one externally produced research snapshot."""

    _assert_json(document)
    detached = json.loads(json.dumps(document, sort_keys=True, allow_nan=False))
    if not isinstance(detached, dict):
        raise HomeSearchSnapshotError("$: snapshot must be a JSON object")
    errors = sorted(
        _validator().iter_errors(detached),
        key=lambda error: (
            tuple(str(part) for part in error.absolute_path),
            error.message,
        ),
    )
    if errors:
        error = errors[0]
        path = ".".join(str(part) for part in error.absolute_path) or "$"
        raise HomeSearchSnapshotError(f"{path}: {error.message}")

    checked_at = datetime.fromisoformat(
        cast(str, detached["checked_at"]).replace("Z", "+00:00")
    )
    if checked_at.tzinfo is None or checked_at.utcoffset() is None:
        raise HomeSearchSnapshotError("checked_at: must include a UTC offset")

    revision = cast(str, detached["revision"])
    if not revision.strip():
        raise HomeSearchSnapshotError("revision: must not be blank")

    sources = cast(list[str], detached["sources"])
    for index, value in enumerate(sources):
        _require_http_url(value, f"sources.{index}")

    raw_candidates = cast(list[dict[str, Any]], detached["candidates"])
    ids = [item["id"] for item in raw_candidates]
    if len(ids) != len(set(ids)):
        raise HomeSearchSnapshotError("candidates: candidate IDs must be unique")
    for index, item in enumerate(raw_candidates):
        text_values = [
            item["address"],
            item["listing_status"],
            *item["why_fit"],
            *item["tradeoffs"],
            *item["unknowns"],
            *item["estimated_all_in"]["assumptions"],
        ]
        if item.get("source_label") is not None:
            text_values.append(item["source_label"])
        if any(not cast(str, value).strip() for value in text_values):
            raise HomeSearchSnapshotError(
                f"candidates.{index}: text values must not be blank"
            )
        _require_http_url(
            cast(str, item["source_url"]), f"candidates.{index}.source_url"
        )

    return SearchSnapshot(
        revision=revision,
        checked_at=checked_at,
        sources=tuple(sources),
        candidates=tuple(_candidate(item) for item in raw_candidates),
    )


def _candidate(raw: dict[str, Any]) -> Candidate:
    estimate = cast(dict[str, Any], raw["estimated_all_in"])
    return Candidate(
        candidate_id=raw["id"],
        address=raw["address"],
        location=raw["location"],
        verification_status=raw["verification_status"],
        listing_status=raw["listing_status"],
        source_url=raw["source_url"],
        source_label=raw.get("source_label"),
        indoor_sqft=raw.get("indoor_sqft"),
        list_price=raw.get("list_price"),
        why_fit=tuple(raw["why_fit"]),
        tradeoffs=tuple(raw["tradeoffs"]),
        unknowns=tuple(raw["unknowns"]),
        estimated_all_in=AllInEstimate(
            amount=estimate["amount"],
            currency=estimate["currency"],
            confidence=estimate["confidence"],
            assumptions=tuple(estimate["assumptions"]),
        ),
    )


def _assert_json(value: object, path: str = "$") -> None:
    if value is None or isinstance(value, (bool, int, str)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise HomeSearchSnapshotError(f"{path}: non-finite numbers are invalid")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _assert_json(item, f"{path}.{index}")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise HomeSearchSnapshotError(f"{path}: object keys must be strings")
            _assert_json(item, f"{path}.{key}")
        return
    raise HomeSearchSnapshotError(
        f"{path}: snapshot must contain only JSON values; got {type(value).__name__}"
    )


def _require_http_url(value: str, path: str) -> None:
    source = urlsplit(value)
    if source.scheme not in {"http", "https"} or not source.netloc:
        raise HomeSearchSnapshotError(f"{path}: must be an http(s) URL")
