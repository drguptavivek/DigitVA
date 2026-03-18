"""Data management service — shared helpers used by both the page routes
and the API routes.

Imported by:
  app/routes/data_management.py       (dashboard page)
  app/routes/api/data_management.py   (JSON API)
"""

import json
import re
import uuid
from datetime import datetime, timedelta
import pytz
import sqlalchemy as sa
from flask_login import current_user

from app import db
from app.models import (
    VaForms,
    VaSiteMaster,
    VaSyncRun,
    VaSubmissions,
    VaSubmissionsAuditlog,
)
from app.models.map_project_site_odk import MapProjectSiteOdk
from app.services.odk_connection_guard_service import guarded_odk_call
from app.services.odk_review_service import resolve_odk_instance_id
from app.utils import va_odk_clientsetup


# ---------------------------------------------------------------------------
# Scope helpers
# ---------------------------------------------------------------------------

def dm_scope_filter(user):
    """SQLAlchemy WHERE clause scoped to the user's data-manager grants."""
    project_ids = sorted(user.get_data_manager_projects())
    project_site_pairs = user.get_data_manager_project_sites()

    project_clause = sa.false()
    if project_ids:
        project_clause = VaForms.project_id.in_(project_ids)

    site_clause = sa.false()
    if project_site_pairs:
        site_clause = sa.tuple_(VaForms.project_id, VaForms.site_id).in_(
            list(project_site_pairs)
        )

    return sa.or_(project_clause, site_clause)


def dm_form_in_scope(user, form_id: str) -> bool:
    row = db.session.execute(
        sa.select(VaForms.project_id, VaForms.site_id).where(VaForms.form_id == form_id)
    ).first()
    if not row:
        return False
    return user.has_data_manager_submission_access(row.project_id, row.site_id)


def dm_scoped_forms(user) -> list[dict]:
    scope_filter = dm_scope_filter(user)
    return [
        {
            "form_id": row.form_id,
            "project_id": row.project_id,
            "site_id": row.site_id,
            "site_name": row.site_name or row.site_id,
            "odk_project_id": row.odk_project_id,
            "odk_form_id": row.odk_form_id,
            "last_synced_at": row.last_synced_at.isoformat() if row.last_synced_at else None,
        }
        for row in db.session.execute(
            sa.select(
                VaForms.form_id,
                VaForms.project_id,
                VaForms.site_id,
                VaSiteMaster.site_name,
                MapProjectSiteOdk.odk_project_id,
                MapProjectSiteOdk.odk_form_id,
                MapProjectSiteOdk.last_synced_at,
            )
            .select_from(VaForms)
            .outerjoin(VaSiteMaster, VaSiteMaster.site_id == VaForms.site_id)
            .outerjoin(
                MapProjectSiteOdk,
                sa.and_(
                    MapProjectSiteOdk.project_id == VaForms.project_id,
                    MapProjectSiteOdk.site_id == VaForms.site_id,
                ),
            )
            .where(scope_filter)
            .order_by(VaForms.project_id, VaForms.site_id, VaForms.form_id)
        ).mappings().all()
    ]


def filter_scoped_forms(
    scoped_forms: list[dict],
    project_ids: list[str] | None,
    site_ids: list[str] | None,
) -> list[dict]:
    selected_projects = set(project_ids or [])
    selected_sites = set(site_ids or [])
    return [
        form
        for form in scoped_forms
        if (not selected_projects or form["project_id"] in selected_projects)
        and (not selected_sites or form["site_id"] in selected_sites)
    ]


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

