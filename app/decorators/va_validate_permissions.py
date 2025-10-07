import sqlalchemy as sa
from app import db
from functools import wraps
from flask import redirect, url_for
from flask_login import current_user
from app.models import VaSubmissions
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
                return redirect(url_for("va_auth.va_login"))
            va_role = kwargs.get("va_role")
            va_action = kwargs.get("va_action")
            va_actiontype = kwargs.get("va_actiontype")
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
                if not validate_sid and va_actiontype not in ["vastartcoding", "varesumecoding", "varesumereviewing"]:
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
    mapping = {
        "coder": current_user.is_coder(),
        "reviewer": current_user.is_reviewer(),
        "sitepi": current_user.is_site_pi(),
    }
    return mapping.get(role)


def _validate_vacode(actiontype, sid, partial):
    form_id = db.session.scalar(
        sa.select(VaSubmissions.va_form_id).where(VaSubmissions.va_sid == sid)
    )
    if actiontype == "vastartcoding":
        if not current_user.is_coder():
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
        if not current_user.is_coder():
            va_permission_abortwithflash(
                "You lack the VA Coder role required to resume VA coding.", 403
            )
        va_permission_ensureanyallocation("coding")
        if partial:
            va_permission_ensureallocation(sid, "coding")
    elif actiontype == "varecode":
        if not current_user.has_va_form_access(form_id, "coder"):
            va_permission_abortwithflash(
                "You do not have coder access for this VA form.", 403
            )
        if not partial:
            va_permission_ensurenoactiveallocation("coding")
            va_permission_validaterecodelimits(sid)
        else:
            va_permission_ensureallocation(sid, "coding")
    elif actiontype == "vaview":
        if not current_user.has_va_form_access(form_id, "coder"):
            va_permission_abortwithflash(
                "You do not have coder access to view this VA form.", 403
            )
        va_permission_ensureviewable(sid)
    else:
        va_permission_abortwithflash("Unknown coding action requested.", 404)


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
        va_permission_ensurereviewed(sid)
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


_ACTION_VALIDATORS = {
    "vacode": _validate_vacode,
    "vareview": _validate_vareview,
    "vasitepi": _validate_vasitepi,
}
