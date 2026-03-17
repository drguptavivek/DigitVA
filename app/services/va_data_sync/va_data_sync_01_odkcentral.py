import os
import uuid
import time
import logging
import traceback
import tempfile
import sqlalchemy as sa
from datetime import datetime, timezone
from flask import current_app
from app import db
from dateutil import parser
from app.models.map_project_site_odk import MapProjectSiteOdk
from app.models.map_project_odk import MapProjectOdk
from app.services.runtime_form_sync_service import sync_runtime_forms_from_site_mappings
from app.services.odk_connection_guard_service import (
    is_retryable_odk_connectivity_error,
)
from app.services.final_cod_authority_service import (
    abandon_active_recode_episode,
    upsert_final_cod_authority,
)
from app.services.submission_workflow_service import (
    WORKFLOW_READY_FOR_CODING,
    set_submission_workflow_state,
    sync_submission_workflow_from_legacy_records,
)
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
    va_odk_clientsetup,
    va_odk_delta_count,
    va_odk_fetch_instance_ids,
    va_odk_fetch_submissions,
    va_odk_fetch_submissions_by_ids,
    va_odk_write_form_csv,
    va_odk_rebuild_form_csv_from_db,
    va_odk_sync_form_attachments,
    va_smartva_prepdata,
    va_smartva_runsmartva,
    va_smartva_formatsmartvaresult,
    va_smartva_appendsmartvaresults,
    va_preprocess_summcatenotification,
    va_preprocess_categoriestodisplay,
)

log = logging.getLogger(__name__)

_ODK_CONNECTIVITY_MAX_ATTEMPTS = 3
_ODK_CONNECTIVITY_BACKOFF_SECONDS = (5, 10)
SYNC_ISSUE_MISSING_IN_ODK = "missing_in_odk"

# ── Language normalization ────────────────────────────────────────────
_language_alias_cache: dict[str, str] | None = None


def _normalize_language(raw: str | None) -> str:
    """Map a raw ODK language value to its canonical code via map_language_aliases.

    Returns the canonical code if a match is found, otherwise returns the
    raw value unchanged (so unknown languages are still stored).
    """
    if not raw:
        return raw or ""
    global _language_alias_cache
    if _language_alias_cache is None:
        from app.models.mas_languages import MapLanguageAliases
        rows = db.session.execute(
            sa.select(MapLanguageAliases.alias, MapLanguageAliases.language_code)
        ).all()
        _language_alias_cache = {r.alias.lower(): r.language_code for r in rows}
    return _language_alias_cache.get(raw.lower(), raw)


def _reset_language_cache():
    """Clear the alias cache (call at start of each sync run)."""
    global _language_alias_cache
    _language_alias_cache = None


def _resolve_project_connections():
    """Return project_id -> connection_id mapping for the current sync run."""
    project_connection_rows = db.session.scalars(sa.select(MapProjectOdk)).all()
    return {
        row.project_id: row.connection_id for row in project_connection_rows
    }


def _is_odk_retryable_error(exc: Exception) -> bool:
    """Return True when an exception should trigger a bounded ODK client refresh/retry."""
    return is_retryable_odk_connectivity_error(exc)


def _get_or_create_sync_odk_client(
    client_cache: dict,
    connection_by_project: dict,
    va_form,
    mapping,
    *,
    force_refresh: bool = False,
):
    """Return a cached pyODK client for a form's connection/project group."""
    if mapping is None:
        return va_odk_clientsetup(project_id=va_form.project_id)

    connection_id = connection_by_project.get(va_form.project_id)
    if connection_id is None:
        return va_odk_clientsetup(project_id=va_form.project_id)

    group_key = (connection_id, int(mapping.odk_project_id))
    if force_refresh:
        client_cache.pop(group_key, None)
    if group_key not in client_cache:
        client_cache[group_key] = va_odk_clientsetup(project_id=va_form.project_id)
    return client_cache[group_key]


