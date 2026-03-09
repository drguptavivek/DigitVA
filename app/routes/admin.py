import uuid
from secrets import token_hex

import sqlalchemy as sa
from flask import Blueprint, abort, jsonify, redirect, render_template, request, session, url_for
from flask_wtf.csrf import generate_csrf

from app import db
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaProjectMaster,
    VaProjectSites,
    VaSiteMaster,
    VaStatuses,
    VaUserAccessGrants,
    VaUsers,
)


admin = Blueprint("admin", __name__)


def _json_error(message, status_code):
    return jsonify({"error": message}), status_code


def _request_user():
    user_id = session.get("_user_id")
    if not user_id:
        return None
    try:
        return db.session.get(VaUsers, uuid.UUID(user_id))
    except (TypeError, ValueError):
        return None


def _require_admin_api_access(user):
    if user is None or user.user_status != VaStatuses.active:
        return _json_error("Authentication required.", 401)
    if user.is_admin() or user.get_project_pi_projects():
        return None
    return _json_error("Admin API access is not allowed for this user.", 403)


def _current_user_can_manage_project(user, project_id):
    return user.is_admin() or user.can_manage_project(project_id)


def _grant_project_id_expression():
    return sa.case(
        (
            VaUserAccessGrants.scope_type == VaAccessScopeTypes.project,
            VaUserAccessGrants.project_id,
        ),
        else_=VaProjectSites.project_id,
    )


def _grant_site_id_expression():
    return sa.case(
        (
            VaUserAccessGrants.scope_type == VaAccessScopeTypes.project_site,
            VaProjectSites.site_id,
        ),
        else_=sa.null(),
    )


def _serialize_project(project):
    return {
        "project_id": project.project_id,
        "project_code": project.project_code,
        "project_name": project.project_name,
        "project_nickname": project.project_nickname,
        "status": project.project_status.value,
    }


def _serialize_site(site):
    return {
        "site_id": site.site_id,
        "site_name": site.site_name,
        "site_abbr": site.site_abbr,
        "status": site.site_status.value,
    }


def _serialize_project_site(row):
    return {
        "project_site_id": str(row.project_site_id),
        "project_id": row.project_id,
        "site_id": row.site_id,
        "project_name": row.project_name,
        "site_name": row.site_name,
        "status": row.project_site_status.value,
    }


def _serialize_grant(row):
    return {
        "grant_id": str(row.grant_id),
        "user_id": str(row.user_id),
        "user_email": row.email,
        "user_name": row.name,
        "role": row.role.value,
        "scope_type": row.scope_type.value,
        "project_id": row.resolved_project_id,
        "site_id": row.resolved_site_id,
        "project_site_id": str(row.project_site_id) if row.project_site_id else None,
        "status": row.grant_status.value,
        "notes": row.notes,
    }


def _resolve_scope_from_payload(payload):
    role_value = payload.get("role")
    scope_value = payload.get("scope_type")
    if role_value not in {role.value for role in VaAccessRoles}:
        raise ValueError("Invalid role.")
    if scope_value not in {scope.value for scope in VaAccessScopeTypes}:
        raise ValueError("Invalid scope_type.")

    role = VaAccessRoles(role_value)
    scope_type = VaAccessScopeTypes(scope_value)
    project_id = payload.get("project_id")
    project_site_id_value = payload.get("project_site_id")
    project_site_id = None
    project_site = None

    if scope_type == VaAccessScopeTypes.global_scope:
        if role != VaAccessRoles.admin:
            raise ValueError("Only admin may use global scope.")
        if project_id or project_site_id_value:
            raise ValueError("Global scope must not include project_id or project_site_id.")
        return role, scope_type, None, None

    if scope_type == VaAccessScopeTypes.project:
        if role not in {
            VaAccessRoles.project_pi,
            VaAccessRoles.collaborator,
            VaAccessRoles.coder,
            VaAccessRoles.reviewer,
        }:
            raise ValueError("This role cannot use project scope.")
        if not project_id or project_site_id_value:
            raise ValueError("Project scope requires project_id only.")
        return role, scope_type, project_id, None

    if role not in {
        VaAccessRoles.site_pi,
        VaAccessRoles.collaborator,
        VaAccessRoles.coder,
        VaAccessRoles.reviewer,
    }:
        raise ValueError("This role cannot use project_site scope.")
    if payload.get("project_id"):
        raise ValueError("Project-site scope must not include project_id.")
    if not project_site_id_value:
        raise ValueError("Project-site scope requires project_site_id.")
    try:
        project_site_id = uuid.UUID(project_site_id_value)
    except (ValueError, TypeError) as exc:
        raise ValueError("Invalid project_site_id.") from exc

    project_site = db.session.get(VaProjectSites, project_site_id)
    if not project_site or project_site.project_site_status != VaStatuses.active:
        raise ValueError("Active project-site mapping not found.")
    return role, scope_type, project_site.project_id, project_site.project_site_id


