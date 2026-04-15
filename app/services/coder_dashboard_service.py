"""Coder dashboard queries backed by canonical workflow state."""

from __future__ import annotations

from collections.abc import Sequence
import hashlib

import sqlalchemy as sa

from app import cache, db
from app.models import (
    VaCoderReview,
    VaFinalAssessments,
    VaForms,
    VaProjectMaster,
    VaResearchProjects,
    VaStatuses,
    VaSubmissionWorkflow,
    VaSubmissions,
)
from app.services.demo_project_service import get_coder_demo_project_form_ids
from app.services.workflow.definition import (
    WORKFLOW_CODER_FINALIZED,
    WORKFLOW_NOT_CODEABLE_BY_CODER,
)
from app.utils import va_render_serialisedates


CODER_DASHBOARD_CACHE_TTL = 300
CODER_DASHBOARD_CACHE_PREFIX = "coder_dashboard:"


def _normalize_form_ids(form_ids: Sequence[str]) -> tuple[str, ...]:
    return tuple(sorted({str(form_id) for form_id in form_ids if str(form_id).strip()}))


def _exclude_demo_form_ids(form_ids: Sequence[str]) -> tuple[str, ...]:
    normalized_form_ids = _normalize_form_ids(form_ids)
    if not normalized_form_ids:
        return ()
    demo_form_ids = get_coder_demo_project_form_ids(only_active=True)
    return tuple(form_id for form_id in normalized_form_ids if form_id not in demo_form_ids)


def _dashboard_scope_hash(form_ids: Sequence[str]) -> str:
    normalized_form_ids = _normalize_form_ids(form_ids)
    digest = hashlib.sha1(
        "\x1f".join(normalized_form_ids).encode("utf-8")
    ).hexdigest()
    return digest


def _dashboard_cache_key(user_id, suffix: str, form_ids: Sequence[str]) -> str:
    return (
        f"{CODER_DASHBOARD_CACHE_PREFIX}{user_id}:{suffix}:"
        f"{_dashboard_scope_hash(form_ids)}"
    )


def _cached_dashboard_value(user_id, suffix: str, form_ids: Sequence[str], compute_fn):
    cache_key = _dashboard_cache_key(user_id, suffix, form_ids)
    try:
        cached_value = cache.get(cache_key)
    except Exception:
        cached_value = None
    if cached_value is not None and not isinstance(cached_value, BaseException):
        return cached_value

    value = compute_fn()
    try:
        cache.set(cache_key, value, timeout=CODER_DASHBOARD_CACHE_TTL)
    except Exception:
        pass
    return value


def _cached_dashboard_project_value(user_id, suffix: str, project_id: str | None, compute_fn):
    cache_key = f"{CODER_DASHBOARD_CACHE_PREFIX}{user_id}:{suffix}:{project_id or 'ALL'}"
    try:
        cached_value = cache.get(cache_key)
    except Exception:
        cached_value = None
    if cached_value is not None and not isinstance(cached_value, BaseException):
        return cached_value

    value = compute_fn()
    try:
        cache.set(cache_key, value, timeout=CODER_DASHBOARD_CACHE_TTL)
    except Exception:
        pass
    return value


def bust_coder_dashboard_cache(user_id) -> int:
    """Delete cached coder dashboard stats/history entries for one user."""
    key_prefix = CODER_DASHBOARD_CACHE_PREFIX
    deleted = 0
    try:
        redis_client = cache.cache._write_client  # type: ignore[attr-defined]
        keys = redis_client.keys(f"*{key_prefix}{user_id}:*")
        if keys:
            deleted = redis_client.delete(*keys)
    except Exception:
        return 0
    return deleted


