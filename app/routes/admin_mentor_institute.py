"""Mentoring-institute staff API: an institute admin manages their own staff.

Thin HTTP layer over ``app.services.mentor_institute_service`` and
``app.services.user_account_service``; routes hang off the ``admin`` blueprint
(``/admin/api/mentor-institutes/...``). A platform admin may use them for any
institute; an institute admin (flag on the membership) only for their own, and
never sees another institute. Nothing here reads or writes grants: an
institute cannot widen its own access. Policy: docs/policy/organization-model.md,
"Mentoring institutes".
"""
import logging

import sqlalchemy as sa
from flask import jsonify, request
from flask_limiter.util import get_remote_address
from flask_login import current_user

from app import db, limiter
from app.decorators import role_required
from app.models import MapMentorInstituteUser, MasMentorInstitute
from app.routes.admin import _json_error, admin
from app.services import mentor_institute_service as mentors
from app.services import user_account_service as accounts
from app.services.organization_service import OrganizationError

log = logging.getLogger(__name__)

_API = "/api/mentor-institutes"

# Account creations per institute per day, shared by its admins; platform
# admins are exempt. Counted per attempt, so probing for registered addresses
# is capped too.
STAFF_CREATE_LIMIT = "20 per day"
_GENERIC_CREATE_REFUSAL = "Could not create this account. Contact a platform administrator."


def _create_limit_key():
    """The institute's bucket for someone who may manage it; their own bucket
    otherwise, so nobody can burn another institute's allowance."""
    if not current_user.is_authenticated:
        return get_remote_address()
    code = str((request.view_args or {}).get("code", "")).strip().upper().replace("-", "_")
    if any(i.institute_code == code for i in mentors.administered_institutes(current_user.user_id)):
        return f"mentor-staff-create:{code}"
    return f"user:{current_user.get_id()}"


def _serialize_institute(institute):
    return {
        "institute_code": institute.institute_code,
        "institute_name": institute.institute_name,
        "is_active": institute.is_active,
    }


def _serialize_staff(user, link):
    return {
        "user_id": str(user.user_id),
        "email": user.email,
        "name": user.name,
        "job_title": user.job_title,
        "is_admin": link.is_admin,
        "account_status": user.user_status.value,
    }


def _institute_or_error(code):
    """(institute, None) when the caller may manage that institute's staff,
    else (None, error response). 404 only for a platform admin: anyone else
    gets the same 403 for an unknown and for another institute's code."""
    try:
        return mentors.institute_for_staff_management(current_user, code), None
    except OrganizationError as exc:
        status = 404 if current_user.is_admin() else 403
        return None, _json_error(str(exc), status)


@admin.get(_API)
@role_required("admin", "mentor_institute_admin")
def mentor_institutes():
    """Institutes the caller may manage: all for a platform admin, else their own."""
    if current_user.is_admin():
        institutes = db.session.scalars(
            sa.select(MasMentorInstitute).order_by(MasMentorInstitute.institute_code)
        ).all()
    else:
        institutes = mentors.administered_institutes(current_user.user_id)
    return jsonify({"institutes": [_serialize_institute(i) for i in institutes]})


@admin.get(f"{_API}/<code>/staff")
@role_required("admin", "mentor_institute_admin")
def mentor_institute_staff(code):
    institute, error = _institute_or_error(code)
    if error:
        return error
    staff = mentors.list_staff(institute)
    return jsonify({"staff": [_serialize_staff(u, link) for u, link in staff]})


@admin.post(f"{_API}/<code>/staff")
@role_required("admin", "mentor_institute_admin")
@limiter.limit(
    STAFF_CREATE_LIMIT,
    key_func=_create_limit_key,
    exempt_when=lambda: current_user.is_authenticated and current_user.is_admin(),
    override_defaults=False,
)
def mentor_institute_create_staff(code):
    """Create an account that is staff of this institute: with an email (a
    verification email follows) or -- platform admin only -- with a mobile
    number only, whose first sign-in code is returned once in this no-store
    response (account-onboarding-and-passwords.md section 5)."""
    from app.services import mobile_sign_in_service

    institute, error = _institute_or_error(code)
    if error:
        return error
    try:
        # Mobile-only accounts (and their codes) from a platform admin only,
        # as in the project import; an institute admin must give an email.
        fields = accounts.validate_new_user_payload(
            request.get_json(silent=True) or {}, allow_mobile_only=current_user.is_admin()
        )
        user = mentors.create_staff(institute, fields, actor_user_id=current_user.user_id)
    except accounts.UserAccountError as exc:
        # Only a platform admin may learn that an email or number is taken.
        taken = isinstance(exc, accounts.EmailInUseError) or str(exc) == accounts.MOBILE_IN_USE_MESSAGE
        return _json_error(
            _GENERIC_CREATE_REFUSAL if taken and not current_user.is_admin() else str(exc), 400
        )
    except OrganizationError as exc:
        return _json_error(str(exc), 400)
    code_for_holder = None
    if user.is_mobile_only:
        code_for_holder = mobile_sign_in_service.issue_code(user, actor_user_id=current_user.user_id)
    db.session.commit()
    accounts.send_invitation(user, actor_user_id=current_user.user_id)
    link = db.session.get(MapMentorInstituteUser, (institute.institute_id, user.user_id))
    body = {"staff": _serialize_staff(user, link)}
    if code_for_holder:
        body["sign_in_code"] = code_for_holder
    response = jsonify(body)
    response.headers["Cache-Control"] = "no-store"
    return response, 201


@admin.post(f"{_API}/<code>/staff/<uuid:user_id>/remove")
@role_required("admin", "mentor_institute_admin")
def mentor_institute_remove_staff(code, user_id):
    """Remove a person from this institute's staff; their in-institute mentor
    grants are deactivated with the membership."""
    institute, error = _institute_or_error(code)
    if error:
        return error
    try:
        deactivated, grants = mentors.remove_staff(
            institute,
            user_id,
            actor_user_id=current_user.user_id,
            actor_is_platform_admin=current_user.is_admin(),
        )
    except OrganizationError as exc:
        db.session.rollback()
        return _json_error(str(exc), 400)
    db.session.commit()
    return jsonify(
        {
            "user_id": str(user_id),
            "account_deactivated": deactivated,
            "grants_deactivated": grants,
        }
    )
