"""Data management blueprint — /data-management/

Page routes and JSON API routes for data-manager user/grant management.
Submission-related JSON API routes live in app/routes/api/data_management.py.
Shared helpers live in app/services/data_management_service.py.
"""

import logging
import uuid
import secrets

import sqlalchemy as sa
from flask import Blueprint, g, jsonify, redirect, render_template, request
from flask_login import current_user
from flask_wtf.csrf import generate_csrf
from functools import wraps

from app import db
from app.decorators import role_required
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaForms,
    VaProjectMaster,
    VaProjectSites,
    VaSiteMaster,
    VaStatuses,
    VaSubmissions,
    VaUserAccessGrants,
    VaUsers,
)
from app.routes.admin import (
    _grant_project_id_expression,
    _grant_site_id_expression,
    _json_error,
    _resolve_scope_from_payload,
    _serialize_grant,
    _serialize_project,
    _serialize_project_site,
    _serialize_user,
)
from app.services.submission_analytics_mv import get_dm_kpi_from_mv
from app.services.data_management_service import (
    dm_odk_edit_url,
    audit_dm_submission_action,
)
from app.utils.va_permission.va_permission_01_abortwithflash import (
    va_permission_abortwithflash,
)

data_management = Blueprint("data_management", __name__)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dm_can_manage_scope(user, role, scope_type, resolved_project_id, project_site_id):
    """Return (ok, error_message) for whether *user* can create/toggle a grant."""
    if user.is_admin():
        if role not in {VaAccessRoles.coder, VaAccessRoles.data_manager}:
            return False, "Only coder or data_manager roles may be assigned from this interface."
        return True, None
    if role not in {VaAccessRoles.coder, VaAccessRoles.data_manager}:
        return False, "Data-managers may only assign coder or data_manager roles."

    dm_projects = user.get_data_manager_projects()
    dm_site_pairs = user.get_data_manager_project_sites()

    if scope_type == VaAccessScopeTypes.project:
        if resolved_project_id not in dm_projects:
            return False, "You do not have access to assign grants at project level for this project."
        return True, None

    if scope_type == VaAccessScopeTypes.project_site:
        ps = db.session.get(VaProjectSites, project_site_id)
        if not ps or ps.project_site_status != VaStatuses.active:
            return False, "Active project-site mapping not found."
        # Project-scoped DM covers all sites in their project
        if ps.project_id in dm_projects:
            return True, None
        # Site-scoped DM covers only their specific sites
        if (ps.project_id, ps.site_id) in dm_site_pairs:
            return True, None
        return False, "You do not have access to assign grants for this site."

    return False, "Invalid scope type."


def _dm_grant_filter(project_id_expression):
    """SQLAlchemy WHERE clause limiting grants to the DM's managed scope."""
    if current_user.is_admin():
        return sa.true()
    dm_projects = current_user.get_data_manager_projects()
    dm_site_pairs = current_user.get_data_manager_project_sites()

    conditions = []
    if dm_projects:
        conditions.append(project_id_expression.in_(list(dm_projects)))
    if dm_site_pairs:
        ps_ids = [
            db.session.scalar(
                sa.select(VaProjectSites.project_site_id).where(
                    VaProjectSites.project_id == pid,
                    VaProjectSites.site_id == sid,
                    VaProjectSites.project_site_status == VaStatuses.active,
                )
            )
            for pid, sid in dm_site_pairs
        ]
        ps_ids = [p for p in ps_ids if p is not None]
        if ps_ids:
            conditions.append(VaUserAccessGrants.project_site_id.in_(ps_ids))

    if not conditions:
        return sa.false()
    return sa.or_(*conditions)


