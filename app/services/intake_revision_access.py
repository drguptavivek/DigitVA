"""Who may open and revise a submitted interview, and open a case's death
report: its owner, or a supervisor (docs/policy/interview-revisions.md
"Supervisor correction").

The owner lookups stay in ``web_intake_service``; this module adds the
supervisor fallback in one place for the draft GET, the revision POST, the
supervision case detail's ``edit_interview`` and the case detail GET. It
imports ``web_intake_service`` lazily: that module imports this one.

A supervisor edits only where they see personal data (``pii_scope``): the
edit screen opens the interview's identifying answers.
"""
import uuid

import sqlalchemy as sa

from app import db
from app.models import VaDeathRegister, VaUsers, VaWebIntakeDraft
from app.services import case_transition_service as cases
from app.services import training_scope
from app.services.case_transition_service import WebIntakeError
from app.services.viewer_pii_service import pii_scope

EDITOR_OWNER = "owner"
EDITOR_SUPERVISOR = "supervisor"


def find_supervised_submission(user: VaUsers, va_sid: str) -> VaWebIntakeDraft | None:
    """The submitted draft holding *va_sid* for a supervisor who may correct
    it (``cases.may_supervisor_edit_interview``) and sees personal data in its
    project (``pii_scope``), or None.

    Only the case's current submission (``death.va_sid``, a completed
    interview): never a superseded, replaced or kept-apart copy, and never a
    partial or refused submission, which no case holds. A consent-withdrawn
    case is sealed and a training case stays in training mode. ODK
    submissions have no draft, so they are never found. At most three
    indexed reads and one EXISTS."""
    death = db.session.scalar(sa.select(VaDeathRegister).where(VaDeathRegister.va_sid == va_sid).limit(1))
    if (death is None or death.consent_withdrawn_at is not None
            or not training_scope.keeps_project(death.project_id)
            or not pii_scope(user).sees(death.project_id)
            or not cases.may_supervisor_edit_interview(user, death)):
        return None
    return db.session.scalar(sa.select(VaWebIntakeDraft).where(
        VaWebIntakeDraft.va_sid == va_sid,
        VaWebIntakeDraft.death_id == death.death_id,
        VaWebIntakeDraft.status == "submitted",
    ).limit(1))


def find_revisable_submission(user: VaUsers, va_sid: str) -> tuple[VaWebIntakeDraft | None, str | None]:
    """``(draft, editor)`` for the submission *va_sid* *user* may revise:
    ``editor`` is ``"owner"`` (``find_own_submission``, tried first so the
    owner wins when both apply) or ``"supervisor"``
    (``find_supervised_submission``); ``(None, None)`` when neither."""
    from app.services import web_intake_service as intake

    draft = intake.find_own_submission(user, va_sid)
    if draft is not None:
        return draft, EDITOR_OWNER
    draft = find_supervised_submission(user, va_sid)
    return (draft, EDITOR_SUPERVISOR) if draft is not None else (None, None)


def draft_reachable_by(user: VaUsers, draft_id: object) -> VaWebIntakeDraft:
    """The caller's own draft (``get_draft``), else the submitted draft *draft_id*
    when *user* may correct it as a supervisor; else 404, as ``get_draft``
    refuses anyone's draft but the owner's. For ``GET /drafts/<id>``."""
    from app.services import web_intake_service as intake

    try:
        return intake.get_draft(user, draft_id)
    except WebIntakeError as exc:
        if exc.status_code != 404:
            raise
    try:
        draft = db.session.get(VaWebIntakeDraft, uuid.UUID(str(draft_id)))
    except ValueError:
        draft = None
    if draft is None or draft.status != "submitted" or not draft.va_sid:
        raise WebIntakeError("Draft not found.", 404)
    found = find_supervised_submission(user, draft.va_sid)
    if found is None or found.draft_id != draft.draft_id:
        raise WebIntakeError("Draft not found.", 404)
    return draft


def case_row_reachable_by(user: VaUsers, death_id: object, *, context: list[dict] | None = None) -> tuple:
    """The case detail row of *death_id*: the interviewer's worklist row
    (``get_case_detail``), else, for a supervisor of the case who sees
    personal data (``get_case_for_supervisor``), its plain row; else 404.
    For ``GET /cases/<id>``."""
    from app.services import web_intake_service as intake

    try:
        return intake.get_case_detail(user, death_id, context=context)
    except WebIntakeError as exc:
        if exc.status_code != 404:
            raise
    return intake.case_row(user, intake.get_case_for_supervisor(user, death_id))


def supervisor_edit_target(user: VaUsers, death: VaDeathRegister) -> dict | None:
    """The supervision case detail's ``edit_interview``: ``{draft_id, va_sid,
    project_id, site_id}`` (what the web interview screen opens in revision
    mode) when *user* may correct *death*'s interview as a supervisor and it
    is revisable now; else None. The interviewer's own submission is theirs
    to revise as its owner, so None for them too."""
    from app.services import web_intake_service as intake

    if not death.va_sid or not intake._revisable_now(death):
        return None
    draft = find_supervised_submission(user, death.va_sid)
    if draft is None or draft.user_id == user.user_id:
        return None
    return {"draft_id": str(draft.draft_id), "va_sid": draft.va_sid,
            "project_id": draft.project_id, "site_id": draft.site_id}
