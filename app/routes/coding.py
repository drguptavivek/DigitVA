import uuid
from datetime import datetime, timedelta
import sqlalchemy as sa
from app import db
from app.models import VaSubmissions, VaSubmissionWorkflow, VaAllocations, VaAllocation, VaStatuses, VaForms, VaSubmissionsAuditlog
from flask_login import current_user, login_required
from flask import Blueprint, render_template, url_for, redirect, request
from app.utils import va_permission_abortwithflash, va_render_serialisedates
from app.services.coder_dashboard_service import (
    get_coder_completed_count,
    get_coder_completed_history,
    get_coder_project_ids,
    get_coder_recodeable_sids,
)
from app.services.project_workflow_service import split_form_ids_by_coding_intake_mode
from app.services.submission_workflow_service import (
    CODER_READY_POOL_STATES,
    WORKFLOW_CODING_IN_PROGRESS,
    infer_workflow_state_after_coding_release,
    set_submission_workflow_state,
)
from app.services.coding_allocation_service import release_stale_coding_allocations
from app.services.final_cod_authority_service import get_authoritative_final_assessment, start_recode_episode
from app.services.coding_service import render_va_coding_page


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


def _available_coding_submission_filters(form_ids, project_id=None):
    filters = [
        VaSubmissions.va_form_id.in_(form_ids),
        VaSubmissions.va_narration_language.in_(current_user.vacode_language),
        VaSubmissionWorkflow.workflow_state.in_(CODER_READY_POOL_STATES),
    ]
    if project_id:
        filters.append(
            VaSubmissions.va_form_id.in_(
                sa.select(VaForms.form_id).where(VaForms.project_id == project_id)
            )
        )
    return filters


def _allocate_submission_for_coding(va_sid: str, audit_action: str, by_role: str):
    gen_uuid = uuid.uuid4()
    db.session.add(VaAllocations(
        va_allocation_id=gen_uuid,
        va_sid=va_sid,
        va_allocated_to=current_user.user_id,
        va_allocation_for=VaAllocation.coding,
    ))
    current_user.vacode_formcount += 1
    db.session.add(VaSubmissionsAuditlog(
        va_sid=va_sid,
        va_audit_byrole=by_role,
        va_audit_by=current_user.user_id,
        va_audit_operation="c",
        va_audit_action=audit_action,
        va_audit_entityid=gen_uuid,
    ))
    set_submission_workflow_state(
        va_sid,
        WORKFLOW_CODING_IN_PROGRESS,
        reason="coder_allocation_created",
        by_user_id=current_user.user_id,
        by_role=by_role,
    )


@coding.get("/start")
@login_required
def start():
    """Allocate a random submission and begin coding."""
    if not current_user.is_coder():
        va_permission_abortwithflash("Coder access is required.", 403)
    release_stale_coding_allocations(timeout_hours=1)
    # If already allocated, redirect to resume
    existing_sid = db.session.scalar(
        sa.select(VaAllocations.va_sid).where(
            (VaAllocations.va_allocated_to == current_user.user_id) &
            (VaAllocations.va_allocation_for == VaAllocation.coding) &
            (VaAllocations.va_allocation_status == VaStatuses.active)
        )
    )
    if existing_sid:
        return redirect(url_for("coding.resume"))
    random_form_ids, _ = split_form_ids_by_coding_intake_mode(current_user.get_coder_va_forms())
    if not random_form_ids:
        va_permission_abortwithflash("No random-allocation coding projects are available to you.", 403)
    va_new_sid = db.session.scalar(
        sa.select(VaSubmissions.va_sid)
        .join(VaSubmissionWorkflow, VaSubmissionWorkflow.va_sid == VaSubmissions.va_sid)
        .where(sa.and_(*_available_coding_submission_filters(random_form_ids)))
    )
    if current_user.is_coder(va_form="UNSW01TR0101"):
        va_new_sid = db.session.scalar(
            sa.select(VaSubmissions.va_sid)
            .join(VaSubmissionWorkflow, VaSubmissionWorkflow.va_sid == VaSubmissions.va_sid)
            .where(sa.and_(
                *_available_coding_submission_filters(random_form_ids),
                sa.func.date(VaSubmissions.va_submission_date) <= datetime(2025, 9, 9).date()
            ))
        )
    if not va_new_sid:
        va_permission_abortwithflash("No forms are available to you for VA coding.", 403)
    _allocate_submission_for_coding(va_new_sid, "form allocated to coder", "vacoder")
    db.session.commit()
    form = db.session.get(VaSubmissions, va_new_sid)
    return render_va_coding_page(form, "vacode", "vastartcoding", "coder")