def _project_access_filter(project_id_expression):
    user = _request_user()
    if user and user.is_admin():
        return sa.true()
    if user:
        return project_id_expression.in_(list(user.get_project_pi_projects()))
    return sa.false()


@admin.before_request
def _enforce_admin_api_access():
    if request.path.startswith("/admin/api/"):
        denied = _require_admin_api_access(_request_user())
        if denied:
            return denied
    return None


@admin.get("/api/bootstrap")
def admin_bootstrap():
    user = _request_user()
    if "csrf_token" not in session:
        session["csrf_token"] = token_hex(32)
    accessible_projects = sorted(user.get_project_pi_projects())
    if user.is_admin():
        accessible_projects = sorted(
            db.session.scalars(
                sa.select(VaProjectMaster.project_id).where(
                    VaProjectMaster.project_status == VaStatuses.active
                )
            ).all()
        )
    return jsonify(
        {
            "csrf_header_name": "X-CSRFToken",
            "csrf_token": generate_csrf(),
            "user": {
                "user_id": str(user.user_id),
                "email": user.email,
                "name": user.name,
                "is_admin": user.is_admin(),
                "project_pi_projects": sorted(user.get_project_pi_projects()),
            },
            "accessible_projects": sorted(accessible_projects),
        }
    )


@admin.get("/api/projects")
def admin_projects():
    user = _request_user()
    master = request.args.get("master") == "1"
    
    if master:
        if not user.is_admin():
            return _json_error("Admin access required.", 403)
        stmt = sa.select(VaProjectMaster)
        if request.args.get("include_inactive") != "1":
            stmt = stmt.where(VaProjectMaster.project_status == VaStatuses.active)
    else:
        stmt = sa.select(VaProjectMaster).where(
            VaProjectMaster.project_status == VaStatuses.active
        )
        if not user.is_admin():
            stmt = stmt.where(
                VaProjectMaster.project_id.in_(list(user.get_project_pi_projects()))
            )
    projects = db.session.scalars(stmt.order_by(VaProjectMaster.project_id)).all()
    return jsonify({"projects": [_serialize_project(project) for project in projects]})


@admin.post("/api/projects")
def admin_create_project():
    user = _request_user()
    if not user.is_admin():
        return _json_error("Admin access required.", 403)
    payload = request.get_json(silent=True) or {}
    project_id = (payload.get("project_id") or "").strip().upper()
    project_code = (payload.get("project_code") or "").strip().upper() or project_id
    project_name = (payload.get("project_name") or "").strip()
    project_nickname = (payload.get("project_nickname") or "").strip()
    
    if not project_id or not project_name or not project_nickname:
        return _json_error("project_id, project_name, and project_nickname are required.", 400)
        
    if len(project_id) != 6:
        return _json_error("project_id must be exactly 6 characters.", 400)
        
    existing = db.session.get(VaProjectMaster, project_id)
    if existing:
        return _json_error("Project ID already exists.", 400)
        
    project = VaProjectMaster(
        project_id=project_id,
        project_code=project_code,
        project_name=project_name,
        project_nickname=project_nickname,
        project_status=VaStatuses.active
    )
    db.session.add(project)
    db.session.commit()
    return jsonify({"project": _serialize_project(project)}), 201


@admin.put("/api/projects/<project_id>")
def admin_update_project(project_id):
    user = _request_user()
    if not user.is_admin():
        return _json_error("Admin access required.", 403)
        
    project = db.session.get(VaProjectMaster, project_id)
    if not project:
        return _json_error("Project not found.", 404)
        
    payload = request.get_json(silent=True) or {}
    
    if "project_code" in payload:
        project.project_code = (payload["project_code"] or "").strip().upper() or project.project_id
        
    if "project_name" in payload:
        project_name = (payload["project_name"] or "").strip()
        if not project_name:
            return _json_error("project_name cannot be empty.", 400)
        project.project_name = project_name
        
    if "project_nickname" in payload:
        project_nickname = (payload["project_nickname"] or "").strip()
        if not project_nickname:
            return _json_error("project_nickname cannot be empty.", 400)
        project.project_nickname = project_nickname
        
    if "status" in payload:
        try:
            project.project_status = VaStatuses(payload["status"])
        except ValueError:
            return _json_error("Invalid status.", 400)
            
    db.session.commit()
    return jsonify({"project": _serialize_project(project)})


