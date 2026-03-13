import uuid
from flask import Blueprint, render_template, make_response, render_template_string, redirect, url_for
from flask_login import login_required, current_user
# from app.models import VaSubmissions, VaReviewerReview
# from app.decorators.va_validate_permissions import va_confirm_role
import sqlalchemy as sa
from app import db
from datetime import datetime
from app.decorators import va_validate_permissions
from app.models import VaAllocations, VaAllocation, VaStatuses, VaSubmissions, VaReviewerReview, VaInitialAssessments, VaFinalAssessments, VaCoderReview, VaSubmissionsAuditlog
from app.services.category_rendering_service import (
    get_category_rendering_service,
    get_visible_category_codes,
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
            )
    if va_action == "vacode":
        if va_actiontype == "vastartcoding":
            for record in db.session.scalars(
                sa.select(VaAllocations).where(
                    (VaAllocations.va_allocation_status == VaStatuses.active) &
                    (VaAllocations.va_allocation_for == VaAllocation.coding) &
                    (VaAllocations.va_allocation_createdat + sa.text("interval '1 hours'") < sa.func.now())
                )
            ).all():
                record.va_allocation_status = VaStatuses.deactive
                db.session.add(
                    VaSubmissionsAuditlog(
                        va_sid = record.va_sid,
                        va_audit_entityid = record.va_allocation_id,
                        va_audit_byrole = "vaadmin",
                        va_audit_operation = "d",
                        va_audit_action = "va_allocation_deletion_due to timeout",
                    )
                )
                va_initialassess = db.session.scalar(
                    sa.select(VaInitialAssessments).where(
                        (VaInitialAssessments.va_sid == record.va_sid)
                        & (VaInitialAssessments.va_iniassess_status == VaStatuses.active)
                    )
                )
                if va_initialassess:
                    va_initialassess.va_iniassess_status = VaStatuses.deactive
                    db.session.add(
                        VaSubmissionsAuditlog(
                            va_sid = va_initialassess.va_sid,
                            va_audit_entityid = va_initialassess.va_iniassess_id,
                            va_audit_byrole = "vaadmin",
                            va_audit_operation = "d",
                            va_audit_action = "va_partial_iniasses_deletion due to timeout",
                        )
                    )
            va_new_sid = db.session.scalar(sa.select(VaAllocations.va_sid).where((VaAllocations.va_allocated_to == current_user.user_id)&(VaAllocations.va_allocation_for == VaAllocation.coding)&(VaAllocations.va_allocation_status == VaStatuses.active)))
            if va_new_sid:
                return redirect(url_for('va_cta.va_calltoaction', va_action = "vacode", va_actiontype = "varesumecoding", va_sid = "varesumecoding"))
            va_inicoded_forms = db.session.scalars(
                sa.select(VaInitialAssessments.va_sid).where(
                    (VaInitialAssessments.va_iniassess_status == VaStatuses.active)
                )
            ).all()
            va_fincoded_forms = db.session.scalars(
                sa.select(VaFinalAssessments.va_sid).where(
                    (VaFinalAssessments.va_finassess_status == VaStatuses.active)
                )
            ).all()
            va_error_forms = db.session.scalars(
                sa.select(VaCoderReview.va_sid).where(
                (VaCoderReview.va_creview_status == VaStatuses.active) 
                )
            ).all()
            va_alreadyreserved = db.session.scalars(
                sa.select(VaAllocations.va_sid).where(
                    (VaAllocations.va_allocation_status == VaStatuses.active) &
                    (VaAllocations.va_allocation_for == VaAllocation.coding)
                )
            ).all()
            va_new_sid = db.session.scalar(
                sa.select(VaSubmissions.va_sid)
                .where(
                    sa.sql.and_(
                        VaSubmissions.va_form_id.in_(current_user.get_coder_va_forms()),
                        VaSubmissions.va_narration_language.in_(
                            current_user.vacode_language
                        ),
                        VaSubmissions.va_sid.notin_(va_inicoded_forms),
                        VaSubmissions.va_sid.notin_(va_fincoded_forms),
                        VaSubmissions.va_sid.notin_(va_error_forms),
                        VaSubmissions.va_sid.notin_(va_alreadyreserved),
                    )
                )
            )
            # the following is the temporary code to allow TR01 to code only old 88 forms, please remove it later
            if current_user.is_coder(va_form = "UNSW01TR0101"):
                va_new_sid = db.session.scalar(
                    sa.select(VaSubmissions.va_sid)
                    .where(
                        sa.sql.and_(
                            VaSubmissions.va_form_id.in_(current_user.get_coder_va_forms()),
                            VaSubmissions.va_narration_language.in_(
                                current_user.vacode_language
                            ),
                            VaSubmissions.va_sid.notin_(va_inicoded_forms),
                            VaSubmissions.va_sid.notin_(va_fincoded_forms),
                            VaSubmissions.va_sid.notin_(va_error_forms),
                            VaSubmissions.va_sid.notin_(va_alreadyreserved),
                            sa.func.date(VaSubmissions.va_submission_date) <= datetime(2025, 9, 9).date()
                        )
                    )
                )
            # till here, remove this part for TR01 in future
            if va_new_sid:
                gen_uuid = uuid.uuid4()
                db.session.add(
                    VaAllocations(
                        va_allocation_id = gen_uuid,
                        va_sid = va_new_sid,
                        va_allocated_to = current_user.user_id,
                        va_allocation_for = VaAllocation.coding,
                    )
                )
                current_user.vacode_formcount += 1
                db.session.add(
                VaSubmissionsAuditlog(
                    va_sid = va_new_sid,
                    va_audit_byrole = "vacoder",
                    va_audit_by = current_user.user_id,
                    va_audit_operation = "c",
                    va_audit_action = "form allocated to coder",
                    va_audit_entityid = gen_uuid
                )
            )
                db.session.commit()
            else:
                va_permission_abortwithflash(
                    "No forms are available to you for VA coding.",
                    403,
                )
        if va_actiontype == "vademo_start_coding":
            existing_alloc = db.session.scalar(
                sa.select(VaAllocations).where(
                    (VaAllocations.va_allocated_to == current_user.user_id) &
                    (VaAllocations.va_allocation_for == VaAllocation.coding) &
                    (VaAllocations.va_allocation_status == VaStatuses.active)
                )
            )
            if existing_alloc:
                existing_alloc.va_allocation_status = VaStatuses.deactive
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
            va_inicoded_forms = db.session.scalars(
                sa.select(VaInitialAssessments.va_sid).where(
                    VaInitialAssessments.va_iniassess_status == VaStatuses.active
                )
            ).all()
            va_fincoded_forms = db.session.scalars(
                sa.select(VaFinalAssessments.va_sid).where(
                    VaFinalAssessments.va_finassess_status == VaStatuses.active
                )
            ).all()
            va_error_forms = db.session.scalars(
                sa.select(VaCoderReview.va_sid).where(
                    VaCoderReview.va_creview_status == VaStatuses.active
                )
            ).all()
            va_alreadyreserved = db.session.scalars(
                sa.select(VaAllocations.va_sid).where(
                    (VaAllocations.va_allocation_status == VaStatuses.active) &
                    (VaAllocations.va_allocation_for == VaAllocation.coding)
                )
            ).all()
            va_new_sid = db.session.scalar(
                sa.select(VaSubmissions.va_sid)
                .where(
                    sa.sql.and_(
                        VaSubmissions.va_sid.notin_(va_inicoded_forms),
                        VaSubmissions.va_sid.notin_(va_fincoded_forms),
                        VaSubmissions.va_sid.notin_(va_error_forms),
                        VaSubmissions.va_sid.notin_(va_alreadyreserved),
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
            db.session.commit()
            return redirect(url_for('va_cta.va_calltoaction', va_action = "vacode", va_actiontype = "varesumecoding", va_sid = "varesumecoding"))
        if va_actiontype in ("vastartcoding", "vademo_start_coding", "varesumecoding", "vaview"):
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
            )
    return render_template_string("<h1>Invalid route</h1>")
