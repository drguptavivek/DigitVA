import re
import uuid
from decimal import Decimal, InvalidOperation
from secrets import token_hex

import sqlalchemy as sa
from flask import Blueprint, abort, jsonify, redirect, render_template, request, session, url_for
from flask_wtf.csrf import generate_csrf

from app import db
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    MasOdkConnections,
    MapProjectOdk,
    MapProjectSiteOdk,
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


def _validate_entity_id(entity_id, length, name="ID"):
    if not entity_id or len(entity_id) != length:
        return f"{name} must be exactly {length} characters."
    if not re.match(r'^[A-Z0-9]+$', entity_id):
        return f"{name} must contain only uppercase letters and digits."
    return None


def _ordered_field_lists_for_form_type(form_type_id):
    """Return ordered field objects keyed by category and subcategory."""
    from sqlalchemy import select as sa_select
    from sqlalchemy.orm import aliased
    from app.models import MasFieldDisplayConfig
    from app.models.va_field_mapping import MasSubcategoryOrder

    subcat_order = aliased(MasSubcategoryOrder)
    rows = db.session.execute(
        sa_select(
            MasFieldDisplayConfig.category_code,
            MasFieldDisplayConfig.subcategory_code,
            MasFieldDisplayConfig.field_id,
            MasFieldDisplayConfig.short_label,
            MasFieldDisplayConfig.display_order,
            MasFieldDisplayConfig.flip_color,
            MasFieldDisplayConfig.is_info,
            MasFieldDisplayConfig.is_pii,
            MasFieldDisplayConfig.summary_include,
            subcat_order.display_order.label("subcategory_display_order"),
        )
        .outerjoin(
            subcat_order,
            sa.and_(
                subcat_order.form_type_id == MasFieldDisplayConfig.form_type_id,
                subcat_order.category_code == MasFieldDisplayConfig.category_code,
                subcat_order.subcategory_code == MasFieldDisplayConfig.subcategory_code,
                subcat_order.is_active == True,
            )
        )
        .where(
            MasFieldDisplayConfig.form_type_id == form_type_id,
            MasFieldDisplayConfig.is_active == True,
            MasFieldDisplayConfig.category_code.is_not(None),
        )
        .order_by(
            subcat_order.display_order.is_(None),
            subcat_order.display_order,
            MasFieldDisplayConfig.subcategory_code,
            MasFieldDisplayConfig.display_order,
            MasFieldDisplayConfig.field_id,
        )
    ).all()

    by_category = {}
    by_subcategory = {}
    for row in rows:
        field_data = {
            "field_id": row.field_id,
            "label": row.short_label or row.field_id,
            "display_order": str(row.display_order),
            "subcategory_code": row.subcategory_code,
            "flip_color": bool(getattr(row, "flip_color", False)),
            "is_info": bool(getattr(row, "is_info", False)),
            "is_pii": bool(getattr(row, "is_pii", False)),
            "summary_include": bool(getattr(row, "summary_include", False)),
        }
        by_category.setdefault(row.category_code, []).append(field_data)
        if row.subcategory_code:
            by_subcategory[(row.category_code, row.subcategory_code)] = (
                by_subcategory.get((row.category_code, row.subcategory_code), []) + [field_data]
            )
    return by_category, by_subcategory


def _serialize_category_browser_state(form_type, category_code):
    """Return category + subcategory field-browser state for the 3-panel UI."""
    from sqlalchemy import select as sa_select
    from app.models.va_field_mapping import MasCategoryOrder, MasSubcategoryOrder

    category = db.session.scalar(
        sa_select(MasCategoryOrder).where(
            MasCategoryOrder.form_type_id == form_type.form_type_id,
            MasCategoryOrder.category_code == category_code,
        )
    )
    if not category:
        return None

    fields_by_category, fields_by_subcategory = _ordered_field_lists_for_form_type(
        form_type.form_type_id
    )
    subcategories = db.session.scalars(
        sa_select(MasSubcategoryOrder)
        .where(
            MasSubcategoryOrder.form_type_id == form_type.form_type_id,
            MasSubcategoryOrder.category_code == category_code,
        )
        .order_by(MasSubcategoryOrder.display_order)
    ).all()

    return {
        "category": {
            "category_code": category.category_code,
            "category_name": category.category_name,
            "display_order": category.display_order,
            "ordered_fields": fields_by_category.get(category_code, []),
        },
        "subcategories": [
            {
                "subcategory_code": sub.subcategory_code,
                "subcategory_name": sub.subcategory_name,
                "display_order": sub.display_order,
                "ordered_fields": fields_by_subcategory.get(
                    (category_code, sub.subcategory_code), []
                ),
            }
            for sub in subcategories
        ],
    }

from functools import wraps

def require_api_role(*roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            user = _request_user()
            if not user or user.user_status != VaStatuses.active:
                return _json_error("Authentication required.", 401)
                
            if "any" in roles:
                return f(*args, **kwargs)
                
            is_admin = user.is_admin()
            is_pi = bool(user.get_project_pi_projects())
            
            if "admin" in roles and is_admin:
                return f(*args, **kwargs)
                
            if "project_pi" in roles and is_pi:
                return f(*args, **kwargs)
                
            return _json_error("Admin API access is not allowed for this user.", 403)
        return decorated_function
    return decorator



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
        "narrative_qa_enabled": project.narrative_qa_enabled,
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


@admin.get("/api/bootstrap")
@require_api_role("admin", "project_pi")
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
@require_api_role("admin", "project_pi")
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
@require_api_role("admin")
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
        
    if err := _validate_entity_id(project_id, 6, "project_id"):
        return _json_error(err, 400)
        
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
@require_api_role("admin")
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

    if "narrative_qa_enabled" in payload:
        project.narrative_qa_enabled = bool(payload["narrative_qa_enabled"])

    db.session.commit()
    return jsonify({"project": _serialize_project(project)})


@admin.post("/api/projects/<project_id>/toggle")
@require_api_role("admin")
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
@require_api_role("admin", "project_pi")
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
@require_api_role("admin")
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
        
    if err := _validate_entity_id(site_id, 4, "site_id"):
        return _json_error(err, 400)
        
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
@require_api_role("admin")
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
@require_api_role("admin")
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
@require_api_role("admin", "project_pi")
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
@require_api_role("admin", "project_pi")
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
@require_api_role("admin", "project_pi")
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
@require_api_role("admin", "project_pi")
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
@require_api_role("admin")
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
@require_api_role("admin")
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
@require_api_role("admin")
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
@require_api_role("admin", "project_pi")
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


@admin.get("/api/access-grants/orphaned")
@require_api_role("admin", "project_pi")
def admin_orphaned_grants():
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
            VaUserAccessGrants.scope_type == VaAccessScopeTypes.project_site,
            sa.or_(
                VaProjectSites.project_site_id == None,
                VaProjectSites.project_site_status == VaStatuses.deactive
            ),
            _project_access_filter(project_id_expression),
        )
    )
    
    project_id = request.args.get("project_id")
    if project_id:
        if not _current_user_can_manage_project(user, project_id):
            return _json_error("You do not have access to that project.", 403)
        stmt = stmt.where(project_id_expression == project_id)
        
    rows = db.session.execute(
        stmt.order_by(project_id_expression, site_id_expression, VaUsers.email)
    ).all()
    return jsonify({"grants": [_serialize_grant(row) for row in rows]})


@admin.post("/api/access-grants")
@require_api_role("admin", "project_pi")
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
@require_api_role("admin", "project_pi")
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
            return _json_error("This operation is not permitted for this resource.", 403)

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


@admin.get("/panels/project-forms")
def admin_panel_project_forms():
    user = _request_user()
    if not user.is_admin():
        return render_template("va_errors/va_403.html"), 403
    return render_template("admin/panels/project_forms.html")


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


@admin.get("/panels/odk-connections")
def admin_panel_odk_connections():
    denied = _require_admin_ui_access()
    if denied:
        return denied
    user = _request_user()
    if not user.is_admin():
        return render_template("va_errors/va_403.html"), 403
    return render_template("admin/panels/odk_connections.html")


# ---------------------------------------------------------------------------
# Field Mapping Admin  (admin-only)
# ---------------------------------------------------------------------------

@admin.get("/api/form-types/<form_type_code>/categories/<category_code>/subcategories")
@require_api_role("admin")
def admin_form_type_subcategories(form_type_code, category_code):
    """Return subcategories for a given form type + category."""
    from sqlalchemy import select as sa_select
    from app.models import MasFormTypes
    from app.models.va_field_mapping import MasSubcategoryOrder

    form_type = db.session.scalar(
        sa_select(MasFormTypes).where(MasFormTypes.form_type_code == form_type_code)
    )
    if not form_type:
        return _json_error("Form type not found.", 404)

    state = _serialize_category_browser_state(form_type, category_code)
    if not state:
        return _json_error("Category not found.", 404)
    return jsonify({"subcategories": state["subcategories"]})


