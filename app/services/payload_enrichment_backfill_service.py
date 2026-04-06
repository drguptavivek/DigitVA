"""Backfill ODK enrichment metadata for payload versions stored without it.

When submissions are synced without an active ODK client (or before the
enrichment step was added), the stored payload_data contains only the raw
OData form fields.  The six metadata fields required for the sync-completeness
dashboard — FormVersion, DeviceID, SubmitterID, instanceID, AttachmentsExpected,
AttachmentsPresent — are absent.

All six fields are in VOLATILE_PAYLOAD_KEYS, so they are excluded from the
canonical fingerprint.  Updating them in-place on an existing payload version
does NOT change the fingerprint and does NOT trigger a new version.  We simply
patch payload_data and recompute the two precomputed columns.

Entry points
------------
  enrich_unenriched_payloads()  — call from CLI or Celery task
"""

from __future__ import annotations

import logging

import sqlalchemy as sa

from app import db
from app.models import VaForms, VaSubmissions
from app.models.va_submission_payload_versions import VaSubmissionPayloadVersion
from app.services.submission_payload_version_service import _derive_payload_metadata

log = logging.getLogger(__name__)

_BATCH_SIZE = 50


def enrich_unenriched_payloads(
    *,
    form_id: str | None = None,
    batch_size: int = _BATCH_SIZE,
    dry_run: bool = False,
) -> dict:
    """Fetch ODK metadata for every active payload version missing has_required_metadata.

    Groups work by form so one ODK client is created per project.  Commits
    after each batch to keep transactions short.

    Args:
        form_id:    if given, restrict to submissions belonging to this form.
        batch_size: how many submissions to commit per transaction.
        dry_run:    log what would happen without writing anything.

    Returns:
        {"processed": int, "enriched": int, "failed": int, "skipped": int}
    """
    from app.services.va_data_sync.va_data_sync_01_odkcentral import (
        _enrich_submission_payload_for_storage,
    )
    from app.utils.va_odk.va_odk_01_clientsetup import va_odk_clientsetup

    stats = {"processed": 0, "enriched": 0, "failed": 0, "skipped": 0}

    # --- query: unenriched active payload versions grouped by form --------------
    query = (
        sa.select(
            VaSubmissionPayloadVersion,
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

    rows = db.session.execute(query).all()
    if not rows:
        log.info("payload-enrich: nothing to do — all active payloads already enriched")
        return stats

    log.info("payload-enrich: %d unenriched active payload versions to process", len(rows))

    # --- group by form_id -------------------------------------------------------
    by_form: dict[str, list] = {}
    for pv, fid in rows:
        by_form.setdefault(fid, []).append(pv)

    # --- process each form with its own ODK client ------------------------------
    for fid, versions in by_form.items():
        va_form = db.session.get(VaForms, fid)
        if va_form is None:
            log.warning("payload-enrich: form %s not found — skipping %d versions", fid, len(versions))
            stats["skipped"] += len(versions)
            continue

        try:
            client = va_odk_clientsetup(project_id=va_form.project_id)
        except Exception as exc:
            log.warning(
                "payload-enrich: cannot create ODK client for form %s (project %s): %s — skipping",
                fid, va_form.project_id, exc,
            )
            stats["skipped"] += len(versions)
            continue

        log.info(
            "payload-enrich: form %s — %d submissions to enrich",
            fid, len(versions),
        )

        batch: list[VaSubmissionPayloadVersion] = []
        for pv in versions:
            stats["processed"] += 1
            instance_id = (pv.payload_data or {}).get("KEY")
            if not instance_id:
                log.warning(
                    "payload-enrich: %s has no KEY in payload_data — skipping", pv.va_sid
                )
                stats["skipped"] += 1
                continue

            try:
                enriched = _enrich_submission_payload_for_storage(
                    va_form, pv.payload_data, client=client
                )
            except Exception as exc:
                log.warning(
                    "payload-enrich: enrichment failed for %s: %s", pv.va_sid, exc
                )
                stats["failed"] += 1
                continue

            has_meta, att_expected = _derive_payload_metadata(enriched)
            if not has_meta:
                # ODK returned but fields still missing (e.g. deleted submission)
                log.debug("payload-enrich: %s enriched but still incomplete", pv.va_sid)

            if not dry_run:
                pv.payload_data = enriched
                pv.has_required_metadata = has_meta
                pv.attachments_expected = att_expected

            stats["enriched"] += 1
            batch.append(pv)

            if len(batch) >= batch_size:
                if not dry_run:
                    db.session.commit()
                log.debug("payload-enrich: committed batch of %d", len(batch))
                batch = []

        if batch and not dry_run:
            db.session.commit()
            log.debug("payload-enrich: committed final batch of %d for form %s", len(batch), fid)

    log.info(
        "payload-enrich: done — processed=%d enriched=%d failed=%d skipped=%d",
        stats["processed"], stats["enriched"], stats["failed"], stats["skipped"],
    )
    return stats