@coding.get("/resume")
@login_required
def resume():
    """Resume the active coding allocation."""
    if not current_user.is_coder() and not current_user.is_admin():
        va_permission_abortwithflash("Coder access is required.", 403)
    va_sid = db.session.scalar(
        sa.select(VaAllocations.va_sid).where(
            (VaAllocations.va_allocated_to == current_user.user_id) &
            (VaAllocations.va_allocation_for == VaAllocation.coding) &
            (VaAllocations.va_allocation_status == VaStatuses.active)
        )
    )
    if not va_sid:
        va_permission_abortwithflash("No active coding allocation found.", 404)
    form = db.session.get(VaSubmissions, va_sid)
    return render_va_coding_page(form, "vacode", "varesumecoding", "coder")


@coding.get("/pick/<va_sid>")
@login_required
def pick(va_sid):
    """Pick a specific submission for coding (pick-mode projects)."""
    if current_user.vacode_formcount >= 200:
        va_permission_abortwithflash("You have reached your yearly limit of 200 coded VA forms.", 403)
    form = db.session.get(VaSubmissions, va_sid)
    if not form:
        va_permission_abortwithflash("Submission not found.", 404)
    if not current_user.has_va_form_access(form.va_form_id, "coder"):
        va_permission_abortwithflash("You do not have coder access for this VA form.", 403)
    _allocate_submission_for_coding(va_sid, "form picked by coder for coding", "vacoder")
    db.session.commit()
    return render_va_coding_page(form, "vacode", "vapickcoding", "coder")


@coding.get("/recode/<va_sid>")
@login_required
def recode(va_sid):
    """Start a recode episode for a finalized submission."""
    if not current_user.is_coder():
        va_permission_abortwithflash("Coder access is required.", 403)
    authoritative_final = get_authoritative_final_assessment(va_sid)
    if not authoritative_final:
        va_permission_abortwithflash("Only coder-finalized submissions can be reopened for recode.", 403)
    if authoritative_final.va_finassess_createdat <= (
        datetime.now(authoritative_final.va_finassess_createdat.tzinfo) - timedelta(hours=24)
    ):
        va_permission_abortwithflash("This submission is outside the recode window.", 403)
    episode = start_recode_episode(va_sid, current_user.user_id, base_final_assessment=authoritative_final)
    gen_uuid = uuid.uuid4()
    db.session.add(VaAllocations(
        va_allocation_id=gen_uuid,
        va_sid=va_sid,
        va_allocated_to=current_user.user_id,
        va_allocation_for=VaAllocation.coding,
    ))
    db.session.add(VaSubmissionsAuditlog(
        va_sid=va_sid,
        va_audit_byrole="vacoder",
        va_audit_by=current_user.user_id,
        va_audit_operation="c",
        va_audit_action="form allocated to coder for recoding",
        va_audit_entityid=gen_uuid,
    ))
    db.session.add(VaSubmissionsAuditlog(
        va_sid=va_sid,
        va_audit_byrole="vacoder",
        va_audit_by=current_user.user_id,
        va_audit_operation="c",
        va_audit_action="recode episode started",
        va_audit_entityid=episode.episode_id,
    ))
    set_submission_workflow_state(va_sid, WORKFLOW_CODING_IN_PROGRESS, reason="recode_allocation_created",
        by_user_id=current_user.user_id, by_role="vacoder")
    db.session.commit()
    return redirect(url_for("coding.resume"))


