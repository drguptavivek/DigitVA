"""Backfill ODK enrichment metadata for payload versions stored without it.

When submissions are synced without an active ODK client (or before the
enrichment step was added), the stored payload_data contains only the raw
OData form fields.  The six metadata fields required for the sync-completeness
dashboard — FormVersion, DeviceID, SubmitterID, instanceID, AttachmentsExpected,
AttachmentsPresent — are absent.

All six fields are in VOLATILE_PAYLOAD_KEYS, so they are excluded from the
canonical fingerprint.  Updating them in-place on an existing payload version
does NOT change the fingerprint and does NOT trigger a new version.

Update strategy: explicit sa.update() per row with json.dumps() + ::jsonb cast.
SQLAlchemy's ORM flush uses executemany for batches which loses the JSONB type
adapter and causes a bind error; explicit UPDATE statements avoid this.

Entry points
------------
  enrich_unenriched_payloads()  — call from CLI or Celery task
"""

from __future__ import annotations

import logging
import os

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from flask import current_app

from app import db
from app.models import VaForms, VaSubmissions
from app.models.va_selectives import VaStatuses
from app.models.va_smartva_results import VaSmartvaResults
from app.models.va_submission_payload_versions import VaSubmissionPayloadVersion
from app.services.submission_payload_version_service import _derive_payload_metadata

log = logging.getLogger(__name__)

_BATCH_SIZE = 10


def _submission_label(*, index: int, total: int, va_sid: str, form_id: str | None = None) -> str:
    base = f"Submission {index}/{total} [{va_sid}]"
    if form_id:
        return f"{base} [{form_id}]"
    return base


def _log_submission_start(sub: str) -> None:
    log.info("%s", sub)


def _log_submission_step(message: str, *args) -> None:
    rendered = message % args if args else message
    log.info("  %s", rendered)


def _log_submission_inline_status(*, va_sid: str, audit_by_sid: dict) -> None:
    row = audit_by_sid.get(va_sid) or {}
    log.info(
        "  final: enrich=%s attachments=%s smartva=%s workflow=%s",
        row.get("enrich", "pending"),
        row.get("attachments", "pending"),
        row.get("smartva", "pending"),
        row.get("workflow", "pending"),
    )


def _ensure_submission_audit(
    audit_by_sid: dict,
    *,
    va_sid: str,
    form_id: str,
    index: int,
    total: int,
) -> dict:
    row = audit_by_sid.get(va_sid)
    if row is None:
        row = {
            "va_sid": va_sid,
            "form_id": form_id,
            "index": index,
            "total": total,
            "enrich": "pending",
            "attachments": "pending",
            "smartva": "pending",
            "workflow": "pending",
            "notes": [],
            "final_status": "pending",
        }
        audit_by_sid[va_sid] = row
    return row


def _set_stage(audit_by_sid: dict, va_sid: str, stage: str, value: str, note: str | None = None) -> None:
    row = audit_by_sid.get(va_sid)
    if row is None:
        return
    row[stage] = value
    if note:
        row["notes"].append(note)


def _log_submission_audit_report(audit_by_sid: dict) -> dict[str, int]:
    """Return final status counts without replaying per-submission lines."""
    counts = {"completed": 0, "partial": 0, "failed": 0}
    if not audit_by_sid:
        log.info("Submission audit: no processed submissions")
        return counts

    def _final_status(row: dict) -> str:
        stages = [row["enrich"], row["attachments"], row["smartva"], row["workflow"]]
        if any(str(s).startswith("failed") for s in stages):
            return "failed"
        if all(s in {"done", "already-current", "not-eligible", "skip:no-instance-id", "dry-run"} for s in stages):
            return "completed"
        if row["enrich"] in {"done", "dry-run"}:
            return "partial"
        return "failed"

    ordered = sorted(audit_by_sid.values(), key=lambda r: (r["index"], r["form_id"], r["va_sid"]))
    for row in ordered:
        status = _final_status(row)
        row["final_status"] = status
        counts[status] += 1

    log.info(
        "Submission audit summary: completed=%d partial=%d failed=%d",
        counts["completed"],
        counts["partial"],
        counts["failed"],
    )
    return counts


