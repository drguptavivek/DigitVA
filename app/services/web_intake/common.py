"""Constants and small helpers every web intake module shares: instrument ids, regexes, the clock and device-time readers.

Part of the web intake service split (bead digitva-r8nh.12); the public
module is ``app.services.web_intake_service``, which re-exports every name.
Code that tests patch on that module is read back through ``facade()``.
"""
from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta

import pytz

from app.models import (
    VaProjectMaster,
    VaUsers,
    VaWebIntakeDraft,
)
from app.services.case_transition_service import WebIntakeError

# One logger for the whole web intake path, under the name it always had.
log = logging.getLogger("app.services.web_intake_service")


INSTRUMENT_ID = "va_who_2022"


ATTACHMENT_REFERENCE_PREFIX = "who-va-attachment:"


AUDIT_ROLE = "vainterviewer"


PAYLOAD_ROLE = "vainterviewer"


#: ``YYYY`` or ``YYYY-MM``: a birth date whose day (or day and month) is unknown.
_PARTIAL_DATE_RE = re.compile(r"^\d{4}(-(0[1-9]|1[0-2]))?$", re.ASCII)


#: The earliest plausible birth year; the WHO dob_year constraint's floor.
PARTIAL_BIRTH_MIN_YEAR = 1900


_ABHA_NUMBER_RE = re.compile(r"^(\d{14}|\d{2}-\d{4}-\d{4}-\d{4})$")


_ABHA_ADDRESS_RE = re.compile(r"^[A-Za-z0-9._]{4,32}@(abdm|sbx)$")


# Phone: exactly 10 digits, optionally after +91, 91 or 0.
_SECTION_NAME_RE = re.compile(r"^[A-Za-z0-9_]{1,64}$")


#: An instrument locale code as the XLSForm writes it ("hi", "kha", "pt-BR").
_LOCALE_CODE_RE = re.compile(r"^[A-Za-z0-9-]{2,16}$")


#: The welcome note a project shows before the questionnaire starts when it
#: has not written one of its own. A constant rather than a stored default so
#: the wording can change without a migration: a NULL
#: ``web_intake_intake_note`` resolves to this text, an empty string means the
#: project wants no welcome screen. Decided 2026-09-19,
#: docs/policy/va-web-form-options.md.
DEFAULT_INTAKE_NOTE = (
    "Before you begin: confirm the respondent has consented, is comfortable, "
    "and has time for the interview. Answers are saved as you go."
)


#: What a project that collects on the web is created with when the client
#: says nothing (docs/planning/web-capture-project-configuration-plan.md, WP1).
#: Applied by POST /admin/api/projects to every key the payload omits whenever
#: ``web_intake_mode`` is not ``off``; an explicit value always wins. The two
#: language lists are filtered to the codes the validators accept before they
#: are applied, so a deployment that has not vendored Hindi translations or
#: seeded the language rows still creates the project instead of failing it.
WEB_PROJECT_DEFAULTS = {
    "web_intake_form_type_code": "WHO_2022_VA",
    "web_intake_intake_note": None,
    "web_intake_death_summary_enabled": True,
    "web_intake_medical_records_enabled": True,
    "web_intake_equity_enabled": True,
    "social_autopsy_enabled": False,
    "web_intake_available_locales": ["en", "hi"],
    "web_intake_narration_languages": ["english", "hindi"],
    "coding_intake_mode": "pick_and_choose",
}


def resolve_intake_note(project: VaProjectMaster) -> str:
    """The welcome note this project shows, ``""`` when it shows none.

    NULL is "the project never set one", which is the system default text;
    a stored empty (or whitespace-only) string is a project that deliberately
    turned the welcome screen off. The ``intake_screen`` extension is served
    exactly when this is non-empty.
    """
    note = project.web_intake_intake_note
    if note is None:
        return DEFAULT_INTAKE_NOTE
    return note.strip()


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _expression_now(user: VaUsers, at: datetime) -> datetime:
    """``at`` read in the interviewer's own timezone, for the expression
    evaluator's ``today()`` -- the same "whatever the device considers
    local" the browser's ``formatLocalDate`` uses (see
    docs/policy/xform-expression-evaluator.md). Falls back to this
    application's primary deployment timezone, matching
    ``app._current_user_timezone``."""
    tz_name = getattr(user, "timezone", None) or "Asia/Kolkata"
    try:
        tz = pytz.timezone(tz_name)
    except pytz.UnknownTimeZoneError:
        tz = pytz.timezone("Asia/Kolkata")
    return at.astimezone(tz)


def _device_time(value: object) -> datetime | None:
    """An ISO 8601 time with a UTC offset, in that offset; None for anything
    else (not text, unparsable, or no offset -- an offset-less time cannot
    be placed, docs/policy/field-data-collection.md "Interview times")."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


#: The phone's measured clock offset (phone minus server) is kept within a year
#: (a wilder value is clamped, never refused: the upload must not be lost). An
#: offset past 4 h (the owner's block rule) or a start or completion time more
#: than 10 min ahead of the server marks the upload as clock-suspect.
_MAX_CLOCK_OFFSET_SECONDS = 366 * 86400


_CLOCK_BLOCK_SECONDS = 4 * 3600


_FUTURE_TOLERANCE = timedelta(minutes=10)


def _clock_meta(envelope: dict, now: datetime) -> dict:
    """Meta for the device clock: ``clockOffsetSeconds`` when the envelope
    carries one, and ``clockSuspect`` when the offset or a future start or
    completion time says the phone's clock was wrong. Audit and display only."""
    out: dict = {}
    offset = envelope.get("clockOffsetSeconds")
    if offset is not None:
        out["clockOffsetSeconds"] = max(-_MAX_CLOCK_OFFSET_SECONDS, min(_MAX_CLOCK_OFFSET_SECONDS, offset))
    times = [_device_time(envelope.get(k)) for k in ("startedAt", "completedAt")]
    if abs(out.get("clockOffsetSeconds", 0)) > _CLOCK_BLOCK_SECONDS or any(
        t is not None and t > now + _FUTURE_TOLERANCE for t in times
    ):
        out["clockSuspect"] = True
    return out


def _completion_time(envelope: dict, now: datetime) -> datetime:
    """When the interview was completed, in server time: the device's
    ``completedAt`` corrected by its clock drift (``now - deviceClockAt`` is
    how far the device runs behind, as in ``sync_device_draft``) and never
    later than *now*. Without both times (a browser submit, an older app) it
    is *now*, the moment the server received it."""
    done, clock = _device_time(envelope.get("completedAt")), _device_time(envelope.get("deviceClockAt"))
    if done is None or clock is None:
        return now
    return min(now, now - (clock - done))


def draft_is_stale(draft: VaWebIntakeDraft, if_updated_at: object) -> bool:
    """True when a browser save made on an older view (*if_updated_at*, the
    ``updated_at`` of the last reply it saw) would overwrite a newer version.
    400 when not an ISO 8601 time with an offset."""
    seen = _device_time(if_updated_at)
    if seen is None:
        raise WebIntakeError("if_updated_at must be an ISO 8601 time with a UTC offset.")
    return seen != draft.updated_at