@coding.get("/demo")
@login_required
def demo():
    """Start a demo coding session (admin only)."""
    if not current_user.is_admin():
        va_permission_abortwithflash("Only admin users can start a demo coding session.", 403)
    coder_form_ids = current_user.get_coder_va_forms()
    if not coder_form_ids:
        va_permission_abortwithflash("You do not have coder access to any VA forms for demo coding.", 403)
    requested_project_id = (request.args.get("project_id") or "").strip().upper()
    if requested_project_id:
        allowed_project_ids = set(db.session.scalars(
            sa.select(VaForms.project_id).where(VaForms.form_id.in_(coder_form_ids))
        ).all())
        if requested_project_id not in allowed_project_ids:
            va_permission_abortwithflash("You do not have coder access to the selected project.", 403)
    existing_alloc = db.session.scalar(
        sa.select(VaAllocations).where(
            (VaAllocations.va_allocated_to == current_user.user_id) &
            (VaAllocations.va_allocation_for == VaAllocation.coding) &
            (VaAllocations.va_allocation_status == VaStatuses.active)
        )
    )
    released_existing_sid = None
    if existing_alloc:
        released_existing_sid = existing_alloc.va_sid
        existing_alloc.va_allocation_status = VaStatuses.deactive
        db.session.flush()
        set_submission_workflow_state(
            existing_alloc.va_sid,
            infer_workflow_state_after_coding_release(existing_alloc.va_sid),
            reason="demo_allocation_reset", by_user_id=current_user.user_id, by_role="vaadmin",
        )
        db.session.add(VaSubmissionsAuditlog(
            va_sid=existing_alloc.va_sid,
            va_audit_entityid=existing_alloc.va_allocation_id,
            va_audit_byrole="vaadmin",
            va_audit_by=current_user.user_id,
            va_audit_operation="d",
            va_audit_action="va_allocation_released_by_admin_for_demo",
        ))
    va_new_sid = db.session.scalar(
        sa.select(VaSubmissions.va_sid)
        .join(VaSubmissionWorkflow, VaSubmissionWorkflow.va_sid == VaSubmissions.va_sid)
        .where(sa.and_(*_available_coding_submission_filters(coder_form_ids, requested_project_id or None)))
        .order_by(sa.func.random())
    )
    if not va_new_sid:
        va_permission_abortwithflash("No forms are currently available for demo coding.", 403)
    gen_uuid = uuid.uuid4()
    db.session.add(VaAllocations(
        va_allocation_id=gen_uuid,
        va_sid=va_new_sid,
        va_allocated_to=current_user.user_id,
        va_allocation_for=VaAllocation.coding,
    ))
    db.session.add(VaSubmissionsAuditlog(
        va_sid=va_new_sid,
        va_audit_byrole="vaadmin",
        va_audit_by=current_user.user_id,
        va_audit_operation="c",
        va_audit_action="form allocated to admin for demo coding",
        va_audit_entityid=gen_uuid,
    ))
    set_submission_workflow_state(va_new_sid, WORKFLOW_CODING_IN_PROGRESS,
        reason="demo_coder_allocation_created", by_user_id=current_user.user_id, by_role="vaadmin")
    db.session.commit()
    if released_existing_sid:
        set_submission_workflow_state(
            released_existing_sid,
            infer_workflow_state_after_coding_release(released_existing_sid),
            reason="demo_allocation_reset_finalized",
            by_user_id=current_user.user_id, by_role="vaadmin",
        )
        db.session.commit()
    form = db.session.get(VaSubmissions, va_new_sid)
    return render_va_coding_page(form, "vacode", "vademo_start_coding", "coder")


@coding.get("/view/<va_sid>")
@login_required
def view_submission(va_sid):
    """View a completed/finalized coding submission."""
    form = db.session.get(VaSubmissions, va_sid)
    if not form:
        va_permission_abortwithflash("Submission not found.", 404)
    if not current_user.has_va_form_access(form.va_form_id, "coder"):
        va_permission_abortwithflash("You do not have coder access to view this submission.", 403)
    return render_va_coding_page(form, "vacode", "vaview", "coder")