def enrich_unenriched_payloads(
    *,
    form_id: str | None = None,
    batch_size: int = _BATCH_SIZE,
    max_forms: int | None = None,
    max_per_form: int | None = None,
    dry_run: bool = False,
    force_attachments_redownload: bool = False,
) -> dict:
    """Fetch ODK metadata for every active payload version missing has_required_metadata.

    Groups work by form so one ODK client is created per project.  Commits
    after each batch using explicit SQL UPDATE (not ORM flush) to avoid
    SQLAlchemy executemany dropping the JSONB type adapter.

    Args:
        form_id:      if given, restrict to submissions belonging to this form.
        batch_size:   how many submissions to UPDATE per transaction (default 10).
        max_forms:    stop after processing this many forms (useful for test runs).
        max_per_form: cap submissions processed per form (useful for smoke tests).
        dry_run:      fetch enrichment data but write nothing.

    Returns:
        {
            "processed": int,
            "enriched": int,
            "failed": int,
            "skipped": int,
            "attachments_checked": int,
            "attachments_downloaded": int,
            "attachments_skipped": int,
            "attachments_errors": int,
            "smartva_checked": int,
            "smartva_missing": int,
            "smartva_generated": int,
            "smartva_failed": int,
            "smartva_noop": int,
            "workflow_attachment_to_smartva": int,
            "workflow_smartva_to_ready": int,
            "workflow_errors": int,
        }
    """
    from app.services.va_data_sync.va_data_sync_01_odkcentral import (
        _enrich_submission_payload_for_storage,
    )
    from app.utils.va_odk.va_odk_01_clientsetup import va_odk_clientsetup
    from app.services.workflow.transitions import system_actor

    stats = {
        "processed": 0,
        "enriched": 0,
        "failed": 0,
        "skipped": 0,
        "attachments_checked": 0,
        "attachments_downloaded": 0,
        "attachments_skipped": 0,
        "attachments_errors": 0,
        "attachments_etag_not_modified": 0,
        "attachments_local_present_on_etag": 0,
        "attachments_local_missing_on_etag": 0,
        "smartva_checked": 0,
        "smartva_missing": 0,
        "smartva_generated": 0,
        "smartva_failed": 0,
        "smartva_noop": 0,
        "workflow_attachment_to_smartva": 0,
        "workflow_smartva_to_ready": 0,
        "workflow_errors": 0,
        "audit_completed": 0,
        "audit_partial": 0,
        "audit_failed": 0,
    }
    smartva_candidate_sids: set[str] = set()
    attachment_candidate_by_form: dict[str, dict[str, str]] = {}
    audit_by_sid: dict[str, dict] = {}
    app_data_root = current_app.config.get("APP_DATA") if not dry_run else None
    if not dry_run and not app_data_root:
        log.warning("APP_DATA not configured: attachment stage will fail per submission")

    # --- Step 1: load rows and immediately release the DB connection -----------
    # We must NOT hold an open transaction during ODK HTTP calls — the DB has
    # an idle-in-transaction timeout that kills connections left open while
    # network I/O is in progress.
    query = (
        sa.select(
            VaSubmissionPayloadVersion.payload_version_id,
            VaSubmissionPayloadVersion.va_sid,
            VaSubmissionPayloadVersion.payload_data,
            VaSubmissions.va_form_id.label("va_form_id"),
        )
        .join(VaSubmissions, VaSubmissions.va_sid == VaSubmissionPayloadVersion.va_sid)
        .where(
            VaSubmissionPayloadVersion.version_status == "active",
            VaSubmissionPayloadVersion.has_required_metadata.is_(False),
        )
        .order_by(VaSubmissions.va_form_id, VaSubmissions.va_sid)
    )
    if form_id:
        query = query.where(VaSubmissions.va_form_id == form_id)

    log.debug("Query: load unenriched active payload versions")
    rows = db.session.execute(query).mappings().all()
    db.session.close()  # release connection before ODK I/O begins
    log.debug("Query complete: rows=%d, DB connection released", len(rows))

    if not rows:
        log.info("Nothing to do: all active payloads already enriched")
        return stats

    log.debug("Plan: unenriched active payload versions=%d", len(rows))

    # Load form objects into plain dicts so they survive session.close()
    form_ids = list(dict.fromkeys(r["va_form_id"] for r in rows))
    log.debug("Plan: forms=%d -> %s", len(form_ids), form_ids)
    if max_forms is not None:
        form_ids = form_ids[:max_forms]
        log.debug("Plan: apply --max-forms=%d -> %s", max_forms, form_ids)

    forms_by_id: dict[str, VaForms] = {}
    for fid in form_ids:
        va_form = db.session.get(VaForms, fid)
        if va_form:
            forms_by_id[fid] = va_form
            log.debug("Form %s loaded (project=%s)", fid, va_form.project_id)
        else:
            log.warning("Form %s not found in VaForms", fid)
    db.session.close()

    # Group rows by form
    by_form: dict[str, list] = {}
    for row in rows:
        fid = row["va_form_id"]
        if fid in forms_by_id:
            by_form.setdefault(fid, []).append(row)

    # --- Step 2: ODK I/O + per-submission atomic writes ----------------------

    total_candidates = 0
    for fid in form_ids:
        form_rows = by_form.get(fid) or []
        if max_per_form is not None and len(form_rows) > max_per_form:
            total_candidates += max_per_form
        else:
            total_candidates += len(form_rows)

    submission_index = 0
    for fid in form_ids:
        form_rows = by_form.get(fid)
        if not form_rows:
            log.warning("Form %s: no rows found in by_form; skip", fid)
            continue

        va_form = forms_by_id.get(fid)
        if va_form is None:
            log.warning("Form %s: missing form config, skipping submissions=%d", fid, len(form_rows))
            stats["skipped"] += len(form_rows)
            continue

        log.debug("Form %s: init ODK client (project=%s)", fid, va_form.project_id)
        try:
            client = va_odk_clientsetup(project_id=va_form.project_id)
            log.debug("Form %s: ODK client ready", fid)
        except Exception as exc:
            log.warning(
                "Form %s: ODK client setup failed (project=%s): %s; skip form",
                fid, va_form.project_id, exc,
            )
            stats["skipped"] += len(form_rows)
            continue

        if max_per_form is not None and len(form_rows) > max_per_form:
            log.debug(
                "Form %s: apply --max-per-form=%d of %d",
                fid, max_per_form, len(form_rows),
            )
            form_rows = form_rows[:max_per_form]

        log.debug("Form %s: enrich submissions=%d", fid, len(form_rows))
        media_dir = None
        if not dry_run and app_data_root:
            form_dir = os.path.join(app_data_root, fid)
            media_dir = os.path.join(form_dir, "media")
            os.makedirs(media_dir, exist_ok=True)
        workflow_actor = system_actor() if not dry_run else None

        for row in form_rows:
            stats["processed"] += 1
            submission_index += 1
            sub = _submission_label(
                index=submission_index,
                total=total_candidates,
                va_sid=row["va_sid"],
                form_id=fid,
            )
            _ensure_submission_audit(
                audit_by_sid,
                va_sid=row["va_sid"],
                form_id=fid,
                index=submission_index,
                total=total_candidates,
            )
            _log_submission_start(sub)
            try:
                _log_submission_step("enrich: start")
                key_val = (row["payload_data"] or {}).get("KEY")
                if not key_val:
                    log.warning("  enrich: skip (missing KEY)")
                    stats["skipped"] += 1
                    _set_stage(audit_by_sid, row["va_sid"], "enrich", "failed:missing-key")
                    _set_stage(audit_by_sid, row["va_sid"], "attachments", "skip:no-key")
                    _set_stage(audit_by_sid, row["va_sid"], "smartva", "skip:no-key")
                    _set_stage(audit_by_sid, row["va_sid"], "workflow", "skip:no-key")
                    continue
                smartva_candidate_sids.add(row["va_sid"])
                attachment_candidate_by_form.setdefault(fid, {})[row["va_sid"]] = key_val

                _log_submission_step("enrich: fetch ODK metadata")
                try:
                    enriched = _enrich_submission_payload_for_storage(
                        va_form, row["payload_data"], client=client
                    )
                except Exception as exc:
                    log.warning("  enrich: failed (ODK fetch): %s", exc)
                    stats["failed"] += 1
                    _set_stage(audit_by_sid, row["va_sid"], "enrich", "failed:odk-fetch", str(exc))
                    continue

                if enriched is None:
                    log.warning("  enrich: failed (empty enrichment result)")
                    stats["failed"] += 1
                    _set_stage(audit_by_sid, row["va_sid"], "enrich", "failed:empty-enrichment")
                    continue

                _log_submission_step("enrich: derive metadata")
                has_meta, att_expected = _derive_payload_metadata(enriched)
                if not has_meta:
                    log.warning(
                        "  enrich: metadata incomplete, missing=%s",
                        [
                            k
                            for k in (
                                "FormVersion",
                                "DeviceID",
                                "SubmitterID",
                                "instanceID",
                                "AttachmentsExpected",
                                "AttachmentsPresent",
                            )
                            if not enriched.get(k)
                        ],
                    )
                else:
                    _log_submission_step("enrich: metadata ok")

                if not dry_run:
                    _log_submission_step("enrich: save DB")
                    try:
                        _flush_single_update(
                            pv_id=row["payload_version_id"],
                            payload_data=enriched,
                            has_required_metadata=has_meta,
                            attachments_expected=att_expected,
                        )
                        stats["enriched"] += 1
                        _set_stage(audit_by_sid, row["va_sid"], "enrich", "done")
                        _run_single_submission_attachment(
                            va_form=va_form,
                            media_dir=media_dir,
                            va_sid=row["va_sid"],
                            instance_id=key_val,
                            client=client,
                            stats=stats,
                            audit_by_sid=audit_by_sid,
                            force_redownload=force_attachments_redownload,
                        )
                        _run_single_submission_smartva(
                            va_sid=row["va_sid"],
                            stats=stats,
                            audit_by_sid=audit_by_sid,
                        )
                        _run_single_submission_workflow_transition(
                            va_sid=row["va_sid"],
                            stats=stats,
                            audit_by_sid=audit_by_sid,
                            workflow_actor=workflow_actor,
                        )
                    except Exception as exc:
                        db.session.rollback()
                        stats["failed"] += 1
                        log.error("  enrich: save failed: %s", exc, exc_info=True)
                        _set_stage(audit_by_sid, row["va_sid"], "enrich", "failed:db-save", str(exc))
                else:
                    stats["enriched"] += 1
                    _set_stage(audit_by_sid, row["va_sid"], "enrich", "dry-run")
            finally:
                _log_submission_inline_status(va_sid=row["va_sid"], audit_by_sid=audit_by_sid)

    # --- Step 3: staged follow-through ---------------------------------------
    if dry_run:
        stats["smartva_checked"] = len(smartva_candidate_sids)
        stats["smartva_missing"] = len(
            _find_missing_current_payload_smartva_sids(smartva_candidate_sids)
        )
        stats["attachments_checked"] = sum(
            len(form_map) for form_map in attachment_candidate_by_form.values()
        )
        log.info(
            (
                "[dry-run] stage checks only — "
                "attachments_checked=%d smartva_checked=%d missing_current_payload=%d"
            ),
            stats["attachments_checked"],
            stats["smartva_checked"],
            stats["smartva_missing"],
        )
        for va_sid in smartva_candidate_sids:
            _set_stage(audit_by_sid, va_sid, "attachments", "dry-run")
            _set_stage(audit_by_sid, va_sid, "smartva", "dry-run")
            _set_stage(audit_by_sid, va_sid, "workflow", "dry-run")

    audit_counts = _log_submission_audit_report(audit_by_sid)
    stats["audit_completed"] = audit_counts.get("completed", 0)
    stats["audit_partial"] = audit_counts.get("partial", 0)
    stats["audit_failed"] = audit_counts.get("failed", 0)

    log.info(
        (
            "Run done — processed=%d enriched=%d failed=%d skipped=%d "
            "attachments_checked=%d attachments_downloaded=%d attachments_skipped=%d "
            "attachments_errors=%d attachments_etag_not_modified=%d "
            "attachments_local_present_on_etag=%d attachments_local_missing_on_etag=%d "
            "smartva_checked=%d smartva_missing=%d smartva_generated=%d "
            "smartva_failed=%d smartva_noop=%d "
            "workflow_attachment_to_smartva=%d workflow_smartva_to_ready=%d "
            "workflow_errors=%d"
        ),
        stats["processed"],
        stats["enriched"],
        stats["failed"],
        stats["skipped"],
        stats["attachments_checked"],
        stats["attachments_downloaded"],
        stats["attachments_skipped"],
        stats["attachments_errors"],
        stats["attachments_etag_not_modified"],
        stats["attachments_local_present_on_etag"],
        stats["attachments_local_missing_on_etag"],
        stats["smartva_checked"],
        stats["smartva_missing"],
        stats["smartva_generated"],
        stats["smartva_failed"],
        stats["smartva_noop"],
        stats["workflow_attachment_to_smartva"],
        stats["workflow_smartva_to_ready"],
        stats["workflow_errors"],
    )
    return stats


