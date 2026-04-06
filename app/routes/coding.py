import sqlalchemy as sa
from app import db
from app.models import VaSubmissions, VaSubmissionWorkflow, VaAllocations, VaAllocation, VaStatuses, VaForms
from flask_login import current_user
from flask import Blueprint, render_template, url_for, redirect, request
from app.decorators import role_required
from app.utils import va_permission_abortwithflash, va_render_serialisedates
from app.services.coder_dashboard_service import (
    get_coder_completed_count,
    get_coder_completed_history,
    get_coder_recodeable_sids,
)
from app.services.workflow.definition import CODER_READY_POOL_STATES
from app.services.workflow.intake_modes import split_form_ids_by_coding_intake_mode
from app.services.coding_service import render_va_coding_page
from app.services.coder_workflow_service import (
    AllocationError,
    AllocationResult,
    _narration_language_filter,
    allocate_random_form,
    allocate_pick_form,
    start_recode_allocation,
    start_demo_allocation,
    get_active_coding_allocation,
    get_pick_available_forms,
)
from app.services.demo_project_service import should_use_demo_actiontype_for_submission
from app.services.demo_project_service import get_demo_training_project_ids
from datetime import datetime


coding = Blueprint("coding", __name__)


def _handle_allocation_error(e: AllocationError):
    va_permission_abortwithflash(e.message, e.status_code)


@coding.get("/")
@role_required("coder", "admin")
def dashboard():
    va_form_access = current_user.get_coder_va_forms()
    if va_form_access:
        narration_language_filter = _narration_language_filter(current_user)
        random_form_ids, pick_form_ids = split_form_ids_by_coding_intake_mode(va_form_access)
        total_filters = [
            VaSubmissions.va_form_id.in_(va_form_access),
            VaSubmissionWorkflow.workflow_state.in_(CODER_READY_POOL_STATES),
        ]
        if narration_language_filter is not None:
            total_filters.append(narration_language_filter)
        va_total_forms = db.session.scalar(
            sa.select(sa.func.count())
            .select_from(VaSubmissions)
            .join(VaSubmissionWorkflow, VaSubmissionWorkflow.va_sid == VaSubmissions.va_sid)
            .where(sa.and_(*total_filters))
        )
        va_random_ready_forms = 0
        if random_form_ids:
            random_filters = [
                VaSubmissions.va_form_id.in_(random_form_ids),
                VaSubmissionWorkflow.workflow_state.in_(CODER_READY_POOL_STATES),
            ]
            if narration_language_filter is not None:
                random_filters.append(narration_language_filter)
            va_random_ready_forms = db.session.scalar(
                sa.select(sa.func.count())
                .select_from(VaSubmissions)
                .join(VaSubmissionWorkflow, VaSubmissionWorkflow.va_sid == VaSubmissions.va_sid)
                .where(sa.and_(*random_filters))
            )
        # Temporary: TR01 site restricted to submissions up to 2025-09-09
        if current_user.is_coder(va_form="UNSW01TR0101"):
            tr_total_filters = [
                VaSubmissions.va_form_id.in_(va_form_access),
                VaSubmissionWorkflow.workflow_state.in_(CODER_READY_POOL_STATES),
                sa.func.date(VaSubmissions.va_submission_date) <= datetime(2025, 9, 9).date(),
            ]
            if narration_language_filter is not None:
                tr_total_filters.append(narration_language_filter)
            va_total_forms = db.session.scalar(
                sa.select(sa.func.count())
                .select_from(VaSubmissions)
                .join(VaSubmissionWorkflow, VaSubmissionWorkflow.va_sid == VaSubmissions.va_sid)
                .where(sa.and_(*tr_total_filters))
            )
            if random_form_ids:
                tr_random_filters = [
                    VaSubmissions.va_form_id.in_(random_form_ids),
                    VaSubmissionWorkflow.workflow_state.in_(CODER_READY_POOL_STATES),
                    sa.func.date(VaSubmissions.va_submission_date) <= datetime(2025, 9, 9).date(),
                ]
                if narration_language_filter is not None:
                    tr_random_filters.append(narration_language_filter)
                va_random_ready_forms = db.session.scalar(
                    sa.select(sa.func.count())
                    .select_from(VaSubmissions)
                    .join(VaSubmissionWorkflow, VaSubmissionWorkflow.va_sid == VaSubmissions.va_sid)
                    .where(sa.and_(*tr_random_filters))
                )
        pick_ready_rows = get_pick_available_forms(current_user, pick_form_ids)
        va_forms_completed = get_coder_completed_count(current_user.user_id, va_form_access)
        va_forms = get_coder_completed_history(current_user.user_id, va_form_access)
        va_pick_ready_forms_count = len(pick_ready_rows)
        has_random_mode = bool(random_form_ids)
        has_pick_mode = bool(pick_form_ids)
        from app.models import VaSites, VaResearchProjects  # noqa: PLC0415
        eligibility_rows = db.session.execute(
            sa.select(
                VaResearchProjects.project_nickname,
                VaSites.site_name,
                VaSites.site_abbr,
                VaForms.form_id,
            )
            .join(VaSites, VaSites.site_id == VaForms.site_id)
            .join(VaResearchProjects, VaResearchProjects.project_id == VaForms.project_id)
            .where(VaForms.form_id.in_(va_form_access))
            .order_by(VaResearchProjects.project_id, VaSites.site_id)
        ).all()
        coder_eligibility = [
            {"project": r.project_nickname, "site": r.site_name, "site_abbr": r.site_abbr, "form_id": r.form_id}
            for r in eligibility_rows
        ]
        coder_languages = sorted(current_user.vacode_language or [])
    else:
        va_total_forms = 0
        va_random_ready_forms = 0
        va_forms_completed = 0
        va_forms = []
        pick_ready_rows = []
        va_pick_ready_forms_count = 0
        has_random_mode = False
        has_pick_mode = False
        coder_eligibility = []
        coder_languages = []

    va_has_allocation = get_active_coding_allocation(current_user.user_id)
    demo_projects = []
    if va_form_access:
        demo_projects = get_demo_training_project_ids(va_form_access)

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
        coder_eligibility=coder_eligibility,
        coder_languages=coder_languages,
    )


