import uuid
from flask import Blueprint, render_template, make_response, render_template_string, redirect, request, url_for
from flask_login import login_required, current_user
# from app.models import VaSubmissions, VaReviewerReview
# from app.decorators.va_validate_permissions import va_confirm_role
import sqlalchemy as sa
from app import db
from datetime import datetime
from app.decorators import va_validate_permissions
from app.models import VaAllocations, VaAllocation, VaStatuses, VaSubmissions, VaReviewerReview, VaInitialAssessments, VaFinalAssessments, VaCoderReview, VaSubmissionsAuditlog, VaForms
from app.models.va_submission_workflow import VaSubmissionWorkflow
from app.services.coding_allocation_service import release_stale_coding_allocations
from app.services.category_rendering_service import (
    get_category_rendering_service,
    get_visible_category_codes,
)
from app.services.project_workflow_service import (
    split_form_ids_by_coding_intake_mode,
)
from app.services.submission_workflow_service import (
    CODER_READY_POOL_STATES,
    WORKFLOW_CODING_IN_PROGRESS,
    infer_workflow_state_after_coding_release,
    set_submission_workflow_state,
)
from app.utils import va_get_form_type_code_for_form, va_permission_abortwithflash

va_cta = Blueprint("va_cta", __name__)


def _get_category_render_context(va_form, va_action: str) -> tuple[list, str | None]:
    form_type_code = va_get_form_type_code_for_form(va_form.va_form_id)
    category_service = get_category_rendering_service()
    visible_codes = get_visible_category_codes(va_form.va_data, va_form.va_form_id)
    category_nav = category_service.get_category_nav(
        form_type_code,
        va_action,
        visible_codes,
    )
    default_category_code = category_service.get_default_category_code(
        form_type_code,
        va_action,
        visible_codes,
    )
    return category_nav, default_category_code, visible_codes


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
    db.session.add(
        VaAllocations(
            va_allocation_id=gen_uuid,
            va_sid=va_sid,
            va_allocated_to=current_user.user_id,
            va_allocation_for=VaAllocation.coding,
        )
    )
    current_user.vacode_formcount += 1
    db.session.add(
        VaSubmissionsAuditlog(
            va_sid=va_sid,
            va_audit_byrole=by_role,
            va_audit_by=current_user.user_id,
            va_audit_operation="c",
            va_audit_action=audit_action,
            va_audit_entityid=gen_uuid,
        )
    )
    set_submission_workflow_state(
        va_sid,
        WORKFLOW_CODING_IN_PROGRESS,
        reason="coder_allocation_created",
        by_user_id=current_user.user_id,
        by_role=by_role,
    )

