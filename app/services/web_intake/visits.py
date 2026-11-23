"""Visits, contact attempts and pause (phase 5, digitva-vzk.9).

Part of the web intake service split (bead digitva-r8nh.12); the public
module is ``app.services.web_intake_service``, which re-exports every name.
Code that tests patch on that module is read back through ``facade()``.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app import db
from app.models import (
    MapCaseContactAttempt,
    VaDeathRegister,
    VaUsers,
)
from app.models.va_web_intake import (
    CONTACT_OUTCOMES,
)
from app.services import case_transition_service as cases
from app.services.case_transition_service import WebIntakeError
from app.services.web_intake import facade
from app.services.web_intake.register import (
    _clean,
    get_death,
)

#: Pause reason codes (a code, never free text: the audit reason holds no PII).
PAUSE_REASONS = ("respondent_busy", "respondent_left", "needs_other_respondent", "other")


#: Cases waiting for a visit: a visit date may be set and attempts logged.
_VISIT_STATES = frozenset({"registered", "scheduled", "not_reachable", "paused"})


_VISIT_PAST = timedelta(days=1)


_VISIT_AHEAD = timedelta(days=366)


def _clean_visit_at(raw: object) -> datetime | None:
    """An ISO date-time with a timezone, from yesterday to a year ahead, or None."""
    value = _clean(raw, what="Visit date")
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        parsed = None
    if parsed is None or parsed.tzinfo is None:
        raise WebIntakeError("Visit date must be a date and time with a timezone.")
    now = facade()._utcnow()
    if not now - _VISIT_PAST <= parsed <= now + _VISIT_AHEAD:
        raise WebIntakeError("Visit date must be between yesterday and a year from now.")
    return parsed.astimezone(UTC)


def _waiting_case(user: VaUsers, death_id: object) -> VaDeathRegister:
    """A case in scope (else 404), row-locked, that is waiting for a visit (else 409)."""
    death = cases.lock_case(get_death(user, death_id))
    if death.status not in _VISIT_STATES:
        raise WebIntakeError("Only a case waiting for a visit can take a visit date or a contact attempt.", 409)
    return death


def set_visit(user: VaUsers, death_id: object, *, next_visit_at: object | None) -> VaDeathRegister:
    """Set or clear a case's next visit (appointment or follow-up).

    Setting moves registered / not_reachable to ``scheduled``; on a scheduled
    or paused case it only changes the date. Clearing moves ``scheduled`` back
    to ``registered``; elsewhere it only clears the date.
    """
    visit_at = _clean_visit_at(next_visit_at)
    death = _waiting_case(user, death_id)
    death.next_visit_at = visit_at
    if visit_at is not None and death.status in ("registered", "not_reachable"):
        cases.transition(death, "scheduled", actor=user, action="visit_scheduled")
    elif visit_at is None and death.status == "scheduled":
        cases.transition(death, "registered", actor=user, action="visit_cleared")
    db.session.flush()
    return death


def log_contact_attempt(user: VaUsers, death_id: object, *, outcome: str,
                        next_visit_at: object | None = None,
                        client_attempt_id: uuid.UUID | None = None) -> VaDeathRegister:
    """Record one contact attempt and move the case by its outcome.

    - ``refused``: the case becomes ``refused``; its visit date is cleared (a
      next date is refused).
    - ``no_answer`` / ``wrong_number`` / ``moved``: ``not_reachable`` (stays
      so if already), next visit = the given date or none.
    - ``reached``: with a date, registered / not_reachable become
      ``scheduled`` and a scheduled or paused case takes the new date; without
      one nothing changes but the contact time.
    """
    if outcome not in CONTACT_OUTCOMES:
        raise WebIntakeError("Outcome must be one of " + ", ".join(CONTACT_OUTCOMES) + ".")
    visit_at = _clean_visit_at(next_visit_at)
    if outcome == "refused" and visit_at is not None:
        raise WebIntakeError("A refusal takes no next visit date.")
    death = _waiting_case(user, death_id)
    now = facade()._utcnow()
    db.session.add(MapCaseContactAttempt(
        death_id=death.death_id, attempted_at=now, outcome=outcome,
        next_visit_at=visit_at, by_user_id=user.user_id, client_attempt_id=client_attempt_id,
    ))
    death.last_contact_at = now
    if outcome == "refused":
        death.next_visit_at = None
        cases.transition(death, "refused", actor=user, action="contact_refused")
    elif outcome == "reached":
        if visit_at is not None:
            death.next_visit_at = visit_at
            if death.status in ("registered", "not_reachable"):
                cases.transition(death, "scheduled", actor=user, action="contact_reached")
    else:
        death.next_visit_at = visit_at
        if death.status != "not_reachable":
            cases.transition(death, "not_reachable", actor=user, action=f"contact_{outcome}")
    db.session.flush()
    return death


def pause_interview(user: VaUsers, death_id: object, *, reason: str,
                    next_visit_at: object | None = None) -> VaDeathRegister:
    """Pause an in-progress interview with a reason code and optional revisit
    date. Resuming is starting the draft again (``start_draft``)."""
    if reason not in PAUSE_REASONS:
        raise WebIntakeError("Reason must be one of " + ", ".join(PAUSE_REASONS) + ".")
    visit_at = _clean_visit_at(next_visit_at)
    death = cases.lock_case(get_death(user, death_id))
    # Only an interview in progress pauses; a submitted case leaves coding only
    # through its submitter's later version (revise_submission).
    if death.status != "in_progress":
        raise WebIntakeError("Only an interview in progress can be paused.", 409)
    death.next_visit_at = visit_at
    cases.transition(death, "paused", actor=user, action="interview_paused", reason=reason)
    return death