def require_dm_scope(f):
    """Structural authz gate for grant mutation endpoints.

    Runs _dm_can_manage_scope() before the handler so the check is
    structurally unskippable. Two paths:

    - Toggle (grant_id in URL kwargs): loads grant from DB, resolves scope.
    - Create (no grant_id): resolves scope from JSON payload and stores the
      parsed values in g.dm_scope so the handler avoids re-parsing.
    """
    @wraps(f)
    def wrapper(*args, **kwargs):
        grant_id = kwargs.get("grant_id")

        if grant_id is not None:
            # Toggle path — scope comes from the existing grant record.
            grant = db.session.get(VaUserAccessGrants, grant_id)
            if not grant:
                return _json_error("Grant not found.", 404)
            if grant.scope_type == VaAccessScopeTypes.project:
                resolved_project_id = grant.project_id
            elif grant.scope_type == VaAccessScopeTypes.project_site:
                ps = db.session.get(VaProjectSites, grant.project_site_id)
                resolved_project_id = ps.project_id if ps else None
            else:
                return _json_error("Invalid scope type.", 400)
            ok, err = _dm_can_manage_scope(
                current_user, grant.role, grant.scope_type,
                resolved_project_id, grant.project_site_id,
            )
        else:
            # Create path — scope comes from the request payload.
            payload = request.get_json(silent=True) or {}
            try:
                role, scope_type, resolved_project_id, project_site_id = (
                    _resolve_scope_from_payload(payload)
                )
            except ValueError as exc:
                return _json_error(str(exc), 400)
            ok, err = _dm_can_manage_scope(
                current_user, role, scope_type, resolved_project_id, project_site_id,
            )
            # Store parsed scope on g so the handler doesn't need to re-parse.
            g.dm_scope = (role, scope_type, resolved_project_id, project_site_id)

        if not ok:
            log.warning(
                "Grant scope denied: user=%s path=%s reason=%s",
                current_user.get_id(), request.path, err,
            )
            return _json_error(err, 403)

        return f(*args, **kwargs)
    return wrapper


@data_management.get("/")
@role_required("data_manager", "admin")
def dashboard():
    project_ids = sorted(current_user.get_data_manager_projects())
    project_site_pairs = current_user.get_data_manager_project_sites()
    if not current_user.is_admin() and not project_ids and not project_site_pairs:
        va_permission_abortwithflash("No data-manager scope has been assigned.", 403)

    kpi = get_dm_kpi_from_mv(
        project_ids=project_ids,
        project_site_pairs=project_site_pairs,
    )
    return render_template(
        "va_frontpages/va_data_manager.html",
        total_submissions=kpi["total_submissions"],
        flagged_submissions=kpi["flagged_submissions"],
        odk_has_issues_submissions=kpi["odk_has_issues_submissions"],
        smartva_missing_submissions=kpi["smartva_missing_submissions"],
    )


@data_management.get("/dashboard")
@role_required("data_manager", "admin")
def kpi_dashboard():
    """Data manager KPI analytics dashboard.

    Shell template only — all data fetched client-side from /api/v1/analytics/dm-kpi/* endpoints.
    """
    if not current_user.is_admin():
        project_ids = current_user.get_data_manager_projects()
        project_site_pairs = current_user.get_data_manager_project_sites()
        if not project_ids and not project_site_pairs:
            va_permission_abortwithflash("No data-manager scope has been assigned.", 403)

    return render_template("va_frontpages/va_dm_kpi_dashboard.html")


@data_management.get("/view/<va_sid>")
@role_required("data_manager", "admin")
def view_submission(va_sid):
    """Data manager read-only view of a submission."""
    from app.models import VaSubmissionsAuditlog
    from app.services.coding_service import render_va_coding_page
    form = db.session.get(VaSubmissions, va_sid)
    if not form:
        va_permission_abortwithflash("Submission not found.", 404)
    # ABAC: verify the DM's grant scope covers this submission's project/site
    form_meta = db.session.execute(
        sa.select(VaForms.project_id, VaForms.site_id).where(VaForms.form_id == form.va_form_id)
    ).mappings().first()
    if not form_meta or not current_user.has_data_manager_submission_access(form_meta["project_id"], form_meta["site_id"]):
        va_permission_abortwithflash("You do not have data-manager access to this submission.", 403)
    # Audit read
    db.session.add(VaSubmissionsAuditlog(
        va_sid=va_sid,
        va_audit_byrole="data_manager",
        va_audit_by=current_user.user_id,
        va_audit_operation="r",
        va_audit_action="data_manager_viewed_submission_read_only",
        va_audit_entityid=uuid.uuid4(),
    ))
    db.session.commit()
    return render_va_coding_page(form, "vadata", "vaview", "data_manager")