@admin.post("/api/projects/<project_id>/toggle")
def admin_toggle_project(project_id):
    user = _request_user()
    if not user.is_admin():
        return _json_error("Admin access required.", 403)
        
    project = db.session.get(VaProjectMaster, project_id)
    if not project:
        return _json_error("Project not found.", 404)
        
    project.project_status = (
        VaStatuses.deactive
        if project.project_status == VaStatuses.active
        else VaStatuses.active
    )
    db.session.commit()
    return jsonify({
        "project_id": project.project_id,
        "status": project.project_status.value,
    })


@admin.get("/api/sites")
def admin_sites():
    user = _request_user()
    master = request.args.get("master") == "1"
    
    if master:
        if not user.is_admin():
            return _json_error("Admin access required.", 403)
        stmt = sa.select(VaSiteMaster)
        if request.args.get("include_inactive") != "1":
            stmt = stmt.where(VaSiteMaster.site_status == VaStatuses.active)
    else:
        project_id = request.args.get("project_id")
        stmt = (
            sa.select(VaSiteMaster)
            .join(VaProjectSites, VaProjectSites.site_id == VaSiteMaster.site_id)
            .where(
                VaSiteMaster.site_status == VaStatuses.active,
                VaProjectSites.project_site_status == VaStatuses.active,
            )
        )
        if project_id:
            if not _current_user_can_manage_project(user, project_id):
                return _json_error("You do not have access to that project.", 403)
            stmt = stmt.where(VaProjectSites.project_id == project_id)
        elif not user.is_admin():
            stmt = stmt.where(
                VaProjectSites.project_id.in_(list(user.get_project_pi_projects()))
            )
            
    sites = db.session.scalars(stmt.distinct().order_by(VaSiteMaster.site_id)).all()
    return jsonify({"sites": [_serialize_site(site) for site in sites]})


@admin.post("/api/sites")
def admin_create_site():
    user = _request_user()
    if not user.is_admin():
        return _json_error("Admin access required.", 403)
    payload = request.get_json(silent=True) or {}
    site_id = (payload.get("site_id") or "").strip().upper()
    site_name = (payload.get("site_name") or "").strip()
    site_abbr = (payload.get("site_abbr") or "").strip()
    
    if not site_id or not site_name or not site_abbr:
        return _json_error("site_id, site_name, and site_abbr are required.", 400)
        
    if len(site_id) != 4:
        return _json_error("site_id must be exactly 4 characters.", 400)
        
    existing = db.session.get(VaSiteMaster, site_id)
    if existing:
        return _json_error("Site ID already exists.", 400)
        
    site = VaSiteMaster(
        site_id=site_id,
        site_name=site_name,
        site_abbr=site_abbr,
        site_status=VaStatuses.active
    )
    db.session.add(site)
    db.session.commit()
    return jsonify({"site": _serialize_site(site)}), 201


@admin.put("/api/sites/<site_id>")
def admin_update_site(site_id):
    user = _request_user()
    if not user.is_admin():
        return _json_error("Admin access required.", 403)
        
    site = db.session.get(VaSiteMaster, site_id)
    if not site:
        return _json_error("Site not found.", 404)
        
    payload = request.get_json(silent=True) or {}
    if "site_name" in payload:
        site_name = (payload["site_name"] or "").strip()
        if not site_name:
            return _json_error("site_name cannot be empty.", 400)
        site.site_name = site_name
        
    if "site_abbr" in payload:
        site_abbr = (payload["site_abbr"] or "").strip()
        if not site_abbr:
            return _json_error("site_abbr cannot be empty.", 400)
        site.site_abbr = site_abbr
        
    if "status" in payload:
        try:
            site.site_status = VaStatuses(payload["status"])
        except ValueError:
            return _json_error("Invalid status.", 400)
            
    db.session.commit()
    return jsonify({"site": _serialize_site(site)})


