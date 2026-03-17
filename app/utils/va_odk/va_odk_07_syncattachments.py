"""Per-submission attachment sync with ETag-based caching.

Replaces the full ZIP attachment extraction. For each submission:
  1. Fetch attachment list from ODK Central (cheap — no binary).
  2. For each file with exists=true, check the stored ETag.
  3. Conditional GET with If-None-Match → 304 (skip) or 200 (download).
  4. .amr files are converted to .mp3; images stored as-is.
  5. ETag and local path stored in va_submission_attachments.

The form media directory is NEVER cleared (no rmtree). Existing files for
unchanged submissions remain on disk, so coders never see missing attachments
during an active sync.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import os
import threading

import sqlalchemy as sa
from flask import current_app, has_app_context

from app.services.odk_connection_guard_service import guarded_odk_call

log = logging.getLogger(__name__)
_ATTACHMENT_SYNC_MAX_WORKERS = 3
_STREAM_CHUNK_SIZE = 64 * 1024


@dataclass(slots=True)
class AttachmentChange:
    filename: str
    exists_on_odk: bool
    local_path: str | None = None
    mime_type: str | None = None
    etag: str | None = None
    last_downloaded_at: datetime | None = None


@dataclass(slots=True)
class SubmissionAttachmentSyncResult:
    va_sid: str
    downloaded: int
    skipped: int
    errors: int
    changes: list[AttachmentChange]


def _sync_submission_attachments_no_db(
    va_form,
    instance_id: str,
    va_sid: str,
    media_dir: str,
    existing_etags: dict[str, str | None],
    client,
) -> SubmissionAttachmentSyncResult:
    """Sync one submission's attachments without touching the ORM session."""
    os.makedirs(media_dir, exist_ok=True)
    request_timeout = (
        current_app.config.get("ODK_CONNECT_TIMEOUT_SECONDS", 10),
        current_app.config.get("ODK_READ_TIMEOUT_SECONDS", 60),
    )

    list_url = (
        f"projects/{va_form.odk_project_id}"
        f"/forms/{va_form.odk_form_id}"
        f"/submissions/{instance_id}/attachments"
    )
    list_resp = guarded_odk_call(
        lambda: client.session.get(list_url, timeout=request_timeout),
        client=client,
    )
    if list_resp.status_code != 200:
        raise Exception(
            f"Attachment list fetch failed HTTP {list_resp.status_code} "
            f"for {va_sid}: {list_resp.text[:200]}"
        )
    attachments: list[dict] = list_resp.json()

    downloaded = 0
    skipped = 0
    errors = 0
    changes: list[AttachmentChange] = []

    for attachment in attachments:
        filename: str = attachment.get("name", "")
        exists_on_odk: bool = bool(attachment.get("exists", False))
        if not filename:
            continue

        if not exists_on_odk:
            changes.append(AttachmentChange(filename=filename, exists_on_odk=False))
            continue

        headers: dict = {}
        stored_etag = existing_etags.get(filename)
        if stored_etag:
            headers["If-None-Match"] = stored_etag

        dl_url = (
            f"projects/{va_form.odk_project_id}"
            f"/forms/{va_form.odk_form_id}"
            f"/submissions/{instance_id}/attachments/{filename}"
        )
        dl_resp = None
        try:
            dl_resp = guarded_odk_call(
                lambda: client.session.get(
                    dl_url,
                    headers=headers,
                    stream=True,
                    timeout=request_timeout,
                ),
                client=client,
            )

            if dl_resp.status_code == 304:
                skipped += 1
                continue

            if dl_resp.status_code != 200:
                raise Exception(f"HTTP {dl_resp.status_code}: {dl_resp.text[:200]}")

            new_etag: str | None = (
                dl_resp.headers.get("ETag") or dl_resp.headers.get("etag")
            )
            raw_mime: str = dl_resp.headers.get("Content-Type", "")
            mime_type: str | None = raw_mime.split(";")[0].strip() or None

            write_path = os.path.join(media_dir, filename)
            with open(write_path, "wb") as f:
                for chunk in dl_resp.iter_content(chunk_size=_STREAM_CHUNK_SIZE):
                    if chunk:
                        f.write(chunk)

            local_path = write_path
            if filename.lower().endswith(".amr"):
                local_path = _convert_amr_to_mp3(write_path, va_form.form_id)

            changes.append(
                AttachmentChange(
                    filename=filename,
                    exists_on_odk=True,
                    local_path=local_path,
                    mime_type=mime_type,
                    etag=new_etag,
                    last_downloaded_at=datetime.now(timezone.utc),
                )
            )
            downloaded += 1
        except Exception as exc:
            errors += 1
            log.warning(
                "Attachment sync error [%s/%s]: %s", va_sid, filename, exc, exc_info=True
            )
        finally:
            if dl_resp is not None and hasattr(dl_resp, "close"):
                dl_resp.close()

    return SubmissionAttachmentSyncResult(
        va_sid=va_sid,
        downloaded=downloaded,
        skipped=skipped,
        errors=errors,
        changes=changes,
    )