@data_management.get("/submissions/<path:va_sid>/odk-edit")
@role_required("data_manager", "admin")
def submission_odk_edit(va_sid):
    odk_edit_url = dm_odk_edit_url(current_user, va_sid)
    if not odk_edit_url:
        va_permission_abortwithflash(
            "ODK edit link is not available for this submission.", 404
        )
    audit_dm_submission_action(va_sid, "data_manager_opened_odk_edit_link")
    return redirect(odk_edit_url)


# ---------------------------------------------------------------------------
# User & Grant Management
# ---------------------------------------------------------------------------


@data_management.get("/users")
@role_required("data_manager", "admin")
def user_management():
    """User + grant management page for data-managers."""
    from app.models.mas_languages import MasLanguages

    languages = db.session.scalars(
        sa.select(MasLanguages)
        .where(MasLanguages.is_active == True)
        .order_by(MasLanguages.language_name)
    ).all()
    return render_template(
        "va_frontpages/data_manager_partials/_user_management.html",
        available_languages=[
            {"code": lang.language_code, "name": lang.language_name}
            for lang in languages
        ],
    )


@data_management.get("/api/bootstrap")
@role_required("data_manager", "admin")
def manage_bootstrap():
    """Return CSRF token and scope context for the management JS."""
    is_admin = current_user.is_admin()
    dm_projects = sorted(current_user.get_data_manager_projects())
    dm_site_pairs = current_user.get_data_manager_project_sites()
    # Admins are treated as project-scoped (can assign at project or site level)
    is_project_scoped = is_admin or bool(dm_projects)

    return jsonify({
        "csrf_header_name": "X-CSRFToken",
        "csrf_token": generate_csrf(),
        "user": {
            "user_id": str(current_user.user_id),
            "email": current_user.email,
            "name": current_user.name,
            "is_project_scoped": is_project_scoped,
            "managed_project_ids": dm_projects,
            "managed_site_pairs": [
                {"project_id": pid, "site_id": sid}
                for pid, sid in sorted(dm_site_pairs)
            ],
        },
        "allowed_roles": ["coder", "data_manager"],
    })


@data_management.get("/api/projects")
@role_required("data_manager", "admin")
def manage_projects():
    """Projects the data-manager can manage."""
    dm_projects = current_user.get_data_manager_projects()
    dm_site_pairs = current_user.get_data_manager_project_sites()
    # Union of project IDs from both project-scoped and site-scoped grants
    all_project_ids = dm_projects | {pid for pid, _ in dm_site_pairs}
    # Admins see all projects
    if current_user.is_admin():
        stmt = (
            sa.select(VaProjectMaster)
            .where(VaProjectMaster.project_status == VaStatuses.active)
            .order_by(VaProjectMaster.project_id)
        )
        projects = db.session.scalars(stmt).all()
        return jsonify({"projects": [_serialize_project(p) for p in projects]})
    if not all_project_ids:
        return jsonify({"projects": []})
    stmt = (
        sa.select(VaProjectMaster)
        .where(
            VaProjectMaster.project_status == VaStatuses.active,
            VaProjectMaster.project_id.in_(list(all_project_ids)),
        )
        .order_by(VaProjectMaster.project_id)
    )
    projects = db.session.scalars(stmt).all()
    return jsonify({"projects": [_serialize_project(p) for p in projects]})