@admin.get("/api/form-types/<form_type_code>/categories/<category_code>/browser-state")
@require_api_role("admin")
def admin_form_type_category_browser_state(form_type_code, category_code):
    """Return full browser state for one category in the 3-panel UI."""
    from sqlalchemy import select as sa_select
    from app.models import MasFormTypes

    form_type = db.session.scalar(
        sa_select(MasFormTypes).where(MasFormTypes.form_type_code == form_type_code)
    )
    if not form_type:
        return _json_error("Form type not found.", 404)

    state = _serialize_category_browser_state(form_type, category_code)
    if not state:
        return _json_error("Category not found.", 404)
    return jsonify(state)


@admin.post("/api/form-types/<form_type_code>/categories/<category_code>/fields/reorder")
@require_api_role("admin")
def admin_category_fields_reorder(form_type_code, category_code):
    """Persist ordered field_ids for a category browser selection."""
    from sqlalchemy import select as sa_select
    from app.models import MasFormTypes, MasFieldDisplayConfig

    form_type = db.session.scalar(
        sa_select(MasFormTypes).where(MasFormTypes.form_type_code == form_type_code)
    )
    if not form_type:
        return _json_error("Form type not found.", 404)

    data = request.get_json(silent=True) or {}
    field_ids = data.get("field_ids") or []
    if not isinstance(field_ids, list) or not field_ids:
        return _json_error("field_ids must be a non-empty list.", 400)

    fields = db.session.scalars(
        sa_select(MasFieldDisplayConfig).where(
            MasFieldDisplayConfig.form_type_id == form_type.form_type_id,
            MasFieldDisplayConfig.field_id.in_(field_ids),
        )
    ).all()
    field_by_id = {field.field_id: field for field in fields}
    if len(field_by_id) != len(set(field_ids)):
        return _json_error("One or more field_ids were not found.", 404)

    for index, field_id in enumerate(field_ids, start=1):
        field = field_by_id[field_id]
        if field.category_code != category_code:
            return _json_error("All field_ids must belong to the selected category.", 400)
        field.display_order = Decimal(index * 10)

    db.session.commit()

    from app.services.field_mapping_service import get_mapping_service
    get_mapping_service().clear_cache()

    state = _serialize_category_browser_state(form_type, category_code)
    return jsonify(state)


@admin.post("/api/form-types/<form_type_code>/fields/<field_id>/move")
@require_api_role("admin")
def admin_field_move_to_subcategory(form_type_code, field_id):
    """Move a field to a category/subcategory and append it to that target bucket."""
    from sqlalchemy import select as sa_select
    from app.models import MasFormTypes, MasFieldDisplayConfig
    from app.models.va_field_mapping import MasCategoryOrder, MasSubcategoryOrder

    form_type = db.session.scalar(
        sa_select(MasFormTypes).where(MasFormTypes.form_type_code == form_type_code)
    )
    if not form_type:
        return _json_error("Form type not found.", 404)

    field = db.session.scalar(
        sa_select(MasFieldDisplayConfig).where(
            MasFieldDisplayConfig.form_type_id == form_type.form_type_id,
            MasFieldDisplayConfig.field_id == field_id,
        )
    )
    if not field:
        return _json_error("Field not found.", 404)

    data = request.get_json(silent=True) or {}
    category_code = (data.get("category_code") or "").strip()
    subcategory_code = data.get("subcategory_code")
    if isinstance(subcategory_code, str):
        subcategory_code = subcategory_code.strip() or None

    if not category_code:
        return _json_error("category_code is required.", 400)

    category = db.session.scalar(
        sa_select(MasCategoryOrder).where(
            MasCategoryOrder.form_type_id == form_type.form_type_id,
            MasCategoryOrder.category_code == category_code,
        )
    )
    if not category:
        return _json_error("Category not found.", 404)

    if subcategory_code:
        subcategory = db.session.scalar(
            sa_select(MasSubcategoryOrder).where(
                MasSubcategoryOrder.form_type_id == form_type.form_type_id,
                MasSubcategoryOrder.category_code == category_code,
                MasSubcategoryOrder.subcategory_code == subcategory_code,
            )
        )
        if not subcategory:
            return _json_error("Subcategory not found.", 404)

    max_order = db.session.scalar(
        sa.select(sa.func.max(MasFieldDisplayConfig.display_order)).where(
            MasFieldDisplayConfig.form_type_id == form_type.form_type_id,
            MasFieldDisplayConfig.category_code == category_code,
            MasFieldDisplayConfig.subcategory_code == subcategory_code,
        )
    )

    field.category_code = category_code
    field.subcategory_code = subcategory_code
    field.display_order = Decimal(max_order or 0) + Decimal("10")
    db.session.commit()

    from app.services.field_mapping_service import get_mapping_service
    get_mapping_service().clear_cache()

    state = _serialize_category_browser_state(form_type, category_code)
    return jsonify(state)


@admin.get("/api/form-types/<form_type_code>/fields/search")
@require_api_role("admin")
def admin_form_type_fields_search(form_type_code):
    """Search available fields for assignment into the category browser."""
    from sqlalchemy import select as sa_select
    from app.models import MasFormTypes, MasFieldDisplayConfig

    form_type = db.session.scalar(
        sa_select(MasFormTypes).where(MasFormTypes.form_type_code == form_type_code)
    )
    if not form_type:
        return _json_error("Form type not found.", 404)

    search = request.args.get("q", "").strip()
    if len(search) < 2:
        return jsonify({"fields": []})

    fields = db.session.scalars(
        sa_select(MasFieldDisplayConfig)
        .where(
            MasFieldDisplayConfig.form_type_id == form_type.form_type_id,
            MasFieldDisplayConfig.is_active == True,
            sa.or_(
                MasFieldDisplayConfig.field_id.ilike(f"%{search}%"),
                MasFieldDisplayConfig.short_label.ilike(f"%{search}%"),
            ),
        )
        .order_by(MasFieldDisplayConfig.field_id)
        .limit(25)
    ).all()

    return jsonify({
        "fields": [
            {
                "field_id": field.field_id,
                "label": field.short_label or field.field_id,
                "category_code": field.category_code,
                "subcategory_code": field.subcategory_code,
            }
            for field in fields
        ]
    })


# --- Category CRUD ---

@admin.post("/api/form-types/<form_type_code>/categories")
@require_api_role("admin")
def admin_category_create(form_type_code):
    from sqlalchemy import select as sa_select
    from app.models import MasFormTypes
    from app.models.va_field_mapping import MasCategoryOrder

    form_type = db.session.scalar(
        sa_select(MasFormTypes).where(MasFormTypes.form_type_code == form_type_code)
    )
    if not form_type:
        return _json_error("Form type not found.", 404)

    data = request.get_json(silent=True) or {}
    code = (data.get("category_code") or "").strip()
    name = (data.get("category_name") or "").strip() or None
    order = data.get("display_order")

    if not code:
        return _json_error("category_code is required.", 400)

    existing = db.session.scalar(
        sa_select(MasCategoryOrder).where(
            MasCategoryOrder.form_type_id == form_type.form_type_id,
            MasCategoryOrder.category_code == code,
        )
    )
    if existing:
        return _json_error("Category code already exists for this form type.", 409)

    if order is None:
        max_row = db.session.scalar(
            sa.select(sa.func.max(MasCategoryOrder.display_order)).where(
                MasCategoryOrder.form_type_id == form_type.form_type_id
            )
        )
        order = (max_row or 0) + 10

    cat = MasCategoryOrder(
        form_type_id=form_type.form_type_id,
        category_code=code,
        category_name=name,
        display_order=int(order),
    )
    db.session.add(cat)
    db.session.commit()
    return jsonify({
        "category": {
            "category_code": cat.category_code,
            "category_name": cat.category_name,
            "display_order": cat.display_order,
        }
    }), 201


@admin.put("/api/form-types/<form_type_code>/categories/<category_code>")
@require_api_role("admin")
def admin_category_update(form_type_code, category_code):
    from sqlalchemy import select as sa_select
    from app.models import MasFormTypes
    from app.models.va_field_mapping import MasCategoryOrder

    form_type = db.session.scalar(
        sa_select(MasFormTypes).where(MasFormTypes.form_type_code == form_type_code)
    )
    if not form_type:
        return _json_error("Form type not found.", 404)

    cat = db.session.scalar(
        sa_select(MasCategoryOrder).where(
            MasCategoryOrder.form_type_id == form_type.form_type_id,
            MasCategoryOrder.category_code == category_code,
        )
    )
    if not cat:
        return _json_error("Category not found.", 404)

    data = request.get_json(silent=True) or {}
    if "category_name" in data:
        cat.category_name = (data["category_name"] or "").strip() or None
    if "display_order" in data:
        try:
            cat.display_order = int(data["display_order"])
        except (TypeError, ValueError):
            return _json_error("display_order must be an integer.", 400)

    db.session.commit()
    return jsonify({
        "category": {
            "category_code": cat.category_code,
            "category_name": cat.category_name,
            "display_order": cat.display_order,
        }
    })


