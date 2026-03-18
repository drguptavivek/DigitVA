from datetime import datetime
import sqlalchemy as sa
from app import db
from app.models import VaSubmissions, VaSubmissionWorkflow, VaAllocations, VaAllocation, VaStatuses, VaForms
from flask_login import current_user, login_required
from flask import Blueprint, render_template, url_for
from app.utils import va_permission_abortwithflash, va_render_serialisedates
from app.services.coder_dashboard_service import (
    get_coder_completed_count,
    get_coder_completed_history,
    get_coder_project_ids,
    get_coder_recodeable_sids,
)
from app.services.project_workflow_service import split_form_ids_by_coding_intake_mode
from app.services.submission_workflow_service import CODER_READY_POOL_STATES


coding = Blueprint("coding", __name__)


@coding.get("/")
@login_required
def dashboard():
    if not current_user.is_coder() and not current_user.is_admin():
        va_permission_abortwithflash("Coder access is required.", 403)

    va_form_access = current_user.get_coder_va_forms()
    if va_form_access:
        random_form_ids, pick_form_ids = split_form_ids_by_coding_intake_mode(va_form_access)
        va_total_forms = db.session.scalar(
            sa.select(sa.func.count())
            .select_from(VaSubmissions)
            .join(VaSubmissionWorkflow, VaSubmissionWorkflow.va_sid == VaSubmissions.va_sid)
            .where(
                sa.and_(
                    VaSubmissions.va_form_id.in_(va_form_access),
                    VaSubmissions.va_narration_language.in_(current_user.vacode_language),
                    VaSubmissionWorkflow.workflow_state.in_(CODER_READY_POOL_STATES),
                )
            )
        )
        va_random_ready_forms = 0
        if random_form_ids:
            va_random_ready_forms = db.session.scalar(
                sa.select(sa.func.count())
                .select_from(VaSubmissions)
                .join(VaSubmissionWorkflow, VaSubmissionWorkflow.va_sid == VaSubmissions.va_sid)
                .where(
                    sa.and_(
                        VaSubmissions.va_form_id.in_(random_form_ids),
                        VaSubmissions.va_narration_language.in_(current_user.vacode_language),
                        VaSubmissionWorkflow.workflow_state.in_(CODER_READY_POOL_STATES),
                    )
                )
            )
        # Temporary: TR01 site restricted to submissions up to 2025-09-09
        if current_user.is_coder(va_form="UNSW01TR0101"):
            va_total_forms = db.session.scalar(
                sa.select(sa.func.count())
                .select_from(VaSubmissions)
                .join(VaSubmissionWorkflow, VaSubmissionWorkflow.va_sid == VaSubmissions.va_sid)
                .where(
                    sa.and_(
                        VaSubmissions.va_form_id.in_(va_form_access),
                        VaSubmissions.va_narration_language.in_(current_user.vacode_language),
                        VaSubmissionWorkflow.workflow_state.in_(CODER_READY_POOL_STATES),
                        sa.func.date(VaSubmissions.va_submission_date) <= datetime(2025, 9, 9).date(),
                    )
                )
            )
            if random_form_ids:
                va_random_ready_forms = db.session.scalar(
                    sa.select(sa.func.count())
                    .select_from(VaSubmissions)
                    .join(VaSubmissionWorkflow, VaSubmissionWorkflow.va_sid == VaSubmissions.va_sid)
                    .where(
                        sa.and_(
                            VaSubmissions.va_form_id.in_(random_form_ids),
                            VaSubmissions.va_narration_language.in_(current_user.vacode_language),
                            VaSubmissionWorkflow.workflow_state.in_(CODER_READY_POOL_STATES),
                            sa.func.date(VaSubmissions.va_submission_date) <= datetime(2025, 9, 9).date(),
                        )
                    )
                )
        pick_ready_rows = []
        if pick_form_ids:
            pick_stmt = (
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
                )
                .select_from(VaSubmissions)
                .join(VaForms, VaForms.form_id == VaSubmissions.va_form_id)
                .join(VaSubmissionWorkflow, VaSubmissionWorkflow.va_sid == VaSubmissions.va_sid)
                .where(
                    sa.and_(
                        VaSubmissions.va_form_id.in_(pick_form_ids),
                        VaSubmissions.va_narration_language.in_(current_user.vacode_language),
                        VaSubmissionWorkflow.workflow_state.in_(CODER_READY_POOL_STATES),
                    )
                )
                .order_by(VaForms.project_id, VaForms.site_id, VaSubmissions.va_submission_date, VaSubmissions.va_uniqueid_masked)
            )
            if current_user.is_coder(va_form="UNSW01TR0101"):
                pick_stmt = pick_stmt.where(
                    sa.func.date(VaSubmissions.va_submission_date) <= datetime(2025, 9, 9).date()
                )
            pick_ready_rows = [
                va_render_serialisedates(row, ["va_submission_date"])
                for row in db.session.execute(pick_stmt).mappings().all()
            ]
        va_forms_completed = get_coder_completed_count(current_user.user_id, va_form_access)
        va_forms = get_coder_completed_history(current_user.user_id, va_form_access)
        va_pick_ready_forms_count = len(pick_ready_rows)
        has_random_mode = bool(random_form_ids)
        has_pick_mode = bool(pick_form_ids)
    else:
        va_total_forms = 0
        va_random_ready_forms = 0
        va_forms_completed = 0
        va_forms = []
        pick_ready_rows = []
        va_pick_ready_forms_count = 0
        has_random_mode = False
        has_pick_mode = False

    va_has_allocation = db.session.scalar(
        sa.select(VaAllocations.va_sid).where(
            VaAllocations.va_allocated_to == current_user.user_id,
            VaAllocations.va_allocation_for == VaAllocation.coding,
            VaAllocations.va_allocation_status == VaStatuses.active,
        )
    )
    demo_projects = []
    if current_user.is_admin() and va_form_access:
        demo_projects = get_coder_project_ids(va_form_access)

    return render_template(
        "va_frontpages/va_code.html",
        va_total_forms=va_total_forms,
        va_random_ready_forms=va_random_ready_forms,
        va_pick_ready_forms_count=va_pick_ready_forms_count,
        va_forms_completed=va_forms_completed,
        va_forms=va_forms,
        pick_ready_forms=pick_ready_rows,
        has_random_mode=has_random_mode,
        has_pick_mode=has_pick_mode,
        va_has_allocation=va_has_allocation,
        va_recodeable=get_coder_recodeable_sids(current_user.user_id, va_form_access),
        is_admin=current_user.is_admin(),
        demo_projects=demo_projects,
    )
