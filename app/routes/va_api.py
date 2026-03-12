import os
import uuid
import sqlalchemy as sa
from app import db
from app.models import VaSubmissions, VaReviewerReview, VaAllocations, VaAllocation, VaStatuses, VaIcdCodes, VaFinalAssessments, VaInitialAssessments, VaCoderReview, VaSmartvaResults, VaUsernotes, VaSubmissionsAuditlog, VaNarrativeAssessment
from app.models.va_project_master import VaProjectMaster
from app.models.va_forms import VaForms
from app.decorators import va_validate_permissions
from flask_login import current_user, login_required
from flask import Blueprint, render_template, current_app, send_from_directory, flash, redirect, url_for, jsonify, request
from app.utils import va_get_form_type_code_for_form, va_render_processcategorydata, va_permission_abortwithflash
from app.utils.va_routes.va_api_helpers import va_get_render_datalevel
from app.services.category_rendering_service import get_category_rendering_service
from app.services.field_mapping_service import get_mapping_service
from app.forms import VaReviewerReviewForm, VaInitialAssessmentForm, VaCoderReviewForm, VaFinalAssessmentForm, VaUsernoteForm


va_api = Blueprint("va_api", __name__)
adult = [
    "I10 - Essential Hypertension",
    "E11 - Type 2 Diabetes Mellitus",
    "E10 - Type 1 Diabetes Mellitus",
    "E66 - Obesity",
    "N18 - Chronic Kidney Disease",
    "K74 - Chronic Liver Disease",
    "J44 - Chronic Obstructive Pulmonary Disease",
    "J45 - Asthma",
    "E78 - Dyslipidemia",
    "I50 - Congestive Heart Failure",
    "I25 - Coronary Artery Disease",
    "D64 - Chronic Anaemia",
    "F03 - Dementia",
    "I25.2 - Previous Myocardial Infarction",
    "I69 - Previous Stroke/CVA",
    "C80 - Cancer (non-primary, metastasis, history)",
    "B24 - HIV/AIDS",
    "Z86.1 - Past history of tuberculosis",
    "D89 - Immunosuppression",
    "E03 - Hypothyroidism",
    "E05 - Hyperthyroidism",
    "B18 - Chronic Viral Infections (Hepatitis)",
    "I73.9 - Peripheral Vascular Disease",
    "I09 - Chronic Rheumatic Heart Disease",
    "Z98.8 - History of Major Surgery",
    "Z79.3 - Long-term use of Immunosuppressants"
]

neonate = [
    "P07 - Preterm birth",
    "P07.0, P07.1 - Low Birth Weight",
    "P05 - Intrauterine Growth Restriction",
    "P21 - Birth Asphyxia",
    "P36 - Neonatal Sepsis",
    "P23 - Neonatal Pneumonia",
    "P22 - Hyaline Membrane Disease / Respiratory Distress Syndrome",
    "P24.0 - Meconium Aspiration Syndrome",
    "P59 - Neonatal Jaundice",
    "P90 - Neonatal Convulsions",
    "P91.6 - Hypoxic Ischemic Encephalopathy",
    "P80 - Hypothermia of Newborn",
    "P70.4 - Hypoglycemia of Newborn",
    "P52 - Neonatal Hemorrhage",
    "Q20 - Q28 - Congenital Heart Disease",
    "Q00 - Q99 - Congenital Malformations",
    "Q90 - Chromosomal Abnormalities",
    "A33 - Neonatal Tetanus",
    "P37.9 - Neonatal Meningitis",
    "P77 - Necrotizing Enterocolitis",
    "P00.1 - Maternal Diabetes",
    "P00.0 - Maternal Hypertension",
    "P02.7 - Chorioamnionitis",
    "P01.5 - Twin/Multiple Gestation",
    "P35, P37 - Congenital Infections (TORCH)",
    "P58, P59 - Hyperbilirubinemia",
    "P92 - Feeding Problems of Newborn",
    "P04 - Maternal drug use affecting newborn"
]

