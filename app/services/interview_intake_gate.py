"""The refusal-transition rule of the intake write routes (digitva-r8nh.9).

Every interview write (browser save and submit, phone upload and resend,
revision) asks the same question before it stores answers: does this
transition refuse the interview? That is WHO consent (``Id10013`` no), a
case refusal hold, the consent sent, or the newest consent on file for the
attempt, on the case's current register row (``consent_service.
interview_refused``). How a refusal is reported stays with each route: the
error code, status and message are part of the old-APK contract.
Policy: docs/policy/respondent-consent-notice-draft.md,
docs/policy/web-intake.md.
"""
import uuid

from app import db
from app.models import VaDeathRegister
from app.services import consent_service


def check_refusal_transition(*, death_id: uuid.UUID | None, client_draft_id: uuid.UUID | None,
                             answers: dict, consent=None) -> bool:
    """Whether storing *answers* (with *consent*, the decision sent, if any)
    for the attempt *client_draft_id* of case *death_id* is a refusal.

    The case row is read here, at the moment of the check (None without a
    case): a check made after the case lock sees the locked row."""
    death = db.session.get(VaDeathRegister, death_id) if death_id else None
    return consent_service.interview_refused(
        death=death, client_draft_id=client_draft_id, answers=answers, consent=consent,
    )
