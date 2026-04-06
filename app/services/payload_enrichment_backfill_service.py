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

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from app import db
from app.models import VaForms, VaSubmissions
from app.models.va_submission_payload_versions import VaSubmissionPayloadVersion
from app.services.submission_payload_version_service import _derive_payload_metadata

log = logging.getLogger(__name__)

_BATCH_SIZE = 10


def enrich_unenriched_payloads(
    *,
    form_id: str | None = None,
    batch_size: int = _BATCH_SIZE,
    max_forms: int | None = None,
    max_per_form: int | None = None,
    dry_run: bool = False,
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
        {"processed": int, "enriched": int, "failed": int, "skipped": int}
    """
    from app.services.va_data_sync.va_data_sync_01_odkcentral import (
        _enrich_submission_payload_for_storage,
    )
    from app.utils.va_odk.va_odk_01_clientsetup import va_odk_clientsetup

    stats = {"processed": 0, "enriched": 0, "failed": 0, "skipped": 0}

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

    log.info("payload-enrich: executing query for unenriched active payload versions")
    rows = db.session.execute(query).mappings().all()
    db.session.close()  # release connection before ODK I/O begins
    log.info("payload-enrich: query returned %d rows; DB connection released", len(rows))

    if not rows:
        log.info("payload-enrich: nothing to do — all active payloads already enriched")
        return stats

    log.info("payload-enrich: %d unenriched active payload versions to process", len(rows))

    # Load form objects into plain dicts so they survive session.close()
    form_ids = list(dict.fromkeys(r["va_form_id"] for r in rows))
    log.info("payload-enrich: found %d distinct form(s): %s", len(form_ids), form_ids)
    if max_forms is not None:
        form_ids = form_ids[:max_forms]
        log.info("payload-enrich: limiting to %d form(s) per --max-forms: %s", max_forms, form_ids)

    forms_by_id: dict[str, VaForms] = {}
    for fid in form_ids:
        va_form = db.session.get(VaForms, fid)
        if va_form:
            forms_by_id[fid] = va_form
            log.info("payload-enrich: loaded form %s (project=%s)", fid, va_form.project_id)
        else:
            log.warning("payload-enrich: form %s not found in VaForms table", fid)
    db.session.close()

    # Group rows by form
    by_form: dict[str, list] = {}
    for row in rows:
        fid = row["va_form_id"]
        if fid in forms_by_id:
            by_form.setdefault(fid, []).append(row)

    # --- Step 2: ODK I/O — no open DB transaction ----------------------------
    all_updates: list[dict] = []

    for fid in form_ids:
        form_rows = by_form.get(fid)
        if not form_rows:
            log.warning("payload-enrich: no rows found for form %s in by_form — skipping", fid)
            continue

        va_form = forms_by_id.get(fid)
        if va_form is None:
            log.warning("payload-enrich: form %s not found — skipping %d versions", fid, len(form_rows))
            stats["skipped"] += len(form_rows)
            continue

        log.info("payload-enrich: form %s — creating ODK client (project=%s)", fid, va_form.project_id)
        try:
            client = va_odk_clientsetup(project_id=va_form.project_id)
            log.info("payload-enrich: ODK client created for form %s", fid)
        except Exception as exc:
            log.warning(
                "payload-enrich: cannot create ODK client for form %s (project %s): %s — skipping",
                fid, va_form.project_id, exc,
            )
            stats["skipped"] += len(form_rows)
            continue

        if max_per_form is not None and len(form_rows) > max_per_form:
            log.info(
                "payload-enrich: form %s — capping at %d of %d submissions (--max-per-form)",
                fid, max_per_form, len(form_rows),
            )
            form_rows = form_rows[:max_per_form]

        log.info("payload-enrich: form %s — fetching enrichment for %d submissions", fid, len(form_rows))

        for row in form_rows:
            stats["processed"] += 1
            key_val = (row["payload_data"] or {}).get("KEY")
            if not key_val:
                log.warning("payload-enrich: %s has no KEY in payload_data — skipping", row["va_sid"])
                stats["skipped"] += 1
                continue

            log.debug("payload-enrich: enriching %s (KEY=%s)", row["va_sid"], key_val)
            try:
                enriched = _enrich_submission_payload_for_storage(
                    va_form, row["payload_data"], client=client
                )
            except Exception as exc:
                log.warning("payload-enrich: enrichment failed for %s: %s", row["va_sid"], exc)
                stats["failed"] += 1
                continue

            if enriched is None:
                log.warning("payload-enrich: _enrich_submission_payload_for_storage returned None for %s — skipping", row["va_sid"])
                stats["failed"] += 1
                continue

            has_meta, att_expected = _derive_payload_metadata(enriched)
            if not has_meta:
                log.warning("payload-enrich: %s enriched but metadata still incomplete — missing keys: %s",
                    row["va_sid"],
                    [k for k in ("FormVersion","DeviceID","SubmitterID","instanceID","AttachmentsExpected","AttachmentsPresent") if not enriched.get(k)],
                )
            else:
                log.debug("payload-enrich: %s enriched successfully (has_meta=True)", row["va_sid"])

            stats["enriched"] += 1

            if not dry_run:
                all_updates.append({
                    "pv_id": row["payload_version_id"],
                    "payload_data": enriched,
                    "has_required_metadata": has_meta,
                    "attachments_expected": att_expected,
                })

    # --- Step 3: batch-write all updates (short transactions, no I/O) --------
    if not dry_run:
        for i in range(0, len(all_updates), batch_size):
            batch = all_updates[i: i + batch_size]
            _flush_batch(batch)
            log.debug("payload-enrich: committed batch %d-%d of %d", i + 1, i + len(batch), len(all_updates))

    log.info(
        "payload-enrich: done — processed=%d enriched=%d failed=%d skipped=%d",
        stats["processed"], stats["enriched"], stats["failed"], stats["skipped"],
    )
    return stats


def _flush_batch(updates: list[dict]) -> None:
    """Write a batch of enriched payload updates using explicit SQL UPDATE.

    Uses sa.type_coerce(dict, JSONB) so SQLAlchemy serializes the dict to
    JSON exactly once.  sa.cast(json_string, JSONB) caused double-encoding
    because SQLAlchemy's JSONB adapter re-serializes strings.
    """
    for u in updates:
        db.session.execute(
            sa.update(VaSubmissionPayloadVersion)
            .where(VaSubmissionPayloadVersion.payload_version_id == u["pv_id"])
            .values(
                payload_data=sa.type_coerce(u["payload_data"], JSONB),
                has_required_metadata=u["has_required_metadata"],
                attachments_expected=u["attachments_expected"],
            )
        )
    db.session.commit()
