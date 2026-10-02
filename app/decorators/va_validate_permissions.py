import sqlalchemy as sa
from app import db
from functools import wraps
from flask import redirect, url_for, request
from flask_login import current_user
from app.models import VaForms, VaSubmissions, VaSubmissionWorkflow
from app.services.workflow.definition import CODER_READY_POOL_STATES
from app.services.workflow.intake_modes import (
    CODING_INTAKE_PICK,
    get_project_coding_intake_mode,
)
from app.services.demo_project_service import is_demo_training_submission
from app.services.duplicate_exclusion import DUPLICATE_MESSAGE, is_confirmed_duplicate
from app.services.odk_retirement_service import RETIRED_MESSAGE, is_submission_retired
from app.utils import (
    va_permission_abortwithflash,
    va_permission_ensureallocation,
    va_permission_ensureanyallocation,
    va_permission_ensurenoactiveallocation,
    va_permission_validaterecodelimits,
    va_permission_ensureviewable,
    va_permission_ensurenotreviewed,
    va_permission_ensurereviewed,
    va_permission_ensurecoded,
    va_permission_reviewedonce,
)


def va_validate_permissions():
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if current_user.is_anonymous:
                return redirect(url_for("va_auth.va_login", next=request.url))
            va_role = kwargs.get("va_role")
            va_action = kwargs.get("va_action") or request.values.get("action")
            va_actiontype = kwargs.get("va_actiontype") or request.values.get("actiontype")
            va_sid = kwargs.get("va_sid")
            va_partial = kwargs.get("va_partial")
            if va_role and not any([va_action, va_actiontype, va_sid, va_partial]):
                if not va_hasrole(va_role):
                    va_permission_abortwithflash(
                        f"You don't have permission to access the '{va_role}' dashboard.",
                        403,
                    )
            elif va_action:
                validate_sid = db.session.scalar(sa.select(VaSubmissions.va_sid).where(VaSubmissions.va_sid == va_sid))
                if not validate_sid and va_actiontype not in ["vastartcoding", "vademo_start_coding", "varesumecoding", "varesumereviewing"]:
                    va_permission_abortwithflash("Invalid va_sid in the URL. Please verify and try again.", 404)
                validator = _ACTION_VALIDATORS.get(va_action)
                if not validator:
                    va_permission_abortwithflash("Invalid VA action token in URL.", 404)
                validator(actiontype=va_actiontype, sid=va_sid, partial=va_partial)
            else:
                va_permission_abortwithflash(
                    "The requested URL appears invalid or expired. Please verify and try again.",
                    404,
                )
            return func(*args, **kwargs)

        return wrapper

    return decorator


def va_hasrole(role):
    if current_user.is_admin():
        return True
    mapping = {
        "coder": current_user.is_coder() or current_user.is_coding_tester(),
        "reviewer": current_user.is_reviewer(),
        "sitepi": current_user.is_site_pi(),
        "data_manager": current_user.is_data_manager(),
    }
    return mapping.get(role)


def _has_coding_role() -> bool:
    return current_user.is_coder() or current_user.is_coding_tester()


def _require(action, sid: str) -> None:
    """``authz.require``, refusing with a flash the way allocation errors do."""
    from app.services.authz import AuthzError, require

    try:
        require(current_user, action, sid)
    except AuthzError as e:
        va_permission_abortwithflash(e.message, e.status_code)


def _require_coding_scope(actiontype, sid: str | None) -> None:
    """One authz check for a coding action on one submission.

    VIEW for ``vaview``, RECODE for ``varecode``, CODE for the rest; no
    submission (the start / resume shells) means nothing to check yet.
    """
    if not sid:
        return
    from app.services.authz import Action

    if actiontype == "vaview":
        action = Action.VIEW
    elif actiontype == "varecode":
        action = Action.RECODE
    else:
        action = Action.CODE
    _require(action, sid)


def _validate_vacode(actiontype, sid, partial):
    form_id = db.session.scalar(
        sa.select(VaSubmissions.va_form_id).where(VaSubmissions.va_sid == sid)
    )
    # Admin demo coding is its own path (start_demo_allocation); admin holds
    # no CODE bypass, so it returns before the scope check.
    if actiontype == "vademo_start_coding" and current_user.is_admin():
        return
    # Scope is checked once here, for every coding action, so a new action
    # cannot miss it: form, project-site and unit scope are all authz's.
    # Viewing is the wider right (a grant above the coding scope level still
    # oversees its subtree), so ``vaview`` asks VIEW, not CODE.
    # Policy: docs/policy/organization-model.md.
    _require_coding_scope(actiontype, sid)
    if actiontype == "vastartcoding":
        if not _has_coding_role():
            va_permission_abortwithflash(
                "You lack the VA Coder role required to start coding.", 403
            )
        if current_user.vacode_formcount >= 200:
            va_permission_abortwithflash(
                "You have reached your yearly limit of 200 coded VA forms.", 403
            )
        if partial:
            va_permission_ensureallocation(sid, "coding")
    elif actiontype == "varesumecoding":
        if not _has_coding_role():
            va_permission_abortwithflash(
                "You lack the VA Coder role required to resume VA coding.", 403
            )
        va_permission_ensureanyallocation("coding")
        if partial:
            va_permission_ensureallocation(sid, "coding")
    elif actiontype == "varecode":
        if not partial:
            va_permission_ensurenoactiveallocation("coding")
            va_permission_validaterecodelimits(sid)
        else:
            va_permission_ensureallocation(sid, "coding")
    elif actiontype == "vapickcoding":
        if current_user.vacode_formcount >= 200:
            va_permission_abortwithflash(
                "You have reached your yearly limit of 200 coded VA forms.", 403
            )
        if partial:
            va_permission_ensureallocation(sid, "coding")
            return
        project_id = db.session.scalar(
            sa.select(VaForms.project_id).where(VaForms.form_id == form_id)
        )
        if get_project_coding_intake_mode(project_id) != CODING_INTAKE_PICK:
            va_permission_abortwithflash(
                "This project does not use pick-and-choose coding.", 403
            )
        va_permission_ensurenoactiveallocation("coding")
        workflow_state = db.session.scalar(
            sa.select(VaSubmissionWorkflow.workflow_state).where(
                VaSubmissionWorkflow.va_sid == sid
            )
        )
        if workflow_state not in CODER_READY_POOL_STATES:
            va_permission_abortwithflash(
                "This submission is no longer available for coding.", 409
            )
        # Retired-from-ODK submissions are not codeable; existing allocations
        # are handled by the resume actions above and are left untouched.
        # See docs/policy/odk-retired-submissions.md.
        if is_submission_retired(sid):
            va_permission_abortwithflash(RETIRED_MESSAGE, 409)
        if is_confirmed_duplicate(sid):
            va_permission_abortwithflash(DUPLICATE_MESSAGE, 409)
    elif actiontype == "vademo_start_coding":
        if not _has_coding_role():
            va_permission_abortwithflash(
                "Coder access is required for demo project coding.", 403
            )
        if not sid or not is_demo_training_submission(sid):
            va_permission_abortwithflash(
                "Only admin users can start a demo coding session on non-demo projects.",
                403,
            )
        va_permission_ensureallocation(sid, "coding")
    elif actiontype == "vaview":
        va_permission_ensureviewable(sid)
    else:
        va_permission_abortwithflash("Unknown coding action requested.", 404)