def _run_single_submission_attachment(
    *,
    va_form,
    media_dir: str | None,
    va_sid: str,
    instance_id: str,
    client,
    stats: dict,
    audit_by_sid: dict,
    force_redownload: bool = False,
) -> None:
    from app.utils.va_odk.va_odk_07_syncattachments import va_odk_sync_submission_attachments

    stats["attachments_checked"] += 1
    if not media_dir:
        stats["attachments_errors"] += 1
        _set_stage(audit_by_sid, va_sid, "attachments", "failed:no-app-data")
        log.warning("  attachments: failed (APP_DATA not configured)")
        return
    if not instance_id:
        stats["attachments_errors"] += 1
        _set_stage(audit_by_sid, va_sid, "attachments", "skip:no-instance-id")
        log.warning("  attachments: skip (missing instance id)")
        return
    try:
        per_sid = va_odk_sync_submission_attachments(
            va_form,
            instance_id,
            va_sid,
            media_dir,
            client=client,
            force_redownload=force_redownload,
        )
        db.session.commit()
        downloaded = int(per_sid.get("downloaded", 0) or 0)
        skipped = int(per_sid.get("skipped", 0) or 0)
        errors = int(per_sid.get("errors", 0) or 0)
        etag_not_modified = int(per_sid.get("etag_not_modified", 0) or 0)
        local_present_on_etag = int(per_sid.get("local_present_on_etag", 0) or 0)
        local_missing_on_etag = int(per_sid.get("local_missing_on_etag", 0) or 0)
        stats["attachments_downloaded"] += downloaded
        stats["attachments_skipped"] += skipped
        stats["attachments_errors"] += errors
        stats["attachments_etag_not_modified"] += etag_not_modified
        stats["attachments_local_present_on_etag"] += local_present_on_etag
        stats["attachments_local_missing_on_etag"] += local_missing_on_etag
        _set_stage(
            audit_by_sid,
            va_sid,
            "attachments",
            "done" if errors == 0 else "failed:sync",
            (
                f"downloaded={downloaded} skipped={skipped} "
                f"etag304={etag_not_modified} "
                f"local_missing_on_etag={local_missing_on_etag}"
            ),
        )
        _log_submission_step(
            (
                "attachments: downloaded=%d skipped=%d errors=%d "
                "etag_not_modified=%d local_present_on_etag=%d local_missing_on_etag=%d"
            ),
            downloaded,
            skipped,
            errors,
            etag_not_modified,
            local_present_on_etag,
            local_missing_on_etag,
        )
    except Exception as exc:
        db.session.rollback()
        stats["attachments_errors"] += 1
        _set_stage(audit_by_sid, va_sid, "attachments", "failed:sync", str(exc))
        log.error("  attachments: failed: %s", exc, exc_info=True)