@data_management.get("/api/project-sites")
@role_required("data_manager", "admin")
def manage_project_sites():
    """Project-sites within the data-manager's scope."""
    project_id = request.args.get("project_id")
    dm_projects = current_user.get_data_manager_projects()
    dm_site_pairs = current_user.get_data_manager_project_sites()

    stmt = (
        sa.select(
            VaProjectSites.project_site_id,
            VaProjectSites.project_id,
            VaProjectSites.site_id,
            VaProjectSites.project_site_status,
            VaProjectMaster.project_name,
            VaSiteMaster.site_name,
        )
        .join(VaProjectMaster, VaProjectMaster.project_id == VaProjectSites.project_id)
        .join(VaSiteMaster, VaSiteMaster.site_id == VaProjectSites.site_id)
        .where(
            VaProjectSites.project_site_status == VaStatuses.active,
            VaProjectMaster.project_status == VaStatuses.active,
            VaSiteMaster.site_status == VaStatuses.active,
        )
    )

    if project_id:
        stmt = stmt.where(VaProjectSites.project_id == project_id)

    # Admins see all project-sites.
    if not current_user.is_admin():
        # Filter to DM's accessible sites
        conditions = []
        if dm_projects:
            conditions.append(VaProjectSites.project_id.in_(list(dm_projects)))
        if dm_site_pairs:
            pair_clauses = [
                sa.and_(VaProjectSites.project_id == pid, VaProjectSites.site_id == sid)
                for pid, sid in dm_site_pairs
            ]
            conditions.append(sa.or_(*pair_clauses))
        if conditions:
            stmt = stmt.where(sa.or_(*conditions))
        else:
            return jsonify({"project_sites": []})

    rows = db.session.execute(
        stmt.order_by(VaProjectSites.project_id, VaProjectSites.site_id)
    ).all()
    return jsonify({"project_sites": [_serialize_project_site(r) for r in rows]})


@data_management.get("/api/users")
@role_required("data_manager", "admin")
def manage_users():
    """User search for data-manager grant assignment."""
    query = (request.args.get("query") or "").strip()
    include_inactive = request.args.get("include_inactive", "1") == "1"
    stmt = sa.select(VaUsers)
    if not include_inactive:
        stmt = stmt.where(VaUsers.user_status == VaStatuses.active)
    if query:
        pattern = f"%{query}%"
        stmt = stmt.where(
            sa.or_(VaUsers.email.ilike(pattern), VaUsers.name.ilike(pattern))
        )
    users = db.session.scalars(stmt.order_by(VaUsers.email).limit(25)).all()
    return jsonify({"users": [_serialize_user(u) for u in users]})


