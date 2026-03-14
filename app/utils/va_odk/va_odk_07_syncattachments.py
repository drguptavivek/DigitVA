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

import logging
import os
from datetime import datetime, timezone

import sqlalchemy as sa

log = logging.getLogger(__name__)


def va_odk_sync_submission_attachments(
    va_form,
    instance_id: str,
    va_sid: str,
    media_dir: str,
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
    client = va_odk_clientsetup(project_id=va_form.project_id)

    # 1. Fetch attachment list (returns [{name, exists}, ...])
    list_url = (
        f"projects/{va_form.odk_project_id}"
        f"/forms/{va_form.odk_form_id}"
        f"/submissions/{instance_id}/attachments"
    )
    list_resp = client.session.get(list_url)
    if list_resp.status_code != 200:
        raise Exception(
            f"Attachment list fetch failed HTTP {list_resp.status_code} "
            f"for {va_sid}: {list_resp.text[:200]}"
        )
    attachments: list[dict] = list_resp.json()

    # 2. Load existing ETag records for this submission (keyed by filename)
    existing: dict[str, VaSubmissionAttachments] = {
        r.filename: r
        for r in db.session.scalars(
            sa.select(VaSubmissionAttachments).where(
                VaSubmissionAttachments.va_sid == va_sid
            )
        ).all()
    }

    downloaded = 0
    skipped = 0
    errors = 0

    for attachment in attachments:
        filename: str = attachment.get("name", "")
        exists_on_odk: bool = bool(attachment.get("exists", False))

        if not filename:
            continue

        # Mark files ODK no longer has
        if not exists_on_odk:
            if filename in existing:
                existing[filename].exists_on_odk = False
            continue

        rec = existing.get(filename)
        stored_etag: str | None = rec.etag if rec else None

        # 3. Conditional download
        dl_url = (
            f"projects/{va_form.odk_project_id}"
            f"/forms/{va_form.odk_form_id}"
            f"/submissions/{instance_id}/attachments/{filename}"
        )
        headers: dict = {}
        if stored_etag:
            headers["If-None-Match"] = stored_etag

        try:
            dl_resp = client.session.get(dl_url, headers=headers)

            if dl_resp.status_code == 304:
                skipped += 1
                log.debug("Attachment [%s/%s]: 304 Not Modified — skipped", va_sid, filename)
                continue

            if dl_resp.status_code != 200:
                raise Exception(f"HTTP {dl_resp.status_code}: {dl_resp.text[:200]}")

            new_etag: str | None = (
                dl_resp.headers.get("ETag") or dl_resp.headers.get("etag")
            )
            raw_mime: str = dl_resp.headers.get("Content-Type", "")
            mime_type: str | None = raw_mime.split(";")[0].strip() or None

            # Write the file
            write_path = os.path.join(media_dir, filename)
            with open(write_path, "wb") as f:
                f.write(dl_resp.content)

            local_path = write_path

            # .amr → .mp3 conversion
            if filename.lower().endswith(".amr"):
                local_path = _convert_amr_to_mp3(write_path, va_form.form_id)

            # Upsert ETag record
            now = datetime.now(timezone.utc)
            if rec:
                rec.local_path = local_path
                rec.mime_type = mime_type
                rec.etag = new_etag
                rec.exists_on_odk = True
                rec.last_downloaded_at = now
            else:
                db.session.add(VaSubmissionAttachments(
                    va_sid=va_sid,
                    filename=filename,
                    local_path=local_path,
                    mime_type=mime_type,
                    etag=new_etag,
                    exists_on_odk=True,
                    last_downloaded_at=now,
                ))

            downloaded += 1
            log.debug(
                "Attachment [%s/%s]: downloaded %d bytes", va_sid, filename, len(dl_resp.content)
            )

        except Exception as e:
            errors += 1
            log.warning(
                "Attachment sync error [%s/%s]: %s", va_sid, filename, e, exc_info=True
            )

    # Flush ETag records to DB — caller commits after processing all submissions
    db.session.flush()

    return {"downloaded": downloaded, "skipped": skipped, "errors": errors}


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
