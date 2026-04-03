from app import db
import sqlalchemy as sa
from flask_login import current_user
from flask import jsonify, render_template, url_for, flash, request
from app.models import (
    VaAllocations,
    VaAllocation,
    VaCoderReview,
    VaFinalAssessments,
    VaInitialAssessments,
    VaReviewerReview,
    VaSmartvaResults,
    VaStatuses,
    VaSubmissions,
    VaSubmissionsAuditlog,
    VaUsernotes,
)
from app.utils import (
    va_get_form_type_code_for_form,
    va_mapping_fieldcoder,
    va_render_processcategorydata,
)
from app.services.category_rendering_service import (
    get_category_rendering_service,
    get_visible_category_codes,
)
from app.services.field_mapping_service import get_mapping_service
from app.services.submission_payload_version_service import get_active_payload_version


VA_RENDER_FOR_ALL = set(
    "vainterviewdetails|vademographicdetails|vaneonatalperioddetails|vainjuriesdetails|vahealthhistorydetails|vageneralsymptoms|varespiratorycardiacsymptoms|vaabdominalsymptoms|vaneurologicalsymptoms|vaskinmucosalsymptoms|vaneonatalfeedingsymptoms|vamaternalsymptoms|vahealthserviceutilisation|vanarrationanddocuments".split(
        "|"
    )
)

ADULT_CHOICES = [
    item.strip()
    for item in "I10 - Essential Hypertension|E11 - Type 2 Diabetes Mellitus|E10 - Type 1 Diabetes Mellitus|E66 - Obesity|N18 - Chronic Kidney Disease|K74 - Chronic Liver Disease|J44 - Chronic Obstructive Pulmonary Disease|J45 - Asthma|E78 - Dyslipidemia|I50 - Congestive Heart Failure|I25 - Coronary Artery Disease|D64 - Chronic Anaemia|F03 - Dementia|I25.2 - Previous Myocardial Infarction|I69 - Previous Stroke/CVA|C80 - Cancer (non-primary, metastasis, history)|B24 - HIV/AIDS|Z86.1 - Past history of tuberculosis|D89 - Immunosuppression|E03 - Hypothyroidism|E05 - Hyperthyroidism|B18 - Chronic Viral Infections (Hepatitis)|I73.9 - Peripheral Vascular Disease|I09 - Chronic Rheumatic Heart Disease|Z98.8 - History of Major Surgery|Z79.3 - Long-term use of Immunosuppressants".split(
        "|"
    )
]

NEONATE_CHOICES = [
    item.strip()
    for item in "P07 - Preterm birth|P07.0, P07.1 - Low Birth Weight|P05 - Intrauterine Growth Restriction|P21 - Birth Asphyxia|P36 - Neonatal Sepsis|P23 - Neonatal Pneumonia|P22 - Hyaline Membrane Disease / Respiratory Distress Syndrome|P24.0 - Meconium Aspiration Syndrome|P59 - Neonatal Jaundice|P90 - Neonatal Convulsions|P91.6 - Hypoxic Ischemic Encephalopathy|P80 - Hypothermia of Newborn|P70.4 - Hypoglycemia of Newborn|P52 - Neonatal Hemorrhage|Q20 - Q28 - Congenital Heart Disease|Q00 - Q99 - Congenital Malformations|Q90 - Chromosomal Abnormalities|A33 - Neonatal Tetanus|P37.9 - Neonatal Meningitis|P77 - Necrotizing Enterocolitis|P00.1 - Maternal Diabetes|P00.0 - Maternal Hypertension|P02.7 - Chorioamnionitis|P01.5 - Twin/Multiple Gestation|P35, P37 - Congenital Infections (TORCH)|P58, P59 - Hyperbilirubinemia|P92 - Feeding Problems of Newborn|P04 - Maternal drug use affecting newborn".split(
        "|"
    )
]

CHILDREN_CHOICES = [
    item.strip()
    for item in "J06, J20, J21 - Acute Respiratory Infections|J45 - Asthma|D50 - D53 - Anemia|E40 - E46 - Malnutrition|E66 - Obesity|E10, E11 - Diabetes Mellitus (Type 1/2)|G40 - Epilepsy|Q20 - Q28 - Congenital Heart Disease|D57 - Sickle Cell Disease|D56 - Thalassemia|Q90 - Down Syndrome|E84 - Cystic Fibrosis|N18, N04 - Renal Disease|A15 - A19 - Tuberculosis|B20 - B24 - HIV/AIDS|D80 - D89 - Immunodeficiency|I05 - I09 - Rheumatic Heart Disease|G80 - Cerebral Palsy|F84 - Autism Spectrum Disorders|F70 - F79 - Intellectual Disability|C91 - C95, C81 - C85, C00 - C80 - Cancer|D57.3 - Sickle Cell Trait|D56.3 - Thalassemia Trait|Z98.8 - Previous Major Surgery|P07 - History of Prematurity/Low Birth Weight|Z28.3 - Incomplete immunization Status".split(
        "|"
    )
]

