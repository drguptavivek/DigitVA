"""Bounded, first-party workflow timelines kept beside interview answers."""

from __future__ import annotations

import math
import re
from datetime import UTC, datetime
from typing import Iterable

MAX_EVENTS = 8
MAX_ELAPSED_MS = 86_400_000
TIMELINE_EVENTS = (
    "interview_started",
    "identity_saved",
    "questionnaire_midpoint",
    "review_opened",
    "submit_started",
    "submitted",
    "coding_allocated",
    "coding_opened",
    "doris_processed",
    "initial_saved",
    "final_saved",
)
INTERVIEW_TIMELINE_EVENTS = frozenset(TIMELINE_EVENTS[:6])
INTERVIEW_SAVE_EVENTS = frozenset(TIMELINE_EVENTS[:5])
CODING_TIMELINE_EVENTS = frozenset(TIMELINE_EVENTS[6:])
_ORDER = {event: index for index, event in enumerate(TIMELINE_EVENTS)}
_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")


class WorkflowTimelineError(ValueError):
    """An untrusted timeline failed the fixed bounded contract."""


def _timestamp(value: object) -> str:
    if not isinstance(value, str) or not _TIMESTAMP.fullmatch(value):
        raise WorkflowTimelineError("Invalid workflow timeline.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise WorkflowTimelineError("Invalid workflow timeline.") from None
    if parsed.tzinfo is None:
        raise WorkflowTimelineError("Invalid workflow timeline.")
    return value


def _allowed(allowed_events: Iterable[str] | None) -> frozenset[str]:
    allowed = frozenset(allowed_events) if allowed_events is not None else frozenset(TIMELINE_EVENTS)
    if not allowed.issubset(_ORDER):
        raise WorkflowTimelineError("Invalid workflow timeline.")
    return allowed


def parse_timeline(value: object, allowed_events: Iterable[str] | None = None) -> list[dict]:
    """Validate and return a canonical first-event-wins timeline."""
    allowed = _allowed(allowed_events)
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > MAX_EVENTS:
        raise WorkflowTimelineError("Invalid workflow timeline.")
    result: list[dict] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict) or set(item) - {"event", "at", "elapsed_ms"}:
            raise WorkflowTimelineError("Invalid workflow timeline.")
        event = item.get("event")
        if not isinstance(event, str) or event not in allowed:
            raise WorkflowTimelineError("Invalid workflow timeline.")
        if event in seen:
            continue
        at = _timestamp(item.get("at"))
        elapsed = item.get("elapsed_ms")
        if elapsed is not None and (
            isinstance(elapsed, bool) or not isinstance(elapsed, (int, float)) or
            not math.isfinite(elapsed) or int(elapsed) != elapsed or not 0 <= elapsed <= MAX_ELAPSED_MS
        ):
            raise WorkflowTimelineError("Invalid workflow timeline.")
        seen.add(event)
        result.append({"event": event, "at": at, **({"elapsed_ms": int(elapsed)} if elapsed is not None else {})})
    return sorted(result, key=lambda entry: _ORDER[entry["event"]])


def merge_timeline(
    current: object,
    incoming: object,
    allowed_events: Iterable[str] | None = None,
) -> list[dict]:
    """Merge retries idempotently; values already stored always win."""
    allowed = _allowed(allowed_events)
    left = parse_timeline(current, allowed)
    right = parse_timeline(incoming, allowed)
    merged = list(left)
    names = {entry["event"] for entry in left}
    for entry in right:
        if entry["event"] not in names:
            merged.append(entry)
            names.add(entry["event"])
    if len(merged) > MAX_EVENTS:
        raise WorkflowTimelineError("Invalid workflow timeline.")
    return sorted(merged, key=lambda entry: _ORDER[entry["event"]])


def server_event(event: str, *, at: datetime | None = None) -> dict:
    """Create a server-canonical event without accepting a client timestamp."""
    if event not in _ORDER:
        raise WorkflowTimelineError("Invalid workflow timeline.")
    stamp = at or datetime.now(UTC)
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise WorkflowTimelineError("Invalid workflow timeline.")
    return {"event": event, "at": stamp.isoformat()}