def get_coder_output_summary(user_id, project_id: str | None = None) -> dict[str, int]:
    """Return cached authored-output KPIs, excluding demo-training projects."""

    def compute():
        final_filters = [
            VaFinalAssessments.va_finassess_by == user_id,
            VaFinalAssessments.va_finassess_status == VaStatuses.active,
            sa.or_(
                VaProjectMaster.project_id.is_(None),
                VaProjectMaster.demo_training_enabled.is_(False),
            ),
        ]
        review_filters = [
            VaCoderReview.va_creview_by == user_id,
            VaCoderReview.va_creview_status == VaStatuses.active,
            sa.or_(
                VaProjectMaster.project_id.is_(None),
                VaProjectMaster.demo_training_enabled.is_(False),
            ),
        ]
        if project_id:
            final_filters.append(VaForms.project_id == project_id)
            review_filters.append(VaForms.project_id == project_id)

        completed = db.session.scalar(
            sa.select(sa.func.count(sa.distinct(VaFinalAssessments.va_sid)))
            .select_from(VaFinalAssessments)
            .join(VaSubmissions, VaSubmissions.va_sid == VaFinalAssessments.va_sid)
            .join(VaForms, VaForms.form_id == VaSubmissions.va_form_id)
            .outerjoin(VaProjectMaster, VaProjectMaster.project_id == VaForms.project_id)
            .where(
                *final_filters,
            )
        ) or 0

        not_codeable = db.session.scalar(
            sa.select(sa.func.count(sa.distinct(VaCoderReview.va_sid)))
            .select_from(VaCoderReview)
            .join(VaSubmissions, VaSubmissions.va_sid == VaCoderReview.va_sid)
            .join(VaForms, VaForms.form_id == VaSubmissions.va_form_id)
            .outerjoin(VaProjectMaster, VaProjectMaster.project_id == VaForms.project_id)
            .where(
                *review_filters,
            )
        ) or 0

        return {
            "completed": completed,
            "not_codeable": not_codeable,
        }

    return _cached_dashboard_project_value(
        user_id,
        "output_summary",
        project_id,
        compute,
    )


def get_coder_completed_count(user_id, accessible_form_ids: Sequence[str]) -> int:
    """Return authored final-coding count for non-demo projects."""
    return get_coder_output_summary(user_id)["completed"]


def get_coder_not_codeable_count(user_id, accessible_form_ids: Sequence[str]) -> int:
    """Return authored not-codeable count for non-demo projects."""
    return get_coder_output_summary(user_id)["not_codeable"]


def get_coder_completed_history(user_id, accessible_form_ids: Sequence[str]) -> list[dict]:
    """Return cached coder history rows for non-demo authored outputs."""
    scoped_form_ids = _exclude_demo_form_ids(accessible_form_ids)
    if not scoped_form_ids:
        return []

    def compute():
        final_rows = db.session.execute(
            sa.select(
                VaForms.project_id.label("project_id"),
                VaForms.site_id.label("site_id"),
                sa.func.date(VaSubmissions.va_submission_date).label("va_submission_date"),
                VaSubmissions.va_form_id,
                VaSubmissions.va_sid,
                VaSubmissions.va_uniqueid_masked,
                VaSubmissions.va_deceased_age,
                VaSubmissions.va_deceased_gender,
                VaFinalAssessments.va_finassess_createdat.label("va_coding_date"),
                sa.literal("VA Coding Completed").label("va_code_status"),
            )
            .select_from(VaFinalAssessments)
            .join(VaSubmissions, VaSubmissions.va_sid == VaFinalAssessments.va_sid)
            .join(VaForms, VaForms.form_id == VaSubmissions.va_form_id)
            .where(
                VaFinalAssessments.va_finassess_by == user_id,
                VaFinalAssessments.va_finassess_status == VaStatuses.active,
                VaSubmissions.va_form_id.in_(scoped_form_ids),
            )
        ).mappings().all()

        review_rows = db.session.execute(
            sa.select(
                VaForms.project_id.label("project_id"),
                VaForms.site_id.label("site_id"),
                sa.func.date(VaSubmissions.va_submission_date).label("va_submission_date"),
                VaSubmissions.va_form_id,
                VaSubmissions.va_sid,
                VaSubmissions.va_uniqueid_masked,
                VaSubmissions.va_deceased_age,
                VaSubmissions.va_deceased_gender,
                VaCoderReview.va_creview_createdat.label("va_coding_date"),
                sa.literal("Not Codeable").label("va_code_status"),
            )
            .select_from(VaCoderReview)
            .join(VaSubmissions, VaSubmissions.va_sid == VaCoderReview.va_sid)
            .join(VaForms, VaForms.form_id == VaSubmissions.va_form_id)
            .where(
                VaCoderReview.va_creview_by == user_id,
                VaCoderReview.va_creview_status == VaStatuses.active,
                VaSubmissions.va_form_id.in_(scoped_form_ids),
            )
        ).mappings().all()

        rows = [
            va_render_serialisedates(
                dict(row),
                ["va_submission_date", "va_coding_date"],
            )
            for row in [*final_rows, *review_rows]
        ]
        rows.sort(
            key=lambda row: (
                row.get("va_coding_date") or "",
                row.get("va_submission_date") or "",
            ),
            reverse=True,
        )
        return rows

    return _cached_dashboard_value(
        user_id,
        "history",
        scoped_form_ids,
        compute,
    )