children = [
    "J06, J20, J21 - Acute Respiratory Infections",
    "J45 - Asthma",
    "D50 - D53 - Anemia",
    "E40 - E46 - Malnutrition",
    "E66 - Obesity",
    "E10, E11 - Diabetes Mellitus (Type 1/2)",
    "G40 - Epilepsy",
    "Q20 - Q28 - Congenital Heart Disease",
    "D57 - Sickle Cell Disease",
    "D56 - Thalassemia",
    "Q90 - Down Syndrome",
    "E84 - Cystic Fibrosis",
    "N18, N04 - Renal Disease",
    "A15 - A19 - Tuberculosis",
    "B20 - B24 - HIV/AIDS",
    "D80 - D89 - Immunodeficiency",
    "I05 - I09 - Rheumatic Heart Disease",
    "G80 - Cerebral Palsy",
    "F84 - Autism Spectrum Disorders",
    "F70 - F79 - Intellectual Disability",
    "C91 - C95, C81 - C85, C00 - C80 - Cancer",
    "D57.3 - Sickle Cell Trait",
    "D56.3 - Thalassemia Trait",
    "Z98.8 - Previous Major Surgery",
    "P07 - History of Prematurity/Low Birth Weight",
    "Z28.3 - Incomplete immunization Status"
]


