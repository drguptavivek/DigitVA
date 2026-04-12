"""Data management service — shared helpers used by both the page routes
and the API routes.

Imported by:
  app/routes/data_management.py       (dashboard page)
  app/routes/api/data_management.py   (JSON API)
"""

import csv
import io
import math
import json
import re
import uuid
from urllib.parse import quote
import sqlalchemy as sa
from flask_login import current_user

from app import db
from app.models import (
    MasOdkConnections,
    MapProjectOdk,
    VaAllocations,
    VaCoderReview,
    VaDataManagerReview,
    VaFinalAssessments,
    VaForms,
    VaInitialAssessments,
    VaReviewerFinalAssessments,
    VaReviewerReview,
    VaSiteMaster,
    VaSmartvaRunOutput,
    VaSmartvaResults,
    VaSubmissionPayloadVersion,
    VaStatuses,
    VaSubmissionAttachments,
    VaSubmissionWorkflow,
    VaSyncRun,
    VaSubmissions,
    VaSubmissionsAuditlog,
    VaUsers,
)
from app.models.map_project_site_odk import MapProjectSiteOdk
from app.services.final_cod_authority_service import upsert_final_cod_authority
from app.services.odk_review_service import resolve_odk_instance_id
from app.services.payload_bound_coding_artifact_service import (
    deactivate_active_reviewer_reviews_for_submission,
    deactivate_active_narrative_assessments_for_submission,
    deactivate_active_social_autopsy_analyses_for_submission,
    promote_active_reviewer_reviews_to_payload,
    promote_active_narrative_assessments_to_payload,
    promote_active_social_autopsy_analyses_to_payload,
)
from app.services.smartva_service import promote_active_smartva_to_payload
from app.services.submission_payload_projection_service import (
    apply_payload_to_submission_summary,
)
from app.services.submission_payload_version_service import (
    VOLATILE_PAYLOAD_KEYS,
    get_payload_version,
    normalize_payload_for_fingerprint,
    promote_pending_upstream_payload_version,
)
from app.services.workflow.transitions import admin_actor, data_manager_actor
from app.services.workflow.state_store import get_submission_workflow_record
from app.services.workflow.definition import (
    WORKFLOW_ATTACHMENT_SYNC_PENDING,
    WORKFLOW_CODER_FINALIZED,
    WORKFLOW_CODER_STEP1_SAVED,
    WORKFLOW_CODING_IN_PROGRESS,
    WORKFLOW_READY_FOR_CODING,
    WORKFLOW_REVIEWER_CODING_IN_PROGRESS,
    WORKFLOW_REVIEWER_ELIGIBLE,
    WORKFLOW_REVIEWER_FINALIZED,
    WORKFLOW_SCREENING_PENDING,
    WORKFLOW_SMARTVA_PENDING,
)
from app.services.workflow.upstream_changes import (
    UPSTREAM_CHANGE_STATUS_ACCEPTED,
    UPSTREAM_CHANGE_STATUS_KEPT_CURRENT_ICD,
    get_latest_pending_upstream_change,
    resolve_pending_upstream_change,
)


NON_SUBSTANTIVE_REVIEW_FIELDS = frozenset(
    {
        "AttachmentsExpected",
        "AttachmentsPresent",
        "DeviceID",
        "FormVersion",
        "SubmitterID",
        "updatedAt",
        "audit",
        "instanceID",
    }
)


