"""Reviewer dashboard and queue reads, shared by the web page and /api/v1/reviewing."""

from __future__ import annotations

from datetime import UTC

import sqlalchemy as sa

from app import db
from app.models import (
    VaAllocation,
    VaAllocations,
    VaFinalAssessments,
    VaForms,
    VaProjectSites,
    VaReviewerFinalAssessments,
    VaStatuses,
    VaSubmissions,
    VaSubmissionWorkflow,
)
from app.services.authz import Action, can, scope_filter
from app.services.duplicate_exclusion import not_confirmed_duplicate_condition
from app.services.odk_retirement_service import submission_is_in_odk
from app.services.workflow.definition import (
    WORKFLOW_REVIEWER_CODING_IN_PROGRESS,
    WORKFLOW_REVIEWER_ELIGIBLE,
    WORKFLOW_REVIEWER_FINALIZED,
)
from app.utils import va_render_serialisedates

#: Rows per page of the API lists: the default, and the server-side clamp.
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


def _active_project_site():
    """Join condition: the form's project-site is active."""
    return sa.and_(
        VaProjectSites.project_id == VaForms.project_id,
        VaProjectSites.site_id == VaForms.site_id,
        VaProjectSites.project_site_status == VaStatuses.active,
    )


def count_in_scope(user, project_id: str | None = None) -> int:
    """Submissions the reviewer may see on the dashboard (any workflow state).

    The reviewing scope: the same predicate require(REVIEW) answers for one
    submission (form, pair and unit scope, the coding-scope rule on
    reviewer grants), so the list never offers what start refuses. It
    lists every workflow state (F19, unchanged).
    """
    review_scope = scope_filter(user, Action.REVIEW)
    stmt = (
        sa.select(sa.func.count())
        .select_from(VaSubmissions)
        .join(VaForms, VaForms.form_id == VaSubmissions.va_form_id)
        .join(VaProjectSites, _active_project_site())
        .where(
            sa.sql.and_(
                review_scope,
                VaSubmissions.va_narration_language.in_(user.vacode_language),
                not_confirmed_duplicate_condition(VaSubmissions.va_sid),
            )
        )
    )
    if project_id:
        stmt = stmt.where(VaForms.project_id == project_id)
    return db.session.scalar(stmt)


def count_completed(user, project_id: str | None = None) -> int:
    # "Completed" = this reviewer has submitted a final COD
    # (reviewer_finalized state). NQA and Social Autopsy are supporting
    # artifacts filled during the session — they are not terminal actions
    # and do not count as "completed".
    stmt = (
        sa.select(sa.func.count())
        .select_from(VaReviewerFinalAssessments)
        .where(
            VaReviewerFinalAssessments.va_rfinassess_by == user.user_id,
            VaReviewerFinalAssessments.va_rfinassess_status == VaStatuses.active,
        )
    )
    if project_id:
        stmt = (
            stmt.join(
                VaSubmissions,
                VaSubmissions.va_sid == VaReviewerFinalAssessments.va_sid,
            )
            .join(VaForms, VaForms.form_id == VaSubmissions.va_form_id)
            .where(VaForms.project_id == project_id)
        )
    return db.session.scalar(stmt)