def _run_with_odk_connectivity_backoff(label: str, callback, log_progress=None):
    """Retry ODK connectivity/auth failures with bounded exponential backoff."""
    last_exc = None
    for attempt in range(1, _ODK_CONNECTIVITY_MAX_ATTEMPTS + 1):
        try:
            return callback(attempt)
        except Exception as exc:
            last_exc = exc
            if not _is_odk_retryable_error(exc):
                raise
            if attempt >= _ODK_CONNECTIVITY_MAX_ATTEMPTS:
                break
            delay = _ODK_CONNECTIVITY_BACKOFF_SECONDS[min(
                attempt - 1, len(_ODK_CONNECTIVITY_BACKOFF_SECONDS) - 1
            )]
            message = (
                f"{label} connectivity/auth failure on attempt "
                f"{attempt}/{_ODK_CONNECTIVITY_MAX_ATTEMPTS} — retrying in {delay}s"
            )
            log.warning(message + ": %s", exc)
            if log_progress:
                log_progress(message)
            time.sleep(delay)
    raise last_exc


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


def _normalize_consent(raw_value) -> str:
    """Persist consent values exactly when present, else as an empty string."""
    if raw_value is None:
        return ""
    return str(raw_value).strip()


def _mark_form_sync_issues(va_form, odk_instance_ids: list[str], *, by_role: str = "vaadmin"):
    """Mark local submissions that no longer exist in ODK for a form."""
    expected_sids = {
        f"{instance_id}-{va_form.form_id.lower()}"
        for instance_id in (odk_instance_ids or [])
    }
    now = datetime.now(timezone.utc)

    local_rows = db.session.scalars(
        sa.select(VaSubmissions).where(VaSubmissions.va_form_id == va_form.form_id)
    ).all()

    for submission in local_rows:
        if submission.va_sid in expected_sids:
            if submission.va_sync_issue_code == SYNC_ISSUE_MISSING_IN_ODK:
                submission.va_sync_issue_code = None
                submission.va_sync_issue_detail = None
                submission.va_sync_issue_updated_at = now
                db.session.add(
                    VaSubmissionsAuditlog(
                        va_sid=submission.va_sid,
                        va_audit_byrole=by_role,
                        va_audit_operation="u",
                        va_audit_action="submission restored from ODK sync issue",
                    )
                )
            continue

        if submission.va_sync_issue_code == SYNC_ISSUE_MISSING_IN_ODK:
            continue

        submission.va_sync_issue_code = SYNC_ISSUE_MISSING_IN_ODK
        submission.va_sync_issue_detail = (
            "Submission exists locally but is missing from active ODK submissions."
        )
        submission.va_sync_issue_updated_at = now
        db.session.add(
            VaSubmissionsAuditlog(
                va_sid=submission.va_sid,
                va_audit_byrole=by_role,
                va_audit_operation="u",
                va_audit_action="submission missing from ODK detected during sync",
            )
        )


