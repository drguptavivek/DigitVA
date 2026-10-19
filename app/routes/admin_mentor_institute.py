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
import uuid

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
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            raise accounts.UserAccountError("A JSON object is required.")
        for field in ("email", "email_confirm", "name", "phone", "job_title"):
            if field in payload and payload[field] is not None and (
                not isinstance(payload[field], str) or len(payload[field]) > 200
            ):
                raise accounts.UserAccountError(f"Invalid {field}.")
        languages = payload.get("languages")
        if "languages" in payload and (
            not isinstance(languages, list) or len(languages) > 200 or any(
                not isinstance(language, str) for language in languages
            )
        ):
            raise accounts.UserAccountError("Select valid languages.")
        fields = accounts.validate_new_user_payload(
            payload, allow_mobile_only=current_user.is_admin()
        )
        user = mentors.create_staff(institute, fields, actor_user_id=current_user.user_id)
    except accounts.UserAccountError as exc:
        db.session.rollback()
        # Only a platform admin may learn that an email or number is taken.
        taken = isinstance(exc, accounts.EmailInUseError) or str(exc) == accounts.MOBILE_IN_USE_MESSAGE
        return _json_error(
            _GENERIC_CREATE_REFUSAL if taken and not current_user.is_admin() else str(exc), 400
        )
    except OrganizationError as exc:
        db.session.rollback()
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


@admin.get("/panels/mentor-institutes")
@role_required("admin")
def admin_panel_mentor_institutes():
    """Platform configuration of institutes; pages never grant project access."""
    from flask import render_template

    return render_template("admin/panels/mentor_institutes.html")


@admin.get(f"{_API}/platform")
@role_required("admin")
def mentor_institute_platform_details():
    """Bounded cross-project configuration reads, with keyset cursors.

    Each list returns its next cursor; a selected institute limits staff and
    attachments to that institute. No per-row relationship reads are needed.
    """
    from app.models import (
        MapMentorInstituteOrgUnit,
        MasLanguages,
        MasOrgLevel,
        MasOrgUnit,
        VaProjectMaster,
        VaStatuses,
        VaUsers,
    )

    after = request.args.get("after", "")[:32]
    institutes = db.session.scalars(
        sa.select(MasMentorInstitute)
        .where(MasMentorInstitute.institute_code > after)
        .order_by(MasMentorInstitute.institute_code).limit(51)
    ).all()
    result = {
        "institutes": [_serialize_institute(i) for i in institutes[:50]],
        "next": institutes[49].institute_code if len(institutes) > 50 else None,
    }
    code = request.args.get("code")
    if code:
        institute, error = _institute_or_error(code)
        if error:
            return error
        result["institute"] = _serialize_institute(institute)
        try:
            staff_after = uuid.UUID(request.args.get("staff_after", str(uuid.UUID(int=0))))
            district_after = uuid.UUID(request.args.get("district_after", str(uuid.UUID(int=0))))
        except ValueError:
            return _json_error("Invalid page cursor.", 400)
        staff = db.session.execute(
            sa.select(VaUsers, MapMentorInstituteUser)
            .join(MapMentorInstituteUser, MapMentorInstituteUser.user_id == VaUsers.user_id)
            .where(
                MapMentorInstituteUser.institute_id == institute.institute_id,
                MapMentorInstituteUser.is_active.is_(True),
                VaUsers.user_id > staff_after,
            ).order_by(VaUsers.user_id).limit(51)
        ).all()
        result["staff"] = [_serialize_staff(u, link) for u, link in staff[:50]]
        result["staff_next"] = str(staff[49][0].user_id) if len(staff) > 50 else None
        attached = db.session.execute(
            sa.select(MasOrgUnit.org_unit_id, MasOrgUnit.project_id, MasOrgUnit.unit_code, MasOrgUnit.unit_name)
            .join(MapMentorInstituteOrgUnit,
                  MapMentorInstituteOrgUnit.org_unit_id == MasOrgUnit.org_unit_id)
            .where(MapMentorInstituteOrgUnit.institute_id == institute.institute_id,
                   MapMentorInstituteOrgUnit.is_active.is_(True),
                   MasOrgUnit.org_unit_id > district_after)
            .order_by(MasOrgUnit.org_unit_id).limit(101)
        ).all()
        result["districts"] = [dict(r._mapping) for r in attached[:100]]
        result["districts_next"] = str(attached[99].org_unit_id) if len(attached) > 100 else None
    project_id = request.args.get("project_id", "")[:6]
    unit_after = request.args.get("unit_after", "")[:64]
    units = db.session.execute(
        sa.select(MasOrgUnit.project_id, MasOrgUnit.unit_code, MasOrgUnit.unit_name)
        .join(MasOrgLevel, MasOrgLevel.org_level_id == MasOrgUnit.org_level_id)
        .join(VaProjectMaster, VaProjectMaster.project_id == MasOrgUnit.project_id)
        .where(
            MasOrgUnit.project_id == project_id, MasOrgUnit.unit_code > unit_after,
            MasOrgUnit.is_active.is_(True), MasOrgLevel.depth == 1,
            VaProjectMaster.project_structure_mode == "organization",
            VaProjectMaster.project_status == VaStatuses.active,
        ).order_by(MasOrgUnit.unit_code).limit(51)
    ).all()
    result["available_districts"] = [dict(r._mapping) for r in units[:50]]
    result["units_next"] = units[49].unit_code if len(units) > 50 else None
    result["languages"] = [dict(r._mapping) for r in db.session.execute(
        sa.select(MasLanguages.language_code, MasLanguages.language_name)
        .where(MasLanguages.is_active.is_(True))
        .order_by(MasLanguages.language_code).limit(200)
    )]
    response = jsonify(result)
    response.headers["Cache-Control"] = "no-store"
    return response


