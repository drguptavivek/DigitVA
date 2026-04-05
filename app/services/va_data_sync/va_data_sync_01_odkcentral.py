import os
import time
import logging
import traceback
import math
from decimal import Decimal
import sqlalchemy as sa
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from flask import current_app
from app import db
from dateutil import parser
from app.models.map_project_site_odk import MapProjectSiteOdk
from app.models.map_project_odk import MapProjectOdk
from app.services.runtime_form_sync_service import sync_runtime_forms_from_site_mappings
from app.services.odk_connection_guard_service import (
    OdkConnectionCooldownError,
    guarded_odk_call,
    is_retryable_odk_connectivity_error,
)
from app.services.who_age_normalization import normalize_who_2022_age
from app.services.final_cod_authority_service import (
    abandon_active_recode_episode,
    upsert_final_cod_authority,
)
from app.services.workflow.definition import (
    PROTECTED_WORKFLOW_STATES,
    WORKFLOW_CODER_STEP1_SAVED,
    WORKFLOW_CODING_IN_PROGRESS,
    WORKFLOW_CODER_FINALIZED,
    WORKFLOW_FINALIZED_UPSTREAM_CHANGED,
    WORKFLOW_REVIEWER_ELIGIBLE,
    WORKFLOW_REVIEWER_FINALIZED,
    WORKFLOW_SMARTVA_PENDING,
    WORKFLOW_READY_FOR_CODING,
    WORKFLOW_CONSENT_REFUSED,
)
from app.services.workflow.state_store import (
    get_submission_workflow_state,
)
from app.services.workflow.transitions import (
    mark_upstream_change_detected,
    reset_incomplete_first_pass,
    route_synced_submission,
    system_actor,
)
from app.services.workflow.upstream_changes import record_protected_upstream_change
from app.services.submission_payload_version_service import (
    canonical_payload_fingerprint,
    create_or_update_pending_upstream_payload_version,
    ensure_active_payload_version,
    get_active_payload_version,
)
from app.models import (
    VaAllocations,
    VaAllocation,
    VaCoderReview,
    VaDataManagerReview,
    VaFinalAssessments,
    VaInitialAssessments,
    VaReviewerReview,
    VaUsernotes,
    VaSubmissions,
    VaStatuses,
    VaSubmissionUpstreamChange,
    VaSubmissionsAuditlog,
)
from app.utils import (
    va_odk_clientsetup,
    va_odk_delta_count,
    va_odk_fetch_instance_ids,
    va_odk_fetch_submissions,
    va_odk_fetch_submissions_by_ids,
    va_odk_sync_form_attachments,
    va_preprocess_summcatenotification,
    va_preprocess_categoriestodisplay,
)
from app.utils.va_form.va_form_02_formtyperesolution import (
    va_get_form_type_code_from_form,
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


# Use the canonical definition — do not maintain a local copy that can drift.
SYNC_PROTECTED_STATES = PROTECTED_WORKFLOW_STATES


def _handle_protected_submission_update(existing, va_submission: dict) -> None:
    """Update ODK metadata for a protected submission and transition to finalized_upstream_changed.

    Preserves all workflow artifacts (VaFinalAssessments, VaCoderReview, etc.).
    Only updates ODK-sourced metadata fields and the stored submission data.
    """
    from dateutil import parser as _parser
    va_sid = existing.va_sid
    current_workflow_state = get_submission_workflow_state(va_sid) or WORKFLOW_FINALIZED_UPSTREAM_CHANGED
    workflow_state_before = current_workflow_state
    if current_workflow_state == WORKFLOW_FINALIZED_UPSTREAM_CHANGED:
        latest_change = db.session.scalar(
            sa.select(VaSubmissionUpstreamChange)
            .where(VaSubmissionUpstreamChange.va_sid == va_sid)
            .order_by(VaSubmissionUpstreamChange.updated_at.desc())
            .limit(1)
        )
        if (
            latest_change is not None
            and latest_change.workflow_state_before
            and latest_change.workflow_state_before != WORKFLOW_FINALIZED_UPSTREAM_CHANGED
        ):
            workflow_state_before = latest_change.workflow_state_before
    incoming_updatedat = None
    if va_submission.get("updatedAt"):
        incoming_updatedat = _parser.isoparse(
            va_submission.get("updatedAt")
        ).replace(tzinfo=None)
    elif va_submission.get("SubmissionDate"):
        incoming_updatedat = _parser.isoparse(
            va_submission.get("SubmissionDate")
        ).replace(tzinfo=None)

    previous_payload_version_id = existing.active_payload_version_id
    pending_payload_version = create_or_update_pending_upstream_payload_version(
        existing,
        payload_data=va_submission,
        source_updated_at=incoming_updatedat,
        created_by_role="vasystem",
    )
    record_protected_upstream_change(
        existing,
        va_submission,
        workflow_state_before=workflow_state_before,
        detected_odk_updatedat=incoming_updatedat,
        previous_payload_version_id=previous_payload_version_id,
        incoming_payload_version_id=pending_payload_version.payload_version_id,
    )

    existing.va_sync_issue_code = None
    existing.va_sync_issue_detail = None
    existing.va_sync_issue_updated_at = None

    db.session.add(
        VaSubmissionsAuditlog(
            va_sid=va_sid,
            va_audit_byrole="vaadmin",
            va_audit_operation="u",
            va_audit_action="upstream_odk_data_changed_on_protected_submission",
        )
    )

    mark_upstream_change_detected(
        va_sid,
        reason="upstream_odk_data_changed",
        actor=system_actor(),
    )

    log.warning(
        "DataSync [%s]: upstream ODK data changed on protected submission — "
        "transitioned to finalized_upstream_changed",
        va_sid,
    )


def _normalize_consent(raw_value) -> str:
    """Persist consent values exactly when present, else as an empty string."""
    if raw_value is None:
        return ""
    return str(raw_value).strip()


def _consent_is_valid(consent_value: str) -> bool:
    """Return True only when explicit, non-refused consent is present.

    Consent must be explicitly given. Empty/missing = refused.
    Accepts any value except "no" (e.g. "yes", "telephonic_consent").
    """
    return bool(consent_value) and consent_value.lower() != "no"


def _workflow_state_for_consent(consent_value: str) -> str:
    """Return the appropriate initial workflow state based on consent."""
    return (
        WORKFLOW_SMARTVA_PENDING
        if _consent_is_valid(consent_value)
        else WORKFLOW_CONSENT_REFUSED
    )


def _attach_all_odk_comments(va_form, submissions, client=None, log_progress=None):
    """Attach all ODK review comments to fetched submissions.

    Only submissions currently in ODK `hasIssues` state fetch comments.
    The comments are stored in `OdkReviewComments` sorted newest first.

    Each comment fetch uses guarded_odk_call so failures are recorded against
    the shared connection guard (pacing + cooldown). OdkConnectionCooldownError
    is re-raised immediately to abort the rest of this form's comment fetching
    and propagate up to the per-form error handler. Transient per-submission
    failures (non-cooldown) are logged and skipped — comment data is best-effort
    and must not fail the entire form sync.

    NOTE: Adding or reading comments does NOT change __system/updatedAt on a
    submission in ODK Central. ODK only bumps updatedAt for data-XML edits.
    Comment fetching is therefore invisible to the delta check.
    """
    if not submissions:
        return submissions

    client = client or va_odk_clientsetup(project_id=va_form.project_id)
    comments_url_base = (
        f"projects/{va_form.odk_project_id}"
        f"/forms/{va_form.odk_form_id}/submissions"
    )

    for submission in submissions:
        submission["OdkReviewComments"] = []
        if submission.get("ReviewState") != "hasIssues":
            continue

        instance_id = submission.get("KEY")
        if not instance_id:
            continue

        url = f"{comments_url_base}/{instance_id}/comments"
        try:
            response = guarded_odk_call(
                lambda: client.session.get(url),
                client=client,
            )
            if response.status_code != 200:
                log.warning(
                    "_attach_all_odk_comments [%s]: HTTP %d for %s",
                    va_form.form_id, response.status_code, instance_id,
                )
                continue
            raw_comments = response.json()
            if raw_comments:
                submission["OdkReviewComments"] = [
                    {
                        "body": c.get("body", ""),
                        "created_at": c.get("createdAt", ""),
                    }
                    for c in sorted(
                        raw_comments,
                        key=lambda c: c.get("createdAt", ""),
                        reverse=True,
                    )
                ]
        except OdkConnectionCooldownError:
            raise
        except Exception as exc:
            log.warning(
                "_attach_all_odk_comments [%s]: error fetching comments for %s: %s",
                va_form.form_id, instance_id, exc,
            )

    return submissions


def _fetch_submission_xml_enrichment(va_form, instance_id: str, *, client) -> dict:
    """Fetch XML-only metadata fields needed for the canonical stored payload."""
    response = guarded_odk_call(
        lambda: client.session.get(
            f"projects/{va_form.odk_project_id}/forms/{va_form.odk_form_id}/submissions/{instance_id}.xml"
        ),
        client=client,
    )
    if response.status_code != 200:
        raise Exception(
            f"Submission XML fetch failed HTTP {response.status_code} for "
            f"{va_form.form_id}/{instance_id}: {response.text[:200]}"
        )

    root = ET.fromstring(response.text)
    device_node = root.find(".//deviceid")
    return {
        "FormVersion": root.attrib.get("version"),
        "DeviceID": (
            device_node.text.strip()
            if device_node is not None and device_node.text
            else None
        ),
    }


def _fetch_submission_metadata_enrichment(va_form, instance_id: str, *, client) -> dict:
    """Fetch extended Central submission metadata not present in OData rows."""
    response = guarded_odk_call(
        lambda: client.session.get(
            f"projects/{va_form.odk_project_id}/forms/{va_form.odk_form_id}/submissions/{instance_id}",
            headers={"X-Extended-Metadata": "true"},
        ),
        client=client,
    )
    if response.status_code != 200:
        raise Exception(
            f"Submission metadata fetch failed HTTP {response.status_code} for "
            f"{va_form.form_id}/{instance_id}: {response.text[:200]}"
        )

    payload = response.json() or {}
    current_version = payload.get("currentVersion") or {}
    return {
        "SubmitterID": payload.get("submitterId") or current_version.get("submitterId"),
        "instanceID": payload.get("instanceId") or current_version.get("instanceId"),
        "ReviewState": payload.get("reviewState"),
        "instanceName": current_version.get("instanceName"),
        "DeviceID": payload.get("deviceId") or current_version.get("deviceId"),
    }


def _fetch_submission_attachment_enrichment(va_form, instance_id: str, *, client) -> dict:
    """Fetch attachment-derived metadata fields needed in the canonical payload."""
    response = guarded_odk_call(
        lambda: client.session.get(
            f"projects/{va_form.odk_project_id}/forms/{va_form.odk_form_id}/submissions/{instance_id}/attachments"
        ),
        client=client,
    )
    if response.status_code != 200:
        raise Exception(
            f"Submission attachments fetch failed HTTP {response.status_code} for "
            f"{va_form.form_id}/{instance_id}: {response.text[:200]}"
        )

    attachments = response.json() or []
    audit_name = next(
        (
            attachment.get("name")
            for attachment in attachments
            if str(attachment.get("name") or "").strip().lower() == "audit.csv"
        ),
        None,
    )
    return {
        "AttachmentsExpected": len(attachments),
        "AttachmentsPresent": sum(1 for attachment in attachments if attachment.get("exists")),
        "audit": audit_name,
    }


def _sanitize_payload_value(value):
    """Normalize NaN-like values to None before persistence."""
    if isinstance(value, dict):
        return {
            key: _sanitize_payload_value(child_value)
            for key, child_value in value.items()
        }

    if isinstance(value, list):
        return [_sanitize_payload_value(item) for item in value]

    if isinstance(value, float) and math.isnan(value):
        return None

    if isinstance(value, Decimal) and value.is_nan():
        return None

    if isinstance(value, str) and value.strip().lower() == "nan":
        return None

    return value


def _enrich_submission_payload_for_storage(va_form, va_submission: dict, *, client=None) -> dict:
    """Return canonical OData-first payload plus required persisted metadata."""
    if client is None:
        return _sanitize_payload_value(va_submission)

    instance_id = va_submission.get("KEY")
    if not instance_id:
        return va_submission

    enriched = dict(va_submission)
    xml_data = _fetch_submission_xml_enrichment(va_form, instance_id, client=client)
    metadata = _fetch_submission_metadata_enrichment(va_form, instance_id, client=client)
    attachment_data = _fetch_submission_attachment_enrichment(
        va_form,
        instance_id,
        client=client,
    )

    enriched["FormVersion"] = xml_data.get("FormVersion")
    enriched["DeviceID"] = xml_data.get("DeviceID") or metadata.get("DeviceID")
    enriched["SubmitterID"] = metadata.get("SubmitterID")
    enriched["instanceID"] = metadata.get("instanceID") or instance_id
    enriched["ReviewState"] = enriched.get("ReviewState") or metadata.get("ReviewState")
    enriched["instanceName"] = enriched.get("instanceName") or metadata.get("instanceName")
    enriched["AttachmentsExpected"] = attachment_data.get("AttachmentsExpected")
    enriched["AttachmentsPresent"] = attachment_data.get("AttachmentsPresent")
    enriched["audit"] = attachment_data.get("audit")
    return _sanitize_payload_value(enriched)


def _submission_projection_fields(va_form, va_submission: dict) -> dict:
    va_submission_sid = va_submission.get("sid")
    va_submission_formid = va_submission.get("form_def")
    form_type_code = va_get_form_type_code_from_form(va_form)
    va_submission_date = parser.isoparse(va_submission.get("SubmissionDate"))
    va_submission_updatedat = (
        parser.isoparse(va_submission.get("updatedAt")).replace(tzinfo=None)
        if va_submission.get("updatedAt")
        else None
    )
    va_submission_datacollector = va_submission.get("SubmitterName") or "unknown"
    va_submission_reviewstate = va_submission.get("ReviewState")
    va_submission_reviewcomments = va_submission.get("OdkReviewComments")
    va_submission_instancename = va_submission.get("instanceName")
    va_submission_uniqueid = va_submission.get("unique_id")
    va_submission_uniqueidmask = va_submission.get("unique_id2") or "Unavailable"
    va_submission_consent = _normalize_consent(va_submission.get("Id10013"))
    _raw_lang = (
        va_submission.get("narr_language")
        if va_submission.get("narr_language")
        else va_submission.get("language")
    )
    va_submission_narrlang = _normalize_language(_raw_lang)
    normalized_age = normalize_who_2022_age(va_submission)
    va_submission_age = normalized_age.legacy_age_years
    va_submission_gender = va_submission.get("Id10019") or "unknown"
    return {
        "va_sid": va_submission_sid,
        "va_form_id": va_submission_formid,
        "va_submission_date": va_submission_date,
        "va_odk_updatedat": va_submission_updatedat,
        "va_data_collector": va_submission_datacollector,
        "va_odk_reviewstate": va_submission_reviewstate,
        "va_odk_reviewcomments": va_submission_reviewcomments,
        "va_instance_name": va_submission_instancename,
        "va_uniqueid_real": va_submission_uniqueid,
        "va_uniqueid_masked": va_submission_uniqueidmask,
        "va_consent": va_submission_consent,
        "va_narration_language": va_submission_narrlang,
        "va_deceased_age": va_submission_age,
        "va_deceased_age_normalized_days": normalized_age.normalized_age_days,
        "va_deceased_age_normalized_years": normalized_age.normalized_age_years,
        "va_deceased_age_source": normalized_age.normalized_age_source,
        "va_deceased_gender": va_submission_gender,
        "va_summary": va_preprocess_summcatenotification(va_submission)[0],
        "va_catcount": va_preprocess_summcatenotification(va_submission)[1],
        "va_category_list": va_preprocess_categoriestodisplay(
            va_submission,
            va_submission_formid,
            form_type_code=form_type_code,
        ),
    }


def _apply_submission_projection(submission: VaSubmissions, fields: dict, payload_data: dict) -> None:
    submission.va_sid = fields["va_sid"]
    submission.va_form_id = fields["va_form_id"]
    submission.va_submission_date = fields["va_submission_date"]
    submission.va_odk_updatedat = fields["va_odk_updatedat"]
    submission.va_data_collector = fields["va_data_collector"]
    submission.va_odk_reviewstate = fields["va_odk_reviewstate"]
    submission.va_odk_reviewcomments = fields["va_odk_reviewcomments"]
    submission.va_instance_name = fields["va_instance_name"]
    submission.va_uniqueid_real = fields["va_uniqueid_real"]
    submission.va_uniqueid_masked = fields["va_uniqueid_masked"]
    submission.va_consent = fields["va_consent"]
    submission.va_narration_language = fields["va_narration_language"]
    submission.va_deceased_age = fields["va_deceased_age"]
    submission.va_deceased_age_normalized_days = fields["va_deceased_age_normalized_days"]
    submission.va_deceased_age_normalized_years = fields["va_deceased_age_normalized_years"]
    submission.va_deceased_age_source = fields["va_deceased_age_source"]
    submission.va_deceased_gender = fields["va_deceased_gender"]
    submission.va_sync_issue_code = None
    submission.va_sync_issue_detail = None
    submission.va_sync_issue_updated_at = None
    submission.va_summary = fields["va_summary"]
    submission.va_catcount = fields["va_catcount"]
    submission.va_category_list = fields["va_category_list"]


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


def _upsert_form_submissions(
    va_form,
    va_submissions,
    amended_sids,
    upserted_map=None,
    *,
    client=None,
    enrich_payloads: bool = True,
    defer_protected_updates: bool = False,
):
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
        if enrich_payloads:
            va_submission = _enrich_submission_payload_for_storage(
                va_form,
                va_submission,
                client=client,
            )
        va_submission_amended = False

        fields = _submission_projection_fields(va_form, va_submission)
        va_submission_sid = fields["va_sid"]
        va_submission_formid = fields["va_form_id"]
        va_submission_updatedat = fields["va_odk_updatedat"]
        va_submission_consent = fields["va_consent"]
        incoming_payload_fingerprint = canonical_payload_fingerprint(va_submission)

        existing = db.session.scalar(
            sa.select(VaSubmissions).where(VaSubmissions.va_sid == va_submission_sid)
        )

        if existing:
            active_payload_version = get_active_payload_version(va_submission_sid)
            if active_payload_version is not None:
                active_payload_changed = (
                    canonical_payload_fingerprint(active_payload_version.payload_data or {})
                    != incoming_payload_fingerprint
                )
            else:
                active_payload_changed = True
        else:
            active_payload_changed = True

        if existing and active_payload_changed:
            current_state = get_submission_workflow_state(va_submission_sid)
            if current_state in SYNC_PROTECTED_STATES:
                if not defer_protected_updates:
                    _handle_protected_submission_update(existing, va_submission)
                va_submission_amended = True
                updated += 1
                if not defer_protected_updates:
                    print(
                        f"DataSync Process [Revoked protected VA submission "
                        f"'{va_submission_formid}: {va_submission_sid}' (was {current_state})]"
                    )
            else:
                _apply_submission_projection(existing, fields, va_submission)
                ensure_active_payload_version(
                    existing,
                    payload_data=va_submission,
                    source_updated_at=va_submission_updatedat,
                    created_by_role="vasystem",
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
                # Deactivate any data-manager not-codeable record so the
                # workflow state (re-routed below) is the sole authority.
                # ODK data change supersedes the DM's prior exclusion decision;
                # a DM may re-exclude after reviewing the updated payload.
                for record in db.session.scalars(
                    sa.select(VaDataManagerReview).where(
                        (VaDataManagerReview.va_sid == va_submission_sid)
                        & (VaDataManagerReview.va_dmreview_status == VaStatuses.active)
                    )
                ).all():
                    record.va_dmreview_status = VaStatuses.deactive
                    discarded += 1
                    db.session.add(VaSubmissionsAuditlog(
                        va_sid=va_submission_sid,
                        va_audit_entityid=record.va_dmreview_id,
                        va_audit_byrole="vaadmin",
                        va_audit_operation="d",
                        va_audit_action="va_datamanagerreview_cleared_during_datasync",
                    ))
                # Release any active coding allocation so the coder's session
                # is invalidated immediately rather than waiting for timeout.
                for record in db.session.scalars(
                    sa.select(VaAllocations).where(
                        (VaAllocations.va_sid == va_submission_sid)
                        & (VaAllocations.va_allocation_status == VaStatuses.active)
                    )
                ).all():
                    record.va_allocation_status = VaStatuses.deactive
                    db.session.add(VaSubmissionsAuditlog(
                        va_sid=va_submission_sid,
                        va_audit_entityid=record.va_allocation_id,
                        va_audit_byrole="vaadmin",
                        va_audit_operation="d",
                        va_audit_action="va_allocation_released_during_datasync",
                    ))
                va_submission_amended = True
                updated += 1
                route_synced_submission(
                    va_submission_sid,
                    consent_valid=_consent_is_valid(va_submission_consent),
                    reason="odk_submission_updated",
                    actor=system_actor(),
                )
                print(f"DataSync Process [Updated VA submission '{va_submission_formid}: {va_submission_sid}']")

        elif not existing:
            db.session.add(
                VaSubmissions(
                    va_sid=va_submission_sid,
                    va_form_id=fields["va_form_id"],
                    va_submission_date=fields["va_submission_date"],
                    va_odk_updatedat=va_submission_updatedat,
                    va_data_collector=fields["va_data_collector"],
                    va_odk_reviewstate=fields["va_odk_reviewstate"],
                    va_odk_reviewcomments=fields["va_odk_reviewcomments"],
                    va_instance_name=fields["va_instance_name"],
                    va_uniqueid_real=fields["va_uniqueid_real"],
                    va_uniqueid_masked=fields["va_uniqueid_masked"],
                    va_consent=fields["va_consent"],
                    va_narration_language=fields["va_narration_language"],
                    va_deceased_age=fields["va_deceased_age"],
                    va_deceased_age_normalized_days=fields["va_deceased_age_normalized_days"],
                    va_deceased_age_normalized_years=fields["va_deceased_age_normalized_years"],
                    va_deceased_age_source=fields["va_deceased_age_source"],
                    va_deceased_gender=fields["va_deceased_gender"],
                    va_sync_issue_code=None,
                    va_sync_issue_detail=None,
                    va_sync_issue_updated_at=None,
                    va_summary=fields["va_summary"],
                    va_catcount=fields["va_catcount"],
                    va_category_list=fields["va_category_list"],
                )
            )
            db.session.flush()
            created_submission = db.session.get(VaSubmissions, va_submission_sid)
            ensure_active_payload_version(
                created_submission,
                payload_data=va_submission,
                source_updated_at=va_submission_updatedat,
                created_by_role="vasystem",
            )
            route_synced_submission(
                va_submission_sid,
                consent_valid=_consent_is_valid(va_submission_consent),
                reason="submission_created_during_sync",
                actor=system_actor(),
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

        elif existing and va_submission_updatedat != existing.va_odk_updatedat:
            existing.va_odk_updatedat = va_submission_updatedat
            existing.va_odk_reviewstate = fields["va_odk_reviewstate"]
            existing.va_odk_reviewcomments = fields["va_odk_reviewcomments"]
            existing.va_instance_name = fields["va_instance_name"]
            existing.va_sync_issue_code = None
            existing.va_sync_issue_detail = None
            existing.va_sync_issue_updated_at = None
            db.session.add(
                VaSubmissionsAuditlog(
                    va_sid=va_submission_sid,
                    va_audit_byrole="vaadmin",
                    va_audit_operation="u",
                    va_audit_action="va_submission_metadata_refresh_during_datasync",
                )
            )
            va_submission_amended = True
            updated += 1

        if va_submission_amended:
            amended_sids.add(va_submission_sid)
            if upserted_map is not None:
                upserted_map[va_submission_sid] = va_submission.get("KEY", "")

    return added, updated, discarded, skipped


def _finalize_enriched_submissions_for_form(
    va_form,
    raw_submissions,
    upserted_map,
    amended_sids,
    *,
    client,
    log_progress=None,
):
    finalized = 0
    total = len(upserted_map or {})
    raw_by_sid = {
        submission.get("sid"): submission
        for submission in (raw_submissions or [])
        if submission.get("sid")
    }

    for index, va_sid in enumerate((upserted_map or {}).keys(), start=1):
        raw_submission = raw_by_sid.get(va_sid)
        if raw_submission is None:
            continue

        enriched_submission = _enrich_submission_payload_for_storage(
            va_form,
            raw_submission,
            client=client,
        )
        fields = _submission_projection_fields(va_form, enriched_submission)
        existing = db.session.scalar(
            sa.select(VaSubmissions).where(VaSubmissions.va_sid == va_sid)
        )
        if existing is None:
            continue

        incoming_payload_fingerprint = canonical_payload_fingerprint(enriched_submission)
        active_payload_version = get_active_payload_version(va_sid)
        if active_payload_version is not None:
            active_payload_changed = (
                canonical_payload_fingerprint(active_payload_version.payload_data or {})
                != incoming_payload_fingerprint
            )
        else:
            active_payload_changed = True
        current_state = get_submission_workflow_state(va_sid)

        if current_state in SYNC_PROTECTED_STATES and active_payload_changed:
            _handle_protected_submission_update(existing, enriched_submission)
        else:
            _apply_submission_projection(existing, fields, enriched_submission)
            ensure_active_payload_version(
                existing,
                payload_data=enriched_submission,
                source_updated_at=fields["va_odk_updatedat"],
                created_by_role="vasystem",
            )

        amended_sids.add(va_sid)
        finalized += 1
        if log_progress and (
            finalized == total or finalized % 50 == 0
        ):
            log_progress(
                f"[{va_form.form_id}] enrich: metadata enriched for "
                f"{finalized}/{total} submission(s)"
            )

    return finalized


def _release_active_allocations_after_sync() -> None:
    """Release active allocations after sync without bypassing the workflow layer."""
    active_allocations = db.session.scalars(
        sa.select(VaAllocations).where(
            VaAllocations.va_allocation_status == VaStatuses.active
        )
    ).all()

    for record in active_allocations:
        record.va_allocation_status = VaStatuses.deactive
        db.session.add(
            VaSubmissionsAuditlog(
                va_sid=record.va_sid,
                va_audit_entityid=record.va_allocation_id,
                va_audit_byrole="vasystem",
                va_audit_operation="d",
                va_audit_action="va_allocation_deletion_during_datasync",
            )
        )

        if record.va_allocation_for != VaAllocation.coding:
            continue

        va_initialassess = db.session.scalar(
            sa.select(VaInitialAssessments).where(
                VaInitialAssessments.va_sid == record.va_sid,
                VaInitialAssessments.va_iniassess_status == VaStatuses.active,
            )
        )
        if va_initialassess:
            va_initialassess.va_iniassess_status = VaStatuses.deactive
            db.session.add(
                VaSubmissionsAuditlog(
                    va_sid=va_initialassess.va_sid,
                    va_audit_entityid=va_initialassess.va_iniassess_id,
                    va_audit_byrole="vasystem",
                    va_audit_operation="d",
                    va_audit_action="va_partial_iniasses_deletion_during_datasync",
                )
            )

        current_state = get_submission_workflow_state(record.va_sid)
        if current_state in {
            None,
            WORKFLOW_CODING_IN_PROGRESS,
            WORKFLOW_CODER_STEP1_SAVED,
        }:
            reset_incomplete_first_pass(
                record.va_sid,
                reason="sync_reset_after_submission_update",
                actor=system_actor(),
            )

    db.session.commit()


def va_data_sync_odkcentral(
    log_progress=None,
    attachment_sync_dispatcher=None,
    enrichment_sync_dispatcher=None,
):
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

        connection_by_project = _resolve_project_connections()
        clients_by_group = {}

        form_ids = [f.form_id for f in va_forms]
        _progress(f"Processing {len(form_ids)} form(s): {', '.join(form_ids)}")

        va_submissions_added = 0
        va_submissions_updated = 0
        va_discarded_relrecords = 0
        va_smartva_updated = 0
        amended_sids: set[str] = set()
        failed_form_ids: list[str] = []
        cooldown_skipped_form_ids: list[str] = []
        enrichment_sync_forms_enqueued = 0
        attachment_sync_forms_enqueued = 0
        # Connections that entered cooldown mid-run — remaining forms on the
        # same connection are skipped without touching ODK.
        connections_in_cooldown: set = set()

        # ── Per-form: delta check → download → upsert → commit ─────────────────

        for form_id in form_ids:
            # Re-query each form and mapping fresh so that db.session.remove()
            # in a previous iteration's exception handler does not leave us with
            # detached ORM instances.
            va_form = db.session.get(VaForms, form_id)
            if va_form is None:
                _progress(f"[{form_id}] form not found — skipping")
                continue
            mapping = db.session.scalar(
                sa.select(MapProjectSiteOdk).where(
                    MapProjectSiteOdk.project_id == va_form.project_id,
                    MapProjectSiteOdk.site_id == va_form.site_id,
                )
            )
            # Preemptive cooldown skip — if this connection already tripped
            # cooldown for an earlier form this run, skip immediately.
            _form_connection_id = connection_by_project.get(va_form.project_id)
            if _form_connection_id and _form_connection_id in connections_in_cooldown:
                log.warning(
                    "DataSync [%s] skipped: connection %s still in cooldown",
                    form_id, _form_connection_id,
                )
                _progress(f"[{form_id}] SKIPPED — connection in cooldown")
                cooldown_skipped_form_ids.append(form_id)
                continue
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
                    gap_upserted_map: dict[str, str] = {}
                    gap_records_for_finalize: list[dict] = []
                    form_dir = os.path.join(current_app.config["APP_DATA"], va_form.form_id)
                    media_dir = os.path.join(form_dir, "media")
                    os.makedirs(media_dir, exist_ok=True)

                    for batch_start in range(0, len(missing_ids), _GAP_BATCH):
                        batch_ids = missing_ids[batch_start : batch_start + _GAP_BATCH]
                        batch_records = va_odk_fetch_submissions_by_ids(
                            va_form, batch_ids, client=odk_client,
                        )
                        if batch_records:
                            gap_records_for_finalize.extend(batch_records)
                            upserted_map_batch: dict[str, str] = {}
                            b_added, b_updated, b_discarded, b_skipped = _upsert_form_submissions(
                                va_form,
                                batch_records,
                                amended_sids,
                                upserted_map_batch,
                                enrich_payloads=False,
                                defer_protected_updates=True,
                            )
                            db.session.commit()
                            gap_added_total += b_added
                            gap_updated_total += b_updated
                            gap_skipped_total += b_skipped
                            gap_discarded_total += b_discarded
                            gap_upserted_map.update(upserted_map_batch)

                        done = min(batch_start + _GAP_BATCH, len(missing_ids))
                        skip_msg = f", {gap_skipped_total} skipped" if gap_skipped_total else ""
                        _progress(
                            f"[{va_form.form_id}] gap batch {done}/{len(missing_ids)}: "
                            f"+{gap_added_total} added, {gap_updated_total} updated{skip_msg}"
                        )

                    va_submissions_added += gap_added_total
                    va_submissions_updated += gap_updated_total
                    va_discarded_relrecords += gap_discarded_total

                    # Update last_synced_at after the gap sync path
                    if mapping:
                        mapping.last_synced_at = snapshot_time
                        db.session.commit()

                    skip_msg = f", {gap_skipped_total} skipped (no consent)" if gap_skipped_total else ""
                    _progress(
                        f"[{va_form.form_id}] gap sync done: "
                        f"+{gap_added_total} added, {gap_updated_total} updated{skip_msg}"
                    )
                    if gap_upserted_map:
                        if enrichment_sync_dispatcher is not None:
                            _progress(
                                f"[{va_form.form_id}] enrich: queueing {len(gap_upserted_map)} "
                                f"changed submission(s) for batched metadata enrichment…"
                            )
                            enrichment_sync_dispatcher(
                                va_form,
                                gap_upserted_map,
                                _progress,
                            )
                            enrichment_sync_forms_enqueued += 1
                        else:
                            _progress(
                                f"[{va_form.form_id}] enrich: adding ODK review comments to "
                                f"{len(gap_records_for_finalize)} submission(s)…"
                            )
                            gap_records_for_finalize = _attach_all_odk_comments(
                                va_form,
                                gap_records_for_finalize,
                                client=odk_client,
                                log_progress=_progress,
                            )
                            _progress(
                                f"[{va_form.form_id}] enrich: review comments added for "
                                f"{len(gap_records_for_finalize)} submission(s)"
                            )
                            _progress(
                                f"[{va_form.form_id}] enrich: enriching submission metadata…"
                            )
                            enriched_count = _finalize_enriched_submissions_for_form(
                                va_form,
                                gap_records_for_finalize,
                                gap_upserted_map,
                                amended_sids,
                                client=odk_client,
                                log_progress=_progress,
                            )
                            db.session.commit()
                            _progress(
                                f"[{va_form.form_id}] enrich: complete — "
                                f"metadata enriched for {enriched_count} submission(s)"
                            )
                            if attachment_sync_dispatcher is not None:
                                attachment_sync_dispatcher(
                                    va_form,
                                    gap_upserted_map,
                                    media_dir,
                                    _progress,
                                )
                                attachment_sync_forms_enqueued += 1
                            else:
                                attachment_totals = va_odk_sync_form_attachments(
                                    va_form,
                                    gap_upserted_map,
                                    media_dir,
                                    client_factory=lambda: _get_or_create_sync_odk_client(
                                        clients_by_group, connection_by_project,
                                        va_form, mapping,
                                    ),
                                    progress_callback=_progress,
                                )
                                db.session.commit()
                                _progress(
                                    f"[{va_form.form_id}] attachments: complete — "
                                    f"{attachment_totals['downloaded']} downloaded, "
                                    f"{attachment_totals['skipped']} skipped"
                                    + (
                                        f", {attachment_totals['errors']} errors"
                                        if attachment_totals["errors"]
                                        else ""
                                    )
                                )
                                _progress(
                                    f"[{va_form.form_id}] workflow: attachments finished for "
                                    f"{len(gap_upserted_map)} submission(s); ready for SmartVA"
                                )
                                from app.services import smartva_service
                                _progress(
                                    f"SmartVA {va_form.form_id}: starting for "
                                    f"{len(gap_upserted_map)} submission(s)…"
                                )
                                saved = smartva_service.generate_for_form(
                                    va_form,
                                    amended_sids=set(gap_upserted_map),
                                    log_progress=_progress,
                                )
                                va_smartva_updated += saved
                                _progress(
                                    f"[{va_form.form_id}] pipeline: complete — "
                                    f"{attachment_totals['downloaded']} attachments downloaded, "
                                    f"{saved} SmartVA result(s) generated"
                                    + (
                                        f", {attachment_totals['errors']} attachment error(s)"
                                        if attachment_totals["errors"]
                                        else ""
                                    )
                                )
                    continue  # skip the normal upsert/attachment flow below
                else:
                    # Normal delta or first-sync fetch
                    log.info("DataSync [Fetching submissions via OData: %s].", va_form.form_id)
                    _progress(f"[{va_form.form_id}] fetch: downloading submissions from ODK…")
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
                    _progress(
                        f"[{va_form.form_id}] fetch: downloaded "
                        f"{len(va_submissions_raw)} submission(s) from ODK"
                    )

                form_dir = os.path.join(current_app.config["APP_DATA"], va_form.form_id)
                media_dir = os.path.join(form_dir, "media")
                os.makedirs(media_dir, exist_ok=True)

                # Upsert submissions for this form only
                log.info("DataSync [Upserting submissions: %s].", va_form.form_id)
                _progress(
                    f"[{va_form.form_id}] upsert: saving basic submission data for "
                    f"{len(va_submissions_raw)} submission(s)…"
                )
                upserted_map: dict[str, str] = {}  # {va_sid: instance_id}
                form_added, form_updated, form_discarded, form_skipped = _upsert_form_submissions(
                    va_form,
                    va_submissions_raw,
                    amended_sids,
                    upserted_map,
                    enrich_payloads=False,
                    defer_protected_updates=True,
                )
                va_submissions_added += form_added
                va_submissions_updated += form_updated
                va_discarded_relrecords += form_discarded

                # Per-form commit — isolates failures so other forms are not rolled back
                db.session.commit()
                skip_msg = f", {form_skipped} skipped" if form_skipped else ""
                _progress(
                    f"[{va_form.form_id}] upsert: complete — "
                    f"+{form_added} added, {form_updated} updated{skip_msg}"
                )
                if upserted_map:
                    if enrichment_sync_dispatcher is not None:
                        _progress(
                            f"[{va_form.form_id}] enrich: queueing {len(upserted_map)} "
                            f"changed submission(s) for batched metadata enrichment…"
                        )
                        enrichment_sync_dispatcher(
                            va_form,
                            upserted_map,
                            _progress,
                        )
                        enrichment_sync_forms_enqueued += 1
                    else:
                        _progress(
                            f"[{va_form.form_id}] enrich: adding ODK review comments to "
                            f"{len(va_submissions_raw)} submission(s)…"
                        )
                        va_submissions_raw = _attach_all_odk_comments(
                            va_form,
                            va_submissions_raw,
                            client=odk_client,
                            log_progress=_progress,
                        )
                        _progress(
                            f"[{va_form.form_id}] enrich: review comments added for "
                            f"{len(va_submissions_raw)} submission(s)"
                        )
                        _progress(
                            f"[{va_form.form_id}] enrich: enriching submission metadata…"
                        )
                        enriched_count = _finalize_enriched_submissions_for_form(
                            va_form,
                            va_submissions_raw,
                            upserted_map,
                            amended_sids,
                            client=odk_client,
                            log_progress=_progress,
                        )
                        db.session.commit()
                        _progress(
                            f"[{va_form.form_id}] enrich: complete — "
                            f"metadata enriched for {enriched_count} submission(s)"
                        )
                log.info(
                    "DataSync [%s]: committed — added=%d updated=%d discarded=%d skipped=%d",
                    va_form.form_id, form_added, form_updated, form_discarded, form_skipped,
                )

                # Sync attachments for upserted submissions (ETag-based, no rmtree)
                if upserted_map:
                    if attachment_sync_dispatcher is not None:
                        _progress(
                            f"[{va_form.form_id}] attachments: queueing downloads for "
                            f"{len(upserted_map)} changed submission(s)…"
                        )
                        attachment_sync_dispatcher(
                            va_form,
                            upserted_map,
                            media_dir,
                            _progress,
                        )
                        attachment_sync_forms_enqueued += 1
                    else:
                        total_attach = len(upserted_map)
                        _progress(
                            f"[{va_form.form_id}] attachments: downloading files for "
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
                        try:
                            db.session.commit()  # commit ETag records
                        except sa.exc.OperationalError:
                            db.session.rollback()
                            db.session.remove()
                            log.warning(
                                "DataSync [%s]: stale DB connection after attachment "
                                "download, ETag records lost — will re-sync next run.",
                                form_id,
                            )
                            # Session reset detaches all ORM instances.
                            # Reload form + mapping for the current iteration.
                            va_form = db.session.get(VaForms, form_id)
                            if va_form is None:
                                _progress(
                                    f"[{form_id}] attachments: form missing after DB "
                                    "session reset — skipping SmartVA for this form"
                                )
                                failed_form_ids.append(form_id)
                                continue
                            mapping = db.session.scalar(
                                sa.select(MapProjectSiteOdk).where(
                                    MapProjectSiteOdk.project_id == va_form.project_id,
                                    MapProjectSiteOdk.site_id == va_form.site_id,
                                )
                            )
                        _progress(
                            f"[{va_form.form_id}] attachments: complete — "
                            f"{attachment_totals['downloaded']} downloaded, "
                            f"{attachment_totals['skipped']} skipped"
                            + (
                                f", {attachment_totals['errors']} errors"
                                if attachment_totals["errors"]
                                else ""
                            )
                        )
                        _progress(
                            f"[{va_form.form_id}] workflow: attachments finished for "
                            f"{len(upserted_map)} submission(s); ready for SmartVA"
                        )
                        from app.services import smartva_service
                        _progress(
                            f"SmartVA {va_form.form_id}: starting for "
                            f"{len(upserted_map)} submission(s)…"
                        )
                        saved = smartva_service.generate_for_form(
                            va_form,
                            amended_sids=set(upserted_map),
                            log_progress=_progress,
                        )
                        va_smartva_updated += saved
                        _progress(
                            f"[{va_form.form_id}] pipeline: complete — "
                            f"{attachment_totals['downloaded']} attachments downloaded, "
                            f"{saved} SmartVA result(s) generated"
                            + (
                                f", {attachment_totals['errors']} attachment error(s)"
                                if attachment_totals["errors"]
                                else ""
                            )
                        )

                # Record successful sync time
                if mapping:
                    mapping.last_synced_at = snapshot_time
                    db.session.commit()

            except OdkConnectionCooldownError as form_err:
                db.session.rollback()
                if _form_connection_id:
                    connections_in_cooldown.add(_form_connection_id)
                log.warning(
                    "DataSync [%s] skipped: ODK connection in cooldown until %s — %s",
                    form_id, form_err.cooldown_until, form_err.last_failure_message,
                )
                _progress(
                    f"[{form_id}] SKIPPED (connection cooldown until "
                    f"{form_err.cooldown_until.strftime('%H:%M:%S UTC')})"
                )
                cooldown_skipped_form_ids.append(form_id)
            except Exception as form_err:
                db.session.rollback()
                db.session.remove()
                log.error(
                    "DataSync [%s] failed: %s",
                    form_id, form_err, exc_info=True,
                )
                _progress(f"[{form_id}] FAILED: {form_err}")
                failed_form_ids.append(form_id)

        # ── Release allocations (global — runs after all forms) ─────────────────

        _progress("Releasing active coding allocations…")
        _release_active_allocations_after_sync()

        phase1_msg = (
            f"Per-form sync loop complete — added: {va_submissions_added}, "
            f"updated: {va_submissions_updated}, discarded: {va_discarded_relrecords}"
        )
        if failed_form_ids:
            phase1_msg += f" | failed forms: {', '.join(failed_form_ids)}"
        if cooldown_skipped_form_ids:
            phase1_msg += f" | cooldown-skipped forms: {', '.join(cooldown_skipped_form_ids)}"
        log.info(
            "DataSync Phase 1 complete: added=%d updated=%d discarded=%d "
            "failed=%s cooldown_skipped=%s",
            va_submissions_added, va_submissions_updated, va_discarded_relrecords,
            failed_form_ids, cooldown_skipped_form_ids,
        )
        _progress(phase1_msg)

        if attachment_sync_dispatcher is not None and attachment_sync_forms_enqueued:
            _progress(
                f"Attachment sync queued for {attachment_sync_forms_enqueued} form(s); "
                "SmartVA will run after attachment batches finish."
            )
        elif enrichment_sync_forms_enqueued:
            _progress(
                f"Enrichment sync queued for {enrichment_sync_forms_enqueued} form(s); "
                "attachment batches and SmartVA will run after enrichment finishes."
            )

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
            "enrichment_sync_forms_enqueued": enrichment_sync_forms_enqueued,
            "attachment_sync_forms_enqueued": attachment_sync_forms_enqueued,
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
    from app.services import smartva_service
    return smartva_service.generate_all_pending(log_progress=log_progress)