@va_api.route("/<va_action>/<va_actiontype>/<va_sid>/<va_partial>", methods=["GET", "POST"])
@login_required
@va_validate_permissions()
def va_renderpartial(va_action, va_actiontype, va_sid, va_partial):
    va_submission = db.session.get(VaSubmissions, va_sid)
    _form_type_code = va_get_form_type_code_for_form(
        va_submission.va_form_id if va_submission else None
    )
    category_service = get_category_rendering_service()
    if category_service.is_category_enabled(
        _form_type_code,
        va_action,
        va_submission.va_category_list if va_submission else None,
        va_partial,
    ):
        _mapping_svc = get_mapping_service()
        category_config = category_service.get_category_config(
            _form_type_code,
            va_action,
            va_partial,
        )
        va_mapping_fieldsitepi = _mapping_svc.get_fieldsitepi(_form_type_code)
        va_mapping_choice = _mapping_svc.get_choices(_form_type_code)
        va_mapping_flip = _mapping_svc.get_flip_labels(_form_type_code)
        va_mapping_info = _mapping_svc.get_info_labels(_form_type_code)
        subcategory_labels = _mapping_svc.get_subcategory_labels(_form_type_code, va_partial)

        va_datalevel = va_get_render_datalevel(
            va_action,
            _form_type_code,
            va_submission.va_category_list,
        )
        va_processedcategorydata = va_render_processcategorydata(va_submission.va_data, va_submission.va_form_id, va_datalevel, va_mapping_choice, va_partial)
        va_previouscategory, va_nextcategory = category_service.get_category_neighbours(
            _form_type_code,
            va_action,
            va_submission.va_category_list,
            va_partial,
        )
        reviewobject = db.session.scalar(sa.select(VaReviewerReview).where((VaReviewerReview.va_rreview_status == VaStatuses.active)&(VaReviewerReview.va_sid == va_sid)))
        vafinexists = db.session.scalar(sa.select(VaFinalAssessments.va_sid).where((VaFinalAssessments.va_finassess_status == VaStatuses.active)&(VaFinalAssessments.va_sid == va_sid)))
        vaerrexists = db.session.scalar(sa.select(VaCoderReview.va_sid).where((VaCoderReview.va_creview_status == VaStatuses.active)&(VaCoderReview.va_sid == va_sid)))
        vainiexists = db.session.scalar(sa.select(VaInitialAssessments.va_sid).where((VaInitialAssessments.va_iniassess_status == VaStatuses.active)&(VaInitialAssessments.va_sid == va_sid)))
        va_final_assess = db.session.scalar(sa.select(VaFinalAssessments).where((VaFinalAssessments.va_finassess_status == VaStatuses.active)&(VaFinalAssessments.va_sid == va_sid)))
        va_initial_assess = db.session.scalar(sa.select(VaInitialAssessments).where((VaInitialAssessments.va_iniassess_status == VaStatuses.active)&(VaInitialAssessments.va_sid == va_sid)))
        va_coder_review = db.session.scalar(sa.select(VaCoderReview).where((VaCoderReview.va_creview_status == VaStatuses.active)&(VaCoderReview.va_sid == va_sid)))
        smartva = db.session.scalar(sa.select(VaSmartvaResults).where((VaSmartvaResults.va_sid == va_sid)&(VaSmartvaResults.va_smartva_status == VaStatuses.active)))
        da_va_final_assess = db.session.scalar(sa.select(VaFinalAssessments).where((VaFinalAssessments.va_finassess_status == VaStatuses.deactive)&(VaFinalAssessments.va_sid == va_sid)&(VaFinalAssessments.va_finassess_by == current_user.user_id)))
        da_va_initial_assess = db.session.scalar(sa.select(VaInitialAssessments).where((VaInitialAssessments.va_iniassess_status == VaStatuses.deactive)&(VaInitialAssessments.va_sid == va_sid)&(VaInitialAssessments.va_iniassess_by == current_user.user_id)))
        da_va_coder_review = db.session.scalar(sa.select(VaCoderReview).where((VaCoderReview.va_creview_status == VaStatuses.deactive)&(VaCoderReview.va_sid == va_sid)&(VaCoderReview.va_creview_by == current_user.user_id)))
        # return render_template(
        #     f"va_formcategory_partials/{va_partial}.html",
        #     va_codingplatformid = va_submission.va_uniqueid_masked,
        #     va_processedcategorydata = va_processedcategorydata,
        #     va_previouscategory = va_previouscategory,
        #     va_nextcategory = va_nextcategory,
        #     va_mappingflip = va_mapping_flip,
        #     va_mappinginfo = va_mapping_info,
        # )
        # NQA context (only relevant for vanarrationanddocuments + vacode)
        _nqa_project = _get_project_for_submission(va_sid) if va_partial == "vanarrationanddocuments" else None
        narrative_qa_enabled = bool(_nqa_project and _nqa_project.narrative_qa_enabled)
        va_narrative_assessment = None
        if narrative_qa_enabled and va_action == "vacode":
            va_narrative_assessment = db.session.scalar(
                sa.select(VaNarrativeAssessment).where(
                    VaNarrativeAssessment.va_sid == va_sid,
                    VaNarrativeAssessment.va_nqa_by == current_user.user_id,
                    VaNarrativeAssessment.va_nqa_status == VaStatuses.active,
                )
            )
        template_name = f"va_formcategory_partials/{va_partial}.html"
        if category_config and category_config.render_mode == "table_sections":
            template_name = "va_formcategory_partials/category_table_sections.html"
        elif category_config and category_config.render_mode == "health_history_summary":
            template_name = "va_formcategory_partials/category_health_history_summary.html"
        elif category_config and category_config.render_mode == "attachments":
            template_name = "va_formcategory_partials/category_attachments.html"
        return render_template(
            template_name,
            instance_name = va_submission.va_uniqueid_masked,
            category_data = va_processedcategorydata,
            category_config = category_config,
            subcategory_labels = subcategory_labels,
            va_previouscategory = va_previouscategory,
            va_nextcategory = va_nextcategory,
            flip_list = va_mapping_flip,
            info_list = va_mapping_info,
            va_action = va_action,
            va_actiontype = va_actiontype,
            va_sid = va_sid,
            va_partial = va_partial,
            summary = va_submission.va_summary,
            reviewobject = reviewobject,
            vafinexists = vafinexists,
            vaerrexists = vaerrexists,
            vainiexists = vainiexists,
            va_final_assess = va_final_assess,
            va_initial_assess = va_initial_assess,
            va_coder_review = va_coder_review,
            smartva = smartva,
            da_va_final_assess = da_va_final_assess,
            da_va_initial_assess = da_va_initial_assess,
            da_va_coder_review = da_va_coder_review,
            narrative_qa_enabled = narrative_qa_enabled,
            va_narrative_assessment = va_narrative_assessment,
        )
    if va_partial == "vareviewform":
        form = VaReviewerReviewForm()
        if form.validate_on_submit():
            new_review = VaReviewerReview(
                va_sid=va_sid,
                va_rreview_by=current_user.user_id,
                va_rreview_narrpos=form.va_rreview_narrpos.data,
                va_rreview_narrneg=form.va_rreview_narrneg.data,
                va_rreview_narrchrono=form.va_rreview_narrchrono.data,
                va_rreview_narrdoc=form.va_rreview_narrdoc.data,
                va_rreview_narrcomorb=form.va_rreview_narrcomorb.data,
                va_rreview=form.va_rreview.data,
                va_rreview_fail=form.va_rreview_fail.data.strip() or None,
                va_rreview_remark=form.va_rreview_remark.data.strip() or None,
            )
            va_has_allocation = db.session.scalar(sa.select(VaAllocations).where((VaAllocations.va_allocated_to == current_user.user_id)&(VaAllocations.va_allocation_for == VaAllocation.reviewing)&(VaAllocations.va_allocation_status == VaStatuses.active)))
            va_has_allocation.va_allocation_status = VaStatuses.deactive
            db.session.add(new_review)
            db.session.commit()

            if request.headers.get("HX-Request"):
                response = jsonify(success=True)
                response.headers["HX-Redirect"] = current_user.landing_url()
                flash("Review submitted successfully!", "success")
                return response
        return render_template(
            f"va_form_partials/{va_partial}.html", form = form, va_action = va_action, va_actiontype= va_actiontype, va_sid = va_sid
        )
    if va_partial == "vainitialasses":
        form = VaInitialAssessmentForm()
        save_clicked = form.va_save_assessment.data
        not_codeable_clicked = form.va_not_codeable.data
        agelabels = db.session.execute(
            sa.select(
                VaSubmissions.va_data["isNeonatal"].astext.label("isNeonatal"),
                VaSubmissions.va_data["isChild"].astext.label("isChild"),
                VaSubmissions.va_data["isAdult"].astext.label("isAdult")
            ).where(VaSubmissions.va_sid == va_sid)
        ).mappings().first()
        active_age_label = next(
            (k for k, v in agelabels.items() if str(v).strip() in ("1", "1.0")),
            None
        )
        if active_age_label == "isAdult":
            form.va_other_conditions.choices = adult
        elif active_age_label == "isChild":
            form.va_other_conditions.choices = children
        elif active_age_label == "isNeonate":
            form.va_other_conditions.choices = neonate
        else:
            form.va_other_conditions.choices = adult
        if save_clicked and form.validate_on_submit():
            form1 = VaFinalAssessmentForm()
            smartva = db.session.scalar(sa.select(VaSmartvaResults).where((VaSmartvaResults.va_sid == va_sid)&(VaSmartvaResults.va_smartva_status == VaStatuses.active)))
            gen_uuid = uuid.uuid4()
            new_review = VaInitialAssessments(
                va_iniassess_id=gen_uuid,
                va_sid=va_sid,
                va_iniassess_by=current_user.user_id,
                va_immediate_cod=form.va_immediate_cod.data,
                va_antecedent_cod=form.va_antecedent_cod.data,
                va_other_conditions=" | ".join(form.va_other_conditions.data) if form.va_other_conditions.data else None,
                # va_rreview=form.va_rreview.data,
                # va_rreview_fail=form.va_rreview_fail.data.strip() or None,
                # va_rreview_remark=form.va_rreview_remark.data.strip() or None,
            )
            db.session.add(new_review)
            db.session.add(
                VaSubmissionsAuditlog(
                    va_sid = va_sid,
                    va_audit_byrole = "vacoder",
                    va_audit_by = current_user.user_id,
                    va_audit_operation = "c",
                    va_audit_action = "initial cod submitted",
                    va_audit_entityid = gen_uuid
                )
            )
            db.session.commit()
            va_initial_assess = db.session.scalar(sa.select(VaInitialAssessments).where((VaInitialAssessments.va_iniassess_status == VaStatuses.active)&(VaInitialAssessments.va_sid == va_sid)))
            return render_template("va_form_partials/vafinalasses.html", form = form1, va_action = va_action, va_actiontype= va_actiontype, va_sid = va_sid, smartva=smartva, va_immediate_cod = va_initial_assess.va_immediate_cod or None, va_antecedent_cod = va_initial_assess.va_antecedent_cod or None, va_other_conditions = va_initial_assess.va_other_conditions or None)
        elif not_codeable_clicked:
            form2 = VaCoderReviewForm()
            return render_template("va_form_partials/vacoderreview.html", form = form2, va_action = va_action, va_actiontype= va_actiontype, va_sid = va_sid)
        return render_template(
            f"va_form_partials/{va_partial}.html", form = form, va_action = va_action, va_actiontype= va_actiontype, va_sid = va_sid,
        )
    if va_partial == "vafinalasses":
        form1 = VaFinalAssessmentForm()
        smartva = db.session.scalar(sa.select(VaSmartvaResults).where((VaSmartvaResults.va_sid == va_sid)&(VaSmartvaResults.va_smartva_status == VaStatuses.active)))
        if form1.validate_on_submit():
            # Enforce NQA completion if enabled for this project
            _project = _get_project_for_submission(va_sid)
            if _project and _project.narrative_qa_enabled:
                _nqa_done = db.session.scalar(
                    sa.select(VaNarrativeAssessment).where(
                        VaNarrativeAssessment.va_sid == va_sid,
                        VaNarrativeAssessment.va_nqa_by == current_user.user_id,
                        VaNarrativeAssessment.va_nqa_status == VaStatuses.active,
                    )
                )
                if not _nqa_done:
                    if request.headers.get("HX-Request"):
                        return jsonify({"error": "Narrative Quality Assessment must be completed before submitting the final COD."}), 400
                    flash("Please complete the Narrative Quality Assessment before submitting.", "warning")
                    return redirect(request.referrer or url_for("va_main.va_dashboard", va_role="coder"))
            gen_uuid = uuid.uuid4()
            new_review1 = VaFinalAssessments(
                va_finassess_id=gen_uuid,
                va_sid=va_sid,
                va_finassess_by=current_user.user_id,
                va_conclusive_cod=form1.va_conclusive_cod.data,
                va_finassess_remark=form1.va_finassess_remark.data.strip() or None,
                # va_rreview=form.va_rreview.data,
                # va_rreview_fail=form.va_rreview_fail.data.strip() or None,
                # va_rreview_remark=form.va_rreview_remark.data.strip() or None,
            )
            db.session.add(
                VaSubmissionsAuditlog(
                    va_sid = va_sid,
                    va_audit_byrole = "vacoder",
                    va_audit_by = current_user.user_id,
                    va_audit_operation = "c",
                    va_audit_action = "final cod submitted",
                    va_audit_entityid = gen_uuid
                )
            )
            va_has_allocation = db.session.scalar(sa.select(VaAllocations).where((VaAllocations.va_allocated_to == current_user.user_id)&(VaAllocations.va_allocation_for == VaAllocation.coding)&(VaAllocations.va_allocation_status == VaStatuses.active)))
            va_has_allocation.va_allocation_status = VaStatuses.deactive
            db.session.add(
                VaSubmissionsAuditlog(
                    va_sid = va_sid,
                    va_audit_byrole = "vacoder",
                    va_audit_by = current_user.user_id,
                    va_audit_operation = "d",
                    va_audit_action = "allocated form released from coder",
                    va_audit_entityid = va_has_allocation.va_allocation_id
                )
            )
            db.session.add(new_review1)
            db.session.commit()
            if request.headers.get("HX-Request"):
                response = jsonify(success=True)
                response.headers["HX-Redirect"] = url_for('va_main.va_dashboard', va_role="coder")
                flash("VA Coding submitted successfully!", "success")
                return response
        va_initial_assess = db.session.scalar(sa.select(VaInitialAssessments).where((VaInitialAssessments.va_iniassess_status == VaStatuses.active)&(VaInitialAssessments.va_sid == va_sid)))
        return render_template(
            f"va_form_partials/{va_partial}.html", form = form1, va_action = va_action, va_actiontype= va_actiontype, va_sid = va_sid, smartva=smartva, va_immediate_cod = va_initial_assess.va_immediate_cod or None, va_antecedent_cod = va_initial_assess.va_antecedent_cod or None, va_other_conditions = va_initial_assess.va_other_conditions or None
        )
    if va_partial == "vausernote":
        form = VaUsernoteForm()
        va_usernote = db.session.scalar(
            sa.select(VaUsernotes).where(
                VaUsernotes.note_by == current_user.user_id,
                VaUsernotes.note_vasubmission == va_sid,
                VaUsernotes.note_status == VaStatuses.active,
            )
        )
        if form.validate_on_submit():
            if va_usernote:
                va_usernote.note_content = form.va_note_content.data
            else:
                new_note = VaUsernotes(
                    note_by=current_user.user_id,
                    note_vasubmission=va_sid,
                    note_content=form.va_note_content.data
                )
                db.session.add(new_note)
            db.session.commit()
            obb_response = render_template("va_intermediate_partials/va_note_notification.html", message="Note Saved!")
            main_response = render_template(f"va_form_partials/{va_partial}.html", va_action = va_action, va_actiontype= va_actiontype, va_sid = va_sid, form=form)
            return obb_response + main_response
        form.va_note_content.data = va_usernote.note_content if va_usernote else ""
        return render_template(f"va_form_partials/{va_partial}.html", va_action = va_action, va_actiontype= va_actiontype, va_sid = va_sid, form=form)
    if va_partial == "vacoderreview":
        form = VaCoderReviewForm()
        if form.validate_on_submit():
            gen_uuid = uuid.uuid4()
            new_coder_review = VaCoderReview(
                va_creview_id = gen_uuid,
                va_sid = va_sid,
                va_creview_by = current_user.user_id,
                va_creview_reason = form.va_creview_reason.data,
                va_creview_other = form.va_creview_other.data.strip() or None
            )
            db.session.add(
                VaSubmissionsAuditlog(
                    va_sid = va_sid,
                    va_audit_byrole = "vacoder",
                    va_audit_by = current_user.user_id,
                    va_audit_operation = "c",
                    va_audit_action = "error reported by coder",
                    va_audit_entityid = gen_uuid
                )
            )
            va_has_allocation = db.session.scalar(sa.select(VaAllocations).where((VaAllocations.va_allocated_to == current_user.user_id)&(VaAllocations.va_allocation_for == VaAllocation.coding)&(VaAllocations.va_allocation_status == VaStatuses.active)))
            va_has_allocation.va_allocation_status = VaStatuses.deactive
            db.session.add(
                VaSubmissionsAuditlog(
                    va_sid = va_sid,
                    va_audit_byrole = "vacoder",
                    va_audit_by = current_user.user_id,
                    va_audit_operation = "d",
                    va_audit_action = "allocated form released from coder",
                    va_audit_entityid = va_has_allocation.va_allocation_id
                )
            )
            db.session.add(new_coder_review)
            db.session.commit()
            if request.headers.get("HX-Request"):
                response = jsonify(success=True)
                response.headers["HX-Redirect"] = url_for('va_main.va_dashboard', va_role="coder")
                flash("Error reported successfully!", "success")
                return response
        return render_template(f"va_form_partials/{va_partial}.html", va_action = va_action, va_actiontype= va_actiontype, va_sid = va_sid, form=form)
        
        
        

