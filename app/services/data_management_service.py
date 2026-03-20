"""Data management service — shared helpers used by both the page routes
and the API routes.

Imported by:
  app/routes/data_management.py       (dashboard page)
  app/routes/api/data_management.py   (JSON API)
"""

import json
import re
import uuid
import sqlalchemy as sa
from flask_login import current_user

from app import db
from app.models import (
    VaAllocations,
    VaCoderReview,
    VaDataManagerReview,
    VaFinalAssessments,
    VaForms,
    VaInitialAssessments,
    VaSiteMaster,
    VaSmartvaResults,
    VaStatuses,
    VaSubmissionAttachments,
    VaSubmissionWorkflow,
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

def _csv_values(raw: str) -> list[str]:
    if not raw:
        return []
    return [value.strip() for value in raw.split(",") if value.strip()]


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

# ---------------------------------------------------------------------------
# Paginated submissions table
# ---------------------------------------------------------------------------

_WORKFLOW_LABEL = {
    "not_codeable_by_data_manager": "Flagged by Data Manager",
    "not_codeable_by_coder":        "Not Codeable By Coder",
    "ready_for_coding":             "Ready for Coding",
    "screening_pending":            "Screening Pending",
    "coding_in_progress":           "Coding In Progress",
    "coder_finalized":              "Coder Finalized",
    "revoked_va_data_changed":      "Revoked — Data Changed",
    "consent_refused":              "Consent Refused",
}

_SORT_FIELDS = {
    "va_submission_date": sa.func.date(VaSubmissions.va_submission_date),
    "va_uniqueid_masked": VaSubmissions.va_uniqueid_masked,
    "project_id":         VaForms.project_id,
    "site_id":            VaForms.site_id,
    "workflow_state":     VaSubmissionWorkflow.workflow_state,
    "va_dmreview_createdat": VaDataManagerReview.va_dmreview_createdat,
}


def dm_submissions_page(
    user,
    *,
    page: int = 1,
    per_page: int = 25,
    search: str = "",
    project: str = "",
    site: str = "",
    date_from: str | None = None,
    date_to: str | None = None,
    odk_status: str = "",
    smartva: str = "",
    age_group: str = "",
    gender: str = "",
    odk_sync: str = "",
    workflow: str = "",
    sort_field: str = "va_submission_date",
    sort_dir: str = "desc",
) -> dict:
    """Return one page of submission rows for the data manager table."""
    from app.utils import va_render_serialisedates

    attachment_counts = (
        sa.select(VaSubmissionAttachments.va_sid, sa.func.count().label("cnt"))
        .where(VaSubmissionAttachments.exists_on_odk.is_(True))
        .group_by(VaSubmissionAttachments.va_sid)
        .subquery()
    )
    smartva_sids = (
        sa.select(VaSmartvaResults.va_sid)
        .where(VaSmartvaResults.va_smartva_status == VaStatuses.active)
        .subquery()
    )
    _mv_ref = sa.table(
        "va_submission_analytics_mv",
        sa.column("va_sid"),
        sa.column("analytics_age_band"),
    )
    scope = dm_scope_filter(user)
    conditions = [scope]
    project_values = _csv_values(project)
    site_values = _csv_values(site)

    if search:
        like = f"%{search}%"
        conditions.append(sa.or_(
            VaSubmissions.va_uniqueid_masked.ilike(like),
            VaSubmissions.va_data_collector.ilike(like),
        ))
    if project_values:
        conditions.append(VaForms.project_id.in_(project_values))
    if site_values:
        conditions.append(VaForms.site_id.in_(site_values))
    if date_from:
        conditions.append(sa.func.date(VaSubmissions.va_submission_date) >= date_from)
    if date_to:
        conditions.append(sa.func.date(VaSubmissions.va_submission_date) <= date_to)
    if odk_status == "hasIssues":
        conditions.append(VaSubmissions.va_odk_reviewstate == "hasIssues")
    elif odk_status == "approved":
        conditions.append(VaSubmissions.va_odk_reviewstate == "approved")
    elif odk_status == "no_review_state":
        conditions.append(VaSubmissions.va_odk_reviewstate.is_(None))
    if smartva == "available":
        conditions.append(smartva_sids.c.va_sid.is_not(None))
    elif smartva == "missing":
        conditions.append(smartva_sids.c.va_sid.is_(None))
    if age_group:
        conditions.append(_mv_ref.c.analytics_age_band == age_group)
    if gender:
        conditions.append(VaSubmissions.va_deceased_gender == gender)
    if odk_sync == "missing_in_odk":
        conditions.append(VaSubmissions.va_sync_issue_code == "missing_in_odk")
    elif odk_sync == "in_sync":
        conditions.append(sa.or_(
            VaSubmissions.va_sync_issue_code.is_(None),
            VaSubmissions.va_sync_issue_code != "missing_in_odk",
        ))
    if workflow:
        if workflow == "pending_coding":
            # Special case: pending includes multiple workflow states
            conditions.append(VaSubmissionWorkflow.workflow_state.in_([
                "screening_pending",
                "ready_for_coding",
                "coding_in_progress",
                "partial_coding_saved",
                "coder_step1_saved",
            ]))
        else:
            conditions.append(VaSubmissionWorkflow.workflow_state == workflow)

    base_q = (
        sa.select(
            VaSubmissions.va_sid,
            VaSubmissions.va_uniqueid_masked,
            VaForms.project_id,
            VaForms.site_id,
            sa.func.date(VaSubmissions.va_submission_date).label("va_submission_date"),
            VaSubmissions.va_data_collector,
            sa.func.coalesce(attachment_counts.c.cnt, 0).label("attachment_count"),
            sa.case((smartva_sids.c.va_sid.is_not(None), True), else_=False).label("has_smartva"),
            VaSubmissions.va_odk_reviewstate,
            VaSubmissions.va_odk_reviewcomments,
            VaSubmissions.va_sync_issue_code,
            VaSubmissions.va_sync_issue_updated_at,
            VaSubmissionWorkflow.workflow_state,
            VaDataManagerReview.va_dmreview_createdat,
            _mv_ref.c.analytics_age_band,
            VaSubmissions.va_deceased_gender,
            VaSubmissions.va_consent,
        )
        .select_from(VaSubmissions)
        .join(VaForms, VaForms.form_id == VaSubmissions.va_form_id)
        .join(VaSubmissionWorkflow, VaSubmissionWorkflow.va_sid == VaSubmissions.va_sid)
        .outerjoin(attachment_counts, attachment_counts.c.va_sid == VaSubmissions.va_sid)
        .outerjoin(smartva_sids, smartva_sids.c.va_sid == VaSubmissions.va_sid)
        .outerjoin(VaDataManagerReview, sa.and_(
            VaDataManagerReview.va_sid == VaSubmissions.va_sid,
            VaDataManagerReview.va_dmreview_status == VaStatuses.active,
        ))
        .outerjoin(_mv_ref, _mv_ref.c.va_sid == VaSubmissions.va_sid)
        .where(sa.and_(*conditions))
    )

    total = db.session.scalar(
        sa.select(sa.func.count()).select_from(base_q.subquery())
    ) or 0

    sort_col = _SORT_FIELDS.get(sort_field, sa.func.date(VaSubmissions.va_submission_date))
    order = sort_col.desc() if sort_dir == "desc" else sort_col.asc()
    # secondary sorts for stable ordering
    rows = db.session.execute(
        base_q.order_by(order, VaForms.project_id, VaForms.site_id)
        .limit(per_page)
        .offset((page - 1) * per_page)
    ).mappings().all()

    data = []
    for row in rows:
        r = va_render_serialisedates(dict(row), ["va_submission_date", "va_dmreview_createdat"])
        r["workflow_label"] = _WORKFLOW_LABEL.get(r.get("workflow_state", ""), r.get("workflow_state", ""))
        r["odk_sync_status"] = "missing_in_odk" if r.get("va_sync_issue_code") == "missing_in_odk" else "in_sync"
        data.append(r)

    import math
    last_page = max(1, math.ceil(total / per_page))
    return {"data": data, "last_page": last_page, "total": total}


def dm_kpi(user, project_ids, project_site_pairs) -> dict:
    """Return KPI counts for the data manager dashboard."""
    from app.services.submission_analytics_mv import get_dm_kpi_from_mv
    return get_dm_kpi_from_mv(
        project_ids=project_ids,
        project_site_pairs=project_site_pairs,
    )


def dm_filter_options(user) -> dict:
    """Return distinct filter values available to the data manager."""
    scope = dm_scope_filter(user)
    projects = db.session.scalars(
        sa.select(VaForms.project_id)
        .where(scope)
        .distinct()
        .order_by(VaForms.project_id)
    ).all()
    sites = db.session.execute(
        sa.select(VaForms.project_id, VaForms.site_id)
        .where(scope)
        .distinct()
        .order_by(VaForms.project_id, VaForms.site_id)
    ).mappings().all()
    genders = db.session.scalars(
        sa.select(VaSubmissions.va_deceased_gender)
        .join(VaForms, VaForms.form_id == VaSubmissions.va_form_id)
        .where(scope, VaSubmissions.va_deceased_gender.is_not(None))
        .distinct()
        .order_by(VaSubmissions.va_deceased_gender)
    ).all()
    return {
        "projects": list(projects),
        "sites": [{"project_id": r["project_id"], "site_id": r["site_id"]} for r in sites],
        "genders": list(genders),
    }


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


# ---------------------------------------------------------------------------
# Revoked submission resolution
# ---------------------------------------------------------------------------

def _dm_submission_scope_check(user, va_sid: str):
    """Return (submission, form_row) or raise ValueError if out of scope."""
    submission = db.session.get(VaSubmissions, va_sid)
    if submission is None:
        raise ValueError("Submission not found.")
    form_row = db.session.execute(
        sa.select(VaForms.project_id, VaForms.site_id).where(
            VaForms.form_id == submission.va_form_id
        )
    ).first()
    if not form_row:
        raise ValueError("Form not found.")
    if not user.is_admin() and not user.has_data_manager_submission_access(
        form_row.project_id, form_row.site_id
    ):
        raise PermissionError("You do not have access to this submission.")
    return submission, form_row


def dm_accept_upstream_change(user, va_sid: str) -> None:
    """Accept an upstream ODK data change for a revoked submission.

    Destroys finalized coding artifacts and resets to ready_for_coding so
    the submission can be re-coded against the new ODK data.

    Raises ValueError / PermissionError on invalid input or access denial.
    Does NOT commit — caller is responsible.
    """
    from app.services.submission_workflow_service import (
        WORKFLOW_REVOKED_VA_DATA_CHANGED,
        WORKFLOW_READY_FOR_CODING,
        get_submission_workflow_state,
        set_submission_workflow_state,
    )

    _dm_submission_scope_check(user, va_sid)

    current_state = get_submission_workflow_state(va_sid)
    if current_state != WORKFLOW_REVOKED_VA_DATA_CHANGED:
        raise ValueError(
            f"Submission is in state '{current_state}', not revoked_va_data_changed."
        )

    # Deactivate all coding artifacts so the submission re-enters the coding queue
    for fa in db.session.scalars(
        sa.select(VaFinalAssessments).where(
            VaFinalAssessments.va_sid == va_sid,
            VaFinalAssessments.va_finassess_status == VaStatuses.active,
        )
    ).all():
        fa.va_finassess_status = VaStatuses.deactive

    for ia in db.session.scalars(
        sa.select(VaInitialAssessments).where(
            VaInitialAssessments.va_sid == va_sid,
            VaInitialAssessments.va_iniassess_status == VaStatuses.active,
        )
    ).all():
        ia.va_iniassess_status = VaStatuses.deactive

    for cr in db.session.scalars(
        sa.select(VaCoderReview).where(
            VaCoderReview.va_sid == va_sid,
            VaCoderReview.va_creview_status == VaStatuses.active,
        )
    ).all():
        cr.va_creview_status = VaStatuses.deactive

    for dmr in db.session.scalars(
        sa.select(VaDataManagerReview).where(
            VaDataManagerReview.va_sid == va_sid,
            VaDataManagerReview.va_dmreview_status == VaStatuses.active,
        )
    ).all():
        dmr.va_dmreview_status = VaStatuses.deactive

    for alloc in db.session.scalars(
        sa.select(VaAllocations).where(
            VaAllocations.va_sid == va_sid,
            VaAllocations.va_allocation_status == VaStatuses.active,
        )
    ).all():
        alloc.va_allocation_status = VaStatuses.deactive

    for sva in db.session.scalars(
        sa.select(VaSmartvaResults).where(
            VaSmartvaResults.va_sid == va_sid,
            VaSmartvaResults.va_smartva_status == VaStatuses.active,
        )
    ).all():
        sva.va_smartva_status = VaStatuses.deactive

    set_submission_workflow_state(
        va_sid,
        WORKFLOW_READY_FOR_CODING,
        reason="data_manager_accepted_upstream_change",
        by_user_id=user.user_id,
        by_role="data_manager",
    )
    db.session.add(
        VaSubmissionsAuditlog(
            va_sid=va_sid,
            va_audit_byrole="data_manager",
            va_audit_by=user.user_id,
            va_audit_operation="u",
            va_audit_action="data_manager_accepted_upstream_odk_change",
            va_audit_entityid=uuid.uuid4(),
        )
    )


def dm_reject_upstream_change(user, va_sid: str) -> None:
    """Reject an upstream ODK data change for a revoked submission.

    Restores the coder_finalized state, keeping existing COD artifacts
    intact. The new ODK data is retained in the submission record but
    the COD decision stands.

    Posts a comment to ODK Central (best-effort) indicating the DM rejected
    the change. The ODK reviewState stays as hasIssues.

    Raises ValueError / PermissionError on invalid input or access denial.
    Does NOT commit — caller is responsible.
    """
    from app.services.submission_workflow_service import (
        WORKFLOW_REVOKED_VA_DATA_CHANGED,
        WORKFLOW_CODER_FINALIZED,
        get_submission_workflow_state,
        set_submission_workflow_state,
    )
    from app.services.odk_review_service import post_dm_rejection_comment

    _dm_submission_scope_check(user, va_sid)

    current_state = get_submission_workflow_state(va_sid)
    if current_state != WORKFLOW_REVOKED_VA_DATA_CHANGED:
        raise ValueError(
            f"Submission is in state '{current_state}', not revoked_va_data_changed."
        )

    # Post comment to ODK Central (best-effort, non-blocking)
    post_dm_rejection_comment(va_sid)

    set_submission_workflow_state(
        va_sid,
        WORKFLOW_CODER_FINALIZED,
        reason="data_manager_rejected_upstream_change",
        by_user_id=user.user_id,
        by_role="data_manager",
    )
    db.session.add(
        VaSubmissionsAuditlog(
            va_sid=va_sid,
            va_audit_byrole="data_manager",
            va_audit_by=user.user_id,
            va_audit_operation="u",
            va_audit_action="data_manager_rejected_upstream_odk_change",
            va_audit_entityid=uuid.uuid4(),
        )
    )
