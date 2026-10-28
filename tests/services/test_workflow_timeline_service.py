from datetime import UTC, datetime

import pytest

from app.services.workflow_timeline_service import (
    INTERVIEW_SAVE_EVENTS,
    INTERVIEW_TIMELINE_EVENTS,
    MAX_ELAPSED_MS,
    WorkflowTimelineError,
    merge_timeline,
    parse_timeline,
    server_event,
)


def event(name: str, second: int = 0, elapsed: int | None = None) -> dict:
    value = {"event": name, "at": f"2026-10-28T10:00:{second:02d}+05:30"}
    if elapsed is not None:
        value["elapsed_ms"] = elapsed
    return value


def test_parse_orders_and_deduplicates_first_event() -> None:
    result = parse_timeline(
        [event("review_opened", 3), event("interview_started"), event("review_opened", 9)],
        INTERVIEW_TIMELINE_EVENTS,
    )

    assert [item["event"] for item in result] == ["interview_started", "review_opened"]
    assert result[1]["at"].endswith("10:00:03+05:30")


def test_merge_keeps_stored_first_event_and_is_idempotent() -> None:
    current = [event("interview_started", 1)]
    incoming = [event("interview_started", 8), event("submit_started", 9, 123)]

    merged = merge_timeline(current, incoming, INTERVIEW_SAVE_EVENTS)

    assert merged == [current[0], incoming[1]]
    assert merge_timeline(merged, incoming, INTERVIEW_SAVE_EVENTS) == merged


@pytest.mark.parametrize(
    "value",
    [
        [event("interview_started") | {"elapsed_ms": -1}],
        [event("interview_started") | {"elapsed_ms": MAX_ELAPSED_MS + 1}],
        [event("interview_started") | {"at": "2026-10-28T10:00:00"}],
        [event("submitted")],
    ],
)
def test_parse_rejects_bounds_timezone_and_caller_disallowed_events(value: list[dict]) -> None:
    with pytest.raises(WorkflowTimelineError):
        parse_timeline(value, INTERVIEW_SAVE_EVENTS)


def test_parse_rejects_more_than_eight_events() -> None:
    value = [event(name, index) for index, name in enumerate(
        ("interview_started", "identity_saved", "questionnaire_midpoint", "review_opened", "submit_started",
         "submitted", "coding_opened", "doris_processed", "initial_saved"),
    )]

    with pytest.raises(WorkflowTimelineError):
        parse_timeline(value)


def test_server_event_is_offset_timestamp() -> None:
    result = server_event("submitted", at=datetime(2026, 10, 28, 4, 30, tzinfo=UTC))

    assert result == {"event": "submitted", "at": "2026-10-28T04:30:00+00:00"}
