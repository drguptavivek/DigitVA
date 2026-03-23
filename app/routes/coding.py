import sqlalchemy as sa
from app import db
from app.models import VaSubmissions, VaSubmissionWorkflow, VaAllocations, VaAllocation, VaStatuses, VaForms
from flask_login import current_user, login_required
from flask import Blueprint, render_template, url_for, redirect, request
from app.utils import va_permission_abortwithflash, va_render_serialisedates
from app.services.coder_dashboard_service import (
    get_coder_completed_count,
    get_coder_completed_history,
    get_coder_project_ids,
    get_coder_recodeable_sids,
)
from app.services.workflow.definition import CODER_READY_POOL_STATES
from app.services.workflow.intake_modes import split_form_ids_by_coding_intake_mode
from app.services.coding_service import render_va_coding_page
from app.services.coder_workflow_service import (
    AllocationError,
    AllocationResult,
    allocate_random_form,
    allocate_pick_form,
    start_recode_allocation,
    start_demo_allocation,
    get_active_coding_allocation,
    get_pick_available_forms,
)
from datetime import datetime


coding = Blueprint("coding", __name__)


def _handle_allocation_error(e: AllocationError):
    va_permission_abortwithflash(e.message, e.status_code)


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
        pick_ready_rows = get_pick_available_forms(current_user, pick_form_ids)
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

    va_has_allocation = get_active_coding_allocation(current_user.user_id)
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


@coding.get("/start")
@login_required
def start():
    if not current_user.is_coder():
        va_permission_abortwithflash("Coder access is required.", 403)
    project_id = (request.args.get("project_id") or "").strip().upper() or None
    try:
        result = allocate_random_form(current_user, project_id=project_id)
    except AllocationError as e:
        _handle_allocation_error(e)
    if result.actiontype == "varesumecoding":
        return redirect(url_for("coding.resume"))
    form = db.session.get(VaSubmissions, result.va_sid)
    return render_va_coding_page(form, "vacode", result.actiontype, "coder")


@coding.get("/resume")
@login_required
def resume():
    if not current_user.is_coder() and not current_user.is_admin():
        va_permission_abortwithflash("Coder access is required.", 403)
    va_sid = get_active_coding_allocation(current_user.user_id)
    if not va_sid:
        va_permission_abortwithflash("No active coding allocation found.", 404)
    form = db.session.get(VaSubmissions, va_sid)
    return render_va_coding_page(form, "vacode", "varesumecoding", "coder")


@coding.get("/pick/<va_sid>")
@login_required
def pick(va_sid):
    try:
        result = allocate_pick_form(current_user, va_sid)
    except AllocationError as e:
        _handle_allocation_error(e)
    form = db.session.get(VaSubmissions, result.va_sid)
    return render_va_coding_page(form, "vacode", result.actiontype, "coder")


@coding.get("/recode/<va_sid>")
@login_required
def recode(va_sid):
    if not current_user.is_coder():
        va_permission_abortwithflash("Coder access is required.", 403)
    try:
        start_recode_allocation(current_user, va_sid)
    except AllocationError as e:
        _handle_allocation_error(e)
    return redirect(url_for("coding.resume"))


@coding.get("/demo")
@login_required
def demo():
    if not current_user.is_admin():
        va_permission_abortwithflash("Only admin users can start a demo coding session.", 403)
    project_id = (request.args.get("project_id") or "").strip().upper() or None
    try:
        result = start_demo_allocation(current_user, project_id)
    except AllocationError as e:
        _handle_allocation_error(e)
    form = db.session.get(VaSubmissions, result.va_sid)
    return render_va_coding_page(form, "vacode", result.actiontype, "coder")


@coding.get("/view/<va_sid>")
@login_required
def view_submission(va_sid):
    form = db.session.get(VaSubmissions, va_sid)
    if not form:
        va_permission_abortwithflash("Submission not found.", 404)
    if not current_user.has_va_form_access(form.va_form_id, "coder"):
        va_permission_abortwithflash("You do not have coder access to view this submission.", 403)
    return render_va_coding_page(form, "vacode", "vaview", "coder")