def list_dashboard_forms(user) -> list[dict]:
    """Every in-scope submission with its review status, for the web dashboard."""
    review_scope = scope_filter(user, Action.REVIEW)
    active_final = (
        sa.select(
            VaFinalAssessments.va_sid.label("va_sid"),
            sa.func.max(VaFinalAssessments.va_finassess_createdat).label(
                "va_coded_at"
            ),
        )
        .where(VaFinalAssessments.va_finassess_status == VaStatuses.active)
        .group_by(VaFinalAssessments.va_sid)
        .subquery()
    )
    va_forms_raw = (
        db.session.execute(
            sa.select(
                sa.func.date(VaSubmissions.va_submission_date).label(
                    "va_submission_date"
                ),
                VaForms.project_id.label("project_id"),
                VaForms.site_id.label("site_id"),
                VaSubmissions.va_form_id,
                VaSubmissions.va_sid,
                VaSubmissions.va_uniqueid_masked,
                VaSubmissions.va_data_collector,
                VaSubmissions.va_narration_language,
                VaSubmissions.va_deceased_age,
                VaSubmissions.va_deceased_gender,
                sa.func.date(active_final.c.va_coded_at).label("va_coded_at"),
                # Workflow state is the canonical source for review status.
                # reviewer_finalized  → terminal, final COD submitted
                # reviewer_coding_in_progress → session active
                # anything else       → not yet started
                sa.case(
                    (
                        VaSubmissionWorkflow.workflow_state
                        == "reviewer_finalized",
                        sa.literal("Reviewed"),
                    ),
                    (
                        VaSubmissionWorkflow.workflow_state
                        == "reviewer_coding_in_progress",
                        sa.literal("In Progress"),
                    ),
                    else_=sa.literal("Not Reviewed"),
                ).label("va_review_status"),
                sa.func.date(
                    VaReviewerFinalAssessments.va_rfinassess_createdat
                ).label("va_reviewed_at"),
            )
            .join(VaForms, VaForms.form_id == VaSubmissions.va_form_id)
            .join(VaProjectSites, _active_project_site())
            .outerjoin(
                active_final,
                active_final.c.va_sid == VaSubmissions.va_sid,
            )
            .outerjoin(
                VaSubmissionWorkflow,
                VaSubmissionWorkflow.va_sid == VaSubmissions.va_sid,
            )
            .outerjoin(
                VaReviewerFinalAssessments,
                sa.and_(
                    VaReviewerFinalAssessments.va_sid == VaSubmissions.va_sid,
                    VaReviewerFinalAssessments.va_rfinassess_status
                    == VaStatuses.active,
                ),
            )
            .where(
                sa.sql.and_(
                    review_scope,
                    VaSubmissions.va_narration_language.in_(user.vacode_language),
                    not_confirmed_duplicate_condition(VaSubmissions.va_sid),
                    # A retired submission is not offered for review, but a
                    # review already done or still in session stays visible
                    # (docs/policy/odk-retired-submissions.md). That carve-out
                    # is for retirement only: a confirmed duplicate leaves the
                    # list in every state, finished reviews included.
                    sa.or_(
                        submission_is_in_odk(),
                        VaSubmissionWorkflow.workflow_state.in_(
                            (
                                WORKFLOW_REVIEWER_CODING_IN_PROGRESS,
                                WORKFLOW_REVIEWER_FINALIZED,
                            )
                        ),
                    ),
                )
            )
        )
        .mappings()
        .all()
    )
    va_date_fields = ["va_submission_date", "va_coded_at", "va_reviewed_at"]
    return [va_render_serialisedates(row, va_date_fields) for row in va_forms_raw]


def get_scoped_allocation(user) -> str | None:
    """The va_sid of the reviewer's active reviewing allocation, or None.

    An allocation grants nothing once the submission leaves review scope.
    """
    va_has_allocation = db.session.scalar(
        sa.select(VaAllocations.va_sid).where(
            (VaAllocations.va_allocated_to == user.user_id)
            & (VaAllocations.va_allocation_for == VaAllocation.reviewing)
            & (VaAllocations.va_allocation_status == VaStatuses.active)
        )
    )
    if va_has_allocation and not can(user, Action.REVIEW, va_has_allocation).allowed:
        return None
    return va_has_allocation


def _available_where(user, project_id: str | None) -> list:
    """What ``start_reviewer_coding`` accepts, as conditions.

    REVIEW scope, ``reviewer_eligible``, narration language in the reviewer's
    profile, in ODK (not retired), not a confirmed duplicate, no active
    reviewer final yet, and an active project-site (the join the callers add).
    An allocation the reviewer already holds does not narrow it: the held case
    is in session, not eligible, and the client reads ``allocation`` from stats.
    """
    conditions = [
        scope_filter(user, Action.REVIEW),
        VaSubmissionWorkflow.workflow_state == WORKFLOW_REVIEWER_ELIGIBLE,
        VaSubmissions.va_narration_language.in_(user.vacode_language),
        submission_is_in_odk(),
        not_confirmed_duplicate_condition(VaSubmissions.va_sid),
        ~sa.exists().where(
            VaReviewerFinalAssessments.va_sid == VaSubmissions.va_sid,
            VaReviewerFinalAssessments.va_rfinassess_status == VaStatuses.active,
        ),
    ]
    if project_id:
        conditions.append(VaForms.project_id == project_id)
    return conditions