@va_api.route('/vaservemedia/<va_form_id>/<va_filename>')
@login_required
def va_servemedia(va_form_id, va_filename):
    if not current_user.has_va_form_access(va_form_id):
        va_permission_abortwithflash(f"You don't have permissions to access the media files for '{va_form_id}'", 403)
    media_base = os.path.join(
        current_app.config["APP_DATA"], va_form_id, "media"
    )
    return send_from_directory(media_base, va_filename)



@va_api.route("/icd-search")
def icd_search():
    query = request.args.get("q", "")
    results = (
        db.session.execute(
            sa.select(VaIcdCodes.icd_code, VaIcdCodes.icd_to_display)
            .where(VaIcdCodes.icd_to_display.ilike(f"%{query}%"))
            .limit(20)
        ).all()
    )
    return jsonify([
        {"icd_code": r[0], "icd_to_display": r[1]} for r in results
    ])



# # * api call to fetch coding / smartva information for some sid / va form
# @va_api.route("/form/<sid>/coding", methods=['GET', 'POST'])
# def get_smartva(sid):
#     # check if form exists
#     form_va = db.session.scalar(sa.select(VaSubmissions).where(VaSubmissions.sid == sid))
#     if not form_va:
#         return "Form not found", 404
#     # load the smartva result for sid
#     smartva_result = db.session.scalar(sa.select(VaSmartvaResults).where((VaSmartvaResults.sid == sid) & (VaSmartvaResults.status == "active")))
#     # return 404 if result not found
#     if not smartva_result:
#         return "Form not found", 404
#     # check for existing assessment
#     existing_assessment = db.session.scalar(sa.select(VaFinalAssessments).where((VaFinalAssessments.sid == sid) & (VaFinalAssessments.status == "active")))
#     if existing_assessment:
#         icd_status = db.session.scalar(sa.select(VaIcdCodes).where((VaIcdCodes.icd_code == existing_assessment.icd_code_id)))
#     else:
#         icd_status = None
#     # create form instance
#     form = VaFinalAssessmentForm()
#     form.sid.data = sid
#     # render data
#     return render_template(
#         "partials/category_smartva.html",
#         smartva = smartva_result,
#         sid = sid,
#         summary = form_va.json_summary,
#         existing_assessment=existing_assessment,
#         form=form,
#         icd_status=icd_status.description if icd_status else None
#     )