def _run_single_submission_smartva(
    *,
    va_sid: str,
    stats: dict,
    audit_by_sid: dict,
) -> None:
    from app.services import smartva_service

    stats["smartva_checked"] += 1
    missing = _find_missing_current_payload_smartva_sids({va_sid})
    if not missing:
        _set_stage(audit_by_sid, va_sid, "smartva", "already-current")
        _log_submission_step("smartva: already current payload")
        return
    stats["smartva_missing"] += 1
    try:
        _log_submission_step("smartva: start")
        saved = smartva_service.generate_for_submission(
            va_sid,
            trigger_source="payload_backfill_enrich",
            log_progress=lambda msg: _log_submission_step(
                "smartva: %s",
                msg,
            ),
        )
        if saved > 0:
            stats["smartva_generated"] += saved
            _set_stage(audit_by_sid, va_sid, "smartva", "done", f"saved={saved}")
            _log_submission_step("smartva: done saved=%d", saved)
        else:
            stats["smartva_noop"] += 1
            _set_stage(audit_by_sid, va_sid, "smartva", "noop")
            _log_submission_step("smartva: done saved=0 (protected/no-op/no output)")
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        stats["smartva_failed"] += 1
        _set_stage(audit_by_sid, va_sid, "smartva", "failed:generate", str(exc))
        log.error("  smartva: failed: %s", exc, exc_info=True)