def count_available(user, project_id: str | None = None) -> int:
    return db.session.scalar(
        sa.select(sa.func.count())
        .select_from(VaSubmissions)
        .join(VaForms, VaForms.form_id == VaSubmissions.va_form_id)
        .join(VaProjectSites, _active_project_site())
        .join(VaSubmissionWorkflow, VaSubmissionWorkflow.va_sid == VaSubmissions.va_sid)
        .where(*_available_where(user, project_id))
    )


def list_available(
    user, *, limit: int, offset: int, project_id: str | None = None
) -> tuple[list[dict], bool]:
    """One page of the cases the reviewer may start, and whether more follow.

    Fetches ``limit + 1`` rows to answer ``has_more`` without a count. Order is
    project, site, submission date, masked id, then ``va_sid`` so paging is
    stable.
    """
    rows = (
        db.session.execute(
            sa.select(
                VaSubmissions.va_sid,
                VaSubmissions.va_uniqueid_masked,
                VaSubmissions.va_form_id,
                VaForms.project_id,
                VaForms.site_id,
                sa.func.date(VaSubmissions.va_submission_date).label(
                    "va_submission_date"
                ),
                VaSubmissions.va_data_collector,
                VaSubmissions.va_deceased_age,
                VaSubmissions.va_deceased_gender,
                VaSubmissions.va_narration_language,
            )
            .select_from(VaSubmissions)
            .join(VaForms, VaForms.form_id == VaSubmissions.va_form_id)
            .join(VaProjectSites, _active_project_site())
            .join(
                VaSubmissionWorkflow,
                VaSubmissionWorkflow.va_sid == VaSubmissions.va_sid,
            )
            .where(*_available_where(user, project_id))
            .order_by(
                VaForms.project_id,
                VaForms.site_id,
                VaSubmissions.va_submission_date,
                VaSubmissions.va_uniqueid_masked,
                VaSubmissions.va_sid,
            )
            .limit(limit + 1)
            .offset(offset)
        )
        .mappings()
        .all()
    )
    return (
        [va_render_serialisedates(row, ["va_submission_date"]) for row in rows[:limit]],
        len(rows) > limit,
    )


def list_history(
    user, *, limit: int, offset: int, project_id: str | None = None
) -> tuple[list[dict], bool]:
    """One page of the reviewer's own active final CODs, newest first.

    Only submissions the reviewer may still VIEW (what the history's view link
    opens): authoring a final grants nothing once the case is rerouted out of
    the reviewer's unit. ``va_reviewed_at`` is the final's UTC timestamp, ISO with ``+00:00``.
    """
    stmt = (
        sa.select(
            VaSubmissions.va_sid,
            VaSubmissions.va_uniqueid_masked,
            VaSubmissions.va_form_id,
            VaForms.project_id,
            VaForms.site_id,
            sa.func.date(VaSubmissions.va_submission_date).label("va_submission_date"),
            VaSubmissions.va_data_collector,
            VaSubmissions.va_deceased_age,
            VaSubmissions.va_deceased_gender,
            VaSubmissions.va_narration_language,
            VaReviewerFinalAssessments.va_rfinassess_createdat.label("va_reviewed_at"),
        )
        .select_from(VaReviewerFinalAssessments)
        .join(VaSubmissions, VaSubmissions.va_sid == VaReviewerFinalAssessments.va_sid)
        .join(VaForms, VaForms.form_id == VaSubmissions.va_form_id)
        .where(
            VaReviewerFinalAssessments.va_rfinassess_by == user.user_id,
            VaReviewerFinalAssessments.va_rfinassess_status == VaStatuses.active,
            scope_filter(user, Action.VIEW),
        )
        .order_by(
            VaReviewerFinalAssessments.va_rfinassess_createdat.desc(),
            VaReviewerFinalAssessments.va_rfinassess_id.desc(),
        )
        .limit(limit + 1)
        .offset(offset)
    )
    if project_id:
        stmt = stmt.where(VaForms.project_id == project_id)
    rows = db.session.execute(stmt).mappings().all()
    history = []
    for row in rows[:limit]:
        item = va_render_serialisedates(row, ["va_submission_date"])
        # The column is naive and written as UTC (the model default); say so.
        item["va_reviewed_at"] = (
            row["va_reviewed_at"].replace(tzinfo=UTC).isoformat()
        )
        history.append(item)
    return history, len(rows) > limit
