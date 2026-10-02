import sqlalchemy as sa
from app import db
from app.models import (
    VaAllocations,
    VaAllocation,
    VaFinalAssessments,
    VaReviewerFinalAssessments,
    VaForms,
    VaProjectSites,
    VaStatuses,
    VaSubmissionWorkflow,
    VaSubmissions,
)
from flask_login import current_user
from flask import Blueprint, redirect, render_template, url_for
from app.decorators import role_required
from app.utils import va_permission_abortwithflash, va_render_serialisedates
from app.utils import va_permission_ensureanyallocation
from app.routes.coding import _has_org_unit_area, _require_or_abort
from app.services.authz import Action, scope_filter
from app.services.coding_service import render_va_coding_page
from app.services.duplicate_exclusion import not_confirmed_duplicate_condition
from app.services.odk_retirement_service import submission_is_in_odk
from app.services.workflow.definition import (
    WORKFLOW_REVIEWER_CODING_IN_PROGRESS,
    WORKFLOW_REVIEWER_FINALIZED,
)
from app.services.reviewer_coding_service import (
    ReviewerCodingError,
    get_active_reviewing_allocation,
    start_reviewer_coding,
)

reviewing = Blueprint("reviewing", __name__)


@reviewing.get("/")
@role_required("reviewer")
def dashboard():
    # The reviewing scope: the same predicate require(REVIEW) answers for one
    # submission (form, pair and unit scope, the coding-scope rule on
    # reviewer grants), so the list never offers what start refuses. It
    # lists every workflow state (F19, unchanged).
    review_scope = scope_filter(current_user, Action.REVIEW)
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
    va_total_forms = db.session.scalar(
        sa.select(sa.func.count())
        .select_from(VaSubmissions)
        .join(VaForms, VaForms.form_id == VaSubmissions.va_form_id)
        .join(
            VaProjectSites,
            sa.and_(
                VaProjectSites.project_id == VaForms.project_id,
                VaProjectSites.site_id == VaForms.site_id,
                VaProjectSites.project_site_status == VaStatuses.active,
            ),
        )
        .where(
            sa.sql.and_(
                review_scope,
                VaSubmissions.va_narration_language.in_(
                    current_user.vacode_language
                ),
                not_confirmed_duplicate_condition(VaSubmissions.va_sid),
            )
        )
    )
    # "Completed" = this reviewer has submitted a final COD
    # (reviewer_finalized state). NQA and Social Autopsy are supporting
    # artifacts filled during the session — they are not terminal actions
    # and do not count as "completed".
    va_forms_completed = db.session.scalar(
        sa.select(sa.func.count())
        .select_from(VaReviewerFinalAssessments)
        .where(
            VaReviewerFinalAssessments.va_rfinassess_by == current_user.user_id,
            VaReviewerFinalAssessments.va_rfinassess_status == VaStatuses.active,
        )
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
            .join(
                VaProjectSites,
                sa.and_(
                    VaProjectSites.project_id == VaForms.project_id,
                    VaProjectSites.site_id == VaForms.site_id,
                    VaProjectSites.project_site_status == VaStatuses.active,
                ),
            )
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
                    VaSubmissions.va_narration_language.in_(
                        current_user.vacode_language
                    ),
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
    va_forms = [
        va_render_serialisedates(row, va_date_fields) for row in va_forms_raw
    ]
    va_has_allocation = db.session.scalar(
        sa.select(VaAllocations.va_sid).where(
            (VaAllocations.va_allocated_to == current_user.user_id)
            & (VaAllocations.va_allocation_for == VaAllocation.reviewing)
            & (VaAllocations.va_allocation_status == VaStatuses.active)
        )
    )
    return render_template(
        "va_frontpages/va_reviewer.html",
        va_total_forms=va_total_forms,
        va_forms_completed=va_forms_completed,
        va_forms=va_forms,
        va_has_allocation=va_has_allocation,
        has_org_unit_area=_has_org_unit_area("reviewer"),
    )


@reviewing.post("/start/<va_sid>")
@role_required("reviewer")
def start(va_sid):
    # POST (CSRF-checked) because it allocates and moves the workflow; the
    # redirect keeps a browser refresh from re-firing it.
    try:
        start_reviewer_coding(current_user, va_sid)
    except ReviewerCodingError as exc:
        va_permission_abortwithflash(exc.message, exc.status_code)
    return redirect(url_for("reviewing.resume"))


@reviewing.get("/resume")
@role_required("reviewer")
def resume():
    va_permission_ensureanyallocation("reviewing")
    va_sid = get_active_reviewing_allocation(current_user.user_id)
    form = db.session.get(VaSubmissions, va_sid)
    return render_va_coding_page(form, "vareview", "varesumereviewing", "reviewer")


@reviewing.get("/view/<va_sid>")
@role_required("reviewer")
def view_submission(va_sid):
    # VIEW, not REVIEW: viewing is the wider right, so a reviewer above the
    # coding scope level still opens their subtree read-only (F7). The
    # ``vaview`` partials ask the same VIEW (va_validate_permissions).
    _require_or_abort(Action.VIEW, va_sid)
    form = db.session.get(VaSubmissions, va_sid)
    return render_va_coding_page(form, "vareview", "vaview", "reviewer")