def _run_single_submission_workflow_transition(
    *,
    va_sid: str,
    stats: dict,
    audit_by_sid: dict,
    workflow_actor,
) -> None:
    from app.services.workflow.state_store import get_submission_workflow_state
    from app.services.workflow.transitions import (
        WorkflowTransitionError,
        mark_attachment_sync_completed,
        mark_smartva_completed,
    )

    _set_stage(audit_by_sid, va_sid, "workflow", "not-eligible")
    rows = _find_transition_eligible_rows({va_sid})
    if not rows:
        return
    has_current_payload_smartva = bool(rows[0]["has_current_payload_smartva"])
    try:
        current = get_submission_workflow_state(va_sid)
        if current != "attachment_sync_pending":
            _set_stage(audit_by_sid, va_sid, "workflow", f"skip:state={current}")
            _log_submission_step("workflow: skip (state=%s)", current)
            return
        mark_attachment_sync_completed(
            va_sid,
            reason="attachments_synced_for_current_payload",
            actor=workflow_actor,
        )
        stats["workflow_attachment_to_smartva"] += 1
        _log_submission_step("workflow: attachment_sync_pending -> smartva_pending")
        if has_current_payload_smartva:
            mark_smartva_completed(va_sid, actor=workflow_actor)
            stats["workflow_smartva_to_ready"] += 1
            _set_stage(audit_by_sid, va_sid, "workflow", "done")
            _log_submission_step("workflow: smartva_pending -> ready_for_coding")
        else:
            _set_stage(audit_by_sid, va_sid, "workflow", "done:to-smartva-pending")
        db.session.commit()
    except WorkflowTransitionError as exc:
        db.session.rollback()
        stats["workflow_errors"] += 1
        _set_stage(audit_by_sid, va_sid, "workflow", "failed:transition", str(exc))
        log.warning("  workflow: transition failed: %s", exc)
    except Exception as exc:
        db.session.rollback()
        stats["workflow_errors"] += 1
        _set_stage(audit_by_sid, va_sid, "workflow", "failed:unexpected", str(exc))
        log.error("  workflow: unexpected error: %s", exc, exc_info=True)