@admin.post("/api/sites/<site_id>/toggle")
def admin_toggle_site(site_id):
    user = _request_user()
    if not user.is_admin():
        return _json_error("Admin access required.", 403)
        
    site = db.session.get(VaSiteMaster, site_id)
    if not site:
        return _json_error("Site not found.", 404)
        
    site.site_status = (
        VaStatuses.deactive
        if site.site_status == VaStatuses.active
        else VaStatuses.active
    )
    db.session.commit()
    return jsonify({
        "site_id": site.site_id,
        "status": site.site_status.value,
    })


@admin.get("/api/project-sites")
def admin_project_sites():
    user = _request_user()
    project_id = request.args.get("project_id")
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
    )
    if project_id:
        if not _current_user_can_manage_project(user, project_id):
            return _json_error("You do not have access to that project.", 403)
        stmt = stmt.where(VaProjectSites.project_id == project_id)
    elif not user.is_admin():
        stmt = stmt.where(
            VaProjectSites.project_id.in_(list(user.get_project_pi_projects()))
        )
    include_inactive = request.args.get("include_inactive") == "1"
    if not include_inactive:
        stmt = stmt.where(VaProjectSites.project_site_status == VaStatuses.active)
    rows = db.session.execute(
        stmt.order_by(VaProjectSites.project_id, VaProjectSites.site_id)
    ).all()
    return jsonify({"project_sites": [_serialize_project_site(row) for row in rows]})


@admin.post("/api/project-sites")
def admin_create_project_site():
    user = _request_user()
    payload = request.get_json(silent=True) or {}
    project_id = payload.get("project_id")
    site_id = payload.get("site_id")
    if not project_id or not site_id:
        return _json_error("project_id and site_id are required.", 400)
    if not _current_user_can_manage_project(user, project_id):
        return _json_error("You do not have access to that project.", 403)

    project = db.session.get(VaProjectMaster, project_id)
    site = db.session.get(VaSiteMaster, site_id)
    if not project or project.project_status != VaStatuses.active:
        return _json_error("Active project not found.", 404)
    if not site or site.site_status != VaStatuses.active:
        return _json_error("Active site not found.", 404)

    mapping = db.session.scalar(
        sa.select(VaProjectSites).where(
            VaProjectSites.project_id == project_id,
            VaProjectSites.site_id == site_id,
        )
    )
    status_code = 201
    if mapping:
        if mapping.project_site_status != VaStatuses.active:
            mapping.project_site_status = VaStatuses.active
        status_code = 200
    else:
        mapping = VaProjectSites(
            project_id=project_id,
            site_id=site_id,
            project_site_status=VaStatuses.active,
        )
        db.session.add(mapping)
    db.session.commit()
    db.session.refresh(mapping)
    row = db.session.execute(
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
        .where(VaProjectSites.project_site_id == mapping.project_site_id)
    ).one()
    return jsonify({"project_site": _serialize_project_site(row)}), status_code


@admin.post("/api/project-sites/<uuid:project_site_id>/toggle")
def admin_toggle_project_site(project_site_id):
    user = _request_user()
    mapping = db.session.get(VaProjectSites, project_site_id)
    if not mapping:
        return _json_error("Project-site mapping not found.", 404)
    if not _current_user_can_manage_project(user, mapping.project_id):
        return _json_error("You do not have access to that project.", 403)
    mapping.project_site_status = (
        VaStatuses.deactive
        if mapping.project_site_status == VaStatuses.active
        else VaStatuses.active
    )
    db.session.commit()
    return jsonify({
        "project_site_id": str(mapping.project_site_id),
        "status": mapping.project_site_status.value,
    })


def _serialize_user(user):
    return {
        "user_id": str(user.user_id),
        "email": user.email,
        "name": user.name,
        "status": user.user_status.value,
        "phone": user.phone,
        "landing_page": user.landing_page,
    }


@admin.get("/api/users")
def admin_users():
    user = _request_user()
    query = (request.args.get("query") or "").strip()
    master = request.args.get("master") == "1"
    
    stmt = sa.select(VaUsers)
    
    if master:
        if not user.is_admin():
            return _json_error("Admin access required.", 403)
        if request.args.get("include_inactive") != "1":
            stmt = stmt.where(VaUsers.user_status == VaStatuses.active)
    else:
        stmt = stmt.where(VaUsers.user_status == VaStatuses.active)
        
    if query:
        pattern = f"%{query}%"
        stmt = stmt.where(
            sa.or_(VaUsers.email.ilike(pattern), VaUsers.name.ilike(pattern))
        )
        
    users = db.session.scalars(stmt.order_by(VaUsers.email).limit(25 if not master else None)).all()
    return jsonify({"users": [_serialize_user(u) for u in users]})