@data_management.post("/api/users")
@role_required("data_manager", "admin")
def manage_create_user():
    """Create a new user (data-manager scoped)."""
    from app.models.mas_languages import MasLanguages

    payload = request.get_json(silent=True) or {}
    email = (payload.get("email") or "").strip().lower()
    email_confirm = (payload.get("email_confirm") or "").strip().lower()
    name = (payload.get("name") or "").strip()
    phone = (payload.get("phone") or "").strip()
    languages = payload.get("languages")
    initial_role_value = payload.get("initial_role")
    initial_scope_value = payload.get("initial_scope_type")
    initial_project_id = (payload.get("initial_project_id") or "").strip() or None

    if not email or not email_confirm or not name:
        return _json_error("email, email_confirm, and name are required.", 400)
    if email != email_confirm:
        return _json_error("Email confirmation does not match.", 400)
    if not isinstance(languages, list) or not languages:
        return _json_error("At least one language must be selected.", 400)

    valid_codes = set(
        db.session.scalars(
            sa.select(MasLanguages.language_code).where(MasLanguages.is_active == True)
        ).all()
    )
    invalid = [code for code in languages if code not in valid_codes]
    if invalid:
        return _json_error(f"Invalid language codes: {invalid}", 400)

    existing = db.session.scalar(sa.select(VaUsers).where(VaUsers.email == email))
    if existing:
        return _json_error("Email already in use.", 400)

    if not initial_role_value or not initial_scope_value:
        return _json_error("initial_role and initial_scope_type are required.", 400)
    if not initial_project_id:
        return _json_error("initial_project_id is required.", 400)
    if initial_role_value not in {r.value for r in VaAccessRoles}:
        return _json_error("Invalid initial_role.", 400)
    if initial_scope_value not in {s.value for s in VaAccessScopeTypes}:
        return _json_error("Invalid initial_scope_type.", 400)
    role = VaAccessRoles(initial_role_value)
    scope_type = VaAccessScopeTypes(initial_scope_value)

    resolved_project_id = None
    project_site_id = None
    if scope_type == VaAccessScopeTypes.project:
        resolved_project_id = initial_project_id
    elif scope_type == VaAccessScopeTypes.project_site:
        raw_psid = payload.get("initial_project_site_id")
        if not raw_psid:
            return _json_error("initial_project_site_id is required for site scope.", 400)
        try:
            project_site_id = uuid.UUID(raw_psid)
        except (ValueError, TypeError):
            return _json_error("Invalid initial_project_site_id.", 400)
        ps = db.session.get(VaProjectSites, project_site_id)
        if not ps or ps.project_site_status != VaStatuses.active:
            return _json_error("Active project-site mapping not found.", 404)
        if ps.project_id != initial_project_id:
            return _json_error("initial_project_site_id does not belong to initial_project_id.", 400)
        resolved_project_id = ps.project_id
    else:
        return _json_error("Invalid initial_scope_type.", 400)

    ok, err = _dm_can_manage_scope(
        current_user,
        role,
        scope_type,
        resolved_project_id,
        project_site_id,
    )
    if not ok:
        return _json_error(err, 403)

    new_user = VaUsers(
        email=email,
        name=name,
        phone=phone or None,
        user_status=VaStatuses.active,
        vacode_language=languages,
        permission={},
        landing_page="coder",
        pw_reset_t_and_c=False,
        email_verified=False,
        other={"created_by_user_id": str(current_user.user_id)},
    )
    # Invite-only onboarding: user sets their own password via reset link.
    new_user.set_password(secrets.token_urlsafe(32))

    db.session.add(new_user)
    db.session.flush()
    new_grant = VaUserAccessGrants(
        user_id=new_user.user_id,
        role=role,
        scope_type=scope_type,
        project_id=resolved_project_id if scope_type == VaAccessScopeTypes.project else None,
        project_site_id=project_site_id,
        notes="auto-created with user",
        grant_status=VaStatuses.active,
    )
    db.session.add(new_grant)
    db.session.commit()

    # Send verification + password-setup emails (async via Celery).
    try:
        from app.services.token_service import generate_token
        from app.services.email_service import (
            send_verification_email,
            send_password_reset_email,
        )
        verify_token = generate_token(new_user.user_id, "email_verify")
        reset_token = generate_token(new_user.user_id, "password_reset")
        send_verification_email(new_user, verify_token)
        send_password_reset_email(new_user, reset_token, invite_mode=True)
    except Exception:
        pass  # non-critical — user can request resend/reset

    return jsonify({"user": _serialize_user(new_user)}), 201


@data_management.get("/api/users/<uuid:target_user_id>")
@role_required("data_manager", "admin")
def manage_user_detail(target_user_id):
    """Return user details for DM/admin view."""
    user = db.session.get(VaUsers, target_user_id)
    if not user:
        return _json_error("User not found.", 404)
    return jsonify({"user": _serialize_user(user)})


@data_management.post("/api/users/<uuid:target_user_id>/resend-verification")
@role_required("data_manager", "admin")
def manage_resend_verification(target_user_id):
    """Resend email verification link for a user."""
    user = db.session.get(VaUsers, target_user_id)
    if not user:
        return _json_error("User not found.", 404)
    if user.email_verified:
        return _json_error("User email is already verified.", 400)
    try:
        from app.services.token_service import generate_token
        from app.services.email_service import send_verification_email

        verify_token = generate_token(user.user_id, "email_verify")
        send_verification_email(user, verify_token)
    except Exception as exc:
        log.exception("Resend verification failed for %s: %s", user.email, exc)
        return _json_error("Failed to send verification email.", 500)
    return jsonify({"message": "Verification email sent."})


def _dm_can_edit_user_email(target_user: VaUsers) -> bool:
    """DM can edit email only for users created by them; admins bypass."""
    if current_user.is_admin():
        return True
    other = target_user.other or {}
    created_by = other.get("created_by_user_id")
    return created_by == str(current_user.user_id)