@admin.post(f"{_API}/platform")
@role_required("admin")
def mentor_institute_platform_update():
    """Validated platform-only writes through the audited institute service.

    Caller supplies one allowlisted action; membership and attachments never
    create grants. Any refused write rolls back the entire transaction.
    """
    from app.models import MasOrgUnit, VaProjectMaster, VaStatuses

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _json_error("A JSON object is required.", 400)
    allowed = {"action", "code", "name", "active", "email", "is_admin", "project_id", "unit_code", "user_id"}
    if set(data) - allowed:
        return _json_error("Unknown configuration field.", 400)
    for key in ("action", "code", "name", "email", "project_id", "unit_code", "user_id"):
        if key in data and (not isinstance(data[key], str) or len(data[key]) > 200):
            return _json_error(f"Invalid {key}.", 400)
    for key in ("active", "is_admin"):
        if key in data and type(data[key]) is not bool:
            return _json_error(f"{key} must be true or false.", 400)
    action = data.get("action")
    code = data.get("code", "")
    actor = current_user.user_id
    try:
        if action == "create":
            mentors.create_institute(code, data.get("name", ""), actor_user_id=actor)
        else:
            institute, error = _institute_or_error(code)
            if error:
                return error
            if action == "status" and "active" in data:
                mentors.set_institute_active(code, data["active"], actor_user_id=actor)
            elif action in {"attach", "detach"}:
                project_id = data.get("project_id", "")
                unit_code = data.get("unit_code", "")
                if action == "attach":
                    project = db.session.get(VaProjectMaster, project_id)
                    unit = db.session.scalar(sa.select(MasOrgUnit).where(
                        MasOrgUnit.project_id == project_id, MasOrgUnit.unit_code == unit_code
                    ))
                    if (not institute.is_active or project is None
                            or project.project_structure_mode != "organization"
                            or project.project_status != VaStatuses.active
                            or unit is None or not unit.is_active):
                        raise OrganizationError("Select an active organization project and district, and an active institute.")
                method = mentors.attach_district if action == "attach" else mentors.detach_district
                method(code, project_id, unit_code, actor_user_id=actor)
            elif action == "link":
                if not institute.is_active:
                    raise OrganizationError("That institute is inactive.")
                conflicts = mentors.add_member(code, data.get("email", ""), user_id=data.get("user_id"), actor_user_id=actor)
                if conflicts:
                    raise OrganizationError("This account has incompatible grants; review them before linking institute staff.")
            elif action == "set-admin" and "is_admin" in data:
                mentors.set_member_admin(code, data.get("email", ""), data["is_admin"], user_id=data.get("user_id"), actor_user_id=actor)
            else:
                raise OrganizationError("Invalid configuration action or missing field.")
    except OrganizationError as exc:
        db.session.rollback()
        return _json_error(str(exc), 400)
    except sa.exc.IntegrityError:
        db.session.rollback()
        return _json_error("Configuration changed concurrently. Refresh and retry.", 409)
    try:
        db.session.commit()
    except sa.exc.IntegrityError:
        db.session.rollback()
        return _json_error("Configuration changed concurrently. Refresh and retry.", 409)
    return jsonify({"ok": True})