# # * api call to search for allotable ICD codes
# @va_api.route('/search_icd_codes')
# def search_icd_codes():
#     search_term = request.args.get('q', '')
#     page = int(request.args.get('page', 1))
#     per_page = 20
    
#     query = VaIcdCodes.query
    
#     if search_term:
#         query = query.filter(
#             db.or_(
#                 VaIcdCodes.icd_code.ilike(f'%{search_term}%'),
#                 VaIcdCodes.icd_to_display.ilike(f'%{search_term}%'),
#                 VaIcdCodes.description.ilike(f'%{search_term}%')
#             )
#         )
    
#     pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    
#     results = []
#     for icd in pagination.items:
#         results.append({
#             'id': icd.icd_code,
#             'text': icd.icd_to_display
#         })
    
#     return jsonify({
#         'results': results,
#         'pagination': {
#             'more': pagination.has_next
#         }
#     })

# @va_api.route("/api/<sid>/save-assessment", methods=['POST'])
# def save_assessment(sid):
#     """POST - Save assessment data"""
#     form = VaFinalAssessmentForm()
    
#     if form.validate_on_submit():
#         try:
#             existing_assessment = db.session.scalar(sa.select(VaFinalAssessments).where((VaFinalAssessments.sid == sid) & (VaFinalAssessments.status == "active")))
            