def _apply_submission_attachment_result(existing_records, result):
    """Apply a network-only attachment sync result to ORM records."""
    from app import db
    from app.models.va_submission_attachments import VaSubmissionAttachments

    existing = existing_records.setdefault(result.va_sid, {})
    for change in result.changes:
        rec = existing.get(change.filename)
        if rec:
            rec.exists_on_odk = change.exists_on_odk
            if change.exists_on_odk:
                rec.local_path = change.local_path
                rec.mime_type = change.mime_type
                rec.etag = change.etag
                rec.last_downloaded_at = change.last_downloaded_at
        elif change.exists_on_odk:
            rec = VaSubmissionAttachments(
                va_sid=result.va_sid,
                filename=change.filename,
                local_path=change.local_path,
                mime_type=change.mime_type,
                etag=change.etag,
                exists_on_odk=True,
                last_downloaded_at=change.last_downloaded_at,
            )
            db.session.add(rec)
            existing[change.filename] = rec


def _load_existing_attachment_records(va_sids):
    """Load existing ORM attachment records keyed by submission and filename."""
    from app import db
    from app.models.va_submission_attachments import VaSubmissionAttachments

    if not va_sids:
        return {}
    rows = db.session.scalars(
        sa.select(VaSubmissionAttachments).where(
            VaSubmissionAttachments.va_sid.in_(va_sids)
        )
    ).all()
    existing = {}
    for row in rows:
        existing.setdefault(row.va_sid, {})[row.filename] = row
    return existing