@admin.post("/api/users")
def admin_create_user():
    user = _request_user()
    if not user.is_admin():
        return _json_error("Admin access required.", 403)
        
    payload = request.get_json(silent=True) or {}
    email = (payload.get("email") or "").strip().lower()
    name = (payload.get("name") or "").strip()
    phone = (payload.get("phone") or "").strip()
    password = payload.get("password")
    
    if not email or not name or not password:
        return _json_error("email, name, and password are required.", 400)
        
    existing = db.session.scalar(sa.select(VaUsers).where(VaUsers.email == email))
    if existing:
        return _json_error("Email already in use.", 400)
        
    new_user = VaUsers(
        email=email,
        name=name,
        phone=phone or None,
        user_status=VaStatuses.active,
        vacode_language=["English"],
        permission={},
        landing_page="coder",
        pw_reset_t_and_c=False,
        email_verified=False
    )
    new_user.set_password(password)
    
    db.session.add(new_user)
    db.session.commit()
    return jsonify({"user": _serialize_user(new_user)}), 201


@admin.put("/api/users/<uuid:target_user_id>")
def admin_update_user(target_user_id):
    user = _request_user()
    if not user.is_admin():
        return _json_error("Admin access required.", 403)
        
    target_user = db.session.get(VaUsers, target_user_id)
    if not target_user:
        return _json_error("User not found.", 404)
        
    payload = request.get_json(silent=True) or {}
    
    if "name" in payload:
        name = (payload["name"] or "").strip()
        if not name:
            return _json_error("Name cannot be empty.", 400)
        target_user.name = name
        
    if "phone" in payload:
        target_user.phone = (payload["phone"] or "").strip() or None
        
    if "status" in payload:
        try:
            target_user.user_status = VaStatuses(payload["status"])
        except ValueError:
            return _json_error("Invalid status.", 400)
            
    if payload.get("password"):
        target_user.set_password(payload["password"])
        
    db.session.commit()
    return jsonify({"user": _serialize_user(target_user)})


@admin.post("/api/users/<uuid:target_user_id>/toggle")
def admin_toggle_user(target_user_id):
    user = _request_user()
    if not user.is_admin():
        return _json_error("Admin access required.", 403)
        
    target_user = db.session.get(VaUsers, target_user_id)
    if not target_user:
        return _json_error("User not found.", 404)
        
    if target_user.user_id == user.user_id:
        return _json_error("You cannot deactivate yourself.", 400)
        
    target_user.user_status = (
        VaStatuses.deactive
        if target_user.user_status == VaStatuses.active
        else VaStatuses.active
    )
    db.session.commit()
    return jsonify({
        "user_id": str(target_user.user_id),
        "status": target_user.user_status.value,
    })


@admin.get("/api/access-grants")
def admin_access_grants():
    user = _request_user()
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
            _project_access_filter(project_id_expression),
        )
    )
    project_id = request.args.get("project_id")
    if project_id:
        if not _current_user_can_manage_project(user, project_id):
            return _json_error("You do not have access to that project.", 403)
        stmt = stmt.where(project_id_expression == project_id)
    role = request.args.get("role")
    if role:
        if role not in {member.value for member in VaAccessRoles}:
            return _json_error("Invalid role.", 400)
        stmt = stmt.where(VaUserAccessGrants.role == VaAccessRoles(role))
    user_id = request.args.get("user_id")
    if user_id:
        try:
            stmt = stmt.where(VaUserAccessGrants.user_id == uuid.UUID(user_id))
        except (ValueError, TypeError):
            return _json_error("Invalid user_id.", 400)
    rows = db.session.execute(
        stmt.order_by(project_id_expression, site_id_expression, VaUsers.email)
    ).all()
    return jsonify({"grants": [_serialize_grant(row) for row in rows]})