#             error_report_value = form.error_report.data.strip() if form.error_report.data else ""
            
#             print(f"Error report value (cleaned): '{error_report_value}'")
#             print(f"Error report length: {len(error_report_value)}")
            
#             if error_report_value:
                
#                 # Handle error report
#                 if existing_assessment:
#                     assessment = existing_assessment
#                 else:
#                     assessment = VaFinalAssessments(sid=sid)
#                     db.session.add(assessment)
                
#                 assessment.error_reported = True
#                 assessment.error_report = error_report_value  # ✅ Use cleaned value
#                 assessment.icd_code_id = None
#                 assessment.confidence = None
#                 assessment.comment = None
                
#                 flash("Error reported successfully. Please continue with another submission.", "success")
                
#             else:                
#                 # Handle regular assessment
#                 if existing_assessment:
#                     assessment = existing_assessment
#                 else:
#                     assessment = VaFinalAssessments(sid=sid)
#                     db.session.add(assessment)
                
#                 assessment.error_reported = False
#                 assessment.error_report = None
#                 assessment.icd_code_id = form.icd_code_id.data if form.icd_code_id.data else None
#                 assessment.confidence = form.confidence.data
#                 assessment.comment = form.comment.data
#                 flash("Assessment saved successfully. Please continue with another submission.", "success")
            