@admin.delete("/api/form-types/<form_type_code>/categories/<category_code>")
@require_api_role("admin")
def admin_category_delete(form_type_code, category_code):
    from sqlalchemy import select as sa_select
    from app.models import MasFormTypes
    from app.models.va_field_mapping import MasCategoryOrder

    form_type = db.session.scalar(
        sa_select(MasFormTypes).where(MasFormTypes.form_type_code == form_type_code)
    )
    if not form_type:
        return _json_error("Form type not found.", 404)

    cat = db.session.scalar(
        sa_select(MasCategoryOrder).where(
            MasCategoryOrder.form_type_id == form_type.form_type_id,
            MasCategoryOrder.category_code == category_code,
        )
    )
    if not cat:
        return _json_error("Category not found.", 404)

    db.session.delete(cat)
    db.session.commit()
    return jsonify({"deleted": True})


# --- Subcategory CRUD ---

@admin.post("/api/form-types/<form_type_code>/categories/<category_code>/subcategories")
@require_api_role("admin")
def admin_subcategory_create(form_type_code, category_code):
    from sqlalchemy import select as sa_select
    from app.models import MasFormTypes
    from app.models.va_field_mapping import MasCategoryOrder, MasSubcategoryOrder

    form_type = db.session.scalar(
        sa_select(MasFormTypes).where(MasFormTypes.form_type_code == form_type_code)
    )
    if not form_type:
        return _json_error("Form type not found.", 404)

    cat = db.session.scalar(
        sa_select(MasCategoryOrder).where(
            MasCategoryOrder.form_type_id == form_type.form_type_id,
            MasCategoryOrder.category_code == category_code,
        )
    )
    if not cat:
        return _json_error("Category not found.", 404)

    data = request.get_json(silent=True) or {}
    code = (data.get("subcategory_code") or "").strip()
    name = (data.get("subcategory_name") or "").strip() or None
    order = data.get("display_order")

    if not code:
        return _json_error("subcategory_code is required.", 400)

    existing = db.session.scalar(
        sa_select(MasSubcategoryOrder).where(
            MasSubcategoryOrder.form_type_id == form_type.form_type_id,
            MasSubcategoryOrder.category_code == category_code,
            MasSubcategoryOrder.subcategory_code == code,
        )
    )
    if existing:
        return _json_error("Subcategory code already exists.", 409)

    if order is None:
        max_row = db.session.scalar(
            sa.select(sa.func.max(MasSubcategoryOrder.display_order)).where(
                MasSubcategoryOrder.form_type_id == form_type.form_type_id,
                MasSubcategoryOrder.category_code == category_code,
            )
        )
        order = (max_row or 0) + 10

    sub = MasSubcategoryOrder(
        form_type_id=form_type.form_type_id,
        category_code=category_code,
        subcategory_code=code,
        subcategory_name=name,
        display_order=int(order),
    )
    db.session.add(sub)
    db.session.commit()
    return jsonify({
        "subcategory": {
            "subcategory_code": sub.subcategory_code,
            "subcategory_name": sub.subcategory_name,
            "display_order": sub.display_order,
        }
    }), 201


@admin.put("/api/form-types/<form_type_code>/categories/<category_code>/subcategories/<subcategory_code>")
@require_api_role("admin")
def admin_subcategory_update(form_type_code, category_code, subcategory_code):
    from sqlalchemy import select as sa_select
    from app.models import MasFormTypes
    from app.models.va_field_mapping import MasSubcategoryOrder

    form_type = db.session.scalar(
        sa_select(MasFormTypes).where(MasFormTypes.form_type_code == form_type_code)
    )
    if not form_type:
        return _json_error("Form type not found.", 404)

    sub = db.session.scalar(
        sa_select(MasSubcategoryOrder).where(
            MasSubcategoryOrder.form_type_id == form_type.form_type_id,
            MasSubcategoryOrder.category_code == category_code,
            MasSubcategoryOrder.subcategory_code == subcategory_code,
        )
    )
    if not sub:
        return _json_error("Subcategory not found.", 404)

    data = request.get_json(silent=True) or {}
    if "subcategory_name" in data:
        sub.subcategory_name = (data["subcategory_name"] or "").strip() or None
    if "display_order" in data:
        try:
            sub.display_order = int(data["display_order"])
        except (TypeError, ValueError):
            return _json_error("display_order must be an integer.", 400)

    db.session.commit()
    return jsonify({
        "subcategory": {
            "subcategory_code": sub.subcategory_code,
            "subcategory_name": sub.subcategory_name,
            "display_order": sub.display_order,
        }
    })


@admin.delete("/api/form-types/<form_type_code>/categories/<category_code>/subcategories/<subcategory_code>")
@require_api_role("admin")
def admin_subcategory_delete(form_type_code, category_code, subcategory_code):
    from sqlalchemy import select as sa_select
    from app.models import MasFormTypes
    from app.models.va_field_mapping import MasSubcategoryOrder

    form_type = db.session.scalar(
        sa_select(MasFormTypes).where(MasFormTypes.form_type_code == form_type_code)
    )
    if not form_type:
        return _json_error("Form type not found.", 404)

    sub = db.session.scalar(
        sa_select(MasSubcategoryOrder).where(
            MasSubcategoryOrder.form_type_id == form_type.form_type_id,
            MasSubcategoryOrder.category_code == category_code,
            MasSubcategoryOrder.subcategory_code == subcategory_code,
        )
    )
    if not sub:
        return _json_error("Subcategory not found.", 404)

    db.session.delete(sub)
    db.session.commit()
    return jsonify({"deleted": True})


@admin.get("/api/form-types")
@require_api_role("admin")
def admin_form_types_list():
    """Return all active form types (code + name)."""
    from app.services.form_type_service import get_form_type_service
    svc = get_form_type_service()
    return jsonify({
        "form_types": [
            {
                "form_type_id": str(ft.form_type_id),
                "form_type_code": ft.form_type_code,
                "form_type_name": ft.form_type_name,
            }
            for ft in svc.list_form_types()
        ]
    })


@admin.post("/api/form-types")
@require_api_role("admin")
def admin_form_types_create():
    """Create a new blank form type."""
    user = _request_user()
    if not user.is_admin():
        return _json_error("Admin access required.", 403)

    from app.services.form_type_service import get_form_type_service
    data = request.get_json(silent=True) or {}
    code = (data.get("form_type_code") or "").strip().upper()
    name = (data.get("form_type_name") or "").strip()
    description = (data.get("description") or "").strip() or None

    if not code or not name:
        return _json_error("form_type_code and form_type_name are required.", 400)

    try:
        ft = get_form_type_service().register_form_type(code, name, description)
        return jsonify({"form_type_code": ft.form_type_code, "form_type_name": ft.form_type_name}), 201
    except ValueError as e:
        return _json_error(str(e), 409)


@admin.patch("/api/form-types/<form_type_code>")
@require_api_role("admin")
def admin_form_types_update(form_type_code):
    """Update a form type's name and description."""
    user = _request_user()
    if not user.is_admin():
        return _json_error("Admin access required.", 403)

    from app.models import MasFormTypes
    ft = db.session.scalar(
        sa.select(MasFormTypes).where(MasFormTypes.form_type_code == form_type_code)
    )
    if not ft:
        return _json_error("Form type not found.", 404)

    data = request.get_json(silent=True) or {}
    name = (data.get("form_type_name") or "").strip()
    description = (data.get("description") or "").strip() or None

    if not name:
        return _json_error("form_type_name is required.", 400)

    ft.form_type_name = name
    ft.form_type_description = description
    db.session.commit()
    return jsonify({"form_type_code": ft.form_type_code, "form_type_name": ft.form_type_name})


@admin.post("/api/form-types/<source_code>/duplicate")
@require_api_role("admin")
def admin_form_types_duplicate(source_code):
    """Duplicate a form type — copies all fields, categories, and choices."""
    user = _request_user()
    if not user.is_admin():
        return _json_error("Admin access required.", 403)

    from app.services.form_type_service import get_form_type_service
    data = request.get_json(silent=True) or {}
    new_code = (data.get("new_code") or "").strip().upper()
    new_name = (data.get("new_name") or "").strip()
    description = (data.get("description") or "").strip() or None

    if not new_code or not new_name:
        return _json_error("new_code and new_name are required.", 400)

    try:
        ft = get_form_type_service().duplicate_form_type(
            source_code.upper(), new_code, new_name, description
        )
        return jsonify({"form_type_code": ft.form_type_code, "form_type_name": ft.form_type_name}), 201
    except ValueError as e:
        return _json_error(str(e), 409)


