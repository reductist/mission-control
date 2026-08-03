from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from mission_control.builtin_plugins.landscape.domain import (
    LANDSCAPE_CONTEXT_MAX_LENGTH,
    LANDSCAPE_DETAIL_MAX_LENGTH,
    LANDSCAPE_ID_MAX_LENGTH,
    LANDSCAPE_TITLE_MAX_LENGTH,
    LandscapeAction,
    LandscapeActionState,
    LandscapeAnytime,
    LandscapeEntityKind,
    LandscapeEvent,
    LandscapeInvariantError,
    LandscapeWindow,
)

NOW = datetime(2026, 8, 2, 12, tzinfo=UTC)


def action(**changes: object) -> LandscapeAction:
    values: dict[str, object] = {
        "action_id": "measure-access-route",
        "title": "Measure the backyard access route",
        "state": LandscapeActionState.READY,
        "timing": LandscapeAnytime(),
        "context": "Equipment access",
        "detail": None,
        "version": 1,
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(changes)
    return LandscapeAction(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("length", "valid"),
    (
        (LANDSCAPE_ID_MAX_LENGTH - 1, True),
        (LANDSCAPE_ID_MAX_LENGTH, True),
        (LANDSCAPE_ID_MAX_LENGTH + 1, False),
    ),
)
def test_landscape_identifier_boundaries(length: int, valid: bool) -> None:
    entity_id = "a" + "x" * (length - 1)
    if valid:
        assert action(action_id=entity_id).action_id == entity_id
    else:
        with pytest.raises(LandscapeInvariantError) as invalid:
            action(action_id=entity_id)
        assert (invalid.value.code, invalid.value.field) == (
            "invalid-value",
            "action_id",
        )


@pytest.mark.parametrize(
    ("length", "valid"),
    (
        (LANDSCAPE_TITLE_MAX_LENGTH - 1, True),
        (LANDSCAPE_TITLE_MAX_LENGTH, True),
        (LANDSCAPE_TITLE_MAX_LENGTH + 1, False),
    ),
)
def test_landscape_title_boundaries(length: int, valid: bool) -> None:
    title = "x" * length
    if valid:
        assert action(title=title).title == title
    else:
        with pytest.raises(LandscapeInvariantError, match="at most 256 characters"):
            action(title=title)


@pytest.mark.parametrize(
    ("field", "maximum"),
    (
        ("context", LANDSCAPE_CONTEXT_MAX_LENGTH),
        ("detail", LANDSCAPE_DETAIL_MAX_LENGTH),
    ),
)
@pytest.mark.parametrize("offset", (-1, 0, 1))
def test_optional_text_boundaries(field: str, maximum: int, offset: int) -> None:
    value = "x" * (maximum + offset)
    if offset <= 0:
        assert getattr(action(**{field: value}), field) == value
    else:
        with pytest.raises(LandscapeInvariantError) as invalid:
            action(**{field: value})
        assert invalid.value.field == field


@pytest.mark.parametrize("invalid_title", ("", "  "))
def test_landscape_titles_cannot_be_blank(invalid_title: str) -> None:
    with pytest.raises(LandscapeInvariantError) as invalid:
        action(title=invalid_title)
    assert invalid.value.field == "title"


def test_landscape_timestamps_and_windows_are_ordered_and_aware() -> None:
    with pytest.raises(LandscapeInvariantError, match="timezone-aware"):
        action(updated_at=NOW.replace(tzinfo=None))
    with pytest.raises(LandscapeInvariantError, match="must not precede"):
        action(updated_at=NOW - timedelta(seconds=1))
    with pytest.raises(LandscapeInvariantError, match="later than starts_at"):
        LandscapeWindow(NOW, NOW)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("version", 0),
        ("version", True),
        ("state", "ready"),
        ("timing", object()),
    ),
)
def test_landscape_action_rejects_invalid_typed_values(
    field: str, value: object
) -> None:
    with pytest.raises(LandscapeInvariantError) as invalid:
        action(**{field: value})
    assert invalid.value.field == field


@pytest.mark.parametrize("state", tuple(LandscapeActionState))
def test_complete_transition_matrix(state: LandscapeActionState) -> None:
    current = action(state=state)
    if state is LandscapeActionState.DONE:
        with pytest.raises(LandscapeInvariantError) as invalid:
            current.complete(at=NOW + timedelta(seconds=1))
        assert invalid.value.code == "invalid-transition"
        return

    completed = current.complete(at=NOW + timedelta(seconds=1))
    assert completed.state is LandscapeActionState.DONE
    assert completed.version == current.version + 1
    assert current.state is state
    assert current.version == 1


@pytest.mark.parametrize("state", tuple(LandscapeActionState))
def test_reopen_transition_matrix(state: LandscapeActionState) -> None:
    current = action(state=state)
    if state is not LandscapeActionState.DONE:
        with pytest.raises(LandscapeInvariantError) as invalid:
            current.reopen(at=NOW + timedelta(seconds=1))
        assert invalid.value.code == "invalid-transition"
        return

    reopened = current.reopen(at=NOW + timedelta(seconds=1))
    assert reopened.state is LandscapeActionState.READY
    assert reopened.version == current.version + 1
    assert current.state is LandscapeActionState.DONE


def test_transition_time_cannot_move_backward() -> None:
    with pytest.raises(LandscapeInvariantError, match="current updated_at"):
        action().complete(at=NOW - timedelta(microseconds=1))


def test_landscape_event_payload_is_a_json_object() -> None:
    with pytest.raises(LandscapeInvariantError) as invalid:
        LandscapeEvent(
            sequence=1,
            event_id="event-1",
            entity_kind=LandscapeEntityKind.ACTION,
            entity_id="measure-access-route",
            event_type="landscape.action-imported",
            payload_json="[]",
            occurred_at=NOW,
        )
    assert (invalid.value.code, invalid.value.field) == (
        "invalid-value",
        "payload_json",
    )