def _run_attachment_sync_stage(
    *,
    forms_by_id: dict[str, VaForms],
    attachment_candidate_by_form: dict[str, dict[str, str]],
    stats: dict,
    audit_by_sid: dict,
) -> None:
    """Sync attachments for enriched submissions form-by-form."""
    from app.utils.va_odk.va_odk_01_clientsetup import va_odk_clientsetup
    from app.utils.va_odk.va_odk_07_syncattachments import va_odk_sync_submission_attachments

    app_data_root = current_app.config.get("APP_DATA")
    if not app_data_root:
        log.warning("Attachments stage skipped: APP_DATA not configured")
        stats["attachments_errors"] += sum(
            len(form_map) for form_map in attachment_candidate_by_form.values()
        )
        return

    for form_id, upserted_map in attachment_candidate_by_form.items():
        if not upserted_map:
            continue
        stats["attachments_checked"] += len(upserted_map)
        va_form = forms_by_id.get(form_id) or db.session.get(VaForms, form_id)
        if va_form is None:
            log.warning(
                "Form %s attachments: skip (missing form config), submissions=%d",
                form_id,
                len(upserted_map),
            )
            stats["attachments_errors"] += len(upserted_map)
            continue

        form_dir = os.path.join(app_data_root, form_id)
        media_dir = os.path.join(form_dir, "media")
        os.makedirs(media_dir, exist_ok=True)
        log.info(
            "Form %s attachments: start submissions=%d",
            form_id,
            len(upserted_map),
        )
        try:
            client = va_odk_clientsetup(project_id=va_form.project_id)
        except Exception as exc:
            form_totals = {
                "downloaded": 0,
                "skipped": 0,
                "errors": len(upserted_map),
                "etag_not_modified": 0,
                "local_present_on_etag": 0,
                "local_missing_on_etag": 0,
            }
            stats["attachments_downloaded"] += form_totals["downloaded"]
            stats["attachments_skipped"] += form_totals["skipped"]
            stats["attachments_errors"] += form_totals["errors"]
            stats["attachments_etag_not_modified"] += form_totals["etag_not_modified"]
            stats["attachments_local_present_on_etag"] += form_totals["local_present_on_etag"]
            stats["attachments_local_missing_on_etag"] += form_totals["local_missing_on_etag"]
            log.error(
                "Form %s attachments: client setup failed: %s",
                form_id,
                exc,
                exc_info=True,
            )
            continue
        form_totals = {
            "downloaded": 0,
            "skipped": 0,
            "errors": 0,
            "etag_not_modified": 0,
            "local_present_on_etag": 0,
            "local_missing_on_etag": 0,
        }
        total_form_submissions = len(upserted_map)
        for idx, (va_sid, instance_id) in enumerate(upserted_map.items(), start=1):
            sub = _submission_label(
                index=idx,
                total=total_form_submissions,
                va_sid=va_sid,
                form_id=form_id,
            )
            if not instance_id:
                form_totals["errors"] += 1
                log.warning(
                    "%s attachments: skip (missing instance id)",
                    sub,
                )
                _set_stage(audit_by_sid, va_sid, "attachments", "skip:no-instance-id")
                continue
            try:
                per_sid = va_odk_sync_submission_attachments(
                    va_form,
                    instance_id,
                    va_sid,
                    media_dir,
                    client=client,
                )
                db.session.commit()
                form_totals["downloaded"] += int(per_sid.get("downloaded", 0) or 0)
                form_totals["skipped"] += int(per_sid.get("skipped", 0) or 0)
                form_totals["errors"] += int(per_sid.get("errors", 0) or 0)
                form_totals["etag_not_modified"] += int(per_sid.get("etag_not_modified", 0) or 0)
                form_totals["local_present_on_etag"] += int(per_sid.get("local_present_on_etag", 0) or 0)
                form_totals["local_missing_on_etag"] += int(per_sid.get("local_missing_on_etag", 0) or 0)
                log.debug(
                    (
                        "%s attachments: done downloaded=%d skipped=%d errors=%d "
                        "etag_not_modified=%d local_present_on_etag=%d local_missing_on_etag=%d"
                    ),
                    sub,
                    int(per_sid.get("downloaded", 0) or 0),
                    int(per_sid.get("skipped", 0) or 0),
                    int(per_sid.get("errors", 0) or 0),
                    int(per_sid.get("etag_not_modified", 0) or 0),
                    int(per_sid.get("local_present_on_etag", 0) or 0),
                    int(per_sid.get("local_missing_on_etag", 0) or 0),
                )
                _set_stage(
                    audit_by_sid,
                    va_sid,
                    "attachments",
                    "done",
                    (
                        f"downloaded={int(per_sid.get('downloaded', 0) or 0)} "
                        f"skipped={int(per_sid.get('skipped', 0) or 0)} "
                        f"etag304={int(per_sid.get('etag_not_modified', 0) or 0)} "
                        f"local_missing_on_etag={int(per_sid.get('local_missing_on_etag', 0) or 0)}"
                    ),
                )
            except Exception as exc:
                db.session.rollback()
                form_totals["errors"] += 1
                log.error(
                    "%s attachments: failed: %s",
                    sub,
                    exc,
                    exc_info=True,
                )
                _set_stage(audit_by_sid, va_sid, "attachments", "failed:sync", str(exc))
        stats["attachments_downloaded"] += form_totals["downloaded"]
        stats["attachments_skipped"] += form_totals["skipped"]
        stats["attachments_errors"] += form_totals["errors"]
        stats["attachments_etag_not_modified"] += form_totals["etag_not_modified"]
        stats["attachments_local_present_on_etag"] += form_totals["local_present_on_etag"]
        stats["attachments_local_missing_on_etag"] += form_totals["local_missing_on_etag"]
        log.info(
            (
                "Form %s attachments: summary downloaded=%d skipped=%d errors=%d "
                "etag_not_modified=%d local_present_on_etag=%d local_missing_on_etag=%d"
            ),
            form_id,
            form_totals["downloaded"],
            form_totals["skipped"],
            form_totals["errors"],
            form_totals["etag_not_modified"],
            form_totals["local_present_on_etag"],
            form_totals["local_missing_on_etag"],
        )