@data_management.put("/api/users/<uuid:target_user_id>")
@role_required("data_manager", "admin")
def manage_update_user(target_user_id):
    """Update user email (DM restricted to users created by them)."""
    target_user = db.session.get(VaUsers, target_user_id)
    if not target_user:
        return _json_error("User not found.", 404)
    if not _dm_can_edit_user_email(target_user):
        return _json_error("You may update email only for users created by you.", 403)

    payload = request.get_json(silent=True) or {}
    email = (payload.get("email") or "").strip().lower()
    email_confirm = (payload.get("email_confirm") or "").strip().lower()
    if not email or not email_confirm:
        return _json_error("email and email_confirm are required.", 400)
    if email != email_confirm:
        return _json_error("Email confirmation does not match.", 400)

    if email != target_user.email:
        existing = db.session.scalar(
            sa.select(VaUsers).where(
                VaUsers.email == email,
                VaUsers.user_id != target_user.user_id,
            )
        )
        if existing:
            return _json_error("Email already in use.", 400)
        target_user.email = email
        target_user.email_verified = False
        db.session.commit()
        try:
            from app.services.token_service import generate_token
            from app.services.email_service import send_verification_email

            verify_token = generate_token(target_user.user_id, "email_verify")
            send_verification_email(target_user, verify_token)
        except Exception:
            pass
    return jsonify({"user": _serialize_user(target_user)})


@data_management.get("/api/access-grants")
@role_required("data_manager", "admin")
def manage_access_grants():
    """List coder/data_manager grants within the DM's scope."""
    project_id_expression = _grant_project_id_expression()
    site_id_expression = _grant_site_id_expression()

    stmt = (
        sa.select(
            VaUserAccessGrants.grant_id,
            VaUserAccessGrants.user_id,
            VaUserAccessGrants.role,
            VaUserAccessGrants.scope_type,
            VaUserAccessGrants.project_site_id,
            VaUserAccessGrants.grant_status,
            VaUserAccessGrants.notes,
            VaUsers.email,
            VaUsers.name,
            project_id_expression.label("resolved_project_id"),
            site_id_expression.label("resolved_site_id"),
        )
        .join(VaUsers, VaUsers.user_id == VaUserAccessGrants.user_id)
        .outerjoin(
            VaProjectSites,
            VaProjectSites.project_site_id == VaUserAccessGrants.project_site_id,
        )
        .where(
            VaUserAccessGrants.grant_status == VaStatuses.active,
            VaUserAccessGrants.role.in_([VaAccessRoles.coder, VaAccessRoles.data_manager]),
            _dm_grant_filter(project_id_expression),
        )
    )

    project_id = request.args.get("project_id")
    if project_id:
        stmt = stmt.where(project_id_expression == project_id)
    role = request.args.get("role")
    if role:
        if role not in {member.value for member in VaAccessRoles}:
            return _json_error("Invalid role.", 400)
        stmt = stmt.where(VaUserAccessGrants.role == VaAccessRoles(role))

    rows = db.session.execute(
        stmt.order_by(project_id_expression, site_id_expression, VaUsers.email)
    ).all()
    return jsonify({"grants": [_serialize_grant(r) for r in rows]})


