"""Data management blueprint — /data-management/

Page routes and JSON API routes for data-manager user/grant management.
Submission-related JSON API routes live in app/routes/api/data_management.py.
Shared helpers live in app/services/data_management_service.py.
"""

import logging
import uuid

import sqlalchemy as sa
from flask import Blueprint, jsonify, redirect, render_template, request
from flask_login import current_user
from flask_wtf.csrf import generate_csrf

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

    # Admins see all project-sites
    if current_user.is_admin():
        pass  # no additional filter
    else:
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
    stmt = sa.select(VaUsers).where(VaUsers.user_status == VaStatuses.active)
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
    name = (payload.get("name") or "").strip()
    phone = (payload.get("phone") or "").strip()
    password = payload.get("password")
    languages = payload.get("languages")

    if not email or not name or not password:
        return _json_error("email, name, and password are required.", 400)

    from app.utils.password_policy import password_error_message
    pw_err = password_error_message(password)
    if pw_err:
        return _json_error(pw_err, 400)
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
    )
    new_user.set_password(password)

    db.session.add(new_user)
    db.session.commit()
    return jsonify({"user": _serialize_user(new_user)}), 201


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
def manage_create_access_grant():
    """Create a coder or data_manager grant within the DM's scope."""
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

    try:
        role, scope_type, resolved_project_id, project_site_id = _resolve_scope_from_payload(payload)
    except ValueError as exc:
        return _json_error(str(exc), 400)

    # DM-specific authorization
    ok, err = _dm_can_manage_scope(current_user, role, scope_type, resolved_project_id, project_site_id)
    if not ok:
        return _json_error(err, 403)

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
def manage_toggle_access_grant(grant_id):
    """Toggle (activate/deactivate) a coder or data_manager grant."""
    grant = db.session.get(VaUserAccessGrants, grant_id)
    if not grant:
        return _json_error("Grant not found.", 404)

    # Resolve project_id for scope check
    if grant.scope_type == VaAccessScopeTypes.project:
        resolved_project_id = grant.project_id
    elif grant.scope_type == VaAccessScopeTypes.project_site:
        ps = db.session.get(VaProjectSites, grant.project_site_id)
        resolved_project_id = ps.project_id if ps else None
    else:
        return _json_error("Invalid scope type.", 400)

    # DM cannot toggle non-coder/data_manager grants
    ok, err = _dm_can_manage_scope(
        current_user, grant.role, grant.scope_type, resolved_project_id, grant.project_site_id
    )
    if not ok:
        return _json_error(err, 403)

    grant.grant_status = (
        VaStatuses.deactive if grant.grant_status == VaStatuses.active else VaStatuses.active
    )
    db.session.commit()
    return jsonify({"grant_id": str(grant.grant_id), "status": grant.grant_status.value})