def _within_reviewing_org_scope(sid: str | None) -> bool:
    """Unit-scope gate for a reviewing action on one submission."""
    if not sid:
        return True
    from app.models import VaAccessRoles
    from app.services.org_grant_service import submission_within_org_scope

    return submission_within_org_scope(current_user, sid, VaAccessRoles.reviewer)


def _validate_vareview(actiontype, sid, partial):
    form = (
        db.session.execute(
            sa.select(
                VaSubmissions.va_form_id, VaSubmissions.va_narration_language
            ).where(VaSubmissions.va_sid == sid)
        )
        .mappings()
        .first()
    )
    form_id = form["va_form_id"] if form and form["va_form_id"] else None
    form_lang = (
        form["va_narration_language"]
        if form and form["va_narration_language"]
        else None
    )
    # Same unit-scope rule as coding, with reviewer grants. Checked once for
    # every reviewing action. No-op for projects without an organization tree.
    if not _within_reviewing_org_scope(sid):
        va_permission_abortwithflash(
            "This submission belongs to a unit outside your reviewing scope.", 403
        )
    if actiontype == "vastartreviewing":
        if not partial:
            if not current_user.has_va_form_access(form_id, "reviewer"):
                va_permission_abortwithflash(
                    "Reviewer access is required to access this VA form.", 403
                )
            if form_lang not in current_user.vacode_language:
                va_permission_abortwithflash(
                    f"Your profile does not support reviewing forms in {form_lang}.",
                    403,
                )
            if is_submission_retired(sid):
                va_permission_abortwithflash(RETIRED_MESSAGE, 409)
            va_permission_ensurenotreviewed(sid)
        else:
            va_permission_ensureallocation(sid, "reviewing")
    elif actiontype == "varesumereviewing":
        if not partial:
            if not current_user.is_reviewer():
                va_permission_abortwithflash(
                    "You lack the VA Reviewer role required to resume reviewing.", 403
                )
            va_permission_ensureanyallocation("reviewing")
        else:
            va_permission_ensureallocation(sid, "reviewing")
    elif actiontype == "vaview":
        if not current_user.has_va_form_access(form_id, "reviewer"):
            va_permission_abortwithflash(
                "You do not have reviewer access to view this form.", 403
            )
    else:
        va_permission_abortwithflash("Unknown reviewing action requested.", 404)


def _validate_vasitepi(actiontype, sid, partial):
    form_id = db.session.scalar(
        sa.select(VaSubmissions.va_form_id).where(VaSubmissions.va_sid == sid)
    )
    if not current_user.has_va_form_access(form_id, "sitepi"):
        va_permission_abortwithflash(
            "VA Site PI access is required for this operation.", 403
        )
    if actiontype == "varecode":
        va_permission_ensurecoded(sid)
    elif actiontype == "varereview":
        va_permission_reviewedonce(sid)
    elif actiontype == "vaview":
        pass
    else:
        va_permission_abortwithflash("Unknown SitePI dashboard action requested.", 404)


def _validate_read_only(actiontype, sid, partial):
    """``vadata`` (the data-manager rendering) and ``vaarea`` (the area and
    viewer rendering): opening the submission read-only needs ``VIEW``.

    Read partials need nothing more. The one write partial these renderings
    reach, the data-manager triage panel, requires ``TRIAGE`` in its own
    handler (``va_form._require_partial_write``), so widening the read to
    every viewer does not widen the write. Design: digitva-0wc section 2.4.
    """
    from app.services.authz import Action

    _require(Action.VIEW, sid)
    if actiontype != "vaview":
        va_permission_abortwithflash("Unknown read-only action requested.", 404)


_ACTION_VALIDATORS = {
    "vacode": _validate_vacode,
    "vareview": _validate_vareview,
    "vasitepi": _validate_vasitepi,
    "vadata": _validate_read_only,
    "vaarea": _validate_read_only,
}