@data_management.post("/api/access-grants")
@role_required("data_manager", "admin")
@require_dm_scope
def manage_create_access_grant():
    """Create a coder or data_manager grant within the DM's scope."""
    # Scope already validated by @require_dm_scope; retrieve parsed values from g.
    role, scope_type, resolved_project_id, project_site_id = g.dm_scope

    payload = request.get_json(silent=True) or {}
    user_id_value = payload.get("user_id")
    if not user_id_value:
        return _json_error("user_id is required.", 400)
    try:
        user_id = uuid.UUID(user_id_value)
    except (ValueError, TypeError):
        return _json_error("Invalid user_id.", 400)

    target_user = db.session.get(VaUsers, user_id)
    if not target_user or target_user.user_status != VaStatuses.active:
        return _json_error("Active user not found.", 404)

    if scope_type == VaAccessScopeTypes.project:
        project = db.session.get(VaProjectMaster, resolved_project_id)
        if not project or project.project_status != VaStatuses.active:
            return _json_error("Active project not found.", 404)

    # Check for existing grant (reactivate if found)
    existing = None
    if scope_type == VaAccessScopeTypes.project:
        existing = db.session.scalar(
            sa.select(VaUserAccessGrants).where(
                VaUserAccessGrants.user_id == user_id,
                VaUserAccessGrants.role == role,
                VaUserAccessGrants.scope_type == scope_type,
                VaUserAccessGrants.project_id == resolved_project_id,
            )
        )
    else:
        existing = db.session.scalar(
            sa.select(VaUserAccessGrants).where(
                VaUserAccessGrants.user_id == user_id,
                VaUserAccessGrants.role == role,
                VaUserAccessGrants.scope_type == scope_type,
                VaUserAccessGrants.project_site_id == project_site_id,
            )
        )

    status_code = 201
    if existing:
        existing.grant_status = VaStatuses.active
        existing.notes = payload.get("notes") or existing.notes
        grant = existing
        status_code = 200
    else:
        grant = VaUserAccessGrants(
            user_id=user_id,
            role=role,
            scope_type=scope_type,
            project_id=resolved_project_id if scope_type == VaAccessScopeTypes.project else None,
            project_site_id=project_site_id,
            notes=payload.get("notes"),
            grant_status=VaStatuses.active,
        )
        db.session.add(grant)

    db.session.commit()

    from app.logging.va_logger import log_grant_action
    log_grant_action(
        action="grant_reactivated" if (status_code == 200) else "grant_created",
        actor_user_id=current_user.user_id,
        actor_role="data_manager",
        target_user_id=user_id,
        grant_id=grant.grant_id,
        role=role.value,
        scope_type=scope_type.value,
        project_id=resolved_project_id,
        project_site_id=project_site_id,
        request_ip=request.remote_addr,
    )

    row = db.session.execute(
        sa.select(
            VaUserAccessGrants.grant_id,
            VaUserAccessGrants.user_id,
            VaUserAccessGrants.role,
            VaUserAccessGrants.scope_type,
            VaUserAccessGrants.project_site_id,
            VaUserAccessGrants.grant_status,
            VaUserAccessGrants.notes,
            VaUsers.email,
            VaUsers.name,
            _grant_project_id_expression().label("resolved_project_id"),
            _grant_site_id_expression().label("resolved_site_id"),
        )
        .join(VaUsers, VaUsers.user_id == VaUserAccessGrants.user_id)
        .outerjoin(
            VaProjectSites,
            VaProjectSites.project_site_id == VaUserAccessGrants.project_site_id,
        )
        .where(VaUserAccessGrants.grant_id == grant.grant_id)
    ).one()
    return jsonify({"grant": _serialize_grant(row)}), status_code


@data_management.post("/api/access-grants/<uuid:grant_id>/toggle")
@role_required("data_manager", "admin")
@require_dm_scope
def manage_toggle_access_grant(grant_id):
    """Toggle (activate/deactivate) a coder or data_manager grant."""
    # Scope already validated by @require_dm_scope; load grant for the update.
    grant = db.session.get(VaUserAccessGrants, grant_id)
    if not grant:
        return _json_error("Grant not found.", 404)

    new_status = (
        VaStatuses.deactive if grant.grant_status == VaStatuses.active else VaStatuses.active
    )
    grant.grant_status = new_status
    db.session.commit()

    from app.logging.va_logger import log_grant_action
    log_grant_action(
        action="grant_toggled_inactive" if new_status == VaStatuses.deactive else "grant_toggled_active",
        actor_user_id=current_user.user_id,
        actor_role="data_manager",
        target_user_id=grant.user_id,
        grant_id=grant.grant_id,
        role=grant.role.value,
        scope_type=grant.scope_type.value,
        request_ip=request.remote_addr,
    )

    return jsonify({"grant_id": str(grant.grant_id), "status": grant.grant_status.value})
