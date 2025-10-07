import uuid
import traceback
import sqlalchemy as sa
from app import db
from dateutil import parser
from app.models import (
    VaAllocations,
    VaCoderReview,
    VaFinalAssessments,
    VaInitialAssessments,
    VaReviewerReview,
    VaSmartvaResults,
    VaUsernotes,
    VaForms,
    VaSubmissions,
    VaStatuses,
    VaSubmissionsAuditlog,
)
from app.utils import (
    va_odk_downloadformdata,
    va_smartva_prepdata,
    va_smartva_runsmartva,
    va_smartva_formatsmartvaresult,
    va_smartva_appendsmartvaresults,
    va_preprocess_prepdata,
    va_preprocess_summcatenotification,
    va_preprocess_categoriestodisplay,
)


def va_data_sync_odkcentral():
    try:
        print("DataSync Process [Initiated].")

        print("DataSync Process [Getting VA forms from DB].")
        va_forms = db.session.scalars(
            sa.select(VaForms).where(VaForms.form_status == VaStatuses.active)
        ).all()
        if not va_forms:
            print("DataSync Failed [Could not retrive any VA forms from DB].")
            return

        va_form_dirs = {}
        for va_form in va_forms:
            print(
                f"DataSync Process [Downloading data & formatting attachments: {va_form.form_id}]."
            )
            va_form_dirs[va_form] = va_odk_downloadformdata(va_form)

        va_svainput_files = {}
        for va_form in va_forms:
            print(f"DataSync Process [Preparing SmartVA input: {va_form.form_id}].")
            va_svainput_files[va_form] = va_smartva_prepdata(va_form)

        va_svaoutput_dirs = {}
        for va_form in va_forms:
            print(f"DataSync Process [Initiating SmartVA analysis: {va_form.form_id}].")
            va_svaoutput_dirs[va_form] = va_smartva_runsmartva(va_form)

        va_svaoutput_files = {}
        for va_form in va_forms:
            print(
                f"DataSync Process [Processing & formatting SmartVA result: {va_form.form_id}]."
            )
            va_svaoutput_files[va_form] = va_smartva_formatsmartvaresult(va_form)

        print("DataSync Process [Formatting / appending / analyzing SmartVA results].")
        va_smartva_new_results, va_smartva_existingactive_results = (
            va_smartva_appendsmartvaresults(db.session, va_svaoutput_files)
        )

        va_submissions_added = 0
        va_submissions_updated = 0
        va_smartva_updated = 0
        va_discarded_relrecords = 0

        va_allsubmissions = []
        for va_form in va_forms:
            print(f"DataSync Process [Compiling VA submissions '{va_form.form_id}'].")
            va_submissions = va_preprocess_prepdata(va_form)
            if va_submissions:
                va_allsubmissions.extend(va_submissions)

        for va_submission in va_allsubmissions:
            va_submission_amended = False

            va_submission_sid = va_submission.get("sid")
            va_submission_formid = va_submission.get("form_def")
            va_submission_date = parser.isoparse(va_submission.get("SubmissionDate"))
            va_submission_updatedat = (
                parser.isoparse(va_submission.get("updatedAt")).replace(tzinfo=None)
                if va_submission.get("updatedAt")
                else None
            )
            va_submission_datacollector = va_submission.get("SubmitterName")
            va_submission_reviewstate = va_submission.get("ReviewState")
            va_submission_instancename = va_submission.get("instanceName")
            va_submission_uniqueid = va_submission.get("unique_id")
            va_submission_uniqueidmask = va_submission.get("unique_id2")
            va_submission_consent = va_submission.get("Id10013")
            va_submission_narrlang = (
                va_submission.get("narr_language")
                if va_submission.get("narr_language")
                else va_submission.get("language")
            )
            va_submission_age = (
                int(va_submission.get("finalAgeInYears"))
                if va_submission.get("finalAgeInYears")
                else 0
            )
            va_submission_gender = va_submission.get("Id10019")

            existing_va_submission = db.session.scalar(
                sa.select(VaSubmissions).where(
                    VaSubmissions.va_sid == va_submission_sid
                )
            )

            if (
                existing_va_submission
                and va_submission_updatedat != existing_va_submission.va_odk_updatedat
            ):
                existing_va_submission.va_sid = va_submission_sid
                existing_va_submission.va_form_id = va_submission_formid
                existing_va_submission.va_submission_date = va_submission_date
                existing_va_submission.va_odk_updatedat = va_submission_updatedat
                existing_va_submission.va_data_collector = va_submission_datacollector
                existing_va_submission.va_odk_reviewstate = va_submission_reviewstate
                existing_va_submission.va_instance_name = va_submission_instancename
                existing_va_submission.va_uniqueid_real = va_submission_uniqueid
                existing_va_submission.va_uniqueid_masked = va_submission_uniqueidmask
                existing_va_submission.va_consent = va_submission_consent
                existing_va_submission.va_narration_language = va_submission_narrlang
                existing_va_submission.va_deceased_age = va_submission_age
                existing_va_submission.va_deceased_gender = va_submission_gender
                existing_va_submission.va_data = va_submission
                (
                    existing_va_submission.va_summary,
                    existing_va_submission.va_catcount,
                ) = va_preprocess_summcatenotification(va_submission)
                existing_va_submission.va_category_list = (
                    va_preprocess_categoriestodisplay(
                        va_submission, va_submission_formid
                    )
                )
                db.session.add(
                    VaSubmissionsAuditlog(
                        va_sid = va_submission_sid,
                        va_audit_byrole = "vaadmin",
                        va_audit_operation = "u",
                        va_audit_action = "va_submission_updation_during_datasync",
                    )
                )
                for record in db.session.scalars(
                    sa.select(VaCoderReview).where(
                        (VaCoderReview.va_sid == va_submission_sid)
                        & (VaCoderReview.va_creview_status == VaStatuses.active)
                    )
                ).all():
                    record.va_creview_status = VaStatuses.deactive
                    va_discarded_relrecords += 1
                    db.session.add(
                        VaSubmissionsAuditlog(
                            va_sid = va_submission_sid,
                            va_audit_entityid = record.va_creview_id,
                            va_audit_byrole = "vaadmin",
                            va_audit_operation = "d",
                            va_audit_action = "va_coderreview_deletion_during_datasync",
                        )
                    )
                for record in db.session.scalars(
                    sa.select(VaFinalAssessments).where(
                        (VaFinalAssessments.va_sid == va_submission_sid)
                        & (VaFinalAssessments.va_finassess_status == VaStatuses.active)
                    )
                ).all():
                    record.va_finassess_status = VaStatuses.deactive
                    va_discarded_relrecords += 1
                    db.session.add(
                        VaSubmissionsAuditlog(
                            va_sid = va_submission_sid,
                            va_audit_entityid = record.va_finassess_id,
                            va_audit_byrole = "vaadmin",
                            va_audit_operation = "d",
                            va_audit_action = "va_finalasses_deletion_during_datasync",
                        )
                    )
                for record in db.session.scalars(
                    sa.select(VaInitialAssessments).where(
                        (VaInitialAssessments.va_sid == va_submission_sid)
                        & (
                            VaInitialAssessments.va_iniassess_status
                            == VaStatuses.active
                        )
                    )
                ).all():
                    record.va_iniassess_status = VaStatuses.deactive
                    va_discarded_relrecords += 1
                    db.session.add(
                        VaSubmissionsAuditlog(
                            va_sid = va_submission_sid,
                            va_audit_entityid = record.va_iniassess_id,
                            va_audit_byrole = "vaadmin",
                            va_audit_operation = "d",
                            va_audit_action = "va_initialasses_deletion_during_datasync",
                        )
                    )
                for record in db.session.scalars(
                    sa.select(VaReviewerReview).where(
                        (VaReviewerReview.va_sid == va_submission_sid)
                        & (VaReviewerReview.va_rreview_status == VaStatuses.active)
                    )
                ).all():
                    record.va_rreview_status = VaStatuses.deactive
                    va_discarded_relrecords += 1
                    db.session.add(
                        VaSubmissionsAuditlog(
                            va_sid = va_submission_sid,
                            va_audit_entityid = record.va_rreview_id,
                            va_audit_byrole = "vaadmin",
                            va_audit_operation = "d",
                            va_audit_action = "va_reviewerreview_deletion_during_datasync",
                        )
                    )
                for record in db.session.scalars(
                    sa.select(VaUsernotes).where(
                        (VaUsernotes.note_vasubmission == va_submission_sid)
                        & (VaUsernotes.note_status == VaStatuses.active)
                    )
                ).all():
                    record.note_status = VaStatuses.deactive
                    va_discarded_relrecords += 1
                    db.session.add(
                        VaSubmissionsAuditlog(
                            va_sid = va_submission_sid,
                            va_audit_entityid = record.note_id,
                            va_audit_byrole = "vaadmin",
                            va_audit_operation = "d",
                            va_audit_action = "va_usernote_deletion_during_datasync",
                        )
                    )
                va_submission_amended = True
                va_submissions_updated += 1
                print(
                    f"DataSync Process [Updated VA submission '{va_submission_formid}: {va_submission_sid}']"
                )
            elif not existing_va_submission and va_submission_consent == "yes":
                va_submission_summary, va_submission_catcount = (
                    va_preprocess_summcatenotification(va_submission)
                )
                va_submission_categorylist = va_preprocess_categoriestodisplay(
                    va_submission, va_submission_formid
                )
                db.session.add(
                    VaSubmissions(
                        va_sid=va_submission_sid,
                        va_form_id=va_submission_formid,
                        va_submission_date=va_submission_date,
                        va_odk_updatedat=va_submission_updatedat,
                        va_data_collector=va_submission_datacollector,
                        va_odk_reviewstate=va_submission_reviewstate,
                        va_instance_name=va_submission_instancename,
                        va_uniqueid_real=va_submission_uniqueid,
                        va_uniqueid_masked=va_submission_uniqueidmask,
                        va_consent=va_submission_consent,
                        va_narration_language=va_submission_narrlang,
                        va_deceased_age=va_submission_age,
                        va_deceased_gender=va_submission_gender,
                        va_data=va_submission,
                        va_summary=va_submission_summary,
                        va_catcount=va_submission_catcount,
                        va_category_list=va_submission_categorylist,
                    )
                )
                db.session.flush()
                va_submission_amended = True
                va_submissions_added += 1
                db.session.add(
                    VaSubmissionsAuditlog(
                        va_sid = va_submission_sid,
                        va_audit_byrole = "vaadmin",
                        va_audit_operation = "c",
                        va_audit_action = "va_submission_creation_during_datasync",
                    )
                )
                print(
                    f"DataSync Process [Added VA submission '{va_submission_formid}: {va_submission_sid}']"
                )
            else:
                pass
            if va_submission_amended:
                for va_smartva_record in va_smartva_new_results.itertuples():
                    va_sid = getattr(va_smartva_record, "sid", None)
                    if va_sid == va_submission_sid:
                        va_smartva_existing_record = (
                            va_smartva_existingactive_results.get(va_sid)
                        )
                        if va_smartva_existing_record:
                            va_smartva_existing_record.va_smartva_status = VaStatuses.deactive
                            db.session.add(
                                VaSubmissionsAuditlog(
                                    va_sid = va_submission_sid,
                                    va_audit_entityid = va_smartva_existing_record.va_smartva_id,
                                    va_audit_byrole = "vaadmin",
                                    va_audit_operation = "d",
                                    va_audit_action = "va_smartva_deletion_during_datasync",
                                )
                            )
                        va_smartva_uuid = uuid.uuid4()
                        result_data = {
                            "va_smartva_id": va_smartva_uuid,
                            "va_sid": va_sid,
                            "va_smartva_age": format(
                                float(getattr(va_smartva_record, "age", None)), ".1f"
                            )
                            if getattr(va_smartva_record, "age", None) is not None
                            else None,
                            "va_smartva_gender": getattr(
                                va_smartva_record, "sex", None
                            ),
                            "va_smartva_cause1": getattr(
                                va_smartva_record, "cause1", None
                            ),
                            "va_smartva_likelihood1": getattr(
                                va_smartva_record, "likelihood1", None
                            ),
                            "va_smartva_keysymptom1": getattr(
                                va_smartva_record, "key_symptom1", None
                            ),
                            "va_smartva_cause2": getattr(
                                va_smartva_record, "cause2", None
                            ),
                            "va_smartva_likelihood2": getattr(
                                va_smartva_record, "likelihood2", None
                            ),
                            "va_smartva_keysymptom2": getattr(
                                va_smartva_record, "key_symptom2", None
                            ),
                            "va_smartva_cause3": getattr(
                                va_smartva_record, "cause3", None
                            ),
                            "va_smartva_likelihood3": getattr(
                                va_smartva_record, "likelihood3", None
                            ),
                            "va_smartva_keysymptom3": getattr(
                                va_smartva_record, "key_symptom3", None
                            ),
                            "va_smartva_allsymptoms": getattr(
                                va_smartva_record, "all_symptoms", None
                            ),
                            "va_smartva_resultfor": getattr(
                                va_smartva_record, "result_for", None
                            ),
                            "va_smartva_cause1icd": getattr(
                                va_smartva_record, "cause1_icd", None
                            ),
                            "va_smartva_cause2icd": getattr(
                                va_smartva_record, "cause2_icd", None
                            ),
                            "va_smartva_cause3icd": getattr(
                                va_smartva_record, "cause3_icd", None
                            ),
                        }
                        db.session.add(VaSmartvaResults(**result_data))
                        va_smartva_updated += 1
                        db.session.add(
                            VaSubmissionsAuditlog(
                                va_sid = va_submission_sid,
                                va_audit_entityid = va_smartva_uuid,
                                va_audit_byrole = "vaadmin",
                                va_audit_operation = "c",
                                va_audit_action = "va_smartva_creation_during_datasync",
                            )
                        )
                        print(
                            f"DataSync Process [Updated SmartVA result '{va_submission_formid}: {va_submission_sid}']"
                        )
        for record in db.session.scalars(
            sa.select(VaAllocations).where(
                VaAllocations.va_allocation_status == VaStatuses.active
            )
        ).all():
            record.va_allocation_status = VaStatuses.deactive
            db.session.add(
                VaSubmissionsAuditlog(
                    va_sid = record.va_sid,
                    va_audit_entityid = record.va_allocation_id,
                    va_audit_byrole = "vaadmin",
                    va_audit_operation = "d",
                    va_audit_action = "va_allocation_deletion_during_datasync",
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
                        va_audit_action = "va_partial_iniasses_deletion_during_datasync",
                    )
                )
        print("DataSync Process [Released allocated VA submissions.]")
        db.session.commit()
        print(
            f"DataSync Success [VA added: {va_submissions_added} | VA updated: {va_submissions_updated} | SmartVA updated: {va_smartva_updated} | Related records discarded: {va_discarded_relrecords}]"
        )

    except Exception as e:
        print(f"DataSync Failed [Error: {str(e)}].")
        print(traceback.format_exc())
