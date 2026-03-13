import uuid
import logging
import traceback
import sqlalchemy as sa
from app import db
from dateutil import parser
from app.services.runtime_form_sync_service import sync_runtime_forms_from_site_mappings
from app.models import (
    VaAllocations,
    VaCoderReview,
    VaFinalAssessments,
    VaInitialAssessments,
    VaReviewerReview,
    VaSmartvaResults,
    VaUsernotes,
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

log = logging.getLogger(__name__)


def _pending_smartva_sids(form_id: str) -> set[str]:
    """Return the set of va_sids for va_form that have no active SmartVA result.

    Used to filter SmartVA input to only submissions that actually need
    processing, avoiding re-running SmartVA on already-completed cases.
    """
    all_sids = set(
        db.session.scalars(
            sa.select(VaSubmissions.va_sid).where(
                VaSubmissions.va_form_id == form_id
            )
        ).all()
    )
    done_sids = set(
        db.session.scalars(
            sa.select(VaSmartvaResults.va_sid).where(
                VaSmartvaResults.va_sid.in_(all_sids),
                VaSmartvaResults.va_smartva_status == VaStatuses.active,
            )
        ).all()
    )
    return all_sids - done_sids


def va_data_sync_odkcentral(log_progress=None):
    def _progress(msg):
        print(msg)
        if log_progress:
            log_progress(msg)

    try:
        _progress("Sync started.")

        _progress("Resolving active forms from site mappings…")
        va_forms = sync_runtime_forms_from_site_mappings()
        if not va_forms:
            _progress("No active mapped VA forms found — nothing to sync.")
            return

        # ── Phase 1: Download CSV + attachments ────────────────────────────────

        form_ids = [f.form_id for f in va_forms]
        _progress(f"Phase 1: downloading {len(va_forms)} form(s): {', '.join(form_ids)}")
        for va_form in va_forms:
            log.info("DataSync [Downloading: %s].", va_form.form_id)
            _progress(f"Downloading {va_form.form_id}…")
            va_odk_downloadformdata(va_form)

        # ── Phase 1: Upsert submissions ────────────────────────────────────────

        va_submissions_added = 0
        va_submissions_updated = 0
        va_discarded_relrecords = 0
        amended_sids = set()   # track which SIDs changed — used in Phase 2

        va_allsubmissions = []
        for va_form in va_forms:
            log.info("DataSync [Compiling submissions: %s].", va_form.form_id)
            _progress(f"Compiling submissions: {va_form.form_id}…")
            va_submissions = va_preprocess_prepdata(va_form)
            if va_submissions:
                va_allsubmissions.extend(va_submissions)

        for va_submission in va_allsubmissions:
            va_submission_amended = False

            va_submission_sid          = va_submission.get("sid")
            va_submission_formid       = va_submission.get("form_def")
            va_submission_date         = parser.isoparse(va_submission.get("SubmissionDate"))
            va_submission_updatedat    = (
                parser.isoparse(va_submission.get("updatedAt")).replace(tzinfo=None)
                if va_submission.get("updatedAt")
                else None
            )
            va_submission_datacollector  = va_submission.get("SubmitterName")
            va_submission_reviewstate    = va_submission.get("ReviewState")
            va_submission_instancename   = va_submission.get("instanceName")
            va_submission_uniqueid       = va_submission.get("unique_id")
            va_submission_uniqueidmask   = va_submission.get("unique_id2")
            va_submission_consent        = va_submission.get("Id10013")
            va_submission_narrlang       = (
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
                existing_va_submission.va_sid                 = va_submission_sid
                existing_va_submission.va_form_id             = va_submission_formid
                existing_va_submission.va_submission_date     = va_submission_date
                existing_va_submission.va_odk_updatedat       = va_submission_updatedat
                existing_va_submission.va_data_collector      = va_submission_datacollector
                existing_va_submission.va_odk_reviewstate     = va_submission_reviewstate
                existing_va_submission.va_instance_name       = va_submission_instancename
                existing_va_submission.va_uniqueid_real       = va_submission_uniqueid
                existing_va_submission.va_uniqueid_masked     = va_submission_uniqueidmask
                existing_va_submission.va_consent             = va_submission_consent
                existing_va_submission.va_narration_language  = va_submission_narrlang
                existing_va_submission.va_deceased_age        = va_submission_age
                existing_va_submission.va_deceased_gender     = va_submission_gender
                existing_va_submission.va_data                = va_submission
                (
                    existing_va_submission.va_summary,
                    existing_va_submission.va_catcount,
                ) = va_preprocess_summcatenotification(va_submission)
                existing_va_submission.va_category_list = va_preprocess_categoriestodisplay(
                    va_submission, va_submission_formid
                )
                db.session.add(
                    VaSubmissionsAuditlog(
                        va_sid=va_submission_sid,
                        va_audit_byrole="vaadmin",
                        va_audit_operation="u",
                        va_audit_action="va_submission_updation_during_datasync",
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
                            va_sid=va_submission_sid,
                            va_audit_entityid=record.va_creview_id,
                            va_audit_byrole="vaadmin",
                            va_audit_operation="d",
                            va_audit_action="va_coderreview_deletion_during_datasync",
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
                            va_sid=va_submission_sid,
                            va_audit_entityid=record.va_finassess_id,
                            va_audit_byrole="vaadmin",
                            va_audit_operation="d",
                            va_audit_action="va_finalasses_deletion_during_datasync",
                        )
                    )
                for record in db.session.scalars(
                    sa.select(VaInitialAssessments).where(
                        (VaInitialAssessments.va_sid == va_submission_sid)
                        & (VaInitialAssessments.va_iniassess_status == VaStatuses.active)
                    )
                ).all():
                    record.va_iniassess_status = VaStatuses.deactive
                    va_discarded_relrecords += 1
                    db.session.add(
                        VaSubmissionsAuditlog(
                            va_sid=va_submission_sid,
                            va_audit_entityid=record.va_iniassess_id,
                            va_audit_byrole="vaadmin",
                            va_audit_operation="d",
                            va_audit_action="va_initialasses_deletion_during_datasync",
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
                            va_sid=va_submission_sid,
                            va_audit_entityid=record.va_rreview_id,
                            va_audit_byrole="vaadmin",
                            va_audit_operation="d",
                            va_audit_action="va_reviewerreview_deletion_during_datasync",
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
                            va_sid=va_submission_sid,
                            va_audit_entityid=record.note_id,
                            va_audit_byrole="vaadmin",
                            va_audit_operation="d",
                            va_audit_action="va_usernote_deletion_during_datasync",
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
                        va_sid=va_submission_sid,
                        va_audit_byrole="vaadmin",
                        va_audit_operation="c",
                        va_audit_action="va_submission_creation_during_datasync",
                    )
                )
                print(
                    f"DataSync Process [Added VA submission '{va_submission_formid}: {va_submission_sid}']"
                )

            if va_submission_amended:
                amended_sids.add(va_submission_sid)

        # Release allocations
        for record in db.session.scalars(
            sa.select(VaAllocations).where(
                VaAllocations.va_allocation_status == VaStatuses.active
            )
        ).all():
            record.va_allocation_status = VaStatuses.deactive
            db.session.add(
                VaSubmissionsAuditlog(
                    va_sid=record.va_sid,
                    va_audit_entityid=record.va_allocation_id,
                    va_audit_byrole="vaadmin",
                    va_audit_operation="d",
                    va_audit_action="va_allocation_deletion_during_datasync",
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
                        va_sid=va_initialassess.va_sid,
                        va_audit_entityid=va_initialassess.va_iniassess_id,
                        va_audit_byrole="vaadmin",
                        va_audit_operation="d",
                        va_audit_action="va_partial_iniasses_deletion_during_datasync",
                    )
                )

        _progress("Releasing allocations and committing Phase 1…")
        db.session.commit()
        phase1_msg = (
            f"Phase 1 complete — added: {va_submissions_added}, "
            f"updated: {va_submissions_updated}, discarded: {va_discarded_relrecords}"
        )
        log.info("DataSync Phase 1 complete: added=%d updated=%d discarded=%d",
                 va_submissions_added, va_submissions_updated, va_discarded_relrecords)
        _progress(phase1_msg)

        # ── Phase 2: SmartVA — one form at a time ──────────────────────────────

        va_smartva_updated = 0

        for va_form in va_forms:
            try:
                # Pending = submissions with no active result + any amended this run
                pending = _pending_smartva_sids(va_form.form_id) | (
                    amended_sids & set(
                        db.session.scalars(
                            sa.select(VaSubmissions.va_sid).where(
                                VaSubmissions.va_form_id == va_form.form_id
                            )
                        ).all()
                    )
                )
                if not pending:
                    log.info("DataSync SmartVA [%s]: all results up to date, skipping.", va_form.form_id)
                    _progress(f"SmartVA {va_form.form_id}: all results up to date, skipping.")
                    continue

                log.info("DataSync SmartVA [%s]: preparing input (%d pending).", va_form.form_id, len(pending))
                _progress(f"SmartVA {va_form.form_id}: preparing input ({len(pending)} pending)…")
                va_smartva_prepdata(va_form, pending_sids=pending)

                log.info("DataSync SmartVA [%s]: running analysis.", va_form.form_id)
                _progress(f"SmartVA {va_form.form_id}: running analysis…")
                va_smartva_runsmartva(va_form)

                log.info("DataSync SmartVA [%s]: formatting output.", va_form.form_id)
                _progress(f"SmartVA {va_form.form_id}: formatting results…")
                output_file = va_smartva_formatsmartvaresult(va_form)
                if not output_file:
                    log.warning("DataSync SmartVA [%s]: no output file produced, skipping.", va_form.form_id)
                    continue

                va_smartva_new_results, va_smartva_existingactive_results = (
                    va_smartva_appendsmartvaresults(db.session, {va_form: output_file})
                )
                if va_smartva_new_results is None:
                    log.info("DataSync SmartVA [%s]: no new results.", va_form.form_id)
                    continue

                form_updated = 0
                for va_smartva_record in va_smartva_new_results.itertuples():
                    va_sid = getattr(va_smartva_record, "sid", None)
                    va_smartva_existing = va_smartva_existingactive_results.get(va_sid)

                    # Save if: submission was amended this run (always refresh), or
                    # submission has no existing active SmartVA result (fill gap).
                    if va_sid not in amended_sids and va_smartva_existing:
                        continue
                    if va_smartva_existing:
                        va_smartva_existing.va_smartva_status = VaStatuses.deactive
                        db.session.add(
                            VaSubmissionsAuditlog(
                                va_sid=va_sid,
                                va_audit_entityid=va_smartva_existing.va_smartva_id,
                                va_audit_byrole="vaadmin",
                                va_audit_operation="d",
                                va_audit_action="va_smartva_deletion_during_datasync",
                            )
                        )

                    va_smartva_uuid = uuid.uuid4()
                    db.session.add(
                        VaSmartvaResults(
                            va_smartva_id=va_smartva_uuid,
                            va_sid=va_sid,
                            va_smartva_age=(
                                format(float(getattr(va_smartva_record, "age", None)), ".1f")
                                if getattr(va_smartva_record, "age", None) is not None
                                else None
                            ),
                            va_smartva_gender=getattr(va_smartva_record, "sex", None),
                            va_smartva_cause1=getattr(va_smartva_record, "cause1", None),
                            va_smartva_likelihood1=getattr(va_smartva_record, "likelihood1", None),
                            va_smartva_keysymptom1=getattr(va_smartva_record, "key_symptom1", None),
                            va_smartva_cause2=getattr(va_smartva_record, "cause2", None),
                            va_smartva_likelihood2=getattr(va_smartva_record, "likelihood2", None),
                            va_smartva_keysymptom2=getattr(va_smartva_record, "key_symptom2", None),
                            va_smartva_cause3=getattr(va_smartva_record, "cause3", None),
                            va_smartva_likelihood3=getattr(va_smartva_record, "likelihood3", None),
                            va_smartva_keysymptom3=getattr(va_smartva_record, "key_symptom3", None),
                            va_smartva_allsymptoms=getattr(va_smartva_record, "all_symptoms", None),
                            va_smartva_resultfor=getattr(va_smartva_record, "result_for", None),
                            va_smartva_cause1icd=getattr(va_smartva_record, "cause1_icd", None),
                            va_smartva_cause2icd=getattr(va_smartva_record, "cause2_icd", None),
                            va_smartva_cause3icd=getattr(va_smartva_record, "cause3_icd", None),
                        )
                    )
                    db.session.add(
                        VaSubmissionsAuditlog(
                            va_sid=va_sid,
                            va_audit_entityid=va_smartva_uuid,
                            va_audit_byrole="vaadmin",
                            va_audit_operation="c",
                            va_audit_action="va_smartva_creation_during_datasync",
                        )
                    )
                    form_updated += 1
                    print(
                        f"DataSync Process [Updated SmartVA result '{va_form.form_id}: {va_sid}']"
                    )

                db.session.commit()
                va_smartva_updated += form_updated
                log.info("DataSync SmartVA [%s]: committed %d result(s).", va_form.form_id, form_updated)
                _progress(f"SmartVA {va_form.form_id}: {form_updated} result(s) saved.")

            except Exception as e:
                db.session.rollback()
                log.warning("DataSync SmartVA [%s] failed, skipping: %s", va_form.form_id, e, exc_info=True)
                _progress(f"SmartVA {va_form.form_id}: FAILED — {e}")

        log.info(
            "DataSync complete: added=%d updated=%d smartva=%d discarded=%d",
            va_submissions_added, va_submissions_updated, va_smartva_updated, va_discarded_relrecords,
        )
        print(
            f"DataSync Success [VA added: {va_submissions_added} | VA updated: {va_submissions_updated} | "
            f"SmartVA updated: {va_smartva_updated} | Related records discarded: {va_discarded_relrecords}]"
        )
        return {
            "added": va_submissions_added,
            "updated": va_submissions_updated,
            "smartva_updated": va_smartva_updated,
            "discarded": va_discarded_relrecords,
        }

    except Exception as e:
        log.error("DataSync failed: %s", e, exc_info=True)
        print(f"DataSync Failed [Error: {str(e)}].")
        print(traceback.format_exc())
        raise


def va_smartva_run_pending(log_progress=None):
    """Run SmartVA only (Phase 2) for all forms, saving results for any
    submission that does not yet have an active SmartVA result.
    Does NOT download new data from ODK.
    """
    def _progress(msg):
        print(msg)
        if log_progress:
            log_progress(msg)

    try:
        _progress("SmartVA-only run started.")

        va_forms = sync_runtime_forms_from_site_mappings()
        if not va_forms:
            _progress("No active mapped VA forms found.")
            return {"smartva_updated": 0}

        va_smartva_updated = 0

        for va_form in va_forms:
            try:
                pending = _pending_smartva_sids(va_form.form_id)
                if not pending:
                    log.info("SmartVA-only [%s]: all results up to date, skipping.", va_form.form_id)
                    _progress(f"SmartVA {va_form.form_id}: all results up to date, skipping.")
                    continue

                log.info("SmartVA-only [%s]: preparing input (%d pending).", va_form.form_id, len(pending))
                _progress(f"SmartVA {va_form.form_id}: preparing input ({len(pending)} pending)…")
                va_smartva_prepdata(va_form, pending_sids=pending)

                log.info("SmartVA-only [%s]: running analysis.", va_form.form_id)
                _progress(f"SmartVA {va_form.form_id}: running analysis…")
                va_smartva_runsmartva(va_form)

                log.info("SmartVA-only [%s]: formatting output.", va_form.form_id)
                _progress(f"SmartVA {va_form.form_id}: formatting results…")
                output_file = va_smartva_formatsmartvaresult(va_form)
                if not output_file:
                    log.warning("SmartVA-only [%s]: no output file produced, skipping.", va_form.form_id)
                    continue

                va_smartva_new_results, va_smartva_existingactive_results = (
                    va_smartva_appendsmartvaresults(db.session, {va_form: output_file})
                )
                if va_smartva_new_results is None:
                    log.info("SmartVA-only [%s]: no new results.", va_form.form_id)
                    continue

                form_updated = 0
                for va_smartva_record in va_smartva_new_results.itertuples():
                    va_sid = getattr(va_smartva_record, "sid", None)
                    va_smartva_existing = va_smartva_existingactive_results.get(va_sid)

                    # Input was already filtered to pending only via pending_sids,
                    # so every row in the output should be saved. Deactivate any
                    # stale result that slipped through (e.g. race condition).
                    if va_smartva_existing:
                        va_smartva_existing.va_smartva_status = VaStatuses.deactive
                        db.session.add(
                            VaSubmissionsAuditlog(
                                va_sid=va_sid,
                                va_audit_entityid=va_smartva_existing.va_smartva_id,
                                va_audit_byrole="vaadmin",
                                va_audit_operation="d",
                                va_audit_action="va_smartva_deletion_during_smartva_only_run",
                            )
                        )

                    va_smartva_uuid = uuid.uuid4()
                    db.session.add(
                        VaSmartvaResults(
                            va_smartva_id=va_smartva_uuid,
                            va_sid=va_sid,
                            va_smartva_age=(
                                format(float(getattr(va_smartva_record, "age", None)), ".1f")
                                if getattr(va_smartva_record, "age", None) is not None
                                else None
                            ),
                            va_smartva_gender=getattr(va_smartva_record, "sex", None),
                            va_smartva_cause1=getattr(va_smartva_record, "cause1", None),
                            va_smartva_likelihood1=getattr(va_smartva_record, "likelihood1", None),
                            va_smartva_keysymptom1=getattr(va_smartva_record, "key_symptom1", None),
                            va_smartva_cause2=getattr(va_smartva_record, "cause2", None),
                            va_smartva_likelihood2=getattr(va_smartva_record, "likelihood2", None),
                            va_smartva_keysymptom2=getattr(va_smartva_record, "key_symptom2", None),
                            va_smartva_cause3=getattr(va_smartva_record, "cause3", None),
                            va_smartva_likelihood3=getattr(va_smartva_record, "likelihood3", None),
                            va_smartva_keysymptom3=getattr(va_smartva_record, "key_symptom3", None),
                            va_smartva_allsymptoms=getattr(va_smartva_record, "all_symptoms", None),
                            va_smartva_resultfor=getattr(va_smartva_record, "result_for", None),
                            va_smartva_cause1icd=getattr(va_smartva_record, "cause1_icd", None),
                            va_smartva_cause2icd=getattr(va_smartva_record, "cause2_icd", None),
                            va_smartva_cause3icd=getattr(va_smartva_record, "cause3_icd", None),
                        )
                    )
                    db.session.add(
                        VaSubmissionsAuditlog(
                            va_sid=va_sid,
                            va_audit_entityid=va_smartva_uuid,
                            va_audit_byrole="vaadmin",
                            va_audit_operation="c",
                            va_audit_action="va_smartva_creation_during_smartva_only_run",
                        )
                    )
                    form_updated += 1

                db.session.commit()
                va_smartva_updated += form_updated
                log.info("SmartVA-only [%s]: committed %d result(s).", va_form.form_id, form_updated)
                _progress(f"SmartVA {va_form.form_id}: {form_updated} result(s) saved.")

            except Exception as e:
                db.session.rollback()
                log.warning("SmartVA-only [%s] failed, skipping: %s", va_form.form_id, e, exc_info=True)
                _progress(f"SmartVA {va_form.form_id}: FAILED — {e}")

        log.info("SmartVA-only run complete: smartva_updated=%d", va_smartva_updated)
        _progress(f"SmartVA-only run complete — {va_smartva_updated} result(s) saved.")
        return {"smartva_updated": va_smartva_updated}

    except Exception as e:
        log.error("SmartVA-only run failed: %s", e, exc_info=True)
        _progress(f"SmartVA-only run FAILED: {e}")
        raise