def va_odk_sync_form_attachments(
    va_form,
    upserted_map: dict[str, str],
    media_dir: str,
    *,
    client_factory,
    max_workers: int = _ATTACHMENT_SYNC_MAX_WORKERS,
    progress_callback=None,
):
    """Sync attachments for all changed submissions in a form with bounded parallelism."""
    from app import db

    if not upserted_map:
        return {"downloaded": 0, "skipped": 0, "errors": 0}

    existing_records = _load_existing_attachment_records(list(upserted_map.keys()))
    per_sid_etags = {
        va_sid: {name: rec.etag for name, rec in rows.items()}
        for va_sid, rows in existing_records.items()
    }
    app = current_app._get_current_object() if has_app_context() else None

    thread_local = threading.local()

    def _get_client():
        client = getattr(thread_local, "odk_client", None)
        if client is None:
            client = client_factory()
            thread_local.odk_client = client
        return client

    def _run_submission_sync(va_sid: str, instance_id: str):
        if app is not None:
            with app.app_context():
                return _sync_submission_attachments_no_db(
                    va_form,
                    instance_id,
                    va_sid,
                    media_dir,
                    per_sid_etags.get(va_sid, {}),
                    _get_client(),
                )
        return _sync_submission_attachments_no_db(
            va_form,
            instance_id,
            va_sid,
            media_dir,
            per_sid_etags.get(va_sid, {}),
            _get_client(),
        )

    results = []
    total_count = len(upserted_map)
    completed = 0
    worker_count = min(max_workers, max(1, len(upserted_map)))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        future_map = {
            executor.submit(_run_submission_sync, va_sid, instance_id): (
                va_sid,
                instance_id,
            )
            for va_sid, instance_id in upserted_map.items()
            if instance_id
        }
        for future in as_completed(future_map):
            va_sid, _ = future_map[future]
            try:
                results.append(future.result())
            except Exception as exc:
                log.warning(
                    "Attachment sync failed for %s: %s",
                    va_sid,
                    exc,
                    exc_info=True,
                )
                results.append(
                    SubmissionAttachmentSyncResult(
                        va_sid=va_sid,
                        downloaded=0,
                        skipped=0,
                        errors=1,
                        changes=[],
                    )
                )
            completed += 1
            if progress_callback and completed % 50 == 0:
                progress_callback(f"[{va_form.form_id}] attachments: {completed}/{total_count}")

    totals = {"downloaded": 0, "skipped": 0, "errors": 0}
    for result in results:
        totals["downloaded"] += result.downloaded
        totals["skipped"] += result.skipped
        totals["errors"] += result.errors
        _apply_submission_attachment_result(existing_records, result)

    db.session.flush()
    return totals


def va_odk_sync_submission_attachments(
    va_form,
    instance_id: str,
    va_sid: str,
    media_dir: str,
    client=None,
) -> dict:
    """Sync attachments for one submission using ETag-based conditional download.

    Reads existing ETags from va_submission_attachments. Only downloads
    files that are new or have changed (HTTP 200). Skips unchanged files
    (HTTP 304). Updates ETag records after each download.

    Args:
        va_form: VaForms instance (used for ODK project/form IDs and project_id).
        instance_id: ODK submission UUID (the ``__id`` / KEY value).
        va_sid: Application submission ID (FK in va_submission_attachments).
        media_dir: Absolute path to the form's media directory.

    Returns:
        {"downloaded": int, "skipped": int, "errors": int}
    """
    from app import db
    from app.models.va_submission_attachments import VaSubmissionAttachments
    from app.utils.va_odk.va_odk_01_clientsetup import va_odk_clientsetup

    os.makedirs(media_dir, exist_ok=True)
    client = client or va_odk_clientsetup(project_id=va_form.project_id)
    existing: dict[str, VaSubmissionAttachments] = {
        r.filename: r
        for r in db.session.scalars(
            sa.select(VaSubmissionAttachments).where(
                VaSubmissionAttachments.va_sid == va_sid
            )
        ).all()
    }
    result = _sync_submission_attachments_no_db(
        va_form,
        instance_id,
        va_sid,
        media_dir,
        {name: rec.etag for name, rec in existing.items()},
        client,
    )
    _apply_submission_attachment_result({va_sid: existing}, result)
    db.session.flush()
    return {
        "downloaded": result.downloaded,
        "skipped": result.skipped,
        "errors": result.errors,
    }


def _convert_amr_to_mp3(amr_path: str, form_id: str) -> str:
    """Convert an .amr file to .mp3 in-place. Returns the .mp3 path.

    If conversion fails, the .amr is kept and its path is returned so the
    file is still on disk (better than losing it).
    """
    from pydub import AudioSegment

    mp3_path = amr_path.rsplit(".", 1)[0] + ".mp3"
    try:
        audio = AudioSegment.from_file(amr_path, format="amr")
        audio.export(mp3_path, format="mp3")
        os.remove(amr_path)
        log.info("AMR→MP3 [%s]: %s → %s", form_id, os.path.basename(amr_path), os.path.basename(mp3_path))
        return mp3_path
    except Exception as e:
        log.warning(
            "AMR→MP3 conversion failed [%s/%s]: %s — keeping .amr",
            form_id, os.path.basename(amr_path), e,
        )
        return amr_path