AGE_LABEL_TO_CHOICES = {
    "isAdult": ADULT_CHOICES,
    "isChild": CHILDREN_CHOICES,
    "isNeonate": NEONATE_CHOICES,
}


def _scalar(select_stmt):
    return db.session.scalar(select_stmt)


def va_get_render_datalevel(va_action, form_type_code, visible_category_codes=None):
    """
    Return category mapping for the requested action.

    Coder/reviewer views stay on the legacy static coder mapping where it exists.
    For coder-visible categories introduced in DB config but absent from the static
    dict (for example `social_autopsy`), fall back to the DB-backed mapping so the
    panel does not render empty.
    """
    mapping_svc = get_mapping_service()
    if va_action not in {"vacode", "vareview"}:
        return mapping_svc.get_fieldsitepi(form_type_code)

    merged_mapping = dict(va_mapping_fieldcoder)
    db_mapping = mapping_svc.get_fieldsitepi(form_type_code)
    category_svc = get_category_rendering_service()

    for category_code, category_mapping in db_mapping.items():
        if category_code in merged_mapping:
            continue
        if category_svc.is_category_enabled(
            form_type_code,
            va_action,
            visible_category_codes,
            category_code,
        ):
            merged_mapping[category_code] = category_mapping

    return merged_mapping


def va_get_category_context(va_sid, va_action, va_partial):
    submission = db.session.get(VaSubmissions, va_sid)
    if not submission:
        return None

    active_version = get_active_payload_version(va_sid)
    payload_data = active_version.payload_data if active_version else None

    form_type_code = va_get_form_type_code_for_form(submission.va_form_id)

    mapping_svc = get_mapping_service()

    visible_category_codes = get_visible_category_codes(
        payload_data,
        submission.va_form_id,
    )
    datalevel = va_get_render_datalevel(
        va_action,
        form_type_code,
        visible_category_codes,
    )
    va_mapping_choice = mapping_svc.get_choices(form_type_code)
    va_mapping_flip = mapping_svc.get_flip_labels(form_type_code)
    va_mapping_info = mapping_svc.get_info_labels(form_type_code)

    processed = va_render_processcategorydata(
        payload_data,
        submission.va_form_id,
        datalevel,
        va_mapping_choice,
        va_partial,
    )
    previous_category, next_category = category_service.get_category_neighbours(
        form_type_code,
        va_action,
        visible_category_codes,
        va_partial,
    )
    if va_partial == "vanarrationanddocuments":
        active = lambda model, status: _scalar(  # noqa: E731
            sa.select(model).where(status == VaStatuses.active, model.va_sid == va_sid)
        )
        inactive = lambda model, status, user: _scalar(  # noqa: E731
            sa.select(model).where(
                status == VaStatuses.deactive,
                model.va_sid == va_sid,
                user == current_user.user_id,
            )
        )
        final_assess = active(VaFinalAssessments, VaFinalAssessments.va_finassess_status)
        initial_assess = active(
            VaInitialAssessments, VaInitialAssessments.va_iniassess_status
        )
        coder_review = active(VaCoderReview, VaCoderReview.va_creview_status)
        return {
            "submission": submission,
            "processed_data": processed,
            "previous_category": previous_category,
            "next_category": next_category,
            "mapping_flip": va_mapping_flip,
            "mapping_info": va_mapping_info,
            "review": active(VaReviewerReview, VaReviewerReview.va_rreview_status),
            "final_exists": bool(final_assess),
            "coder_exists": bool(coder_review),
            "initial_exists": bool(initial_assess),
            "final_assess": final_assess,
            "initial_assess": initial_assess,
            "coder_review": coder_review,
            "smartva": active(VaSmartvaResults, VaSmartvaResults.va_smartva_status),
            "inactive_final": inactive(
                VaFinalAssessments,
                VaFinalAssessments.va_finassess_status,
                VaFinalAssessments.va_finassess_by,
            ),
            "inactive_initial": inactive(
                VaInitialAssessments,
                VaInitialAssessments.va_iniassess_status,
                VaInitialAssessments.va_iniassess_by,
            ),
            "inactive_coder": inactive(
                VaCoderReview,
                VaCoderReview.va_creview_status,
                VaCoderReview.va_creview_by,
            ),
        }
    else:
        return {
            "submission": submission,
            "processed_data": processed,
            "previous_category": previous_category,
            "next_category": next_category,
            "mapping_flip": va_mapping_flip,
            "mapping_info": va_mapping_info,
        }
        


