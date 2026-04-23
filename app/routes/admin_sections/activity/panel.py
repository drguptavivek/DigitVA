import sqlalchemy as sa
from flask import render_template, request

from app import db
from app.decorators import role_required
from app.models import VaForms
from app.routes.admin import admin
from app.admin_support.activity import (
    AUDIT_ACTION_DISPLAY as _AUDIT_ACTION_DISPLAY,
    AUDIT_ACTION_EXPLANATIONS as _AUDIT_ACTION_EXPLANATIONS,
    build_activity_rows as _build_activity_rows,
)


@admin.get("/panels/activity")
@role_required("admin")
def admin_panel_activity():
    sid = (request.args.get("sid") or "").strip()
    project_id = (request.args.get("project_id") or "").strip().upper()
    site_id = (request.args.get("site_id") or "").strip().upper()
    user_id = (request.args.get("user_id") or "").strip()
    action = (request.args.get("action") or "").strip()
    try:
        limit = min(max(int(request.args.get("limit", 100)), 1), 300)
    except (TypeError, ValueError):
        limit = 100
    try:
        page = max(int(request.args.get("page", 1)), 1)
    except (TypeError, ValueError):
        page = 1

    activity_rows, total_count = _build_activity_rows(
        limit=limit,
        page=page,
        sid=sid or None,
        project_id=project_id or None,
        site_id=site_id or None,
        user_id=user_id or None,
        action=action or None,
    )
    project_options = db.session.scalars(
        sa.select(VaForms.project_id).distinct().order_by(VaForms.project_id)
    ).all()
    site_options = db.session.scalars(
        sa.select(VaForms.site_id).distinct().order_by(VaForms.site_id)
    ).all()
    from app.models import VaSubmissionsAuditlog

    raw_action_options = db.session.scalars(
        sa.select(VaSubmissionsAuditlog.va_audit_action)
        .distinct()
        .order_by(VaSubmissionsAuditlog.va_audit_action)
    ).all()
    action_options = [
        (opt, _AUDIT_ACTION_DISPLAY.get(opt, opt))
        for opt in raw_action_options
    ]

    return render_template(
        "admin/panels/activity_log.html",
        activity_rows=activity_rows,
        sid=sid,
        project_id=project_id,
        site_id=site_id,
        user_id=user_id,
        action=action,
        limit=limit,
        page=page,
        total_count=total_count,
        total_pages=max((total_count + limit - 1) // limit, 1),
        project_options=project_options,
        site_options=site_options,
        action_options=action_options,
        action_explanations=_AUDIT_ACTION_EXPLANATIONS,
    )