def _find_missing_current_payload_smartva_sids(candidate_sids: set[str]) -> list[str]:
    """Return candidate SIDs with no active SmartVA row for current payload."""
    if not candidate_sids:
        return []

    rows = db.session.scalars(
        sa.select(VaSubmissions.va_sid)
        .outerjoin(
            VaSmartvaResults,
            sa.and_(
                VaSmartvaResults.va_sid == VaSubmissions.va_sid,
                VaSmartvaResults.va_smartva_status == VaStatuses.active,
                VaSmartvaResults.payload_version_id
                == VaSubmissions.active_payload_version_id,
            ),
        )
        .where(
            VaSubmissions.va_sid.in_(candidate_sids),
            VaSubmissions.active_payload_version_id.is_not(None),
            VaSmartvaResults.va_smartva_id.is_(None),
        )
    ).all()
    return sorted(rows)


def _run_missing_current_payload_smartva(
    *,
    candidate_sids: set[str],
    stats: dict,
    audit_by_sid: dict,
) -> None:
    """Generate SmartVA for candidate submissions missing current-payload rows."""
    from app.services import smartva_service

    missing_sids = _find_missing_current_payload_smartva_sids(candidate_sids)
    stats["smartva_checked"] = len(candidate_sids)
    stats["smartva_missing"] = len(missing_sids)
    for va_sid in candidate_sids:
        _set_stage(audit_by_sid, va_sid, "smartva", "already-current")

    if not missing_sids:
        log.info(
            "SmartVA stage: checked=%d all current payloads already covered",
            stats["smartva_checked"],
        )
        return

    log.info(
        "SmartVA stage: checked=%d missing_current_payload=%d",
        stats["smartva_checked"],
        stats["smartva_missing"],
    )
    total_missing = len(missing_sids)
    for idx, va_sid in enumerate(missing_sids, 1):
        sub = _submission_label(index=idx, total=total_missing, va_sid=va_sid)
        log.debug(
            "%s smartva: missing current payload result",
            sub,
        )
        try:
            log.debug("%s smartva: start", sub)
            saved = smartva_service.generate_for_submission(
                va_sid,
                trigger_source="payload_backfill_enrich",
                log_progress=lambda msg, sub_label=sub: log.debug(
                    "%s smartva: %s",
                    sub_label,
                    msg,
                ),
            )
            if saved > 0:
                stats["smartva_generated"] += saved
                log.debug(
                    "%s smartva: done saved=%d",
                    sub,
                    saved,
                )
                _set_stage(audit_by_sid, va_sid, "smartva", "done", f"saved={saved}")
            else:
                stats["smartva_noop"] += 1
                log.debug(
                    "%s smartva: done saved=0 (protected/no-op/no output)",
                    sub,
                )
                _set_stage(audit_by_sid, va_sid, "smartva", "noop")
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            stats["smartva_failed"] += 1
            log.error(
                "%s smartva: failed: %s",
                sub,
                exc,
                exc_info=True,
            )
            _set_stage(audit_by_sid, va_sid, "smartva", "failed:generate", str(exc))