def dm_project_site_submission_stats(user) -> list[dict]:
    scope_filter = dm_scope_filter(user)
    tz_name = getattr(user, "timezone", "Asia/Kolkata") or "Asia/Kolkata"
    user_tz = pytz.timezone(tz_name)
    now_local = datetime.now(user_tz)
    today_start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start_local = today_start_local - timedelta(days=today_start_local.weekday())
    today_start_utc = today_start_local.astimezone(pytz.UTC)
    week_start_utc = week_start_local.astimezone(pytz.UTC)

    return [
        {
            "project_id": row["project_id"],
            "site_id": row["site_id"],
            "total_submissions": row["total_submissions"] or 0,
            "this_week_submissions": row["this_week_submissions"] or 0,
            "today_submissions": row["today_submissions"] or 0,
        }
        for row in db.session.execute(
            sa.select(
                VaForms.project_id,
                VaForms.site_id,
                sa.func.count(VaSubmissions.va_sid).label("total_submissions"),
                sa.func.sum(
                    sa.case(
                        (VaSubmissions.va_submission_date >= week_start_utc, 1),
                        else_=0,
                    )
                ).label("this_week_submissions"),
                sa.func.sum(
                    sa.case(
                        (VaSubmissions.va_submission_date >= today_start_utc, 1),
                        else_=0,
                    )
                ).label("today_submissions"),
            )
            .select_from(VaSubmissions)
            .join(VaForms, VaForms.form_id == VaSubmissions.va_form_id)
            .where(scope_filter)
            .group_by(VaForms.project_id, VaForms.site_id)
            .order_by(VaForms.project_id, VaForms.site_id)
        ).mappings().all()
    ]


# ---------------------------------------------------------------------------
# ODK edit URL
# ---------------------------------------------------------------------------

def dm_odk_edit_url(user, va_sid: str) -> str | None:
    row = db.session.execute(
        sa.select(
            VaSubmissions.va_sid,
            VaForms.project_id,
            VaForms.site_id,
            MapProjectSiteOdk.odk_project_id,
            MapProjectSiteOdk.odk_form_id,
        )
        .select_from(VaSubmissions)
        .join(VaForms, VaForms.form_id == VaSubmissions.va_form_id)
        .outerjoin(
            MapProjectSiteOdk,
            sa.and_(
                MapProjectSiteOdk.project_id == VaForms.project_id,
                MapProjectSiteOdk.site_id == VaForms.site_id,
            ),
        )
        .where(VaSubmissions.va_sid == va_sid)
    ).first()
    if not row:
        return None
    if not user.has_data_manager_submission_access(row.project_id, row.site_id):
        return None
    if not row.odk_project_id or not row.odk_form_id:
        return None
    client = va_odk_clientsetup(project_id=row.project_id)
    instance_id = resolve_odk_instance_id(row.va_sid)
    response = guarded_odk_call(
        lambda: client.session.get(
            f"projects/{int(row.odk_project_id)}/forms/{row.odk_form_id}/submissions/{instance_id}/edit",
            allow_redirects=False,
        ),
        client=client,
    )
    if response is None:
        return None
    return response.headers.get("Location")


# ---------------------------------------------------------------------------
# Sync run helpers
# ---------------------------------------------------------------------------

def sync_run_target_label(run: VaSyncRun) -> str | None:
    if not run.progress_log:
        return None
    try:
        entries = json.loads(run.progress_log)
    except Exception:
        return None
    if not entries:
        return None
    match = re.match(r"^\[([^\]]+)\]", entries[0].get("msg", ""))
    return match.group(1) if match else None


def sync_run_entries(run: VaSyncRun) -> list[dict]:
    if not run.progress_log:
        return []
    try:
        entries = json.loads(run.progress_log)
        return entries if isinstance(entries, list) else []
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------

def audit_dm_submission_action(
    va_sid: str,
    action: str,
    *,
    operation: str = "r",
) -> None:
    db.session.add(
        VaSubmissionsAuditlog(
            va_sid=va_sid,
            va_audit_byrole="data_manager",
            va_audit_by=current_user.user_id,
            va_audit_operation=operation,
            va_audit_action=action,
            va_audit_entityid=uuid.uuid4(),
        )
    )
    db.session.commit()
