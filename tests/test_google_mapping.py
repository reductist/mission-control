from __future__ import annotations

import json
from pathlib import Path

from mission_control.builtin_plugins.google.mapping import mapping_outcome


def test_google_mapping_cases_match_the_production_projection() -> None:
    statuses: set[str] = set()
    resource_kinds: set[str] = set()
    examples = Path(__file__).parents[1] / "schema" / "google" / "examples"
    for path in (
        examples / "valid-mapping-cases.json",
        examples / "valid-mapping-additive-fields.json",
    ):
        document = json.loads(path.read_text(encoding="utf-8"))
        for case in document["cases"]:
            resource_kind = case["resource_kind"]
            outcome = mapping_outcome(
                resource_kind,
                case["input"]["collection"],
                case["input"]["resource"],
            )
            assert outcome == case["outcome"], case["name"]
            statuses.add(outcome["status"])
            resource_kinds.add(resource_kind)

    assert statuses == {"mapped", "filtered", "rejected"}
    assert resource_kinds == {"calendar-event", "task"}