@coding.post("/start")
@role_required("coder", "admin")
def start():
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
@role_required("coder", "admin")
def resume():
    va_sid = get_active_coding_allocation(current_user.user_id)
    if not va_sid:
        va_permission_abortwithflash("No active coding allocation found.", 404)
    form = db.session.get(VaSubmissions, va_sid)
    actiontype = (
        "vademo_start_coding"
        if should_use_demo_actiontype_for_submission(va_sid)
        else "varesumecoding"
    )
    return render_va_coding_page(form, "vacode", actiontype, "coder")


@coding.post("/pick/<va_sid>")
@role_required("coder")
def pick(va_sid):
    try:
        result = allocate_pick_form(current_user, va_sid)
    except AllocationError as e:
        _handle_allocation_error(e)
    form = db.session.get(VaSubmissions, result.va_sid)
    return render_va_coding_page(form, "vacode", result.actiontype, "coder")


@coding.post("/recode/<va_sid>")
@role_required("coder")
def recode(va_sid):
    try:
        start_recode_allocation(current_user, va_sid)
    except AllocationError as e:
        _handle_allocation_error(e)
    return redirect(url_for("coding.resume"))


@coding.post("/demo")
@role_required("admin")
def demo():
    project_id = (request.args.get("project_id") or "").strip().upper() or None
    try:
        result = start_demo_allocation(current_user, project_id)
    except AllocationError as e:
        _handle_allocation_error(e)
    form = db.session.get(VaSubmissions, result.va_sid)
    return render_va_coding_page(form, "vacode", result.actiontype, "coder")


@coding.get("/view/<va_sid>")
@role_required("coder", "admin")
def view_submission(va_sid):
    form = db.session.get(VaSubmissions, va_sid)
    if not form:
        va_permission_abortwithflash("Submission not found.", 404)
    if not current_user.has_va_form_access(form.va_form_id, "coder"):
        va_permission_abortwithflash("You do not have coder access to view this submission.", 403)
    return render_va_coding_page(form, "vacode", "vaview", "coder")