def va_render_category_partial(context, va_action, va_actiontype, va_sid, va_partial):
    submission = context["submission"]
    if va_partial == "vanarrationanddocuments":
        return render_template(
            f"va_formcategory_partials/{va_partial}.html",
            instance_name=submission.va_uniqueid_masked,
            category_data=context["processed_data"],
            va_previouscategory=context["previous_category"],
            va_nextcategory=context["next_category"],
            flip_list=context["mapping_flip"],
            info_list=context["mapping_info"],
            va_action=va_action,
            va_actiontype=va_actiontype,
            va_sid=va_sid,
            va_partial=va_partial,
            summary=submission.va_summary,
            reviewobject=context["review"],
            vafinexists=context["final_exists"],
            vaerrexists=context["coder_exists"],
            vainiexists=context["initial_exists"],
            va_final_assess=context["final_assess"],
            va_initial_assess=context["initial_assess"],
            va_coder_review=context["coder_review"],
            smartva=context["smartva"],
            da_va_final_assess=context["inactive_final"],
            da_va_initial_assess=context["inactive_initial"],
            da_va_coder_review=context["inactive_coder"],
        )
    else:
        return render_template(
            f"va_formcategory_partials/{va_partial}.html",
            instance_name=submission.va_uniqueid_masked,
            category_data=context["processed_data"],
            va_previouscategory=context["previous_category"],
            va_nextcategory=context["next_category"],
            flip_list=context["mapping_flip"],
            info_list=context["mapping_info"],
            va_action=va_action,
            va_actiontype=va_actiontype,
            va_sid=va_sid,
            va_partial=va_partial,
        )


def va_log_submission_action(va_sid, role, action, entity_id, operation="c"):
    db.session.add(
        VaSubmissionsAuditlog(
            va_sid=va_sid,
            va_audit_byrole=role,
            va_audit_by=current_user.user_id,
            va_audit_operation=operation,
            va_audit_action=action,
            va_audit_entityid=entity_id,
        )
    )


def va_deactivate_allocation(user_id, allocation_for):
    allocation = _scalar(
        sa.select(VaAllocations).where(
            VaAllocations.va_allocated_to == user_id,
            VaAllocations.va_allocation_for == allocation_for,
            VaAllocations.va_allocation_status == VaStatuses.active,
        )
    )
    if allocation:
        allocation.va_allocation_status = VaStatuses.deactive
    return allocation


def va_handle_htmx_redirect(route_name, va_role, message):
    response = jsonify(success=True)
    response.headers["HX-Redirect"] = url_for(route_name, va_role=va_role)
    flash(message, "success")
    return response


def va_request_is_htmx():
    return bool(request.headers.get("HX-Request"))


def va_get_age_labels(va_sid):
    active_version = get_active_payload_version(va_sid)
    payload_data = active_version.payload_data if active_version else {}
    return {
        "isNeonatal": payload_data.get("isNeonatal"),
        "isChild": payload_data.get("isChild"),
        "isAdult": payload_data.get("isAdult"),
    }


def va_assign_other_condition_choices(form, agelabels):
    for label, choices in AGE_LABEL_TO_CHOICES.items():
        value = agelabels.get(label)
        if value is not None and str(value).strip() in {"1", "1.0"}:
            form.va_other_conditions.choices = choices
            return choices
    form.va_other_conditions.choices = ADULT_CHOICES
    return ADULT_CHOICES


def va_get_active_initial_assessment(va_sid):
    return _scalar(
        sa.select(VaInitialAssessments).where(
            VaInitialAssessments.va_iniassess_status == VaStatuses.active,
            VaInitialAssessments.va_sid == va_sid,
        )
    )


def va_get_active_smartva_result(va_sid):
    return _scalar(
        sa.select(VaSmartvaResults).where(
            VaSmartvaResults.va_sid == va_sid,
            VaSmartvaResults.va_smartva_status == VaStatuses.active,
        )
    )


def va_get_user_note_for_current_user(va_sid):
    return _scalar(
        sa.select(VaUsernotes).where(
            VaUsernotes.note_by == current_user.user_id,
            VaUsernotes.note_vasubmission == va_sid,
            VaUsernotes.note_status == VaStatuses.active,
        )
    )