def _find_transition_eligible_rows(candidate_sids: set[str]) -> list[dict]:
    """Return attachment_sync_pending rows that are complete for transition."""
    if not candidate_sids:
        return []
    rows = db.session.execute(
        sa.text(
            """
            SELECT s.va_sid,
                   (
                     sva.va_smartva_id IS NOT NULL
                   ) AS has_current_payload_smartva
            FROM va_submissions s
            JOIN va_submission_workflow w ON w.va_sid = s.va_sid
            JOIN va_submission_payload_versions pv
              ON pv.payload_version_id = s.active_payload_version_id
            JOIN (
                SELECT va_sid, COUNT(*) AS att_count
                FROM va_submission_attachments
                WHERE exists_on_odk = true
                GROUP BY va_sid
            ) att ON att.va_sid = s.va_sid
            LEFT JOIN va_smartva_results sva
              ON sva.va_sid = s.va_sid
             AND sva.va_smartva_status = 'active'
             AND sva.payload_version_id = s.active_payload_version_id
            WHERE s.va_sid = ANY(:va_sids)
              AND w.workflow_state = 'attachment_sync_pending'
              AND pv.has_required_metadata = true
              AND pv.attachments_expected > 0
              AND att.att_count >= pv.attachments_expected
            """
        ),
        {"va_sids": list(candidate_sids)},
    ).mappings().all()
    return rows


def _run_workflow_transition_stage(
    *,
    candidate_sids: set[str],
    stats: dict,
    audit_by_sid: dict,
) -> None:
    """Advance workflow after attachment + SmartVA follow-through."""
    from app.services.workflow.state_store import get_submission_workflow_state
    from app.services.workflow.transitions import (
        WorkflowTransitionError,
        mark_attachment_sync_completed,
        mark_smartva_completed,
        system_actor,
    )

    eligible_rows = _find_transition_eligible_rows(candidate_sids)
    if not eligible_rows:
        log.info("Workflow stage: no eligible rows to transition")
        return

    actor = system_actor()
    log.info(
        "Workflow stage: eligible attachment_sync_pending=%d",
        len(eligible_rows),
    )
    for va_sid in candidate_sids:
        _set_stage(audit_by_sid, va_sid, "workflow", "not-eligible")
    total_eligible = len(eligible_rows)
    for idx, row in enumerate(eligible_rows, start=1):
        va_sid = row["va_sid"]
        has_current_payload_smartva = bool(row["has_current_payload_smartva"])
        sub = _submission_label(index=idx, total=total_eligible, va_sid=va_sid)
        try:
            current = get_submission_workflow_state(va_sid)
            if current != "attachment_sync_pending":
                log.debug("%s workflow: skip (state=%s)", sub, current)
                _set_stage(audit_by_sid, va_sid, "workflow", f"skip:state={current}")
                continue
            mark_attachment_sync_completed(
                va_sid,
                reason="attachments_synced_for_current_payload",
                actor=actor,
            )
            stats["workflow_attachment_to_smartva"] += 1
            log.debug("%s workflow: attachment_sync_pending -> smartva_pending", sub)
            if has_current_payload_smartva:
                mark_smartva_completed(va_sid, actor=actor)
                stats["workflow_smartva_to_ready"] += 1
                log.debug("%s workflow: smartva_pending -> ready_for_coding", sub)
                _set_stage(audit_by_sid, va_sid, "workflow", "done")
            else:
                _set_stage(audit_by_sid, va_sid, "workflow", "done:to-smartva-pending")
            db.session.commit()
        except WorkflowTransitionError as exc:
            db.session.rollback()
            stats["workflow_errors"] += 1
            log.warning(
                "%s workflow: transition failed: %s",
                sub,
                exc,
            )
            _set_stage(audit_by_sid, va_sid, "workflow", "failed:transition", str(exc))
        except Exception as exc:
            db.session.rollback()
            stats["workflow_errors"] += 1
            log.error(
                "%s workflow: unexpected error: %s",
                sub,
                exc,
                exc_info=True,
            )
            _set_stage(audit_by_sid, va_sid, "workflow", "failed:unexpected", str(exc))


def _flush_single_update(
    *,
    pv_id,
    payload_data,
    has_required_metadata: bool,
    attachments_expected: int,
) -> None:
    """Write one enriched payload update in its own transaction."""
    db.session.execute(
        sa.update(VaSubmissionPayloadVersion)
        .where(VaSubmissionPayloadVersion.payload_version_id == pv_id)
        .values(
            payload_data=sa.type_coerce(payload_data, JSONB),
            has_required_metadata=has_required_metadata,
            attachments_expected=attachments_expected,
        )
    )
    db.session.commit()