def _coerce_numeric_review_value(value):
    """Return a finite float for numeric-looking values, else None."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        numeric = float(value)
        if math.isnan(numeric) or math.isinf(numeric):
            return None
        return numeric
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            numeric = float(text)
        except ValueError:
            return None
        if math.isnan(numeric) or math.isinf(numeric):
            return None
        return numeric
    return None


def _is_formatting_only_numeric_difference(previous_value, current_value) -> bool:
    """Treat tiny numeric representation differences as formatting-only."""
    previous_numeric = _coerce_numeric_review_value(previous_value)
    current_numeric = _coerce_numeric_review_value(current_value)
    if previous_numeric is None or current_numeric is None:
        return False
    return round(previous_numeric, 5) == round(current_numeric, 5)


def _is_display_equivalent_choice_difference(
    field_id: str,
    previous_value,
    current_value,
    choice_map: dict[str, dict[str, str]],
) -> bool:
    """Treat code-vs-label diffs as formatting-only when they render identically."""
    field_choices = choice_map.get(field_id, {})
    if not field_choices:
        return False
    return _format_upstream_change_value(
        field_id,
        previous_value,
        choice_map,
    ) == _format_upstream_change_value(
        field_id,
        current_value,
        choice_map,
    )

UPSTREAM_REVIEW_HIDDEN_FIELDS = frozenset(
    {
        "Edits",
        "OdkReviewComments",
    }
)

# ---------------------------------------------------------------------------
# Scope helpers
# ---------------------------------------------------------------------------

def dm_scope_filter(user):
    """SQLAlchemy WHERE clause scoped to the user's data-manager grants.

    Project-level grants are expanded to their currently active
    (project_id, site_id) pairs so that sites removed from a project are
    not included.
    """
    from app.services.submission_analytics_mv import _expand_project_ids_to_active_pairs

    project_ids = sorted(user.get_data_manager_projects())
    project_site_pairs = user.get_data_manager_project_sites()

    all_pairs: set[tuple[str, str]] = set(project_site_pairs)
    all_pairs |= _expand_project_ids_to_active_pairs(project_ids)

    if not all_pairs:
        return sa.false()

    return sa.tuple_(VaForms.project_id, VaForms.site_id).in_(list(all_pairs))


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


def _submission_analytics_mv_available() -> bool:
    """Return whether the analytics demographics materialized view currently exists."""
    return bool(
        db.session.execute(
            sa.text("SELECT to_regclass('va_submission_analytics_demographics_mv')")
        ).scalar_one()
    )


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
            MasOdkConnections.base_url,
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
        .outerjoin(
            MapProjectOdk,
            MapProjectOdk.project_id == VaForms.project_id,
        )
        .outerjoin(
            MasOdkConnections,
            MasOdkConnections.connection_id == MapProjectOdk.connection_id,
        )
        .where(VaSubmissions.va_sid == va_sid)
    ).first()
    if not row:
        return None
    if not user.has_data_manager_submission_access(row.project_id, row.site_id):
        return None
    if not row.odk_project_id or not row.odk_form_id:
        return None
    instance_id = quote(resolve_odk_instance_id(row.va_sid), safe="")
    if not row.base_url:
        return None
    base_url = str(row.base_url).rstrip("/")
    return (
        f"{base_url}/projects/{int(row.odk_project_id)}/forms/"
        f"{row.odk_form_id}/submissions/{instance_id}/edit"
    )


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
    "attachment_sync_pending":      "Attachment Sync Pending",
    "coding_in_progress":           "Coding In Progress",
    "coder_finalized":              "Coder Finalized",
    "finalized_upstream_changed":   "Finalized - ODK Data Changed",
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
    coder_final_user = sa.orm.aliased(VaUsers)
    reviewer_final_user = sa.orm.aliased(VaUsers)

    attachment_counts = (
        sa.select(VaSubmissionAttachments.va_sid, sa.func.count().label("cnt"))
        .where(VaSubmissionAttachments.exists_on_odk.is_(True))
        .group_by(VaSubmissionAttachments.va_sid)
        .subquery()
    )
    smartva_sids = (
        sa.select(VaSmartvaResults.va_sid)
        .where(VaSmartvaResults.va_smartva_status == VaStatuses.active)
        .distinct()
        .subquery()
    )
    smartva_failed_sids = (
        sa.select(VaSmartvaResults.va_sid)
        .where(
            VaSmartvaResults.va_smartva_status == VaStatuses.active,
            VaSmartvaResults.va_smartva_outcome == VaSmartvaResults.OUTCOME_FAILED,
        )
        .distinct()
        .subquery()
    )
    _mv_ref = None
    if _submission_analytics_mv_available():
        _mv_ref = sa.table(
            "va_submission_analytics_demographics_mv",
            sa.column("va_sid"),
            sa.column("analytics_age_band"),
        )
    active_final = (
        sa.select(
            VaFinalAssessments.va_sid.label("va_sid"),
            VaFinalAssessments.va_finassess_by,
            VaFinalAssessments.va_finassess_createdat,
        )
        .where(VaFinalAssessments.va_finassess_status == VaStatuses.active)
        .subquery()
    )
    active_reviewer_final = (
        sa.select(
            VaReviewerFinalAssessments.va_sid.label("va_sid"),
            VaReviewerFinalAssessments.va_rfinassess_by,
            VaReviewerFinalAssessments.va_rfinassess_createdat,
        )
        .where(VaReviewerFinalAssessments.va_rfinassess_status == VaStatuses.active)
        .subquery()
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
    elif smartva == "failed":
        conditions.append(smartva_failed_sids.c.va_sid.is_not(None))
    if age_group:
        if _mv_ref is None:
            conditions.append(sa.false())
        else:
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
            conditions.append(VaSubmissionWorkflow.workflow_state.in_([
                WORKFLOW_READY_FOR_CODING,
                WORKFLOW_CODING_IN_PROGRESS,
                WORKFLOW_CODER_STEP1_SAVED,
            ]))
        elif workflow == "coded":
            conditions.append(VaSubmissionWorkflow.workflow_state.in_([
                WORKFLOW_CODER_FINALIZED,
                WORKFLOW_REVIEWER_ELIGIBLE,
                WORKFLOW_REVIEWER_CODING_IN_PROGRESS,
                WORKFLOW_REVIEWER_FINALIZED,
            ]))
        else:
            conditions.append(VaSubmissionWorkflow.workflow_state == workflow)

    analytics_age_band_column = (
        _mv_ref.c.analytics_age_band
        if _mv_ref is not None
        else sa.literal(None).label("analytics_age_band")
    )
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
            analytics_age_band_column,
            VaSubmissions.va_deceased_gender,
            VaSubmissions.va_consent,
            sa.case(
                (
                    active_reviewer_final.c.va_rfinassess_createdat.is_not(None),
                    active_reviewer_final.c.va_rfinassess_createdat,
                ),
                else_=active_final.c.va_finassess_createdat,
            ).label("coded_on"),
            sa.case(
                (
                    active_reviewer_final.c.va_rfinassess_createdat.is_not(None),
                    reviewer_final_user.name,
                ),
                else_=coder_final_user.name,
            ).label("coded_by"),
        )
        .select_from(VaSubmissions)
        .join(VaForms, VaForms.form_id == VaSubmissions.va_form_id)
        .join(VaSubmissionWorkflow, VaSubmissionWorkflow.va_sid == VaSubmissions.va_sid)
        .outerjoin(attachment_counts, attachment_counts.c.va_sid == VaSubmissions.va_sid)
        .outerjoin(smartva_sids, smartva_sids.c.va_sid == VaSubmissions.va_sid)
        .outerjoin(smartva_failed_sids, smartva_failed_sids.c.va_sid == VaSubmissions.va_sid)
        .outerjoin(VaDataManagerReview, sa.and_(
            VaDataManagerReview.va_sid == VaSubmissions.va_sid,
            VaDataManagerReview.va_dmreview_status == VaStatuses.active,
        ))
        .outerjoin(active_final, active_final.c.va_sid == VaSubmissions.va_sid)
        .outerjoin(
            coder_final_user,
            coder_final_user.user_id == active_final.c.va_finassess_by,
        )
        .outerjoin(active_reviewer_final, active_reviewer_final.c.va_sid == VaSubmissions.va_sid)
        .outerjoin(
            reviewer_final_user,
            reviewer_final_user.user_id == active_reviewer_final.c.va_rfinassess_by,
        )
        .where(sa.and_(*conditions))
    )
    if _mv_ref is not None:
        base_q = base_q.outerjoin(_mv_ref, _mv_ref.c.va_sid == VaSubmissions.va_sid)
    count_q = (
        sa.select(sa.func.count())
        .select_from(VaSubmissions)
        .join(VaForms, VaForms.form_id == VaSubmissions.va_form_id)
        .join(VaSubmissionWorkflow, VaSubmissionWorkflow.va_sid == VaSubmissions.va_sid)
        .outerjoin(attachment_counts, attachment_counts.c.va_sid == VaSubmissions.va_sid)
        .outerjoin(smartva_sids, smartva_sids.c.va_sid == VaSubmissions.va_sid)
        .outerjoin(smartva_failed_sids, smartva_failed_sids.c.va_sid == VaSubmissions.va_sid)
        .outerjoin(VaDataManagerReview, sa.and_(
            VaDataManagerReview.va_sid == VaSubmissions.va_sid,
            VaDataManagerReview.va_dmreview_status == VaStatuses.active,
        ))
        .where(sa.and_(*conditions))
    )
    if _mv_ref is not None:
        count_q = count_q.outerjoin(_mv_ref, _mv_ref.c.va_sid == VaSubmissions.va_sid)

    sort_col = _SORT_FIELDS.get(sort_field, sa.func.date(VaSubmissions.va_submission_date))
    order = sort_col.desc() if sort_dir == "desc" else sort_col.asc()
    offset = (page - 1) * per_page
    total = db.session.execute(count_q).scalar_one()
    rows = db.session.execute(
        base_q.order_by(order, VaForms.project_id, VaForms.site_id, VaSubmissions.va_sid)
        .limit(per_page)
        .offset(offset)
    ).mappings().all()

    has_more = offset + len(rows) < total

    data = []
    for row in rows:
        r = va_render_serialisedates(
            dict(row),
            ["va_submission_date", "va_dmreview_createdat", "coded_on"],
        )
        r["workflow_label"] = _WORKFLOW_LABEL.get(r.get("workflow_state", ""), r.get("workflow_state", ""))
        r["odk_sync_status"] = "missing_in_odk" if r.get("va_sync_issue_code") == "missing_in_odk" else "in_sync"
        data.append(r)

    last_page = max(1, math.ceil(total / per_page)) if per_page else 1
    return {
        "data": data,
        "page": page,
        "size": per_page,
        "offset": offset,
        "returned_count": len(data),
        "has_more": has_more,
        "last_page": last_page,
        "total": total,
    }


def _dm_submission_query_parts(
    user,
    *,
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
):
    """Return shared query pieces for the DM grid and full export."""
    attachment_counts = (
        sa.select(VaSubmissionAttachments.va_sid, sa.func.count().label("cnt"))
        .where(VaSubmissionAttachments.exists_on_odk.is_(True))
        .group_by(VaSubmissionAttachments.va_sid)
        .subquery()
    )
    smartva_sids = (
        sa.select(VaSmartvaResults.va_sid)
        .where(VaSmartvaResults.va_smartva_status == VaStatuses.active)
        .distinct()
        .subquery()
    )
    smartva_failed_sids = (
        sa.select(VaSmartvaResults.va_sid)
        .where(
            VaSmartvaResults.va_smartva_status == VaStatuses.active,
            VaSmartvaResults.va_smartva_outcome == VaSmartvaResults.OUTCOME_FAILED,
        )
        .distinct()
        .subquery()
    )
    _mv_ref = None
    if _submission_analytics_mv_available():
        _mv_ref = sa.table(
            "va_submission_analytics_demographics_mv",
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
    elif smartva == "failed":
        conditions.append(smartva_failed_sids.c.va_sid.is_not(None))
    if age_group:
        if _mv_ref is None:
            conditions.append(sa.false())
        else:
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
            conditions.append(VaSubmissionWorkflow.workflow_state.in_([
                WORKFLOW_SCREENING_PENDING,
                WORKFLOW_ATTACHMENT_SYNC_PENDING,
                WORKFLOW_SMARTVA_PENDING,
                WORKFLOW_READY_FOR_CODING,
                WORKFLOW_CODING_IN_PROGRESS,
                WORKFLOW_CODER_STEP1_SAVED,
            ]))
        elif workflow == "coded":
            conditions.append(VaSubmissionWorkflow.workflow_state.in_([
                WORKFLOW_CODER_FINALIZED,
                WORKFLOW_REVIEWER_ELIGIBLE,
                WORKFLOW_REVIEWER_CODING_IN_PROGRESS,
                WORKFLOW_REVIEWER_FINALIZED,
            ]))
        else:
            conditions.append(VaSubmissionWorkflow.workflow_state == workflow)

    return attachment_counts, smartva_sids, smartva_failed_sids, _mv_ref, conditions


def _serialize_csv_cell(value):
    if value is None:
        return ""
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=True, sort_keys=True)
    return str(value)


CSV_EXPORT_OMIT_BASE_HEADERS = frozenset(
    {
        "va_uniqueid_real",
        "va_instance_name",
        "va_data_collector",
    }
)

CSV_EXPORT_OMIT_PAYLOAD_FIELDS = frozenset(
    {
        "unique_id",
        "unique_id2",
        "instanceName",
        "SubmitterName",
        "Id10476_audio",
        "imagenarr",
        "md_im1",
        "md_im2",
        "md_im3",
        "md_im4",
        "md_im5",
        "md_im6",
        "md_im7",
        "md_im8",
        "md_im9",
        "md_im10",
        "md_im11",
        "md_im12",
        "md_im13",
        "md_im14",
        "md_im15",
        "md_im16",
        "md_im17",
        "md_im18",
        "md_im19",
        "md_im20",
        "md_im21",
        "md_im22",
        "md_im23",
        "md_im24",
        "md_im25",
        "md_im26",
        "md_im27",
        "md_im28",
        "md_im29",
        "md_im30",
        "ds_im1",
        "ds_im2",
        "ds_im3",
        "ds_im4",
        "ds_im5",
    }
)


def _pii_payload_fields_by_form(rows) -> dict[str, set[str]]:
    from app.services.field_mapping_service import get_mapping_service
    from app.utils import va_get_form_type_code_for_form

    pii_fields_by_form: dict[str, set[str]] = {}
    for row in rows:
        form_id = row.get("va_form_id")
        if not form_id or form_id in pii_fields_by_form:
            continue
        form_type_code = va_get_form_type_code_for_form(form_id)
        pii_fields_by_form[form_id] = (
            get_mapping_service().get_pii_field_ids(form_type_code)
            if form_type_code
            else set()
        )
    return pii_fields_by_form


def _filter_export_payload(payload: dict, *, form_id: str, pii_fields_by_form: dict[str, set[str]]) -> dict:
    blocked_fields = CSV_EXPORT_OMIT_PAYLOAD_FIELDS | pii_fields_by_form.get(form_id, set())
    return {
        key: value for key, value in (payload or {}).items() if key not in blocked_fields
    }


def dm_submissions_export_csv(
    user,
    *,
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
) -> str:
    """Return a CSV export for all filtered DM submissions."""
    attachment_counts, smartva_sids, smartva_failed_sids, _mv_ref, conditions = _dm_submission_query_parts(
        user,
        search=search,
        project=project,
        site=site,
        date_from=date_from,
        date_to=date_to,
        odk_status=odk_status,
        smartva=smartva,
        age_group=age_group,
        gender=gender,
        odk_sync=odk_sync,
        workflow=workflow,
    )

    active_ini = (
        sa.select(
            VaInitialAssessments.va_sid.label("va_sid"),
            VaInitialAssessments.va_iniassess_by,
            VaInitialAssessments.va_immediate_cod,
            VaInitialAssessments.va_antecedent_cod,
            VaInitialAssessments.va_other_conditions,
            VaInitialAssessments.va_iniassess_createdat,
            VaInitialAssessments.va_iniassess_updatedat,
        )
        .where(VaInitialAssessments.va_iniassess_status == VaStatuses.active)
        .subquery()
    )
    active_coder_review = (
        sa.select(
            VaCoderReview.va_sid.label("va_sid"),
            VaCoderReview.va_creview_by,
            VaCoderReview.va_creview_reason,
            VaCoderReview.va_creview_other,
            VaCoderReview.va_creview_createdat,
            VaCoderReview.va_creview_updatedat,
        )
        .where(VaCoderReview.va_creview_status == VaStatuses.active)
        .subquery()
    )
    active_dm_review = (
        sa.select(
            VaDataManagerReview.va_sid.label("va_sid"),
            VaDataManagerReview.va_dmreview_by,
            VaDataManagerReview.va_dmreview_reason,
            VaDataManagerReview.va_dmreview_other,
            VaDataManagerReview.va_dmreview_createdat,
            VaDataManagerReview.va_dmreview_updatedat,
        )
        .where(VaDataManagerReview.va_dmreview_status == VaStatuses.active)
        .subquery()
    )
    active_reviewer_review = (
        sa.select(
            VaReviewerReview.va_sid.label("va_sid"),
            VaReviewerReview.va_rreview_by,
            VaReviewerReview.va_rreview_narrpos,
            VaReviewerReview.va_rreview_narrneg,
            VaReviewerReview.va_rreview_narrchrono,
            VaReviewerReview.va_rreview_narrdoc,
            VaReviewerReview.va_rreview_narrcomorb,
            VaReviewerReview.va_rreview,
            VaReviewerReview.va_rreview_fail,
            VaReviewerReview.va_rreview_remark,
            VaReviewerReview.va_rreview_createdat,
            VaReviewerReview.va_rreview_updatedat,
        )
        .where(VaReviewerReview.va_rreview_status == VaStatuses.active)
        .subquery()
    )
    active_final = (
        sa.select(
            VaFinalAssessments.va_sid.label("va_sid"),
            VaFinalAssessments.va_finassess_by,
            VaFinalAssessments.va_conclusive_cod,
            VaFinalAssessments.va_finassess_remark,
            VaFinalAssessments.va_finassess_createdat,
            VaFinalAssessments.va_finassess_updatedat,
        )
        .where(VaFinalAssessments.va_finassess_status == VaStatuses.active)
        .subquery()
    )
    active_reviewer_final = (
        sa.select(
            VaReviewerFinalAssessments.va_sid.label("va_sid"),
            VaReviewerFinalAssessments.va_rfinassess_by,
            VaReviewerFinalAssessments.va_conclusive_cod.label("reviewer_conclusive_cod"),
            VaReviewerFinalAssessments.va_rfinassess_remark,
            VaReviewerFinalAssessments.va_rfinassess_createdat,
            VaReviewerFinalAssessments.va_rfinassess_updatedat,
        )
        .where(VaReviewerFinalAssessments.va_rfinassess_status == VaStatuses.active)
        .subquery()
    )

    sort_col = _SORT_FIELDS.get(sort_field, sa.func.date(VaSubmissions.va_submission_date))
    order = sort_col.desc() if sort_dir == "desc" else sort_col.asc()
    analytics_age_band_column = (
        _mv_ref.c.analytics_age_band
        if _mv_ref is not None
        else sa.literal(None).label("analytics_age_band")
    )

    query = (
        sa.select(
            VaSubmissions.va_sid,
            VaSubmissions.va_form_id,
            VaSubmissions.va_uniqueid_masked,
            VaSubmissions.va_uniqueid_real,
            VaForms.project_id,
            VaForms.site_id,
            VaSubmissions.va_submission_date,
            VaSubmissions.va_odk_updatedat,
            VaSubmissions.va_data_collector,
            VaSubmissions.va_instance_name,
            VaSubmissions.va_odk_reviewstate,
            VaSubmissions.va_odk_reviewcomments,
            VaSubmissions.va_sync_issue_code,
            VaSubmissions.va_sync_issue_detail,
            VaSubmissions.va_sync_issue_updated_at,
            VaSubmissions.va_consent,
            VaSubmissions.va_narration_language,
            VaSubmissions.va_deceased_age,
            VaSubmissions.va_deceased_gender,
            VaSubmissions.va_deceased_age_normalized_days,
            VaSubmissions.va_deceased_age_normalized_years,
            VaSubmissions.va_deceased_age_source,
            VaSubmissionPayloadVersion.payload_data,
            sa.func.coalesce(attachment_counts.c.cnt, 0).label("attachment_count"),
            sa.case((smartva_sids.c.va_sid.is_not(None), True), else_=False).label("has_smartva"),
            analytics_age_band_column,
            VaSubmissionWorkflow.workflow_state,
            VaSubmissionWorkflow.workflow_reason,
            VaSubmissionWorkflow.workflow_updated_by_role,
            VaSubmissionWorkflow.workflow_updated_at,
            active_dm_review.c.va_dmreview_by,
            active_dm_review.c.va_dmreview_reason,
            active_dm_review.c.va_dmreview_other,
            active_dm_review.c.va_dmreview_createdat,
            active_dm_review.c.va_dmreview_updatedat,
            active_ini.c.va_iniassess_by,
            active_ini.c.va_immediate_cod,
            active_ini.c.va_antecedent_cod,
            active_ini.c.va_other_conditions,
            active_ini.c.va_iniassess_createdat,
            active_ini.c.va_iniassess_updatedat,
            active_coder_review.c.va_creview_by,
            active_coder_review.c.va_creview_reason,
            active_coder_review.c.va_creview_other,
            active_coder_review.c.va_creview_createdat,
            active_coder_review.c.va_creview_updatedat,
            active_reviewer_review.c.va_rreview_by,
            active_reviewer_review.c.va_rreview_narrpos,
            active_reviewer_review.c.va_rreview_narrneg,
            active_reviewer_review.c.va_rreview_narrchrono,
            active_reviewer_review.c.va_rreview_narrdoc,
            active_reviewer_review.c.va_rreview_narrcomorb,
            active_reviewer_review.c.va_rreview,
            active_reviewer_review.c.va_rreview_fail,
            active_reviewer_review.c.va_rreview_remark,
            active_reviewer_review.c.va_rreview_createdat,
            active_reviewer_review.c.va_rreview_updatedat,
            active_final.c.va_finassess_by,
            active_final.c.va_conclusive_cod,
            active_final.c.va_finassess_remark,
            active_final.c.va_finassess_createdat,
            active_final.c.va_finassess_updatedat,
            active_reviewer_final.c.va_rfinassess_by,
            active_reviewer_final.c.reviewer_conclusive_cod,
            active_reviewer_final.c.va_rfinassess_remark,
            active_reviewer_final.c.va_rfinassess_createdat,
            active_reviewer_final.c.va_rfinassess_updatedat,
        )
        .select_from(VaSubmissions)
        .join(VaForms, VaForms.form_id == VaSubmissions.va_form_id)
        .join(VaSubmissionWorkflow, VaSubmissionWorkflow.va_sid == VaSubmissions.va_sid)
        .outerjoin(
            VaSubmissionPayloadVersion,
            VaSubmissionPayloadVersion.payload_version_id == VaSubmissions.active_payload_version_id,
        )
        .outerjoin(attachment_counts, attachment_counts.c.va_sid == VaSubmissions.va_sid)
        .outerjoin(smartva_sids, smartva_sids.c.va_sid == VaSubmissions.va_sid)
        .outerjoin(smartva_failed_sids, smartva_failed_sids.c.va_sid == VaSubmissions.va_sid)
        .outerjoin(active_dm_review, active_dm_review.c.va_sid == VaSubmissions.va_sid)
        .outerjoin(active_ini, active_ini.c.va_sid == VaSubmissions.va_sid)
        .outerjoin(active_coder_review, active_coder_review.c.va_sid == VaSubmissions.va_sid)
        .outerjoin(active_reviewer_review, active_reviewer_review.c.va_sid == VaSubmissions.va_sid)
        .outerjoin(active_final, active_final.c.va_sid == VaSubmissions.va_sid)
        .outerjoin(active_reviewer_final, active_reviewer_final.c.va_sid == VaSubmissions.va_sid)
        .where(sa.and_(*conditions))
        .order_by(order, VaForms.project_id, VaForms.site_id, VaSubmissions.va_sid)
    )
    if _mv_ref is not None:
        query = query.outerjoin(_mv_ref, _mv_ref.c.va_sid == VaSubmissions.va_sid)
    rows = db.session.execute(query).mappings().all()
    pii_payload_fields_by_form = _pii_payload_fields_by_form(rows)

    base_headers = [
        "va_sid",
        "project_id",
        "site_id",
        "va_form_id",
        "va_uniqueid_masked",
        "va_uniqueid_real",
        "va_submission_date",
        "va_odk_updatedat",
        "va_data_collector",
        "va_instance_name",
        "va_odk_reviewstate",
        "va_odk_reviewcomments",
        "va_sync_issue_code",
        "va_sync_issue_detail",
        "va_sync_issue_updated_at",
        "va_consent",
        "va_narration_language",
        "va_deceased_age",
        "va_deceased_gender",
        "va_deceased_age_normalized_days",
        "va_deceased_age_normalized_years",
        "va_deceased_age_source",
        "attachment_count",
        "has_smartva",
        "analytics_age_band",
        "workflow_state",
        "workflow_reason",
        "workflow_updated_by_role",
        "workflow_updated_at",
        "dm_review_by",
        "dm_review_reason",
        "dm_review_other",
        "dm_review_created_at",
        "dm_review_updated_at",
        "initial_assess_by",
        "initial_immediate_cod",
        "initial_antecedent_cod",
        "initial_other_conditions",
        "initial_assess_created_at",
        "initial_assess_updated_at",
        "coder_review_by",
        "coder_review_reason",
        "coder_review_other",
        "coder_review_created_at",
        "coder_review_updated_at",
        "reviewer_review_by",
        "reviewer_review_narrpos",
        "reviewer_review_narrneg",
        "reviewer_review_narrchrono",
        "reviewer_review_narrdoc",
        "reviewer_review_narrcomorb",
        "reviewer_review_result",
        "reviewer_review_fail",
        "reviewer_review_remark",
        "reviewer_review_created_at",
        "reviewer_review_updated_at",
        "final_assess_by",
        "final_conclusive_cod",
        "final_assess_remark",
        "final_assess_created_at",
        "final_assess_updated_at",
        "reviewer_final_assess_by",
        "reviewer_final_conclusive_cod",
        "reviewer_final_assess_remark",
        "reviewer_final_assess_created_at",
        "reviewer_final_assess_updated_at",
    ]
    base_headers = [
        header for header in base_headers if header not in CSV_EXPORT_OMIT_BASE_HEADERS
    ]

    payload_headers = sorted({
        key
        for row in rows
        for key in _filter_export_payload(
            row.get("payload_data") or {},
            form_id=row.get("va_form_id"),
            pii_fields_by_form=pii_payload_fields_by_form,
        ).keys()
    })
    headers = base_headers + payload_headers

    handle = io.StringIO()
    writer = csv.DictWriter(handle, fieldnames=headers, extrasaction="ignore")
    writer.writeheader()

    for row in rows:
        payload = _filter_export_payload(
            row.get("payload_data") or {},
            form_id=row.get("va_form_id"),
            pii_fields_by_form=pii_payload_fields_by_form,
        )
        export_row = {
            "va_sid": row.get("va_sid"),
            "project_id": row.get("project_id"),
            "site_id": row.get("site_id"),
            "va_form_id": row.get("va_form_id"),
            "va_uniqueid_masked": row.get("va_uniqueid_masked"),
            "va_submission_date": row.get("va_submission_date"),
            "va_odk_updatedat": row.get("va_odk_updatedat"),
            "va_odk_reviewstate": row.get("va_odk_reviewstate"),
            "va_odk_reviewcomments": _serialize_csv_cell(row.get("va_odk_reviewcomments")),
            "va_sync_issue_code": row.get("va_sync_issue_code"),
            "va_sync_issue_detail": row.get("va_sync_issue_detail"),
            "va_sync_issue_updated_at": row.get("va_sync_issue_updated_at"),
            "va_consent": row.get("va_consent"),
            "va_narration_language": row.get("va_narration_language"),
            "va_deceased_age": row.get("va_deceased_age"),
            "va_deceased_gender": row.get("va_deceased_gender"),
            "va_deceased_age_normalized_days": row.get("va_deceased_age_normalized_days"),
            "va_deceased_age_normalized_years": row.get("va_deceased_age_normalized_years"),
            "va_deceased_age_source": row.get("va_deceased_age_source"),
            "attachment_count": row.get("attachment_count"),
            "has_smartva": row.get("has_smartva"),
            "analytics_age_band": row.get("analytics_age_band"),
            "workflow_state": row.get("workflow_state"),
            "workflow_reason": row.get("workflow_reason"),
            "workflow_updated_by_role": row.get("workflow_updated_by_role"),
            "workflow_updated_at": row.get("workflow_updated_at"),
            "dm_review_by": row.get("va_dmreview_by"),
            "dm_review_reason": row.get("va_dmreview_reason"),
            "dm_review_other": row.get("va_dmreview_other"),
            "dm_review_created_at": row.get("va_dmreview_createdat"),
            "dm_review_updated_at": row.get("va_dmreview_updatedat"),
            "initial_assess_by": row.get("va_iniassess_by"),
            "initial_immediate_cod": row.get("va_immediate_cod"),
            "initial_antecedent_cod": row.get("va_antecedent_cod"),
            "initial_other_conditions": row.get("va_other_conditions"),
            "initial_assess_created_at": row.get("va_iniassess_createdat"),
            "initial_assess_updated_at": row.get("va_iniassess_updatedat"),
            "coder_review_by": row.get("va_creview_by"),
            "coder_review_reason": row.get("va_creview_reason"),
            "coder_review_other": row.get("va_creview_other"),
            "coder_review_created_at": row.get("va_creview_createdat"),
            "coder_review_updated_at": row.get("va_creview_updatedat"),
            "reviewer_review_by": row.get("va_rreview_by"),
            "reviewer_review_narrpos": row.get("va_rreview_narrpos"),
            "reviewer_review_narrneg": row.get("va_rreview_narrneg"),
            "reviewer_review_narrchrono": row.get("va_rreview_narrchrono"),
            "reviewer_review_narrdoc": row.get("va_rreview_narrdoc"),
            "reviewer_review_narrcomorb": row.get("va_rreview_narrcomorb"),
            "reviewer_review_result": row.get("va_rreview"),
            "reviewer_review_fail": row.get("va_rreview_fail"),
            "reviewer_review_remark": row.get("va_rreview_remark"),
            "reviewer_review_created_at": row.get("va_rreview_createdat"),
            "reviewer_review_updated_at": row.get("va_rreview_updatedat"),
            "final_assess_by": row.get("va_finassess_by"),
            "final_conclusive_cod": row.get("va_conclusive_cod"),
            "final_assess_remark": row.get("va_finassess_remark"),
            "final_assess_created_at": row.get("va_finassess_createdat"),
            "final_assess_updated_at": row.get("va_finassess_updatedat"),
            "reviewer_final_assess_by": row.get("va_rfinassess_by"),
            "reviewer_final_conclusive_cod": row.get("reviewer_conclusive_cod"),
            "reviewer_final_assess_remark": row.get("va_rfinassess_remark"),
            "reviewer_final_assess_created_at": row.get("va_rfinassess_createdat"),
            "reviewer_final_assess_updated_at": row.get("va_rfinassess_updatedat"),
        }
        for key in payload_headers:
            export_row[key] = _serialize_csv_cell(payload.get(key))
        writer.writerow(export_row)

    return handle.getvalue()


def dm_smartva_input_export_csv(
    user,
    *,
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
) -> str:
    """Return the SmartVA input CSV shape for all filtered submissions."""
    from app.utils.va_smartva.va_smartva_02_prepdata import _clean_payload_for_smartva

    attachment_counts, smartva_sids, smartva_failed_sids, _mv_ref, conditions = _dm_submission_query_parts(
        user,
        search=search,
        project=project,
        site=site,
        date_from=date_from,
        date_to=date_to,
        odk_status=odk_status,
        smartva=smartva,
        age_group=age_group,
        gender=gender,
        odk_sync=odk_sync,
        workflow=workflow,
    )
    sort_col = _SORT_FIELDS.get(sort_field, sa.func.date(VaSubmissions.va_submission_date))
    order = sort_col.desc() if sort_dir == "desc" else sort_col.asc()
    query = (
        sa.select(
            VaSubmissions.va_sid,
            VaSubmissions.va_form_id,
            VaForms.project_id,
            VaForms.site_id,
            VaSubmissions.va_uniqueid_masked,
            VaSubmissionWorkflow.workflow_state,
            VaSubmissionPayloadVersion.payload_data,
        )
        .select_from(VaSubmissions)
        .join(VaForms, VaForms.form_id == VaSubmissions.va_form_id)
        .join(VaSubmissionWorkflow, VaSubmissionWorkflow.va_sid == VaSubmissions.va_sid)
        .join(
            VaSubmissionPayloadVersion,
            VaSubmissionPayloadVersion.payload_version_id == VaSubmissions.active_payload_version_id,
        )
        .outerjoin(smartva_sids, smartva_sids.c.va_sid == VaSubmissions.va_sid)
        .outerjoin(smartva_failed_sids, smartva_failed_sids.c.va_sid == VaSubmissions.va_sid)
        .where(sa.and_(*conditions))
        .order_by(order, VaForms.project_id, VaForms.site_id, VaSubmissions.va_sid)
    )
    if _mv_ref is not None:
        query = query.outerjoin(_mv_ref, _mv_ref.c.va_sid == VaSubmissions.va_sid)
    rows = db.session.execute(query).mappings().all()
    pii_payload_fields_by_form = _pii_payload_fields_by_form(rows)

    prepared_rows = []
    for row in rows:
        filtered_payload = _filter_export_payload(
            row.get("payload_data") or {},
            form_id=row.get("va_form_id"),
            pii_fields_by_form=pii_payload_fields_by_form,
        )
        prepared = _clean_payload_for_smartva(filtered_payload, va_sid=row["va_sid"])
        prepared.update(
            {
                "project_id": row.get("project_id"),
                "site_id": row.get("site_id"),
                "va_form_id": row.get("va_form_id"),
                "va_uniqueid_masked": row.get("va_uniqueid_masked"),
                "workflow_state": row.get("workflow_state"),
            }
        )
        prepared_rows.append(prepared)

    preferred_front = [
        "project_id",
        "site_id",
        "va_form_id",
        "va_uniqueid_masked",
        "workflow_state",
    ]
    payload_headers = []
    for row in prepared_rows:
        for key in row.keys():
            if key not in preferred_front and key not in payload_headers and key != "sid":
                payload_headers.append(key)
    headers = preferred_front + payload_headers + ["sid"]

    handle = io.StringIO()
    writer = csv.DictWriter(handle, fieldnames=headers, extrasaction="ignore")
    writer.writeheader()
    for row in prepared_rows:
        writer.writerow({key: _serialize_csv_cell(value) for key, value in row.items()})
    return handle.getvalue()


def dm_smartva_results_export_csv(
    user,
    *,
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
) -> str:
    """Return active SmartVA summary results for all filtered submissions."""
    attachment_counts, smartva_sids, smartva_failed_sids, _mv_ref, conditions = _dm_submission_query_parts(
        user,
        search=search,
        project=project,
        site=site,
        date_from=date_from,
        date_to=date_to,
        odk_status=odk_status,
        smartva=smartva,
        age_group=age_group,
        gender=gender,
        odk_sync=odk_sync,
        workflow=workflow,
    )
    sort_col = _SORT_FIELDS.get(sort_field, sa.func.date(VaSubmissions.va_submission_date))
    order = sort_col.desc() if sort_dir == "desc" else sort_col.asc()
    query = (
        sa.select(
            VaSubmissions.va_sid,
            VaForms.project_id,
            VaForms.site_id,
            VaSubmissions.va_form_id,
            VaSubmissions.va_uniqueid_masked,
            VaSubmissionWorkflow.workflow_state,
            VaSmartvaResults.va_smartva_resultfor,
            VaSmartvaResults.va_smartva_age,
            VaSmartvaResults.va_smartva_gender,
            VaSmartvaResults.va_smartva_cause1,
            VaSmartvaResults.va_smartva_likelihood1,
            VaSmartvaResults.va_smartva_keysymptom1,
            VaSmartvaResults.va_smartva_cause1icd,
            VaSmartvaResults.va_smartva_cause2,
            VaSmartvaResults.va_smartva_likelihood2,
            VaSmartvaResults.va_smartva_keysymptom2,
            VaSmartvaResults.va_smartva_cause2icd,
            VaSmartvaResults.va_smartva_cause3,
            VaSmartvaResults.va_smartva_likelihood3,
            VaSmartvaResults.va_smartva_keysymptom3,
            VaSmartvaResults.va_smartva_cause3icd,
            VaSmartvaResults.va_smartva_allsymptoms,
            VaSmartvaResults.va_smartva_outcome,
            VaSmartvaResults.va_smartva_failure_stage,
            VaSmartvaResults.va_smartva_failure_detail,
            VaSmartvaResults.va_smartva_addedat,
            VaSmartvaResults.va_smartva_updatedat,
        )
        .select_from(VaSubmissions)
        .join(VaForms, VaForms.form_id == VaSubmissions.va_form_id)
        .join(VaSubmissionWorkflow, VaSubmissionWorkflow.va_sid == VaSubmissions.va_sid)
        .join(
            VaSmartvaResults,
            sa.and_(
                VaSmartvaResults.va_sid == VaSubmissions.va_sid,
                VaSmartvaResults.va_smartva_status == VaStatuses.active,
            ),
        )
        .outerjoin(smartva_sids, smartva_sids.c.va_sid == VaSubmissions.va_sid)
        .outerjoin(smartva_failed_sids, smartva_failed_sids.c.va_sid == VaSubmissions.va_sid)
        .where(sa.and_(*conditions))
        .order_by(order, VaForms.project_id, VaForms.site_id, VaSubmissions.va_sid)
    )
    if _mv_ref is not None:
        query = query.outerjoin(_mv_ref, _mv_ref.c.va_sid == VaSubmissions.va_sid)
    rows = db.session.execute(query).mappings().all()

    headers = [
        "va_sid",
        "project_id",
        "site_id",
        "va_form_id",
        "va_uniqueid_masked",
        "workflow_state",
        "va_smartva_resultfor",
        "va_smartva_age",
        "va_smartva_gender",
        "va_smartva_cause1",
        "va_smartva_likelihood1",
        "va_smartva_keysymptom1",
        "va_smartva_cause1icd",
        "va_smartva_cause2",
        "va_smartva_likelihood2",
        "va_smartva_keysymptom2",
        "va_smartva_cause2icd",
        "va_smartva_cause3",
        "va_smartva_likelihood3",
        "va_smartva_keysymptom3",
        "va_smartva_cause3icd",
        "va_smartva_allsymptoms",
        "va_smartva_outcome",
        "va_smartva_failure_stage",
        "va_smartva_failure_detail",
        "va_smartva_addedat",
        "va_smartva_updatedat",
    ]
    handle = io.StringIO()
    writer = csv.DictWriter(handle, fieldnames=headers, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: _serialize_csv_cell(row.get(key)) for key in headers})
    return handle.getvalue()


def dm_smartva_likelihoods_export_csv(
    user,
    *,
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
) -> str:
    """Return raw SmartVA likelihood rows for all filtered submissions."""
    attachment_counts, smartva_sids, smartva_failed_sids, _mv_ref, conditions = _dm_submission_query_parts(
        user,
        search=search,
        project=project,
        site=site,
        date_from=date_from,
        date_to=date_to,
        odk_status=odk_status,
        smartva=smartva,
        age_group=age_group,
        gender=gender,
        odk_sync=odk_sync,
        workflow=workflow,
    )
    sort_col = _SORT_FIELDS.get(sort_field, sa.func.date(VaSubmissions.va_submission_date))
    order = sort_col.desc() if sort_dir == "desc" else sort_col.asc()
    query = (
        sa.select(
            VaSubmissions.va_sid,
            VaForms.project_id,
            VaForms.site_id,
            VaSubmissions.va_form_id,
            VaSubmissions.va_uniqueid_masked,
            VaSubmissionWorkflow.workflow_state,
            VaSmartvaRunOutput.output_source_name,
            VaSmartvaRunOutput.output_resultfor,
            VaSmartvaRunOutput.output_row_index,
            VaSmartvaRunOutput.output_payload,
        )
        .select_from(VaSubmissions)
        .join(VaForms, VaForms.form_id == VaSubmissions.va_form_id)
        .join(VaSubmissionWorkflow, VaSubmissionWorkflow.va_sid == VaSubmissions.va_sid)
        .join(
            VaSmartvaResults,
            sa.and_(
                VaSmartvaResults.va_sid == VaSubmissions.va_sid,
                VaSmartvaResults.va_smartva_status == VaStatuses.active,
            ),
        )
        .join(
            VaSmartvaRunOutput,
            sa.and_(
                VaSmartvaRunOutput.va_smartva_run_id == VaSmartvaResults.smartva_run_id,
                VaSmartvaRunOutput.output_sid == VaSubmissions.va_sid,
                VaSmartvaRunOutput.output_kind == "likelihood_row",
            ),
        )
        .outerjoin(smartva_sids, smartva_sids.c.va_sid == VaSubmissions.va_sid)
        .outerjoin(smartva_failed_sids, smartva_failed_sids.c.va_sid == VaSubmissions.va_sid)
        .where(sa.and_(*conditions))
        .order_by(order, VaForms.project_id, VaForms.site_id, VaSubmissions.va_sid, VaSmartvaRunOutput.output_row_index)
    )
    if _mv_ref is not None:
        query = query.outerjoin(_mv_ref, _mv_ref.c.va_sid == VaSubmissions.va_sid)
    rows = db.session.execute(query).mappings().all()

    payload_headers = sorted({
        key
        for row in rows
        for key in (row.get("output_payload") or {}).keys()
        if key != "sid"
    })
    headers = [
        "va_sid",
        "project_id",
        "site_id",
        "va_form_id",
        "va_uniqueid_masked",
        "workflow_state",
        "output_source_name",
        "output_resultfor",
        "output_row_index",
    ] + payload_headers

    handle = io.StringIO()
    writer = csv.DictWriter(handle, fieldnames=headers, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        export_row = {
            "va_sid": row.get("va_sid"),
            "project_id": row.get("project_id"),
            "site_id": row.get("site_id"),
            "va_form_id": row.get("va_form_id"),
            "va_uniqueid_masked": row.get("va_uniqueid_masked"),
            "workflow_state": row.get("workflow_state"),
            "output_source_name": row.get("output_source_name"),
            "output_resultfor": row.get("output_resultfor"),
            "output_row_index": row.get("output_row_index"),
        }
        for key in payload_headers:
            export_row[key] = _serialize_csv_cell((row.get("output_payload") or {}).get(key))
        writer.writerow(export_row)
    return handle.getvalue()


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


def _normalize_upstream_compare_dt(value):
    if value is None:
        return None
    if getattr(value, "tzinfo", None) is not None:
        return value.astimezone(value.tzinfo).replace(tzinfo=None)
    return value


def _require_fresh_reviewable_upstream_payload(
    submission: VaSubmissions,
    pending_change,
    pending_payload_version,
) -> None:
    """Ensure DM review actions operate on the latest pending payload snapshot."""
    pending_source = _normalize_upstream_compare_dt(
        pending_payload_version.source_updated_at
    )
    detected_updated = _normalize_upstream_compare_dt(
        pending_change.detected_odk_updatedat
    )
    submission_updated = _normalize_upstream_compare_dt(submission.va_odk_updatedat)

    if pending_source is None:
        raise ValueError(
            "Pending upstream payload has no source update timestamp. "
            "Refresh the submission from ODK and review again."
        )

    if detected_updated is not None and pending_source != detected_updated:
        raise ValueError(
            "Pending upstream payload is stale relative to the detected ODK update. "
            "Refresh the submission from ODK and review again."
        )

    if submission_updated is not None and submission_updated > pending_source:
        raise ValueError(
            "Pending upstream payload is stale relative to the current stored ODK update. "
            "Refresh the submission from ODK and review again."
        )


def _upstream_resolution_actor(user):
    """Return the canonical workflow actor for upstream-change resolution."""
    return admin_actor(user.user_id) if user.is_admin() else data_manager_actor(user.user_id)


def _data_manager_workflow_actor(user):
    """Return canonical workflow actor for DM/admin workflow actions."""
    return admin_actor(user.user_id) if user.is_admin() else data_manager_actor(user.user_id)


def _flatten_form_field_labels(form_type_code: str) -> dict[str, dict[str, str | None]]:
    """Return field metadata keyed by field id for a form type."""
    from app.services.field_mapping_service import get_mapping_service

    field_metadata: dict[str, dict[str, str | None]] = {}
    mapping_service = get_mapping_service()

    for category_code, subcategories in mapping_service.get_fieldsitepi(form_type_code).items():
        for subcategory_code, fields in subcategories.items():
            for field_id, short_label in fields.items():
                field_metadata[field_id] = {
                    "field_label": short_label or field_id,
                    "category_code": category_code,
                    "subcategory_code": subcategory_code,
                }
    return field_metadata


def _format_upstream_change_value(
    field_id: str,
    value,
    choice_map: dict[str, dict[str, str]],
) -> str:
    """Return a user-facing display string for a changed field value."""
    if value is None:
        return "—"

    field_choices = choice_map.get(field_id, {})

    if isinstance(value, list):
        if not value:
            return "[]"
        return ", ".join(
            _format_upstream_change_value(field_id, item, choice_map) for item in value
        )

    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True, ensure_ascii=True)

    text_value = str(value)
    if text_value == "":
        return '""'

    return field_choices.get(text_value, text_value)


def _build_changed_field_row(
    field_id: str,
    previous_value,
    current_value,
    field_metadata: dict[str, dict[str, str | None]],
    choice_map: dict[str, dict[str, str]],
) -> dict:
    metadata = field_metadata.get(field_id, {})
    return {
        "field_id": field_id,
        "field_label": metadata.get("field_label") or field_id,
        "category_code": metadata.get("category_code"),
        "subcategory_code": metadata.get("subcategory_code"),
        "previous_value": previous_value,
        "current_value": current_value,
        "previous_value_display": _format_upstream_change_value(
            field_id,
            previous_value,
            choice_map,
        ),
        "current_value_display": _format_upstream_change_value(
            field_id,
            current_value,
            choice_map,
        ),
    }


def _sort_changed_fields(changed_fields: list[dict]) -> list[dict]:
    changed_fields.sort(
        key=lambda row: (
            row.get("category_code") or "zzz",
            row.get("subcategory_code") or "zzz",
            row.get("field_label") or row["field_id"],
            row["field_id"],
        )
    )
    return changed_fields


def _build_upstream_changed_fields(
    form_type_code: str,
    previous_payload: dict | None,
    incoming_payload: dict | None,
) -> tuple[list[dict], list[dict], list[dict]]:
    """Build structured substantive, formatting-only, and non-substantive diffs."""
    from app.services.field_mapping_service import get_mapping_service

    previous_payload = previous_payload or {}
    incoming_payload = incoming_payload or {}
    normalized_previous = normalize_payload_for_fingerprint(previous_payload or {})
    normalized_incoming = normalize_payload_for_fingerprint(incoming_payload or {})
    field_metadata = _flatten_form_field_labels(form_type_code)
    choice_map = get_mapping_service().get_choices(form_type_code)

    changed_fields: list[dict] = []
    formatting_only_changed_fields: list[dict] = []
    non_substantive_changed_fields: list[dict] = []
    raw_field_ids = sorted(set(previous_payload) | set(incoming_payload))
    previous_key = previous_payload.get("KEY")
    incoming_key = incoming_payload.get("KEY")

    for field_id in raw_field_ids:
        if field_id in UPSTREAM_REVIEW_HIDDEN_FIELDS:
            continue
        previous_raw = previous_payload.get(field_id)
        current_raw = incoming_payload.get(field_id)
        if previous_raw == current_raw:
            continue

        if (
            field_id == "instanceID"
            and previous_key
            and incoming_key
            and previous_key == incoming_key
            and current_raw == incoming_key
            and previous_raw != previous_key
        ):
            continue

        if field_id in NON_SUBSTANTIVE_REVIEW_FIELDS:
            non_substantive_changed_fields.append(
                _build_changed_field_row(
                    field_id,
                    previous_raw,
                    current_raw,
                    field_metadata,
                    choice_map,
                )
            )
            continue

        previous_value = normalized_previous.get(field_id)
        current_value = normalized_incoming.get(field_id)
        if previous_value != current_value:
            if (
                _is_formatting_only_numeric_difference(previous_value, current_value)
                or _is_display_equivalent_choice_difference(
                    field_id,
                    previous_raw,
                    current_raw,
                    choice_map,
                )
            ):
                formatting_only_changed_fields.append(
                    _build_changed_field_row(
                        field_id,
                        previous_raw,
                        current_raw,
                        field_metadata,
                        choice_map,
                    )
                )
                continue
            changed_fields.append(
                _build_changed_field_row(
                    field_id,
                    previous_value,
                    current_value,
                    field_metadata,
                    choice_map,
                )
            )
            continue

        formatting_only_changed_fields.append(
            _build_changed_field_row(
                field_id,
                previous_raw,
                current_raw,
                field_metadata,
                choice_map,
            )
        )

    return (
        _sort_changed_fields(changed_fields),
        _sort_changed_fields(formatting_only_changed_fields),
        _sort_changed_fields(non_substantive_changed_fields),
    )


def dm_upstream_change_details(user, va_sid: str) -> dict:
    """Return structured upstream-change details for a DM/admin-visible submission."""
    from app.utils import va_get_form_type_code_for_form

    submission, _form_row = _dm_submission_scope_check(user, va_sid)
    pending_change = get_latest_pending_upstream_change(va_sid)
    if pending_change is None:
        raise ValueError("Submission has no pending upstream change record.")

    form_type_code = va_get_form_type_code_for_form(submission.va_form_id)
    (
        changed_fields,
        formatting_only_changed_fields,
        non_substantive_changed_fields,
    ) = _build_upstream_changed_fields(
        form_type_code,
        pending_change.previous_va_data,
        pending_change.incoming_va_data,
    )

    return {
        "va_sid": submission.va_sid,
        "form_type_code": form_type_code,
        "workflow_state_before": pending_change.workflow_state_before,
        "detected_odk_updatedat": (
            pending_change.detected_odk_updatedat.isoformat()
            if pending_change.detected_odk_updatedat
            else None
        ),
        "created_at": pending_change.created_at.isoformat(),
        "changed_field_count": len(changed_fields),
        "has_substantive_changes": bool(changed_fields),
        "changed_fields": changed_fields,
        "formatting_only_change_count": len(formatting_only_changed_fields),
        "formatting_only_changed_fields": formatting_only_changed_fields,
        "non_substantive_change_count": len(non_substantive_changed_fields),
        "non_substantive_changed_fields": non_substantive_changed_fields,
    }


def dm_screening_pass(user, va_sid: str) -> None:
    """Move a screening-pending submission into SmartVA processing."""
    from app.services.workflow.definition import WORKFLOW_SCREENING_PENDING
    from app.services.workflow.state_store import get_submission_workflow_state
    from app.services.workflow.transitions import mark_screening_passed

    _dm_submission_scope_check(user, va_sid)
    current_state = get_submission_workflow_state(va_sid)
    if current_state != WORKFLOW_SCREENING_PENDING:
        raise ValueError(
            f"Submission is in state '{current_state}', not screening_pending."
        )
    actor = _data_manager_workflow_actor(user)
    mark_screening_passed(
        va_sid,
        reason="data_manager_screening_passed",
        actor=actor,
    )


def dm_screening_reject(user, va_sid: str) -> None:
    """Reject a screening-pending submission before SmartVA/coding."""
    from app.services.workflow.definition import WORKFLOW_SCREENING_PENDING
    from app.services.workflow.state_store import get_submission_workflow_state
    from app.services.workflow.transitions import mark_screening_rejected

    _dm_submission_scope_check(user, va_sid)
    current_state = get_submission_workflow_state(va_sid)
    if current_state != WORKFLOW_SCREENING_PENDING:
        raise ValueError(
            f"Submission is in state '{current_state}', not screening_pending."
        )
    actor = _data_manager_workflow_actor(user)
    mark_screening_rejected(
        va_sid,
        reason="data_manager_screening_rejected",
        actor=actor,
    )


def dm_accept_upstream_change(user, va_sid: str) -> None:
    """Accept an upstream ODK data change for a revoked submission.

    Destroys finalized coding artifacts and returns the submission to
    smartva_pending so the new payload undergoes SmartVA before coding.

    Raises ValueError / PermissionError on invalid input or access denial.
    Does NOT commit — caller is responsible.
    """
    from app.services.workflow.definition import WORKFLOW_FINALIZED_UPSTREAM_CHANGED
    from app.services.workflow.transitions import accept_upstream_change

    _dm_submission_scope_check(user, va_sid)

    workflow_record = get_submission_workflow_record(va_sid, for_update=True)
    current_state = workflow_record.workflow_state if workflow_record else None
    if current_state != WORKFLOW_FINALIZED_UPSTREAM_CHANGED:
        raise ValueError(
            f"Submission is in state '{current_state}', not finalized_upstream_changed."
        )

    pending_change = get_latest_pending_upstream_change(va_sid)
    if pending_change is None or pending_change.incoming_payload_version_id is None:
        raise ValueError("Submission has no pending upstream payload version.")

    submission = db.session.scalar(
        sa.select(VaSubmissions).where(VaSubmissions.va_sid == va_sid).with_for_update()
    )
    if submission is None:
        raise ValueError("Submission not found.")

    pending_payload_version = get_payload_version(
        pending_change.incoming_payload_version_id
    )
    if pending_payload_version is None:
        raise ValueError("Pending upstream payload version not found.")
    _require_fresh_reviewable_upstream_payload(
        submission,
        pending_change,
        pending_payload_version,
    )

    actor = _upstream_resolution_actor(user)
    actor_role = actor.audit_role

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

    for rfa in db.session.scalars(
        sa.select(VaReviewerFinalAssessments).where(
            VaReviewerFinalAssessments.va_sid == va_sid,
            VaReviewerFinalAssessments.va_rfinassess_status == VaStatuses.active,
        )
    ).all():
        rfa.va_rfinassess_status = VaStatuses.deactive
    deactivate_active_reviewer_reviews_for_submission(
        va_sid,
        audit_byrole=actor.audit_role,
        audit_by=user.user_id,
        audit_action="reviewer review deactivated for recoding after upstream change",
    )

    deactivate_active_narrative_assessments_for_submission(
        va_sid,
        audit_byrole=actor.audit_role,
        audit_by=user.user_id,
        audit_action="narrative quality assessment deactivated for recoding after upstream change",
    )
    deactivate_active_social_autopsy_analyses_for_submission(
        va_sid,
        audit_byrole=actor.audit_role,
        audit_by=user.user_id,
        audit_action="social autopsy analysis deactivated for recoding after upstream change",
    )

    promote_pending_upstream_payload_version(submission, pending_payload_version)
    apply_payload_to_submission_summary(
        submission,
        pending_payload_version.payload_data,
        source_updated_at=pending_payload_version.source_updated_at,
    )

    accept_upstream_change(
        va_sid,
        reason="data_manager_accepted_upstream_change",
        actor=actor,
    )
    upsert_final_cod_authority(
        va_sid,
        None,
        reason="data_manager_accepted_upstream_change",
        source_role=actor_role,
        updated_by=user.user_id,
    )
    resolve_pending_upstream_change(
        va_sid,
        resolution_status=UPSTREAM_CHANGE_STATUS_ACCEPTED,
        resolved_by=user.user_id,
        resolved_by_role=actor_role,
    )


def dm_keep_current_icd_on_upstream_change(user, va_sid: str) -> None:
    """Promote new ODK data while preserving the current finalized ICD decision.

    The incoming upstream payload becomes the active submission payload, but
    finalized ICD/COD artifacts remain active and the workflow returns to the
    prior finalized state instead of reopening coding.

    Raises ValueError / PermissionError on invalid input or access denial.
    Does NOT commit — caller is responsible.
    """
    from app.services.workflow.definition import (
        WORKFLOW_CODER_FINALIZED,
        WORKFLOW_FINALIZED_UPSTREAM_CHANGED,
    )
    from app.services.workflow.state_store import infer_workflow_state_from_legacy_records
    from app.services.workflow.transitions import keep_current_icd_on_upstream_change

    _dm_submission_scope_check(user, va_sid)

    workflow_record = get_submission_workflow_record(va_sid, for_update=True)
    current_state = workflow_record.workflow_state if workflow_record else None
    if current_state != WORKFLOW_FINALIZED_UPSTREAM_CHANGED:
        raise ValueError(
            f"Submission is in state '{current_state}', not finalized_upstream_changed."
        )

    pending_change = get_latest_pending_upstream_change(va_sid)
    if pending_change is None:
        raise ValueError("Submission has no pending upstream change record.")

    restore_state = pending_change.workflow_state_before or WORKFLOW_CODER_FINALIZED
    if restore_state == WORKFLOW_FINALIZED_UPSTREAM_CHANGED:
        inferred_state = infer_workflow_state_from_legacy_records(va_sid)
        restore_state = (
            inferred_state
            if inferred_state != WORKFLOW_FINALIZED_UPSTREAM_CHANGED
            else WORKFLOW_CODER_FINALIZED
        )
    pending_payload_version = get_payload_version(
        pending_change.incoming_payload_version_id
    )
    if pending_payload_version is None:
        raise ValueError("Pending upstream payload version not found.")

    submission = db.session.scalar(
        sa.select(VaSubmissions).where(VaSubmissions.va_sid == va_sid).with_for_update()
    )
    if submission is None:
        raise ValueError("Submission not found.")
    previous_payload_version_id = submission.active_payload_version_id
    _require_fresh_reviewable_upstream_payload(
        submission,
        pending_change,
        pending_payload_version,
    )

    actor = _upstream_resolution_actor(user)
    actor_role = actor.audit_role

    promote_pending_upstream_payload_version(submission, pending_payload_version)
    apply_payload_to_submission_summary(
        submission,
        pending_payload_version.payload_data,
        source_updated_at=pending_payload_version.source_updated_at,
    )
    promote_active_smartva_to_payload(
        va_sid,
        from_payload_version_id=previous_payload_version_id,
        to_payload_version_id=pending_payload_version.payload_version_id,
    )
    promote_active_reviewer_reviews_to_payload(
        va_sid,
        to_payload_version_id=pending_payload_version.payload_version_id,
    )
    promote_active_narrative_assessments_to_payload(
        va_sid,
        to_payload_version_id=pending_payload_version.payload_version_id,
    )
    promote_active_social_autopsy_analyses_to_payload(
        va_sid,
        to_payload_version_id=pending_payload_version.payload_version_id,
    )

    keep_current_icd_on_upstream_change(
        va_sid,
        target_state=restore_state,
        reason="data_manager_kept_current_icd_after_upstream_change",
        actor=actor,
    )
    resolve_pending_upstream_change(
        va_sid,
        resolution_status=UPSTREAM_CHANGE_STATUS_KEPT_CURRENT_ICD,
        resolved_by=user.user_id,
        resolved_by_role=actor_role,
    )


def dm_reject_upstream_change(user, va_sid: str) -> None:
    """Backward-compatible alias for keeping the current ICD decision.

    Route names and some callers still use "reject" language, but the current
    behavior is to adopt the latest ODK payload while preserving finalized ICD
    artifacts and finalized workflow state.
    """
    dm_keep_current_icd_on_upstream_change(user, va_sid)