def _upsert_form_submissions(va_form, va_submissions, amended_sids, upserted_map=None):
    """Upsert a single form's submissions into the DB.

    Returns (added, updated, discarded, skipped) counts.
    If upserted_map is provided (dict), it is populated with {va_sid: KEY}
    for every submission that was added or updated — used by the attachment
    sync step to know which submissions' attachments need refreshing.
    Caller is responsible for committing.
    """
    added = 0
    updated = 0
    discarded = 0
    skipped = 0

    for va_submission in (va_submissions or []):
        va_submission_amended = False

        va_submission_sid         = va_submission.get("sid")
        va_submission_formid      = va_submission.get("form_def")
        va_submission_date        = parser.isoparse(va_submission.get("SubmissionDate"))
        va_submission_updatedat   = (
            parser.isoparse(va_submission.get("updatedAt")).replace(tzinfo=None)
            if va_submission.get("updatedAt")
            else None
        )
        va_submission_datacollector  = va_submission.get("SubmitterName")
        va_submission_reviewstate    = va_submission.get("ReviewState")
        va_submission_instancename   = va_submission.get("instanceName")
        va_submission_uniqueid       = va_submission.get("unique_id")
        va_submission_uniqueidmask   = va_submission.get("unique_id2")
        va_submission_consent        = _normalize_consent(va_submission.get("Id10013"))
        _raw_lang = (
            va_submission.get("narr_language")
            if va_submission.get("narr_language")
            else va_submission.get("language")
        )
        va_submission_narrlang = _normalize_language(_raw_lang)
        _raw_age = va_submission.get("finalAgeInYears")
        try:
            va_submission_age = int(_raw_age) if _raw_age else 0
        except (ValueError, TypeError):
            va_submission_age = 0
        va_submission_gender = va_submission.get("Id10019")

        existing = db.session.scalar(
            sa.select(VaSubmissions).where(VaSubmissions.va_sid == va_submission_sid)
        )

        if existing and va_submission_updatedat != existing.va_odk_updatedat:
            existing.va_sid                = va_submission_sid
            existing.va_form_id            = va_submission_formid
            existing.va_submission_date    = va_submission_date
            existing.va_odk_updatedat      = va_submission_updatedat
            existing.va_data_collector     = va_submission_datacollector
            existing.va_odk_reviewstate    = va_submission_reviewstate
            existing.va_instance_name      = va_submission_instancename
            existing.va_uniqueid_real      = va_submission_uniqueid
            existing.va_uniqueid_masked    = va_submission_uniqueidmask
            existing.va_consent            = va_submission_consent
            existing.va_narration_language = va_submission_narrlang
            existing.va_deceased_age       = va_submission_age
            existing.va_deceased_gender    = va_submission_gender
            existing.va_sync_issue_code    = None
            existing.va_sync_issue_detail  = None
            existing.va_sync_issue_updated_at = None
            existing.va_data               = va_submission
            (
                existing.va_summary,
                existing.va_catcount,
            ) = va_preprocess_summcatenotification(va_submission)
            existing.va_category_list = va_preprocess_categoriestodisplay(
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
                discarded += 1
                db.session.add(VaSubmissionsAuditlog(
                    va_sid=va_submission_sid,
                    va_audit_entityid=record.va_creview_id,
                    va_audit_byrole="vaadmin",
                    va_audit_operation="d",
                    va_audit_action="va_coderreview_deletion_during_datasync",
                ))
            for record in db.session.scalars(
                sa.select(VaFinalAssessments).where(
                    (VaFinalAssessments.va_sid == va_submission_sid)
                    & (VaFinalAssessments.va_finassess_status == VaStatuses.active)
                )
            ).all():
                record.va_finassess_status = VaStatuses.deactive
                discarded += 1
                db.session.add(VaSubmissionsAuditlog(
                    va_sid=va_submission_sid,
                    va_audit_entityid=record.va_finassess_id,
                    va_audit_byrole="vaadmin",
                    va_audit_operation="d",
                    va_audit_action="va_finalasses_deletion_during_datasync",
                ))
            upsert_final_cod_authority(
                va_submission_sid,
                None,
                reason="submission_updated_during_sync",
                source_role="vaadmin",
            )
            abandon_active_recode_episode(
                va_submission_sid,
                by_role="vaadmin",
                audit_action="recode episode abandoned due to data sync update",
            )
            for record in db.session.scalars(
                sa.select(VaInitialAssessments).where(
                    (VaInitialAssessments.va_sid == va_submission_sid)
                    & (VaInitialAssessments.va_iniassess_status == VaStatuses.active)
                )
            ).all():
                record.va_iniassess_status = VaStatuses.deactive
                discarded += 1
                db.session.add(VaSubmissionsAuditlog(
                    va_sid=va_submission_sid,
                    va_audit_entityid=record.va_iniassess_id,
                    va_audit_byrole="vaadmin",
                    va_audit_operation="d",
                    va_audit_action="va_initialasses_deletion_during_datasync",
                ))
            for record in db.session.scalars(
                sa.select(VaReviewerReview).where(
                    (VaReviewerReview.va_sid == va_submission_sid)
                    & (VaReviewerReview.va_rreview_status == VaStatuses.active)
                )
            ).all():
                record.va_rreview_status = VaStatuses.deactive
                discarded += 1
                db.session.add(VaSubmissionsAuditlog(
                    va_sid=va_submission_sid,
                    va_audit_entityid=record.va_rreview_id,
                    va_audit_byrole="vaadmin",
                    va_audit_operation="d",
                    va_audit_action="va_reviewerreview_deletion_during_datasync",
                ))
            for record in db.session.scalars(
                sa.select(VaUsernotes).where(
                    (VaUsernotes.note_vasubmission == va_submission_sid)
                    & (VaUsernotes.note_status == VaStatuses.active)
                )
            ).all():
                record.note_status = VaStatuses.deactive
                discarded += 1
                db.session.add(VaSubmissionsAuditlog(
                    va_sid=va_submission_sid,
                    va_audit_entityid=record.note_id,
                    va_audit_byrole="vaadmin",
                    va_audit_operation="d",
                    va_audit_action="va_usernote_deletion_during_datasync",
                ))
            va_submission_amended = True
            updated += 1
            sync_submission_workflow_from_legacy_records(
                va_submission_sid,
                reason="odk_submission_updated",
                by_role="vaadmin",
            )
            print(f"DataSync Process [Updated VA submission '{va_submission_formid}: {va_submission_sid}']")

        elif not existing:
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
                    va_sync_issue_code=None,
                    va_sync_issue_detail=None,
                    va_sync_issue_updated_at=None,
                    va_data=va_submission,
                    va_summary=va_submission_summary,
                    va_catcount=va_submission_catcount,
                    va_category_list=va_submission_categorylist,
                )
            )
            db.session.flush()
            set_submission_workflow_state(
                va_submission_sid,
                WORKFLOW_READY_FOR_CODING,
                reason="submission_created_during_sync",
                by_role="vaadmin",
            )
            va_submission_amended = True
            added += 1
            db.session.add(
                VaSubmissionsAuditlog(
                    va_sid=va_submission_sid,
                    va_audit_byrole="vaadmin",
                    va_audit_operation="c",
                    va_audit_action="va_submission_creation_during_datasync",
                )
            )
            print(f"DataSync Process [Added VA submission '{va_submission_formid}: {va_submission_sid}']")

        if va_submission_amended:
            amended_sids.add(va_submission_sid)
            if upserted_map is not None:
                upserted_map[va_submission_sid] = va_submission.get("KEY", "")

    return added, updated, discarded, skipped