@admin.post("/api/access-grants")
def admin_create_access_grant():
    acting_user = _request_user()
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
        role, scope_type, resolved_project_id, project_site_id = _resolve_scope_from_payload(
            payload
        )
    except ValueError as exc:
        return _json_error(str(exc), 400)

    if scope_type == VaAccessScopeTypes.project:
        project = db.session.get(VaProjectMaster, resolved_project_id)
        if not project or project.project_status != VaStatuses.active:
            return _json_error("Active project not found.", 404)

    if not acting_user.is_admin():
        if role in {VaAccessRoles.admin, VaAccessRoles.project_pi}:
            return _json_error("Project PI may not manage admin or project_pi grants.", 403)
        if not _current_user_can_manage_project(acting_user, resolved_project_id):
            return _json_error("You do not have access to that project.", 403)

    status_code = 201
    existing = None
    if scope_type == VaAccessScopeTypes.global_scope:
        existing = db.session.scalar(
            sa.select(VaUserAccessGrants).where(
                VaUserAccessGrants.user_id == user_id,
                VaUserAccessGrants.role == role,
                VaUserAccessGrants.scope_type == scope_type,
            )
        )
    elif scope_type == VaAccessScopeTypes.project:
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
            project_id=resolved_project_id
            if scope_type == VaAccessScopeTypes.project
            else None,
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


@admin.post("/api/access-grants/<uuid:grant_id>/toggle")
def admin_toggle_access_grant(grant_id):
    user = _request_user()
    grant = db.session.get(VaUserAccessGrants, grant_id)
    if not grant:
        return _json_error("Grant not found.", 404)

    if grant.scope_type == VaAccessScopeTypes.project:
        resolved_project_id = grant.project_id
    elif grant.scope_type == VaAccessScopeTypes.project_site:
        project_site = db.session.get(VaProjectSites, grant.project_site_id)
        resolved_project_id = project_site.project_id if project_site else None
    else:
        resolved_project_id = None

    if not user.is_admin():
        if grant.role in {VaAccessRoles.admin, VaAccessRoles.project_pi}:
            return _json_error("Project PI may not manage admin or project_pi grants.", 403)
        if not resolved_project_id or not _current_user_can_manage_project(
            user,
            resolved_project_id
        ):
            return _json_error("You do not have access to that project.", 403)

    grant.grant_status = (
        VaStatuses.deactive
        if grant.grant_status == VaStatuses.active
        else VaStatuses.active
    )
    db.session.commit()

    return jsonify({"grant_id": str(grant.grant_id), "status": grant.grant_status.value})


# ---------------------------------------------------------------------------
# Admin UI shell and panel routes
# ---------------------------------------------------------------------------

def _require_admin_ui_access():
    """Return a response to short-circuit if the user cannot access /admin UI,
    or None if access is allowed."""
    user = _request_user()
    if not user or user.user_status != VaStatuses.active:
        return redirect(url_for("va_auth.va_login"))
    if user.is_admin() or user.get_project_pi_projects():
        return None
    return render_template("va_errors/va_403.html"), 403


@admin.get("/", strict_slashes=False)
def admin_index():
    denied = _require_admin_ui_access()
    if denied:
        return denied
    return render_template("admin/admin_index.html")


@admin.get("/panels/access-grants")
def admin_panel_access_grants():
    denied = _require_admin_ui_access()
    if denied:
        return denied
    project_id = request.args.get("project_id") or ""
    return render_template("admin/panels/access_grants.html", project_id=project_id)


@admin.get("/panels/project-sites")
def admin_panel_project_sites():
    denied = _require_admin_ui_access()
    if denied:
        return denied
    project_id = request.args.get("project_id") or ""
    return render_template("admin/panels/project_sites.html", project_id=project_id)


@admin.get("/panels/projects")
def admin_panel_projects():
    denied = _require_admin_ui_access()
    if denied:
        return denied
    user = _request_user()
    if not user.is_admin():
        return render_template("va_errors/va_403.html"), 403
    return render_template("admin/panels/projects.html")


@admin.get("/panels/sites")
def admin_panel_sites():
    denied = _require_admin_ui_access()
    if denied:
        return denied
    user = _request_user()
    if not user.is_admin():
        return render_template("va_errors/va_403.html"), 403
    return render_template("admin/panels/sites.html")


@admin.get("/panels/users")
def admin_panel_users():
    denied = _require_admin_ui_access()
    if denied:
        return denied
    user = _request_user()
    if not user.is_admin():
        return render_template("va_errors/va_403.html"), 403
    return render_template("admin/panels/users.html")


@admin.get("/panels/project-pi")
def admin_panel_project_pi():
    denied = _require_admin_ui_access()
    if denied:
        return denied
    user = _request_user()
    if not user.is_admin():
        return render_template("va_errors/va_403.html"), 403
    return render_template("admin/panels/project_pi.html")
