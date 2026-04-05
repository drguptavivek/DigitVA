"""Per-submission attachment sync with ETag-based caching.

Replaces the full ZIP attachment extraction. For each submission:
  1. Fetch attachment list from ODK Central (cheap — no binary).
  2. For each file with exists=true, check the stored ETag.
  3. Conditional GET with If-None-Match → 304 (skip) or 200 (download).
  4. .amr files are converted to .mp3 via SoX; images stored as-is.
  5. ETag, local path, and storage_name stored in va_submission_attachments.

Files are stored on disk as {storage_name} (uuid4().hex + ext) instead of
their original ODK filename.  The original filename is preserved in the DB
row for lookup; the opaque storage_name is used for serving URLs.

The form media directory is NEVER cleared (no rmtree). Existing files for
unchanged submissions remain on disk, so coders never see missing attachments
during an active sync.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
import os
import subprocess
import threading
import uuid

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from flask import current_app, has_app_context

from app.services.odk_connection_guard_service import guarded_odk_call

log = logging.getLogger(__name__)
_ATTACHMENT_SYNC_MAX_WORKERS = 3
_STREAM_CHUNK_SIZE = 64 * 1024


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_attachment_filename(filename: str) -> str:
    """Normalize filename for cache key use. Case-insensitive .amr → .mp3."""
    if filename.lower().endswith(".amr"):
        return filename[: -len(".amr")] + ".mp3"
    return filename


def _generate_storage_name(original_filename: str) -> str:
    """Generate a unique opaque storage name (uuid4 hex + lowercase ext)."""
    ext = os.path.splitext(original_filename)[1].lower()
    if ext == ".amr":
        ext = ".mp3"
    return uuid.uuid4().hex + ext


def _invalidate_attachment_cache(
    storage_name: str | None,
    va_sid: str,
    filename: str,
    extra_storage_name: str | None = None,
) -> None:
    """Delete Redis cache entries for an attachment.

    Deletes:
      att:{storage_name}            — serving route cache
      att_name:{va_sid}:{normalized} — render resolver cache
      att:{extra_storage_name}      — pre-emptive new-token invalidation (optional)
    """
    try:
        from app import cache as flask_cache
        normalized = _normalize_attachment_filename(filename)
        if storage_name:
            flask_cache.delete(f"att:{storage_name}")
        flask_cache.delete(f"att_name:{va_sid}:{normalized}")
        if extra_storage_name:
            flask_cache.delete(f"att:{extra_storage_name}")
    except Exception as exc:
        log.warning("Cache invalidation error for %s/%s: %s", va_sid, filename, exc)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class AttachmentChange:
    filename: str
    exists_on_odk: bool
    local_path: str | None = None
    mime_type: str | None = None
    etag: str | None = None
    last_downloaded_at: datetime | None = None
    storage_name: str | None = None


@dataclass(slots=True)
class SubmissionAttachmentSyncResult:
    va_sid: str
    downloaded: int
    skipped: int
    errors: int
    changes: list[AttachmentChange]


# ---------------------------------------------------------------------------
# Network-only sync (no DB, no ORM)
# ---------------------------------------------------------------------------

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
    if has_app_context():
        request_timeout = (
            current_app.config.get("ODK_CONNECT_TIMEOUT_SECONDS", 10),
            current_app.config.get("ODK_READ_TIMEOUT_SECONDS", 60),
        )
    else:
        request_timeout = (10, 60)

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
        tmp_path: str | None = None
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

            storage_name = _generate_storage_name(filename)
            tmp_path = os.path.join(media_dir, f".tmp_{uuid.uuid4().hex}")

            # Download to temp file
            with open(tmp_path, "wb") as f:
                for chunk in dl_resp.iter_content(chunk_size=_STREAM_CHUNK_SIZE):
                    if chunk:
                        f.write(chunk)

            # Rename / convert to final storage_name path
            final_path = os.path.join(media_dir, storage_name)
            if filename.lower().endswith(".amr"):
                local_path = _convert_amr_to_mp3(tmp_path, va_form.form_id, output_path=final_path)
                tmp_path = None  # conversion consumed the temp file
            else:
                os.rename(tmp_path, final_path)
                tmp_path = None  # rename consumed the temp file
                local_path = final_path

            changes.append(
                AttachmentChange(
                    filename=filename,
                    exists_on_odk=True,
                    local_path=local_path,
                    mime_type=mime_type,
                    etag=new_etag,
                    last_downloaded_at=datetime.now(timezone.utc),
                    storage_name=storage_name,
                )
            )
            downloaded += 1
        except Exception as exc:
            errors += 1
            log.warning(
                "Attachment sync error [%s/%s]: %s", va_sid, filename, exc, exc_info=True
            )
        finally:
            # Clean up temp file if it still exists (rename/conversion didn't consume it)
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            if dl_resp is not None and hasattr(dl_resp, "close"):
                dl_resp.close()

    return SubmissionAttachmentSyncResult(
        va_sid=va_sid,
        downloaded=downloaded,
        skipped=skipped,
        errors=errors,
        changes=changes,
    )


# ---------------------------------------------------------------------------
# DB apply
# ---------------------------------------------------------------------------

def _apply_submission_attachment_result(existing_records, result):
    """Apply a network-only attachment sync result using PK-safe upserts."""
    from app import db
    from app.models.va_submission_attachments import VaSubmissionAttachments

    existing = existing_records.setdefault(result.va_sid, {})
    for change in result.changes:
        rec = existing.get(change.filename)
        if rec:
            if change.exists_on_odk and change.local_path is not None:
                # Fresh download — rotate storage_name
                old_storage_name = rec.storage_name
                rec.exists_on_odk = True
                rec.local_path = change.local_path
                rec.mime_type = change.mime_type
                rec.etag = change.etag
                rec.last_downloaded_at = change.last_downloaded_at
                rec.storage_name = change.storage_name
                if old_storage_name is not None:
                    _invalidate_attachment_cache(
                        old_storage_name,
                        result.va_sid,
                        change.filename,
                        extra_storage_name=change.storage_name,
                    )
            else:
                # File removed on ODK — update flag and invalidate cache
                old_storage_name = rec.storage_name
                rec.exists_on_odk = change.exists_on_odk
                _invalidate_attachment_cache(old_storage_name, result.va_sid, change.filename)
            continue

        # New record — upsert with collision retry
        values = {
            "va_sid": result.va_sid,
            "filename": change.filename,
            "exists_on_odk": change.exists_on_odk,
            "local_path": change.local_path if change.exists_on_odk else None,
            "mime_type": change.mime_type if change.exists_on_odk else None,
            "etag": change.etag if change.exists_on_odk else None,
            "last_downloaded_at": (
                change.last_downloaded_at if change.exists_on_odk else None
            ),
            "storage_name": change.storage_name if change.exists_on_odk else None,
        }

        for attempt in range(3):
            try:
                insert_stmt = pg_insert(VaSubmissionAttachments).values(**values)
                db.session.execute(
                    insert_stmt.on_conflict_do_update(
                        index_elements=[
                            VaSubmissionAttachments.va_sid,
                            VaSubmissionAttachments.filename,
                        ],
                        set_={
                            "exists_on_odk": insert_stmt.excluded.exists_on_odk,
                            "local_path": insert_stmt.excluded.local_path,
                            "mime_type": insert_stmt.excluded.mime_type,
                            "etag": insert_stmt.excluded.etag,
                            "last_downloaded_at": insert_stmt.excluded.last_downloaded_at,
                            "storage_name": insert_stmt.excluded.storage_name,
                        },
                    )
                )
                break
            except IntegrityError as exc:
                db.session.rollback()
                if "ix_va_submission_attachments_storage_name" in str(exc) and attempt < 2:
                    log.warning(
                        "storage_name collision for %s/%s, retrying (%d/3)",
                        result.va_sid, change.filename, attempt + 1,
                    )
                    values["storage_name"] = _generate_storage_name(change.filename)
                else:
                    raise

        existing.pop(change.filename, None)


# ---------------------------------------------------------------------------
# Batch form sync
# ---------------------------------------------------------------------------

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
    """Sync attachments for one submission using ETag-based conditional download."""
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


# ---------------------------------------------------------------------------
# AMR conversion
# ---------------------------------------------------------------------------

def _convert_amr_to_mp3(amr_path: str, form_id: str, output_path: str | None = None) -> str:
    """Convert an .amr file to .mp3. Returns the .mp3 path.

    Uses SoX with smart bitrate: probes source via soxi, then targets 2x
    the source bitrate (capped 16–64 kbps). AMR-NB speech (~12 kbps) ends
    up at 24 kbps — optimal quality for the source without bloated output.

    If output_path is provided, write the .mp3 there (and delete amr_path).
    Otherwise derive the output path by replacing the .amr extension.

    If conversion fails, the source file is kept and its path returned.
    """
    mp3_path = output_path or amr_path.rsplit(".", 1)[0] + ".mp3"
    try:
        # Probe source bitrate via soxi
        target_bitrate = 24  # sensible default
        try:
            duration = float(subprocess.check_output(["soxi", "-D", amr_path]).decode().strip())
            file_size = os.path.getsize(amr_path)
            source_kbps = int((file_size * 8) / duration / 1000)
            target_bitrate = max(16, min(64, source_kbps * 2))
        except Exception:
            pass  # fallback to default

        subprocess.run(
            ["sox", amr_path, "-C", str(target_bitrate), mp3_path],
            check=True,
            capture_output=True,
            text=True,
        )
        os.remove(amr_path)
        log.info(
            "AMR→MP3 [%s]: %s → %s (%dkbps)", form_id,
            os.path.basename(amr_path), os.path.basename(mp3_path), target_bitrate,
        )
        return mp3_path
    except Exception as e:
        log.warning(
            "AMR→MP3 conversion failed [%s/%s]: %s — keeping source",
            form_id, os.path.basename(amr_path), e,
        )
        return amr_path