@va_cta.route("/<va_action>/<va_actiontype>/<va_sid>")
@login_required
@va_validate_permissions()
def va_calltoaction(va_action, va_actiontype, va_sid):
    if va_action == "vareview":
        if va_actiontype == "vastartreviewing":
            gen_uuid = uuid.uuid4()
            db.session.add(
                VaAllocations(
                    va_allocation_id = gen_uuid,
                    va_sid = va_sid,
                    va_allocated_to = current_user.user_id,
                    va_allocation_for = VaAllocation.reviewing,
                )
            )
            db.session.add(
                VaSubmissionsAuditlog(
                    va_sid = va_sid,
                    va_audit_byrole = "vacoder",
                    va_audit_by = current_user.user_id,
                    va_audit_operation = "c",
                    va_audit_action = "form allocated to coder",
                    va_audit_entityid = gen_uuid
                )
            )
            db.session.commit()
        if va_actiontype == "varesumereviewing":
            va_has_allocation = db.session.scalar(sa.select(VaAllocations.va_sid).where((VaAllocations.va_allocated_to == current_user.user_id)&(VaAllocations.va_allocation_for == VaAllocation.reviewing)&(VaAllocations.va_allocation_status == VaStatuses.active)))
        if va_actiontype == "vastartreviewing" or va_actiontype == "varesumereviewing" or va_actiontype == "vaview":
            va_form = db.session.get(VaSubmissions, va_has_allocation if va_actiontype == "varesumereviewing" else va_sid)
            category_nav, default_category_code, visible_codes = _get_category_render_context(
                va_form,
                va_action,
            )
            return render_template(
                "va_frontpages/va_coding.html",
                va_sid = va_has_allocation if va_actiontype == "varesumereviewing" else va_sid,
                va_action = va_action,
                va_actiontype= va_actiontype,
                catlist = visible_codes,
                category_nav = category_nav,
                default_category_code = default_category_code,
                catcount = va_form.va_catcount,
                form_type_code = va_get_form_type_code_for_form(va_form.va_form_id),
                va_uniqueid = va_form.va_uniqueid_masked,
                va_age = va_form.va_deceased_age,
                va_gender = va_form.va_deceased_gender,
                back_dashboard_role = "reviewer",
            )
    if va_action == "vacode":
        if va_actiontype == "vastartcoding":
            release_stale_coding_allocations(timeout_hours=1)
            va_new_sid = db.session.scalar(sa.select(VaAllocations.va_sid).where((VaAllocations.va_allocated_to == current_user.user_id)&(VaAllocations.va_allocation_for == VaAllocation.coding)&(VaAllocations.va_allocation_status == VaStatuses.active)))
            if va_new_sid:
                return redirect(url_for('va_cta.va_calltoaction', va_action = "vacode", va_actiontype = "varesumecoding", va_sid = "varesumecoding"))
            random_form_ids, _ = split_form_ids_by_coding_intake_mode(
                current_user.get_coder_va_forms()
            )
            if not random_form_ids:
                va_permission_abortwithflash(
                    "No random-allocation coding projects are available to you.",
                    403,
                )
            va_new_sid = db.session.scalar(
                sa.select(VaSubmissions.va_sid)
                .join(
                    VaSubmissionWorkflow,
                    VaSubmissionWorkflow.va_sid == VaSubmissions.va_sid,
                )
                .where(
                    sa.sql.and_(
                        *_available_coding_submission_filters(
                            random_form_ids
                        ),
                    )
                )
            )
            # the following is the temporary code to allow TR01 to code only old 88 forms, please remove it later
            if current_user.is_coder(va_form = "UNSW01TR0101"):
                va_new_sid = db.session.scalar(
                    sa.select(VaSubmissions.va_sid)
                    .join(
                        VaSubmissionWorkflow,
                        VaSubmissionWorkflow.va_sid == VaSubmissions.va_sid,
                    )
                    .where(
                        sa.sql.and_(
                            *_available_coding_submission_filters(
                                random_form_ids
                            ),
                            sa.func.date(VaSubmissions.va_submission_date) <= datetime(2025, 9, 9).date()
                        )
                    )
                )
            # till here, remove this part for TR01 in future
            if va_new_sid:
                _allocate_submission_for_coding(
                    va_new_sid,
                    audit_action="form allocated to coder",
                    by_role="vacoder",
                )
                db.session.commit()
            else:
                va_permission_abortwithflash(
                    "No forms are available to you for VA coding.",
                    403,
                )
        if va_actiontype == "vapickcoding":
            _allocate_submission_for_coding(
                va_sid,
                audit_action="form picked by coder for coding",
                by_role="vacoder",
            )
            db.session.commit()
            va_new_sid = va_sid
        if va_actiontype == "vademo_start_coding":
            coder_form_ids = current_user.get_coder_va_forms()
            if not coder_form_ids:
                va_permission_abortwithflash(
                    "You do not have coder access to any VA forms for demo coding.",
                    403,
                )

            requested_project_id = (request.args.get("project_id") or "").strip().upper()
            if requested_project_id:
                allowed_project_ids = set(
                    db.session.scalars(
                        sa.select(VaForms.project_id).where(
                            VaForms.form_id.in_(coder_form_ids)
                        )
                    ).all()
                )
                if requested_project_id not in allowed_project_ids:
                    va_permission_abortwithflash(
                        "You do not have coder access to the selected project.",
                        403,
                    )
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
                    reason="demo_allocation_reset",
                    by_user_id=current_user.user_id,
                    by_role="vaadmin",
                )
                db.session.add(
                    VaSubmissionsAuditlog(
                        va_sid=existing_alloc.va_sid,
                        va_audit_entityid=existing_alloc.va_allocation_id,
                        va_audit_byrole="vaadmin",
                        va_audit_by=current_user.user_id,
                        va_audit_operation="d",
                        va_audit_action="va_allocation_released_by_admin_for_demo",
                    )
                )
            va_new_sid = db.session.scalar(
                sa.select(VaSubmissions.va_sid)
                .join(
                    VaSubmissionWorkflow,
                    VaSubmissionWorkflow.va_sid == VaSubmissions.va_sid,
                )
                .where(
                    sa.sql.and_(
                        *_available_coding_submission_filters(
                            coder_form_ids,
                            requested_project_id or None,
                        ),
                    )
                )
                .order_by(sa.func.random())
            )
            if va_new_sid:
                gen_uuid = uuid.uuid4()
                db.session.add(
                    VaAllocations(
                        va_allocation_id=gen_uuid,
                        va_sid=va_new_sid,
                        va_allocated_to=current_user.user_id,
                        va_allocation_for=VaAllocation.coding,
                    )
                )
                db.session.add(
                    VaSubmissionsAuditlog(
                        va_sid=va_new_sid,
                        va_audit_byrole="vaadmin",
                        va_audit_by=current_user.user_id,
                        va_audit_operation="c",
                        va_audit_action="form allocated to admin for demo coding",
                        va_audit_entityid=gen_uuid,
                    )
                )
                set_submission_workflow_state(
                    va_new_sid,
                    WORKFLOW_CODING_IN_PROGRESS,
                    reason="demo_coder_allocation_created",
                    by_user_id=current_user.user_id,
                    by_role="vaadmin",
                )
                db.session.commit()
                if released_existing_sid:
                    set_submission_workflow_state(
                        released_existing_sid,
                        infer_workflow_state_after_coding_release(released_existing_sid),
                        reason="demo_allocation_reset_finalized",
                        by_user_id=current_user.user_id,
                        by_role="vaadmin",
                    )
                    db.session.commit()
            else:
                va_permission_abortwithflash(
                    "No forms are currently available for demo coding.",
                    403,
                )
        if va_actiontype == "varesumecoding":
            va_new_sid = db.session.scalar(sa.select(VaAllocations.va_sid).where((VaAllocations.va_allocated_to == current_user.user_id)&(VaAllocations.va_allocation_for == VaAllocation.coding)&(VaAllocations.va_allocation_status == VaStatuses.active)))
        if va_actiontype == "varecode":
            va_initialassess = db.session.scalar(
                    sa.select(VaInitialAssessments).where(
                        (VaInitialAssessments.va_sid == va_sid)
                        & (VaInitialAssessments.va_iniassess_status == VaStatuses.active)
                    )
                )
            if va_initialassess:
                va_initialassess.va_iniassess_status = VaStatuses.deactive
                db.session.add(
                    VaSubmissionsAuditlog(
                        va_sid = va_initialassess.va_sid,
                        va_audit_entityid = va_initialassess.va_iniassess_id,
                        va_audit_by = current_user.user_id,
                        va_audit_byrole = "vacoder",
                        va_audit_operation = "d",
                        va_audit_action = "va_partial_iniasses_deletion due to recode",
                    )
                )
            va_finassess = db.session.scalar(
                    sa.select(VaFinalAssessments).where(
                        (VaFinalAssessments.va_sid == va_sid)
                        & (VaFinalAssessments.va_finassess_status == VaStatuses.active)
                    )
                )
            if va_finassess:
                va_finassess.va_finassess_status = VaStatuses.deactive
                db.session.add(
                    VaSubmissionsAuditlog(
                        va_sid = va_finassess.va_sid,
                        va_audit_entityid = va_finassess.va_finassess_id,
                        va_audit_by = current_user.user_id,
                        va_audit_byrole = "vacoder",
                        va_audit_operation = "d",
                        va_audit_action = "va_partial_finassess_deletion due to recode",
                    )
                )
            va_coderreview = db.session.scalar(
                    sa.select(VaCoderReview).where(
                        (VaCoderReview.va_sid == va_sid)
                        & (VaCoderReview.va_creview_status == VaStatuses.active)
                    )
                )
            if va_coderreview:
                va_coderreview.va_creview_status = VaStatuses.deactive
                db.session.add(
                    VaSubmissionsAuditlog(
                        va_sid = va_coderreview.va_sid,
                        va_audit_entityid = va_coderreview.va_creview_id,
                        va_audit_by = current_user.user_id,
                        va_audit_byrole = "vacoder",
                        va_audit_operation = "d",
                        va_audit_action = "va_partial_coder review_deletion due to recode",
                    )
                )
            gen_uuid = uuid.uuid4()
            db.session.add(
                VaAllocations(
                    va_allocation_id = gen_uuid,
                    va_sid = va_sid,
                    va_allocated_to = current_user.user_id,
                    va_allocation_for = VaAllocation.coding,
                )
            )
            db.session.add(
                VaSubmissionsAuditlog(
                    va_sid = va_sid,
                    va_audit_byrole = "vacoder",
                    va_audit_by = current_user.user_id,
                    va_audit_operation = "c",
                    va_audit_action = "form allocated to coder for recoding",
                    va_audit_entityid = gen_uuid
                )
            )
            set_submission_workflow_state(
                va_sid,
                WORKFLOW_CODING_IN_PROGRESS,
                reason="recode_allocation_created",
                by_user_id=current_user.user_id,
                by_role="vacoder",
            )
            db.session.commit()
            return redirect(url_for('va_cta.va_calltoaction', va_action = "vacode", va_actiontype = "varesumecoding", va_sid = "varesumecoding"))
        if va_actiontype in ("vastartcoding", "vapickcoding", "vademo_start_coding", "varesumecoding", "vaview"):
            va_form = db.session.get(VaSubmissions, va_sid if va_actiontype == "vaview" else va_new_sid)
            category_nav, default_category_code, visible_codes = _get_category_render_context(
                va_form,
                va_action,
            )
            return render_template(
                "va_frontpages/va_coding.html",
                va_sid = va_sid if va_actiontype == "vaview" else va_new_sid,
                va_action = va_action,
                va_actiontype= va_actiontype,
                catlist = visible_codes,
                category_nav = category_nav,
                default_category_code = default_category_code,
                catcount = va_form.va_catcount,
                form_type_code = va_get_form_type_code_for_form(va_form.va_form_id),
                va_uniqueid = va_form.va_uniqueid_masked,
                va_age = va_form.va_deceased_age,
                va_gender = va_form.va_deceased_gender,
                back_dashboard_role = "coder",
            )
    if va_action == "vadata":
        if va_actiontype == "vaview":
            va_form = db.session.get(VaSubmissions, va_sid)
            category_nav, default_category_code, visible_codes = _get_category_render_context(
                va_form,
                va_action,
            )
            return render_template(
                "va_frontpages/va_coding.html",
                va_sid=va_sid,
                va_action=va_action,
                va_actiontype=va_actiontype,
                catlist=visible_codes,
                category_nav=category_nav,
                default_category_code=default_category_code,
                catcount=va_form.va_catcount,
                form_type_code=va_get_form_type_code_for_form(va_form.va_form_id),
                va_uniqueid=va_form.va_uniqueid_masked,
                va_age=va_form.va_deceased_age,
                va_gender=va_form.va_deceased_gender,
                back_dashboard_role="data_manager",
            )
    return render_template_string("<h1>Invalid route</h1>")