def get_coder_recodeable_sids(user_id, accessible_form_ids: Sequence[str]) -> list[str]:
    """Return recently finalized SIDs that are eligible for recode."""
    if not accessible_form_ids:
        return []

    recent_window = sa.text("interval '24 hours'")
    stmt = (
        sa.select(VaSubmissions.va_sid)
        .select_from(VaSubmissions)
        .join(VaSubmissionWorkflow, VaSubmissionWorkflow.va_sid == VaSubmissions.va_sid)
        .outerjoin(
            VaFinalAssessments,
            sa.and_(
                VaFinalAssessments.va_sid == VaSubmissions.va_sid,
                VaFinalAssessments.va_finassess_status == VaStatuses.active,
                VaFinalAssessments.va_finassess_by == user_id,
            ),
        )
        .outerjoin(
            VaCoderReview,
            sa.and_(
                VaCoderReview.va_sid == VaSubmissions.va_sid,
                VaCoderReview.va_creview_status == VaStatuses.active,
                VaCoderReview.va_creview_by == user_id,
            ),
        )
        .where(
            VaSubmissions.va_form_id.in_(accessible_form_ids),
            VaSubmissionWorkflow.workflow_state == WORKFLOW_CODER_FINALIZED,
            VaFinalAssessments.va_finassess_id.is_not(None),
            VaFinalAssessments.va_finassess_createdat + recent_window
            > sa.func.now(),
            VaCoderReview.va_creview_id.is_(None),
        )
    )
    return db.session.scalars(stmt).all()


def get_coder_project_ids(accessible_form_ids: Sequence[str]) -> list[str]:
    """Return distinct project IDs for the supplied form set."""
    if not accessible_form_ids:
        return []

    return db.session.execute(
        sa.select(VaForms.project_id)
        .where(VaForms.form_id.in_(accessible_form_ids))
        .distinct()
        .order_by(VaForms.project_id)
    ).scalars().all()


def get_coder_project_options(accessible_form_ids: Sequence[str]) -> list[dict[str, str]]:
    """Return distinct project options for the supplied form set."""
    if not accessible_form_ids:
        return []

    rows = db.session.execute(
        sa.select(
            VaForms.project_id,
            VaResearchProjects.project_name,
        )
        .select_from(VaForms)
        .outerjoin(VaResearchProjects, VaResearchProjects.project_id == VaForms.project_id)
        .where(VaForms.form_id.in_(accessible_form_ids))
        .distinct()
        .order_by(VaForms.project_id)
    ).all()
    return [
        {
            "project_id": project_id,
            "project_name": project_name or project_id,
        }
        for project_id, project_name in rows
    ]