#             assessment.status = "active"
            
#             db.session.commit()
            
#             saved_assessment = db.session.scalar(sa.select(VaFinalAssessments).where((VaFinalAssessments.sid == sid) & (VaFinalAssessments.status == "active")))
            
#             # Return to GET route to show updated data
#             return redirect(url_for('main.vacoding', sid=sid))
            
#         except Exception as e:
#             db.session.rollback()
#             print(f"ERROR during save: {str(e)}")
#             flash(f'Error saving assessment: {str(e)}', 'danger')
#             return redirect(url_for('main.vacoding', sid=sid))
    
#     else:
#         # Validation failed - show errors
#         for field, errors in form.errors.items():
#             print(f"Field {field} errors:", errors)
#             for error in errors:
#                 flash(f'{field}: {error}', 'danger')


# ---------------------------------------------------------------------------
# Narrative Quality Assessment (NQA)
# ---------------------------------------------------------------------------

def _get_project_for_submission(va_sid: str):
    """Return the VaProjectMaster for a submission, or None."""
    form_id = db.session.scalar(
        sa.select(VaSubmissions.va_form_id).where(VaSubmissions.va_sid == va_sid)
    )
    if not form_id:
        return None
    project_id = db.session.scalar(
        sa.select(VaForms.project_id).where(VaForms.form_id == form_id)
    )
    if not project_id:
        return None
    return db.session.get(VaProjectMaster, project_id)