def va_data_sync_odkcentral(log_progress=None):
    def _progress(msg):
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"{ts} {msg}")
        if log_progress:
            log_progress(msg)

    try:
        _progress("Sync started.")
        _reset_language_cache()

        # Capture before any ODK calls — ensures submissions arriving during
        # the run are caught on the next sync rather than silently skipped.
        snapshot_time = datetime.now(timezone.utc)

        _progress("Resolving active forms from site mappings…")
        va_forms = sync_runtime_forms_from_site_mappings()
        if not va_forms:
            _progress("No active mapped VA forms found — nothing to sync.")
            return

        # Build (project_id, site_id) → MapProjectSiteOdk lookup for delta check
        all_mappings = db.session.scalars(sa.select(MapProjectSiteOdk)).all()
        mappings_by_ps = {(m.project_id, m.site_id): m for m in all_mappings}
        connection_by_project = _resolve_project_connections()
        clients_by_group = {}

        form_ids = [f.form_id for f in va_forms]
        _progress(f"Processing {len(va_forms)} form(s): {', '.join(form_ids)}")

        va_submissions_added = 0
        va_submissions_updated = 0
        va_discarded_relrecords = 0
        amended_sids: set[str] = set()
        failed_form_ids: list[str] = []
        downloaded_forms: list = []  # forms that were downloaded (not skipped)

        # ── Per-form: delta check → download → upsert → commit ─────────────────

        for va_form in va_forms:
            mapping = mappings_by_ps.get((va_form.project_id, va_form.site_id))
            try:
                odk_client = _get_or_create_sync_odk_client(
                    clients_by_group,
                    connection_by_project,
                    va_form,
                    mapping,
                )
                odk_ids_current = va_odk_fetch_instance_ids(va_form, client=odk_client)
                _mark_form_sync_issues(va_form, odk_ids_current)
                # Delta check
                use_gap_sync = False
                if mapping and mapping.last_synced_at is not None:
                    since_str = mapping.last_synced_at.strftime("%Y-%m-%dT%H:%M:%SZ")
                    try:
                        delta = va_odk_delta_count(
                            odk_project_id=int(va_form.odk_project_id),
                            odk_form_id=va_form.odk_form_id,
                            since=mapping.last_synced_at,
                            app_project_id=va_form.project_id,
                            client=odk_client,
                        )
                        if delta == 0:
                            _progress(
                                f"[{va_form.form_id}] delta check: 0 changes "
                                f"since {since_str} — checking for gaps…"
                            )
                            use_gap_sync = True
                        else:
                            _progress(
                                f"[{va_form.form_id}] delta check: {delta} change(s) "
                                f"since {since_str} — downloading…"
                            )
                    except Exception as delta_err:
                        _progress(
                            f"[{va_form.form_id}] delta check failed "
                            f"({delta_err}) — falling back to gap check"
                        )
                        log.warning(
                            "DataSync [%s]: delta check failed, using gap sync: %s",
                            va_form.form_id, delta_err,
                        )
                        use_gap_sync = True
                else:
                    _progress(f"[{va_form.form_id}] first sync — downloading…")

                # ── Gap sync: compare ODK IDs with local, fetch only missing ──
                if use_gap_sync:
                    odk_ids = odk_ids_current
                    # va_sid = "{instance_id}-{form_id_lower}" — build a set
                    # of expected sids from the ODK instance IDs for fast lookup
                    form_id_lower = va_form.form_id.lower()
                    local_sids = set(
                        db.session.scalars(
                            sa.select(VaSubmissions.va_sid).where(
                                VaSubmissions.va_form_id == va_form.form_id
                            )
                        ).all()
                    )
                    missing_ids = [
                        iid for iid in odk_ids
                        if f"{iid}-{form_id_lower}" not in local_sids
                    ]
                    if not missing_ids:
                        _progress(
                            f"[{va_form.form_id}] gap check: "
                            f"{len(odk_ids)} in ODK, {len(local_sids)} local — in sync"
                        )
                        if mapping:
                            mapping.last_synced_at = snapshot_time
                            db.session.commit()
                        continue
                    _progress(
                        f"[{va_form.form_id}] gap check: "
                        f"{len(missing_ids)} missing of {len(odk_ids)} "
                        f"— fetching & upserting in batches of 50…"
                    )

                    # Fetch + upsert in batches so progress is saved incrementally
                    _GAP_BATCH = 50
                    gap_added_total = 0
                    gap_updated_total = 0
                    gap_discarded_total = 0
                    gap_skipped_total = 0  # Submissions skipped due to consent
                    gap_errors = 0
                    form_dir = os.path.join(current_app.config["APP_DATA"], va_form.form_id)
                    media_dir = os.path.join(form_dir, "media")
                    os.makedirs(media_dir, exist_ok=True)

                    for batch_start in range(0, len(missing_ids), _GAP_BATCH):
                        batch_ids = missing_ids[batch_start : batch_start + _GAP_BATCH]
                        batch_records = va_odk_fetch_submissions_by_ids(
                            va_form, batch_ids, client=odk_client,
                        )
                        if batch_records:
                            upserted_map_batch: dict[str, str] = {}
                            b_added, b_updated, b_discarded, b_skipped = _upsert_form_submissions(
                                va_form, batch_records, amended_sids, upserted_map_batch
                            )
                            db.session.commit()
                            gap_added_total += b_added
                            gap_updated_total += b_updated
                            gap_skipped_total += b_skipped
                            gap_discarded_total += b_discarded

                            # Sync attachments for this batch
                            if upserted_map_batch:
                                va_odk_sync_form_attachments(
                                    va_form, upserted_map_batch, media_dir,
                                    client_factory=lambda: _get_or_create_sync_odk_client(
                                        clients_by_group, connection_by_project,
                                        va_form, mapping,
                                    ),
                                )
                                db.session.commit()

                        done = min(batch_start + _GAP_BATCH, len(missing_ids))
                        skip_msg = f", {gap_skipped_total} skipped" if gap_skipped_total else ""
                        _progress(
                            f"[{va_form.form_id}] gap batch {done}/{len(missing_ids)}: "
                            f"+{gap_added_total} added, {gap_updated_total} updated{skip_msg}"
                        )

                    va_submissions_added += gap_added_total
                    va_submissions_updated += gap_updated_total
                    va_discarded_relrecords += gap_discarded_total

                    # Rebuild full CSV and update last_synced_at
                    va_odk_rebuild_form_csv_from_db(va_form, form_dir)
                    if mapping:
                        mapping.last_synced_at = snapshot_time
                        db.session.commit()

                    skip_msg = f", {gap_skipped_total} skipped (no consent)" if gap_skipped_total else ""
                    _progress(
                        f"[{va_form.form_id}] gap sync done: "
                        f"+{gap_added_total} added, {gap_updated_total} updated{skip_msg}"
                    )
                    downloaded_forms.append(va_form)
                    continue  # skip the normal upsert/attachment flow below
                else:
                    # Normal delta or first-sync fetch
                    log.info("DataSync [Fetching submissions via OData: %s].", va_form.form_id)
                    _progress(f"[{va_form.form_id}] fetching submissions from ODK…")
                    va_submissions_raw = _run_with_odk_connectivity_backoff(
                        f"[{va_form.form_id}] ODK fetch",
                        lambda attempt: va_odk_fetch_submissions(
                            va_form,
                            since=mapping.last_synced_at if mapping else None,
                            client=_get_or_create_sync_odk_client(
                                clients_by_group,
                                connection_by_project,
                                va_form,
                                mapping,
                                force_refresh=(attempt > 1),
                            ),
                        ),
                        log_progress=_progress,
                    )

                # Write CSV for SmartVA (same format as ZIP-extracted CSV)
                form_dir = os.path.join(current_app.config["APP_DATA"], va_form.form_id)
                media_dir = os.path.join(form_dir, "media")
                os.makedirs(media_dir, exist_ok=True)
                va_odk_write_form_csv(va_submissions_raw, va_form, form_dir)

                # Upsert submissions for this form only
                log.info("DataSync [Upserting submissions: %s].", va_form.form_id)
                _progress(f"[{va_form.form_id}] upserting {len(va_submissions_raw)} submission(s)…")
                upserted_map: dict[str, str] = {}  # {va_sid: instance_id}
                form_added, form_updated, form_discarded, form_skipped = _upsert_form_submissions(
                    va_form, va_submissions_raw, amended_sids, upserted_map
                )
                va_submissions_added += form_added
                va_submissions_updated += form_updated
                va_discarded_relrecords += form_discarded

                # Per-form commit — isolates failures so other forms are not rolled back
                db.session.commit()
                skip_msg = f", {form_skipped} skipped" if form_skipped else ""
                _progress(
                    f"[{va_form.form_id}] done: "
                    f"+{form_added} added, {form_updated} updated{skip_msg}"
                )
                log.info(
                    "DataSync [%s]: committed — added=%d updated=%d discarded=%d skipped=%d",
                    va_form.form_id, form_added, form_updated, form_discarded, form_skipped,
                )

                # Sync attachments for upserted submissions (ETag-based, no rmtree)
                if upserted_map:
                    total_attach = len(upserted_map)
                    _progress(
                        f"[{va_form.form_id}] syncing attachments for "
                        f"{total_attach} submission(s)…"
                    )
                    attachment_totals = va_odk_sync_form_attachments(
                        va_form,
                        upserted_map,
                        media_dir,
                        client_factory=lambda: _get_or_create_sync_odk_client(
                            clients_by_group,
                            connection_by_project,
                            va_form,
                            mapping,
                        ),
                        progress_callback=_progress,
                    )
                    db.session.commit()  # commit ETag records
                    _progress(
                        f"[{va_form.form_id}] attachments done: "
                        f"{attachment_totals['downloaded']} downloaded, "
                        f"{attachment_totals['skipped']} skipped"
                        + (
                            f", {attachment_totals['errors']} errors"
                            if attachment_totals["errors"]
                            else ""
                        )
                    )

                # Rebuild full CSV from DB so SmartVA-only runs have all submissions
                va_odk_rebuild_form_csv_from_db(va_form, form_dir)

                # Record successful sync time
                if mapping:
                    mapping.last_synced_at = snapshot_time
                    db.session.commit()

                downloaded_forms.append(va_form)

            except Exception as form_err:
                db.session.rollback()
                log.error(
                    "DataSync [%s] failed: %s",
                    va_form.form_id, form_err, exc_info=True,
                )
                _progress(f"[{va_form.form_id}] FAILED: {form_err}")
                failed_form_ids.append(va_form.form_id)

        # ── Release allocations (global — runs after all forms) ─────────────────

        _progress("Releasing active coding allocations…")
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
            sync_submission_workflow_from_legacy_records(
                record.va_sid,
                reason="sync_reset_after_submission_update",
                by_role="vaadmin",
            )

        db.session.commit()

        phase1_msg = (
            f"Downloads complete — added: {va_submissions_added}, "
            f"updated: {va_submissions_updated}, discarded: {va_discarded_relrecords}"
        )
        if failed_form_ids:
            phase1_msg += f" | failed forms: {', '.join(failed_form_ids)}"
        log.info(
            "DataSync Phase 1 complete: added=%d updated=%d discarded=%d failed=%s",
            va_submissions_added, va_submissions_updated,
            va_discarded_relrecords, failed_form_ids,
        )
        _progress(phase1_msg)

        # ── Phase 2: SmartVA — one form at a time ──────────────────────────────

        va_smartva_updated = 0

        # Run SmartVA only for forms that were actually downloaded this run
        for va_form in downloaded_forms:
            try:
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

                with tempfile.TemporaryDirectory() as workspace_dir:
                    log.info("DataSync SmartVA [%s]: preparing input (%d pending).", va_form.form_id, len(pending))
                    _progress(f"SmartVA {va_form.form_id}: preparing input ({len(pending)} pending)…")
                    va_smartva_prepdata(va_form, workspace_dir, pending_sids=pending)

                    log.info("DataSync SmartVA [%s]: running analysis.", va_form.form_id)
                    _progress(f"SmartVA {va_form.form_id}: running analysis…")
                    va_smartva_runsmartva(va_form, workspace_dir)

                    log.info("DataSync SmartVA [%s]: formatting output.", va_form.form_id)
                    _progress(f"SmartVA {va_form.form_id}: formatting results…")
                    output_file = va_smartva_formatsmartvaresult(va_form, workspace_dir)
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
                    print(f"DataSync Process [Updated SmartVA result '{va_form.form_id}: {va_sid}']")

                db.session.commit()
                va_smartva_updated += form_updated
                log.info("DataSync SmartVA [%s]: committed %d result(s).", va_form.form_id, form_updated)
                _progress(f"SmartVA {va_form.form_id}: {form_updated} result(s) saved.")

            except Exception as e:
                db.session.rollback()
                log.warning("DataSync SmartVA [%s] failed, skipping: %s", va_form.form_id, e, exc_info=True)
                _progress(f"SmartVA {va_form.form_id}: FAILED — {e}")

        log.info(
            "DataSync complete: added=%d updated=%d smartva=%d discarded=%d failed=%s",
            va_submissions_added, va_submissions_updated,
            va_smartva_updated, va_discarded_relrecords, failed_form_ids,
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
            "failed_forms": failed_form_ids,
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
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"{ts} {msg}")
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