@admin.get("/api/form-types/<form_type_code>/export")
@require_api_role("admin")
def admin_form_types_export(form_type_code):
    """Download a form type configuration as a JSON file."""
    from flask import Response
    from app.services.form_type_service import get_form_type_service
    import json

    user = _request_user()
    if not user.is_admin():
        return _json_error("Admin access required.", 403)

    try:
        data = get_form_type_service().export_form_type(form_type_code.upper())
    except ValueError as e:
        return _json_error(str(e), 404)

    filename = f"form_type_{form_type_code.lower()}.json"
    return Response(
        json.dumps(data, indent=2, ensure_ascii=False),
        mimetype="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@admin.post("/api/form-types/import")
@require_api_role("admin")
def admin_form_types_import():
    """Import a form type from an uploaded JSON file."""
    import json

    user = _request_user()
    if not user.is_admin():
        return _json_error("Admin access required.", 403)

    uploaded = request.files.get("file")
    if not uploaded:
        return _json_error("No file uploaded.", 400)

    try:
        raw = uploaded.read()
        if len(raw) > 10 * 1024 * 1024:  # 10 MB safety cap
            return _json_error("File too large (max 10 MB).", 400)
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return _json_error("Invalid JSON file.", 400)

    override_code = (request.form.get("override_code") or "").strip().upper() or None
    override_name = (request.form.get("override_name") or "").strip() or None
    override_description = request.form.get("override_description")
    if override_description is not None:
        override_description = override_description.strip() or None

    from app.services.form_type_service import get_form_type_service
    try:
        ft, stats = get_form_type_service().import_form_type(
            data,
            override_code=override_code,
            override_name=override_name,
            override_description=override_description,
        )
    except ValueError as e:
        return _json_error(str(e), 409)

    return jsonify({
        "form_type_code": ft.form_type_code,
        "form_type_name": ft.form_type_name,
        **stats,
    }), 201


@admin.get("/panels/field-mapping")
def admin_panel_field_mapping():
    denied = _require_admin_ui_access()
    if denied:
        return denied
    user = _request_user()
    if not user.is_admin():
        return render_template("va_errors/va_403.html"), 403

    from app.services.form_type_service import get_form_type_service
    svc = get_form_type_service()
    form_types = svc.list_form_types()
    stats = [svc.get_form_type_stats(ft.form_type_code) for ft in form_types]
    return render_template(
        "admin/panels/field_mapping.html",
        form_types=form_types,
        stats=stats,
    )


@admin.get("/panels/field-mapping/fields")
def admin_panel_field_mapping_fields():
    denied = _require_admin_ui_access()
    if denied:
        return denied
    user = _request_user()
    if not user.is_admin():
        return render_template("va_errors/va_403.html"), 403

    from sqlalchemy import select as sa_select
    from sqlalchemy.orm import aliased
    from app.models import MasFieldDisplayConfig, MasFormTypes, MasCategoryOrder, MasSubcategoryOrder

    form_type_code = request.args.get("form_type", "WHO_2022_VA")
    category_filter = request.args.get("category", "")
    subcategory_filter = request.args.get("subcategory", "")
    search = request.args.get("search", "").strip()
    flag_filters = set(request.args.getlist("flag")) & {"flip", "info", "summary", "pii"}
    no_category = request.args.get("no_category", "") == "1"

    form_type = db.session.scalar(
        sa_select(MasFormTypes).where(MasFormTypes.form_type_code == form_type_code)
    )
    if not form_type:
        return "Form type not found", 404

    # Load ordered categories and subcategories for filter dropdowns
    cats = db.session.scalars(
        sa_select(MasCategoryOrder)
        .where(
            MasCategoryOrder.form_type_id == form_type.form_type_id,
            MasCategoryOrder.is_active == True,
        )
        .order_by(MasCategoryOrder.display_order)
    ).all()

    subcats_for_filter = []
    if category_filter:
        subcats_for_filter = db.session.scalars(
            sa_select(MasSubcategoryOrder)
            .where(
                MasSubcategoryOrder.form_type_id == form_type.form_type_id,
                MasSubcategoryOrder.category_code == category_filter,
                MasSubcategoryOrder.is_active == True,
            )
            .order_by(MasSubcategoryOrder.display_order)
        ).all()

    # Build lookup maps for display in table
    cat_name_map = {c.category_code: c.category_name or c.category_code for c in cats}
    all_subcats = db.session.scalars(
        sa_select(MasSubcategoryOrder)
        .where(
            MasSubcategoryOrder.form_type_id == form_type.form_type_id,
            MasSubcategoryOrder.is_active == True,
        )
    ).all()
    subcat_name_map = {
        (s.category_code, s.subcategory_code): s.subcategory_name or s.subcategory_code
        for s in all_subcats
    }

    cat_order = aliased(MasCategoryOrder)
    subcat_order = aliased(MasSubcategoryOrder)

    query = (
        sa_select(MasFieldDisplayConfig)
        .outerjoin(
            cat_order,
            sa.and_(
                cat_order.form_type_id == MasFieldDisplayConfig.form_type_id,
                cat_order.category_code == MasFieldDisplayConfig.category_code,
                cat_order.is_active == True,
            )
        )
        .outerjoin(
            subcat_order,
            sa.and_(
                subcat_order.form_type_id == MasFieldDisplayConfig.form_type_id,
                subcat_order.category_code == MasFieldDisplayConfig.category_code,
                subcat_order.subcategory_code == MasFieldDisplayConfig.subcategory_code,
                subcat_order.is_active == True,
            )
        )
        .where(
            MasFieldDisplayConfig.form_type_id == form_type.form_type_id,
            MasFieldDisplayConfig.is_active == True,
        )
        .order_by(
            cat_order.display_order.is_(None),
            cat_order.display_order,
            MasFieldDisplayConfig.category_code,
            subcat_order.display_order.is_(None),
            subcat_order.display_order,
            MasFieldDisplayConfig.subcategory_code,
            MasFieldDisplayConfig.display_order,
            MasFieldDisplayConfig.field_id,
        )
    )
    if no_category:
        query = query.where(MasFieldDisplayConfig.category_code == None)
    elif category_filter:
        query = query.where(MasFieldDisplayConfig.category_code == category_filter)
    if subcategory_filter:
        query = query.where(MasFieldDisplayConfig.subcategory_code == subcategory_filter)
    _FLAG_FILTERS = {
        "flip":    MasFieldDisplayConfig.flip_color == True,
        "info":    MasFieldDisplayConfig.is_info == True,
        "summary": MasFieldDisplayConfig.summary_include == True,
        "pii":     MasFieldDisplayConfig.is_pii == True,
    }
    for f in flag_filters:
        query = query.where(_FLAG_FILTERS[f])
    if search:
        query = query.where(
            sa.or_(
                MasFieldDisplayConfig.field_id.ilike(f"%{search}%"),
                MasFieldDisplayConfig.short_label.ilike(f"%{search}%"),
            )
        )

    fields = db.session.scalars(query).all()

    # Group subcategories by category_code for inline selects
    subcats_by_cat = {}
    for s in all_subcats:
        subcats_by_cat.setdefault(s.category_code, []).append(s)

    return render_template(
        "admin/panels/field_mapping_fields.html",
        form_type_code=form_type_code,
        fields=fields,
        category_filter=category_filter,
        subcategory_filter=subcategory_filter,
        search=search,
        flag_filters=flag_filters,
        no_category=no_category,
        categories=cats,
        subcategories_for_filter=subcats_for_filter,
        cat_name_map=cat_name_map,
        subcat_name_map=subcat_name_map,
        subcats_by_cat=subcats_by_cat,
    )


@admin.route("/panels/field-mapping/field/<form_type_code>/<field_id>",
             methods=["GET", "POST"])
def admin_panel_field_mapping_field_edit(form_type_code, field_id):
    denied = _require_admin_ui_access()
    if denied:
        return denied
    user = _request_user()
    if not user.is_admin():
        return render_template("va_errors/va_403.html"), 403

    from sqlalchemy import select as sa_select
    from app.models import MasFieldDisplayConfig, MasFormTypes
    from app.models.va_field_mapping import MasCategoryOrder, MasSubcategoryOrder

    form_type = db.session.scalar(
        sa_select(MasFormTypes).where(MasFormTypes.form_type_code == form_type_code)
    )
    if not form_type:
        return "Form type not found", 404

    field = db.session.scalar(
        sa_select(MasFieldDisplayConfig).where(
            MasFieldDisplayConfig.form_type_id == form_type.form_type_id,
            MasFieldDisplayConfig.field_id == field_id,
        )
    )
    if not field:
        return "Field not found", 404

    # Load categories for this form type
    categories = db.session.scalars(
        sa_select(MasCategoryOrder)
        .where(MasCategoryOrder.form_type_id == form_type.form_type_id)
        .order_by(MasCategoryOrder.display_order)
    ).all()

    # Load subcategories for the field's current category (if any)
    subcategories = []
    if field.category_code:
        subcategories = db.session.scalars(
            sa_select(MasSubcategoryOrder)
            .where(
                MasSubcategoryOrder.form_type_id == form_type.form_type_id,
                MasSubcategoryOrder.category_code == field.category_code,
            )
            .order_by(MasSubcategoryOrder.display_order)
        ).all()

    if request.method == "POST":
        field.short_label = request.form.get("short_label") or field.short_label
        field.full_label = request.form.get("full_label") or None
        field.category_code = request.form.get("category_code") or None
        field.subcategory_code = request.form.get("subcategory_code") or None
        raw_order = (request.form.get("display_order") or "").strip()
        if raw_order:
            try:
                field.display_order = Decimal(raw_order)
            except InvalidOperation:
                return "display_order must be a number.", 400
        field.flip_color = request.form.get("flip_color") == "on"
        field.is_info = request.form.get("is_info") == "on"
        field.summary_include = request.form.get("summary_include") == "on"
        field.is_pii = request.form.get("is_pii") == "on"
        field.pii_type = request.form.get("pii_type") or None
        db.session.commit()

        # Clear service cache so updated label is reflected immediately
        from app.services.field_mapping_service import get_mapping_service
        get_mapping_service().clear_cache()

        # Return updated table row for hx-swap="outerHTML"
        all_subcats_row = db.session.scalars(
            sa_select(MasSubcategoryOrder)
            .where(MasSubcategoryOrder.form_type_id == form_type.form_type_id)
        ).all()
        cat_name_map_row = {c.category_code: c.category_name or c.category_code for c in categories}
        subcat_name_map_row = {
            (s.category_code, s.subcategory_code): s.subcategory_name or s.subcategory_code
            for s in all_subcats_row
        }
        subcats_by_cat_row = {}
        for s in all_subcats_row:
            subcats_by_cat_row.setdefault(s.category_code, []).append(s)
        return render_template(
            "admin/panels/field_mapping_field_row.html",
            form_type_code=form_type_code,
            field=field,
            categories=categories,
            cat_name_map=cat_name_map_row,
            subcat_name_map=subcat_name_map_row,
            subcats_by_cat=subcats_by_cat_row,
        )

    return render_template(
        "admin/panels/field_mapping_field_edit.html",
        form_type_code=form_type_code,
        field=field,
        categories=categories,
        subcategories=subcategories,
    )


@admin.patch("/panels/field-mapping/field/<form_type_code>/<field_id>/category")
def admin_panel_field_mapping_field_quick_category(form_type_code, field_id):
    """Quick inline update of category/subcategory only. Returns updated table row HTML."""
    denied = _require_admin_ui_access()
    if denied:
        return denied
    user = _request_user()
    if not user.is_admin():
        return render_template("va_errors/va_403.html"), 403

    from sqlalchemy import select as sa_select
    from app.models import MasFieldDisplayConfig, MasFormTypes
    from app.models.va_field_mapping import MasCategoryOrder, MasSubcategoryOrder

    form_type = db.session.scalar(
        sa_select(MasFormTypes).where(MasFormTypes.form_type_code == form_type_code)
    )
    if not form_type:
        return "Form type not found", 404

    field = db.session.scalar(
        sa_select(MasFieldDisplayConfig).where(
            MasFieldDisplayConfig.form_type_id == form_type.form_type_id,
            MasFieldDisplayConfig.field_id == field_id,
        )
    )
    if not field:
        return "Field not found", 404

    new_cat = request.form.get("category_code") or None
    new_sub = request.form.get("subcategory_code") or None

    # Clear subcategory if category changed
    if new_cat != field.category_code:
        new_sub = None

    field.category_code = new_cat
    field.subcategory_code = new_sub
    db.session.commit()

    from app.services.field_mapping_service import get_mapping_service
    get_mapping_service().clear_cache()

    # Build context needed to render the row with inline selects
    cats = db.session.scalars(
        sa_select(MasCategoryOrder)
        .where(MasCategoryOrder.form_type_id == form_type.form_type_id)
        .order_by(MasCategoryOrder.display_order)
    ).all()
    all_subcats = db.session.scalars(
        sa_select(MasSubcategoryOrder)
        .where(MasSubcategoryOrder.form_type_id == form_type.form_type_id)
    ).all()
    cat_name_map = {c.category_code: c.category_name or c.category_code for c in cats}
    subcat_name_map = {
        (s.category_code, s.subcategory_code): s.subcategory_name or s.subcategory_code
        for s in all_subcats
    }
    subcats_by_cat = {}
    for s in all_subcats:
        subcats_by_cat.setdefault(s.category_code, []).append(s)

    return render_template(
        "admin/panels/field_mapping_field_row.html",
        form_type_code=form_type_code,
        field=field,
        categories=cats,
        cat_name_map=cat_name_map,
        subcat_name_map=subcat_name_map,
        subcats_by_cat=subcats_by_cat,
    )


@admin.patch("/panels/field-mapping/field/<form_type_code>/<field_id>/order")
def admin_panel_field_mapping_field_quick_order(form_type_code, field_id):
    """Quick inline update of field display_order. Returns updated table row HTML."""
    denied = _require_admin_ui_access()
    if denied:
        return denied
    user = _request_user()
    if not user.is_admin():
        return render_template("va_errors/va_403.html"), 403

    from sqlalchemy import select as sa_select
    from app.models import MasFieldDisplayConfig, MasFormTypes
    from app.models.va_field_mapping import MasCategoryOrder, MasSubcategoryOrder

    form_type = db.session.scalar(
        sa_select(MasFormTypes).where(MasFormTypes.form_type_code == form_type_code)
    )
    if not form_type:
        return "Form type not found", 404

    field = db.session.scalar(
        sa_select(MasFieldDisplayConfig).where(
            MasFieldDisplayConfig.form_type_id == form_type.form_type_id,
            MasFieldDisplayConfig.field_id == field_id,
        )
    )
    if not field:
        return "Field not found", 404

    raw_order = (request.form.get("display_order") or "").strip()
    try:
        field.display_order = Decimal(raw_order)
    except InvalidOperation:
        return "display_order must be a number.", 400

    db.session.commit()

    from app.services.field_mapping_service import get_mapping_service
    get_mapping_service().clear_cache()

    cats = db.session.scalars(
        sa_select(MasCategoryOrder)
        .where(MasCategoryOrder.form_type_id == form_type.form_type_id)
        .order_by(MasCategoryOrder.display_order)
    ).all()
    all_subcats = db.session.scalars(
        sa_select(MasSubcategoryOrder)
        .where(MasSubcategoryOrder.form_type_id == form_type.form_type_id)
    ).all()
    cat_name_map = {c.category_code: c.category_name or c.category_code for c in cats}
    subcat_name_map = {
        (s.category_code, s.subcategory_code): s.subcategory_name or s.subcategory_code
        for s in all_subcats
    }
    subcats_by_cat = {}
    for s in all_subcats:
        subcats_by_cat.setdefault(s.category_code, []).append(s)

    return render_template(
        "admin/panels/field_mapping_field_row.html",
        form_type_code=form_type_code,
        field=field,
        categories=cats,
        cat_name_map=cat_name_map,
        subcat_name_map=subcat_name_map,
        subcats_by_cat=subcats_by_cat,
    )


@admin.get("/panels/field-mapping/categories")
def admin_panel_field_mapping_categories():
    denied = _require_admin_ui_access()
    if denied:
        return denied
    user = _request_user()
    if not user.is_admin():
        return render_template("va_errors/va_403.html"), 403

    from sqlalchemy import select as sa_select
    from app.models import MasFormTypes
    from app.models.va_field_mapping import MasCategoryOrder

    form_type_code = request.args.get("form_type", "").strip()
    form_type = db.session.scalar(
        sa_select(MasFormTypes).where(MasFormTypes.form_type_code == form_type_code)
    )
    if not form_type:
        return "Form type not found", 404

    fields_by_category, _ = _ordered_field_lists_for_form_type(form_type.form_type_id)

    categories = db.session.scalars(
        sa_select(MasCategoryOrder)
        .where(MasCategoryOrder.form_type_id == form_type.form_type_id)
        .order_by(MasCategoryOrder.display_order)
    ).all()

    categories_json = [
        {
            "category_code": c.category_code,
            "category_name": c.category_name,
            "display_order": c.display_order,
            "ordered_fields": fields_by_category.get(c.category_code, []),
        }
        for c in categories
    ]

    return render_template(
        "admin/panels/field_mapping_categories.html",
        form_type_code=form_type_code,
        form_type_name=form_type.form_type_name,
        categories_json=categories_json,
    )


@admin.get("/panels/field-mapping/sync")
def admin_panel_field_mapping_sync():
    denied = _require_admin_ui_access()
    if denied:
        return denied
    user = _request_user()
    if not user.is_admin():
        return render_template("va_errors/va_403.html"), 403

    form_type_code = request.args.get("form_type", "WHO_2022_VA")
    return render_template(
        "admin/panels/field_mapping_sync.html",
        form_type_code=form_type_code,
    )


@admin.post("/panels/field-mapping/sync/preview")
def admin_panel_field_mapping_sync_preview():
    denied = _require_admin_ui_access()
    if denied:
        return denied
    user = _request_user()
    if not user.is_admin():
        return _json_error("Admin access required.", 403)

    from app.services.odk_schema_sync_service import get_sync_service
    data = request.get_json(force=True)
    form_type_code = data.get("form_type_code")
    odk_project_id = data.get("odk_project_id")
    odk_form_id = data.get("odk_form_id")
    connection_id_str = data.get("connection_id")

    if not all([form_type_code, odk_project_id, odk_form_id, connection_id_str]):
        return _json_error("Missing required fields.", 400)

    try:
        conn_uuid = uuid.UUID(connection_id_str)
    except (ValueError, AttributeError):
        return _json_error("Invalid connection_id.", 400)

    conn = db.session.get(MasOdkConnections, conn_uuid)
    if not conn:
        return _json_error("ODK connection not found.", 404)
    if conn.status.value != "active":
        return _json_error(f"ODK connection '{conn.connection_name}' is not active.", 400)

    client = _get_odk_client_for_connection(conn)
    result = get_sync_service().preview_sync(
        form_type_code, int(odk_project_id), odk_form_id, client=client
    )
    return jsonify(result)


@admin.post("/panels/field-mapping/sync/apply")
def admin_panel_field_mapping_sync_apply():
    """Apply a user-selected subset of previewed sync changes."""
    denied = _require_admin_ui_access()
    if denied:
        return denied
    user = _request_user()
    if not user.is_admin():
        return _json_error("Admin access required.", 403)

    from app.services.odk_schema_sync_service import get_sync_service
    data = request.get_json(force=True)
    form_type_code = data.get("form_type_code")
    selected = data.get("selected") or {}

    if not form_type_code:
        return _json_error("form_type_code is required.", 400)

    stats = get_sync_service().sync_selected(form_type_code, selected)
    return jsonify(stats)


@admin.post("/panels/field-mapping/sync")
def admin_panel_field_mapping_sync_run():
    denied = _require_admin_ui_access()
    if denied:
        return denied
    user = _request_user()
    if not user.is_admin():
        return _json_error("Admin access required.", 403)

    from app.services.odk_schema_sync_service import get_sync_service
    data = request.get_json(force=True)
    form_type_code = data.get("form_type_code")
    odk_project_id = data.get("odk_project_id")
    odk_form_id = data.get("odk_form_id")
    connection_id_str = data.get("connection_id")

    if not all([form_type_code, odk_project_id, odk_form_id, connection_id_str]):
        return _json_error("Missing form_type_code, connection_id, odk_project_id, or odk_form_id.", 400)

    try:
        conn_uuid = uuid.UUID(connection_id_str)
    except (ValueError, AttributeError):
        return _json_error("Invalid connection_id.", 400)

    conn = db.session.get(MasOdkConnections, conn_uuid)
    if not conn:
        return _json_error("ODK connection not found.", 404)
    if conn.status.value != "active":
        return _json_error(f"ODK connection '{conn.connection_name}' is not active.", 400)

    client = _get_odk_client_for_connection(conn)
    stats = get_sync_service().sync_form_choices(
        form_type_code, int(odk_project_id), odk_form_id, client=client
    )
    return jsonify(stats)


# ---------------------------------------------------------------------------
# ODK Connections API  (admin-only)
# ---------------------------------------------------------------------------

def _serialize_odk_connection(conn, project_ids: list[str]) -> dict:
    """Serialize an ODK connection — never include encrypted fields."""
    return {
        "connection_id": str(conn.connection_id),
        "connection_name": conn.connection_name,
        "base_url": conn.base_url,
        "status": conn.status.value,
        "notes": conn.notes or "",
        "project_ids": project_ids,
        "created_at": conn.created_at.isoformat(),
        "updated_at": conn.updated_at.isoformat(),
    }


def _get_connection_project_ids(connection_id: uuid.UUID) -> list[str]:
    rows = db.session.scalars(
        sa.select(MapProjectOdk.project_id).where(
            MapProjectOdk.connection_id == connection_id
        )
    ).all()
    return sorted(rows)


@admin.get("/api/odk-connections")
@require_api_role("admin")
def admin_odk_connections_list():
    user = _request_user()
    if not user.is_admin():
        return _json_error("Admin access required.", 403)

    conns = db.session.scalars(
        sa.select(MasOdkConnections).order_by(MasOdkConnections.connection_name)
    ).all()
    result = [
        _serialize_odk_connection(c, _get_connection_project_ids(c.connection_id))
        for c in conns
    ]
    return jsonify({"connections": result})


@admin.post("/api/odk-connections")
@require_api_role("admin")
def admin_odk_connections_create():
    user = _request_user()
    if not user.is_admin():
        return _json_error("Admin access required.", 403)

    payload = request.get_json(silent=True) or {}
    connection_name = (payload.get("connection_name") or "").strip()
    base_url = (payload.get("base_url") or "").strip().rstrip("/")
    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""

    if not connection_name:
        return _json_error("connection_name is required.", 400)
    if not base_url:
        return _json_error("base_url is required.", 400)
    if not username:
        return _json_error("username is required.", 400)
    if not password:
        return _json_error("password is required.", 400)

    existing = db.session.scalar(
        sa.select(MasOdkConnections).where(
            MasOdkConnections.connection_name == connection_name
        )
    )
    if existing:
        return _json_error("A connection with that name already exists.", 400)

    from app.utils.credential_crypto import encrypt_credential, get_odk_pepper
    try:
        pepper = get_odk_pepper()
    except RuntimeError as exc:
        return _json_error(str(exc), 500)

    username_enc, username_salt = encrypt_credential(username, pepper)
    password_enc, password_salt = encrypt_credential(password, pepper)

    conn = MasOdkConnections(
        connection_name=connection_name,
        base_url=base_url,
        username_enc=username_enc,
        username_salt=username_salt,
        password_enc=password_enc,
        password_salt=password_salt,
        status=VaStatuses.active,
        notes=(payload.get("notes") or "").strip() or None,
    )
    db.session.add(conn)
    db.session.commit()
    return jsonify(
        {"connection": _serialize_odk_connection(conn, [])}
    ), 201


@admin.put("/api/odk-connections/<uuid:connection_id>")
@require_api_role("admin")
def admin_odk_connections_update(connection_id):
    user = _request_user()
    if not user.is_admin():
        return _json_error("Admin access required.", 403)

    conn = db.session.get(MasOdkConnections, connection_id)
    if not conn:
        return _json_error("Connection not found.", 404)

    payload = request.get_json(silent=True) or {}

    if "connection_name" in payload:
        name = (payload["connection_name"] or "").strip()
        if not name:
            return _json_error("connection_name cannot be empty.", 400)
        dup = db.session.scalar(
            sa.select(MasOdkConnections).where(
                MasOdkConnections.connection_name == name,
                MasOdkConnections.connection_id != connection_id,
            )
        )
        if dup:
            return _json_error("A connection with that name already exists.", 400)
        conn.connection_name = name

    if "base_url" in payload:
        base_url = (payload["base_url"] or "").strip().rstrip("/")
        if not base_url:
            return _json_error("base_url cannot be empty.", 400)
        conn.base_url = base_url

    if "notes" in payload:
        conn.notes = (payload["notes"] or "").strip() or None

    # Re-encrypt credentials only if new values are provided
    if payload.get("username") or payload.get("password"):
        from app.utils.credential_crypto import encrypt_credential, decrypt_credential, get_odk_pepper
        try:
            pepper = get_odk_pepper()
        except RuntimeError as exc:
            return _json_error(str(exc), 500)

        if payload.get("username"):
            username = (payload["username"] or "").strip()
            if not username:
                return _json_error("username cannot be empty.", 400)
            conn.username_enc, conn.username_salt = encrypt_credential(username, pepper)

        if payload.get("password"):
            conn.password_enc, conn.password_salt = encrypt_credential(
                payload["password"], pepper
            )

    if "status" in payload:
        try:
            conn.status = VaStatuses(payload["status"])
        except ValueError:
            return _json_error("Invalid status.", 400)

    db.session.commit()
    project_ids = _get_connection_project_ids(connection_id)
    return jsonify({"connection": _serialize_odk_connection(conn, project_ids)})


@admin.post("/api/odk-connections/<uuid:connection_id>/toggle")
@require_api_role("admin")
def admin_odk_connections_toggle(connection_id):
    user = _request_user()
    if not user.is_admin():
        return _json_error("Admin access required.", 403)

    conn = db.session.get(MasOdkConnections, connection_id)
    if not conn:
        return _json_error("Connection not found.", 404)

    conn.status = (
        VaStatuses.deactive if conn.status == VaStatuses.active else VaStatuses.active
    )
    db.session.commit()
    return jsonify(
        {"connection_id": str(conn.connection_id), "status": conn.status.value}
    )


@admin.post("/api/odk-connections/<uuid:connection_id>/test")
@require_api_role("admin")
def admin_odk_connections_test(connection_id):
    """Attempt a live authentication check against the ODK server."""
    user = _request_user()
    if not user.is_admin():
        return _json_error("Admin access required.", 403)

    conn = db.session.get(MasOdkConnections, connection_id)
    if not conn:
        return _json_error("Connection not found.", 404)

    from app.utils.credential_crypto import decrypt_credential, get_odk_pepper
    try:
        pepper = get_odk_pepper()
        username = decrypt_credential(conn.username_enc, conn.username_salt, pepper)
        password = decrypt_credential(conn.password_enc, conn.password_salt, pepper)
    except (RuntimeError, ValueError) as exc:
        return _json_error(f"Credential decryption failed: {exc}", 500)

    try:
        import requests as http
        resp = http.post(
            f"{conn.base_url}/v1/sessions",
            json={"email": username, "password": password},
            timeout=10,
        )
        if resp.status_code == 200:
            return jsonify({"ok": True, "message": "Authentication successful."})
        return jsonify(
            {"ok": False, "message": f"ODK returned HTTP {resp.status_code}."}
        ), 200
    except Exception as exc:
        return jsonify({"ok": False, "message": f"Connection error: {exc}"}), 200


# ---------------------------------------------------------------------------
# Project ↔ ODK connection mapping API
# ---------------------------------------------------------------------------

@admin.get("/api/odk-connections/<uuid:connection_id>/projects")
@require_api_role("admin")
def admin_odk_connection_projects(connection_id):
    user = _request_user()
    if not user.is_admin():
        return _json_error("Admin access required.", 403)

    conn = db.session.get(MasOdkConnections, connection_id)
    if not conn:
        return _json_error("Connection not found.", 404)

    return jsonify({"project_ids": _get_connection_project_ids(connection_id)})


@admin.post("/api/odk-connections/<uuid:connection_id>/assign-project")
@require_api_role("admin")
def admin_odk_assign_project(connection_id):
    user = _request_user()
    if not user.is_admin():
        return _json_error("Admin access required.", 403)

    conn = db.session.get(MasOdkConnections, connection_id)
    if not conn:
        return _json_error("Connection not found.", 404)

    payload = request.get_json(silent=True) or {}
    project_id = (payload.get("project_id") or "").strip().upper()
    if not project_id:
        return _json_error("project_id is required.", 400)

    project = db.session.get(VaProjectMaster, project_id)
    if not project:
        return _json_error("Project not found.", 404)

    existing = db.session.scalar(
        sa.select(MapProjectOdk).where(MapProjectOdk.project_id == project_id)
    )
    if existing:
        if existing.connection_id == connection_id:
            return jsonify({"message": "Already assigned.", "project_id": project_id})
        # Re-point to new connection
        existing.connection_id = connection_id
    else:
        db.session.add(MapProjectOdk(project_id=project_id, connection_id=connection_id))

    db.session.commit()
    return jsonify({"project_id": project_id, "connection_id": str(connection_id)}), 201


@admin.delete("/api/odk-connections/<uuid:connection_id>/assign-project/<project_id>")
@require_api_role("admin")
def admin_odk_unassign_project(connection_id, project_id):
    user = _request_user()
    if not user.is_admin():
        return _json_error("Admin access required.", 403)

    mapping = db.session.scalar(
        sa.select(MapProjectOdk).where(
            MapProjectOdk.connection_id == connection_id,
            MapProjectOdk.project_id == project_id.upper(),
        )
    )
    if not mapping:
        return _json_error("Mapping not found.", 404)

    db.session.delete(mapping)
    db.session.commit()
    return jsonify({"message": "Project unassigned."})


# ---------------------------------------------------------------------------
# ODK Central live data (projects / forms) fetched via pyODK
# ---------------------------------------------------------------------------

def _get_odk_client_for_connection(conn: MasOdkConnections):
    """Return a ready pyODK Client for the given connection row."""
    import os
    from flask import current_app
    from app.utils.va_odk.va_odk_01_clientsetup import client_from_connection
    pyodk_dir = os.path.join(current_app.config.get("APP_RESOURCE"), "pyodk")
    return client_from_connection(conn, pyodk_dir)


@admin.get("/api/odk-connections/<uuid:connection_id>/odk-projects")
@require_api_role("admin")
def admin_odk_list_odk_projects(connection_id):
    """List ODK Central projects available on the connection."""
    user = _request_user()
    if not user.is_admin():
        return _json_error("Admin access required.", 403)

    conn = db.session.get(MasOdkConnections, connection_id)
    if not conn:
        return _json_error("Connection not found.", 404)

    try:
        client = _get_odk_client_for_connection(conn)
        projects = client.projects.list()
        return jsonify({
            "odk_projects": [
                {"id": p.id, "name": p.name} for p in projects
            ]
        })
    except Exception as exc:
        return _json_error(f"Failed to fetch ODK projects: {exc}", 502)


@admin.get("/api/odk-connections/<uuid:connection_id>/odk-projects/<int:odk_project_id>/forms")
@require_api_role("admin")
def admin_odk_list_forms(connection_id, odk_project_id):
    """List forms in a specific ODK Central project."""
    user = _request_user()
    if not user.is_admin():
        return _json_error("Admin access required.", 403)

    conn = db.session.get(MasOdkConnections, connection_id)
    if not conn:
        return _json_error("Connection not found.", 404)

    try:
        client = _get_odk_client_for_connection(conn)
        forms = client.forms.list(project_id=odk_project_id)
        return jsonify({
            "forms": [
                {"xmlFormId": f.xmlFormId, "name": f.name, "version": f.version}
                for f in forms
            ]
        })
    except Exception as exc:
        return _json_error(f"Failed to fetch ODK forms: {exc}", 502)


# ---------------------------------------------------------------------------
# Project-site → ODK form mappings
# ---------------------------------------------------------------------------

@admin.get("/api/projects/<project_id>/odk-connection")
@require_api_role("admin")
def admin_project_odk_connection(project_id):
    """Return the ODK connection linked to this project, or null."""
    user = _request_user()
    if not user.is_admin():
        return _json_error("Admin access required.", 403)

    mapping = db.session.scalar(
        sa.select(MapProjectOdk).where(
            MapProjectOdk.project_id == project_id.upper()
        )
    )
    if not mapping:
        return jsonify({"connection": None})

    conn = db.session.get(MasOdkConnections, mapping.connection_id)
    if not conn:
        return jsonify({"connection": None})

    return jsonify({
        "connection": {
            "connection_id": str(conn.connection_id),
            "connection_name": conn.connection_name,
            "status": conn.status.value,
        }
    })

@admin.get("/api/projects/<project_id>/odk-site-mappings")
@require_api_role("admin")
def admin_odk_site_mappings_list(project_id):
    """Return ODK form mappings for all sites in a project."""
    user = _request_user()
    if not user.is_admin():
        return _json_error("Admin access required.", 403)

    project_id = project_id.upper()
    rows = db.session.scalars(
        sa.select(MapProjectSiteOdk).where(
            MapProjectSiteOdk.project_id == project_id
        )
    ).all()
    return jsonify({
        "mappings": [
            {
                "site_id": r.site_id,
                "odk_project_id": r.odk_project_id,
                "odk_form_id": r.odk_form_id,
                "form_type_id": str(r.form_type_id) if r.form_type_id else None,
                "form_type_code": r.form_type.form_type_code if r.form_type else None,
            }
            for r in rows
        ]
    })


@admin.post("/api/projects/<project_id>/odk-site-mappings")
@require_api_role("admin")
def admin_odk_site_mappings_save(project_id):
    """Upsert the ODK form mapping for a single project-site.

    Body: { "site_id": "XX01", "odk_project_id": 3, "odk_form_id": "va_form",
            "form_type_id": "<uuid>" }
    form_type_id is optional but strongly recommended.
    """
    user = _request_user()
    if not user.is_admin():
        return _json_error("Admin access required.", 403)

    from app.models.va_field_mapping import MasFormTypes
    import uuid as _uuid

    data = request.get_json(silent=True) or {}
    project_id = project_id.upper()
    site_id = (data.get("site_id") or "").upper()
    odk_project_id = data.get("odk_project_id")
    odk_form_id = (data.get("odk_form_id") or "").strip()
    form_type_id_raw = (data.get("form_type_id") or "").strip()

    if not site_id or odk_project_id is None or not odk_form_id:
        return _json_error("site_id, odk_project_id, and odk_form_id are required.", 400)

    try:
        odk_project_id = int(odk_project_id)
    except (TypeError, ValueError):
        return _json_error("odk_project_id must be an integer.", 400)

    # Resolve form_type_id if provided
    form_type_id = None
    if form_type_id_raw:
        try:
            parsed_uuid = _uuid.UUID(form_type_id_raw)
        except ValueError:
            return _json_error("form_type_id must be a valid UUID.", 400)
        ft = db.session.get(MasFormTypes, parsed_uuid)
        if not ft:
            return _json_error("form_type_id not found.", 404)
        form_type_id = parsed_uuid

    project = db.session.get(VaProjectMaster, project_id)
    if not project:
        return _json_error("Project not found.", 404)

    site = db.session.get(VaSiteMaster, site_id)
    if not site:
        return _json_error("Site not found.", 404)

    existing = db.session.scalar(
        sa.select(MapProjectSiteOdk).where(
            MapProjectSiteOdk.project_id == project_id,
            MapProjectSiteOdk.site_id == site_id,
        )
    )
    if existing:
        existing.odk_project_id = odk_project_id
        existing.odk_form_id = odk_form_id
        existing.form_type_id = form_type_id
        status_code = 200
    else:
        existing = MapProjectSiteOdk(
            project_id=project_id,
            site_id=site_id,
            odk_project_id=odk_project_id,
            odk_form_id=odk_form_id,
            form_type_id=form_type_id,
        )
        db.session.add(existing)
        status_code = 201

    db.session.commit()
    # Refresh to load the relationship
    db.session.refresh(existing)
    return jsonify({
        "mapping": {
            "site_id": existing.site_id,
            "odk_project_id": existing.odk_project_id,
            "odk_form_id": existing.odk_form_id,
            "form_type_id": str(existing.form_type_id) if existing.form_type_id else None,
            "form_type_code": existing.form_type.form_type_code if existing.form_type else None,
        }
    }), status_code


@admin.delete("/api/projects/<project_id>/odk-site-mappings/<site_id>")
@require_api_role("admin")
def admin_odk_site_mappings_delete(project_id, site_id):
    """Remove the ODK form mapping for a project-site."""
    user = _request_user()
    if not user.is_admin():
        return _json_error("Admin access required.", 403)

    project_id = project_id.upper()
    site_id = site_id.upper()
    
    project = db.session.get(VaProjectMaster, project_id)
    if not project:
        return _json_error("Project not found.", 404)

    mapping = db.session.scalar(
        sa.select(MapProjectSiteOdk).where(
            MapProjectSiteOdk.project_id == project_id,
            MapProjectSiteOdk.site_id == site_id,
        )
    )
    if not mapping:
        return _json_error("Mapping not found.", 404)

    db.session.delete(mapping)
    db.session.commit()
    return jsonify({"message": "Mapping removed."})


# ---------------------------------------------------------------------------
# Sync Dashboard  (admin-only)
# ---------------------------------------------------------------------------

@admin.get("/panels/sync")
def admin_panel_sync():
    denied = _require_admin_ui_access()
    if denied:
        return denied
    user = _request_user()
    if not user.is_admin():
        return render_template("va_errors/va_403.html"), 403
    return render_template("admin/panels/sync_dashboard.html")


@admin.get("/api/sync/status")
@require_api_role("admin")
def admin_sync_status():
    from app.models.va_sync_runs import VaSyncRun

    running = db.session.scalar(
        sa.select(VaSyncRun)
        .where(VaSyncRun.status == "running")
        .order_by(VaSyncRun.started_at.desc())
        .limit(1)
    )
    last_completed = db.session.scalar(
        sa.select(VaSyncRun)
        .where(VaSyncRun.status.in_(["success", "error"]))
        .order_by(VaSyncRun.started_at.desc())
        .limit(1)
    )

    schedule_hours = _get_sync_schedule_hours()

    return jsonify({
        "is_running": running is not None,
        "current_run": _sync_run_dict(running) if running else None,
        "last_completed": _sync_run_dict(last_completed) if last_completed else None,
        "schedule_hours": schedule_hours,
    })


@admin.get("/api/sync/history")
@require_api_role("admin")
def admin_sync_history():
    from app.models.va_sync_runs import VaSyncRun

    try:
        limit = min(int(request.args.get("limit", 20)), 100)
    except (TypeError, ValueError):
        limit = 20

    runs = db.session.scalars(
        sa.select(VaSyncRun)
        .order_by(VaSyncRun.started_at.desc())
        .limit(limit)
    ).all()

    return jsonify({"runs": [_sync_run_dict(r) for r in runs]})


@admin.post("/api/sync/trigger")
@require_api_role("admin")
def admin_sync_trigger():
    from app.models.va_sync_runs import VaSyncRun
    from app.tasks.sync_tasks import run_odk_sync

    running = db.session.scalar(
        sa.select(VaSyncRun)
        .where(VaSyncRun.status == "running")
        .limit(1)
    )
    if running:
        return _json_error("A sync is already in progress.", 409)

    user = _request_user()
    task = run_odk_sync.delay(
        triggered_by="manual",
        user_id=str(user.user_id) if user else None,
    )
    return jsonify({"message": "Sync started.", "task_id": task.id}), 202


@admin.post("/api/sync/schedule")
@require_api_role("admin")
def admin_sync_schedule():
    import json as _json

    data = request.get_json(silent=True) or {}
    try:
        hours = int(data.get("interval_hours", 0))
    except (TypeError, ValueError):
        return _json_error("interval_hours must be an integer.", 400)
    if not (1 <= hours <= 168):
        return _json_error("interval_hours must be between 1 and 168.", 400)

    try:
        with db.engine.begin() as conn:
            interval_id = conn.execute(sa.text(
                "SELECT id FROM public.celery_intervalschedule "
                "WHERE every = :h AND period = 'hours' LIMIT 1"
            ), {"h": hours}).scalar()
            if interval_id is None:
                interval_id = conn.execute(sa.text(
                    "INSERT INTO public.celery_intervalschedule (every, period) "
                    "VALUES (:h, 'hours') RETURNING id"
                ), {"h": hours}).scalar()

            conn.execute(sa.text("""
                UPDATE public.celery_periodictask
                SET schedule_id = :sid,
                    discriminator = 'intervalschedule',
                    date_changed = NOW()
                WHERE name = :name
            """), {"sid": interval_id, "name": "ODK Sync — every 6 hours"})

            # Signal beat to reload
            conn.execute(sa.text(
                "INSERT INTO public.celery_periodictaskchanged (last_update) "
                "VALUES (NOW()) ON CONFLICT DO NOTHING"
            ))
    except Exception as e:
        return _json_error(f"Could not update schedule: {str(e)}", 503)

    return jsonify({"interval_hours": hours})


@admin.get("/api/sync/coverage")
@require_api_role("admin")
def admin_sync_coverage():
    from app.models.va_submissions import VaSubmissions
    from app.models.va_forms import VaForms
    from app.utils.va_odk.va_odk_04_submissioncount import va_odk_submissioncount

    mappings = db.session.scalars(sa.select(MapProjectSiteOdk)).all()

    rows = []
    odk_total = 0
    local_total = 0

    for mapping in mappings:
        form = db.session.scalar(
            sa.select(VaForms).where(
                VaForms.project_id == mapping.project_id,
                VaForms.site_id == mapping.site_id,
            )
        )
        local_count = 0
        if form:
            local_count = db.session.scalar(
                sa.select(sa.func.count()).where(
                    VaSubmissions.va_form_id == form.form_id
                )
            ) or 0

        try:
            odk_count = va_odk_submissioncount(
                mapping.odk_project_id, mapping.odk_form_id
            )
            odk_error = None
        except Exception as e:
            odk_count = None
            odk_error = str(e)

        rows.append({
            "project_id": mapping.project_id,
            "site_id": mapping.site_id,
            "odk_project_id": mapping.odk_project_id,
            "odk_form_id": mapping.odk_form_id,
            "form_id": form.form_id if form else None,
            "odk_total": odk_count,
            "local_total": local_count,
            "missing": (odk_count - local_count) if odk_count is not None else None,
            "error": odk_error,
        })

        if odk_count is not None:
            odk_total += odk_count
        local_total += local_count

    return jsonify({
        "mappings": rows,
        "totals": {"odk_total": odk_total, "local_total": local_total},
    })


def _sync_run_dict(run) -> dict:
    """Serialise a VaSyncRun to a JSON-safe dict."""
    if run is None:
        return None
    duration = None
    if run.finished_at and run.started_at:
        duration = int((run.finished_at - run.started_at).total_seconds())
    return {
        "sync_run_id": str(run.sync_run_id),
        "triggered_by": run.triggered_by,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "duration_seconds": duration,
        "status": run.status,
        "records_added": run.records_added,
        "records_updated": run.records_updated,
        "error_message": run.error_message,
    }


def _get_sync_schedule_hours() -> int | None:
    """Return the configured sync interval in hours, or None if not set."""
    try:
        with db.engine.connect() as conn:
            row = conn.execute(sa.text("""
                SELECT i.every
                FROM public.celery_periodictask t
                JOIN public.celery_intervalschedule i ON i.id = t.schedule_id
                WHERE t.name = 'ODK Sync — every 6 hours'
                  AND t.discriminator = 'intervalschedule'
                LIMIT 1
            """)).fetchone()
            return row[0] if row else None
    except Exception:
        return None