def _nqa_score(length, pos_symptoms, neg_symptoms, chronology, doc_review, comorbidity) -> int:
    return length + pos_symptoms + neg_symptoms + chronology + doc_review + comorbidity


@va_api.route("/<va_action>/<va_actiontype>/<va_sid>/narrative-qa", methods=["POST"])
@login_required
@va_validate_permissions()
def va_save_narrative_qa(va_action, va_actiontype, va_sid):
    """Save or update the Narrative Quality Assessment for a coder on a submission."""
    if va_action != "vacode":
        return jsonify({"error": "NQA only available during coding."}), 403

    project = _get_project_for_submission(va_sid)
    if not project or not project.narrative_qa_enabled:
        return jsonify({"error": "Narrative QA is not enabled for this project."}), 400

    data = request.get_json(force=True) or {}

    def _int(key, min_val, max_val):
        try:
            v = int(data[key])
            if not (min_val <= v <= max_val):
                raise ValueError
            return v
        except (KeyError, TypeError, ValueError):
            return None

    length       = _int("length",       1, 3)
    pos_symptoms = _int("pos_symptoms", 1, 3)
    neg_symptoms = _int("neg_symptoms", 0, 1)
    chronology   = _int("chronology",   0, 1)
    doc_review   = _int("doc_review",   0, 1)
    comorbidity  = _int("comorbidity",  0, 1)

    missing = [k for k, v in {
        "length": length, "pos_symptoms": pos_symptoms,
        "neg_symptoms": neg_symptoms, "chronology": chronology,
        "doc_review": doc_review, "comorbidity": comorbidity,
    }.items() if v is None]
    if missing:
        return jsonify({"error": f"Invalid or missing fields: {', '.join(missing)}"}), 400

    score = _nqa_score(length, pos_symptoms, neg_symptoms, chronology, doc_review, comorbidity)

    existing = db.session.scalar(
        sa.select(VaNarrativeAssessment).where(
            VaNarrativeAssessment.va_sid == va_sid,
            VaNarrativeAssessment.va_nqa_by == current_user.user_id,
            VaNarrativeAssessment.va_nqa_status == VaStatuses.active,
        )
    )
    if existing:
        existing.va_nqa_length       = length
        existing.va_nqa_pos_symptoms = pos_symptoms
        existing.va_nqa_neg_symptoms = neg_symptoms
        existing.va_nqa_chronology   = chronology
        existing.va_nqa_doc_review   = doc_review
        existing.va_nqa_comorbidity  = comorbidity
        existing.va_nqa_score        = score
        nqa = existing
    else:
        nqa = VaNarrativeAssessment(
            va_sid=va_sid,
            va_nqa_by=current_user.user_id,
            va_nqa_length=length,
            va_nqa_pos_symptoms=pos_symptoms,
            va_nqa_neg_symptoms=neg_symptoms,
            va_nqa_chronology=chronology,
            va_nqa_doc_review=doc_review,
            va_nqa_comorbidity=comorbidity,
            va_nqa_score=score,
            va_nqa_status=VaStatuses.active,
        )
        db.session.add(nqa)

    db.session.commit()
    return jsonify({
        "saved": True,
        "score": nqa.va_nqa_score,
        "rating": nqa.rating,
        "rating_class": nqa.rating_class,
    })
#         return redirect(url_for('main.vacoding', sid=sid))
