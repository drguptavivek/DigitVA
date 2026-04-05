import mimetypes
import os
import sqlalchemy as sa
from datetime import datetime, timezone
from flask import current_app
from sqlalchemy.exc import IntegrityError
from werkzeug.utils import secure_filename

from app import db
from app.models import VaForms, VaSubmissionAttachments, VaSubmissions
from app.services.submission_payload_version_service import get_active_payload_version
from app.utils.va_render.va_render_06_processcategorydata import va_isattachment
from app.utils.va_odk.va_odk_07_syncattachments import (
    _generate_storage_name,
    _normalize_attachment_filename,
)

_AUDIT_CSV = "audit.csv"


def _candidate_attachment_paths(media_dir: str, raw_value: str) -> list[tuple[str, str]]:
    """Return candidate (filename, local_path) pairs for a stored attachment value."""
    value = (raw_value or "").strip()
    if not value:
        return []

    candidates: list[str] = []
    for candidate in (value, secure_filename(value)):
        if candidate and candidate not in candidates:
            candidates.append(candidate)

    if value.lower().endswith(".amr"):
        mp3_value = value[:-4] + ".mp3"
        mp3_safe = secure_filename(mp3_value)
        for candidate in (mp3_value, mp3_safe):
            if candidate and candidate not in candidates:
                candidates.append(candidate)

    return [
        (candidate, os.path.join(media_dir, candidate))
        for candidate in candidates
    ]


def _submission_attachment_refs(submission: VaSubmissions, media_dir: str) -> tuple[list[dict], int]:
    """Return attachment refs from payload_data that exist on disk and a missing count."""
    refs: list[dict] = []
    seen_filenames: set[str] = set()
    missing_count = 0
    active_version = get_active_payload_version(submission.va_sid)
    va_data = active_version.payload_data if active_version else {}

    for field_id in va_isattachment:
        raw_value = va_data.get(field_id)
        if not isinstance(raw_value, str) or not raw_value.strip():
            continue

        original_name = raw_value.strip()
        if original_name == _AUDIT_CSV:
            continue

        for resolved_name, local_path in _candidate_attachment_paths(media_dir, original_name):
            if not os.path.exists(local_path):
                continue
            if original_name in seen_filenames:
                break
            seen_filenames.add(original_name)
            mime_type = mimetypes.guess_type(local_path)[0]
            refs.append(
                {
                    "filename": original_name,
                    "local_path": local_path,
                    "mime_type": mime_type,
                    "last_downloaded_at": datetime.fromtimestamp(
                        os.path.getmtime(local_path), tz=timezone.utc
                    ),
                }
            )
            break
        else:
            missing_count += 1

    return refs, missing_count


def _assign_storage_name_and_rename(media_dir: str, ref: dict) -> dict:
    """Generate a storage_name, rename file on disk, return updated ref dict.

    Skips if the file is already at a storage_name path (storage_name already set
    is checked by callers; this handles the disk rename).
    """
    storage_name = _generate_storage_name(ref["filename"])
    new_local_path = os.path.join(media_dir, storage_name)
    old_local_path = ref["local_path"]

    if os.path.exists(old_local_path):
        os.rename(old_local_path, new_local_path)
    # If old path doesn't exist, proceed anyway — storage_name will be assigned
    # and local_path updated; the file may have been renamed by a previous run.

    return {**ref, "local_path": new_local_path, "storage_name": storage_name}


def _scoped_forms(project_id: str | None = None, site_id: str | None = None, form_id: str | None = None):
    stmt = sa.select(VaForms).order_by(VaForms.project_id, VaForms.site_id, VaForms.form_id)
    if project_id:
        stmt = stmt.where(VaForms.project_id == project_id)
    if site_id:
        stmt = stmt.where(VaForms.site_id == site_id)
    if form_id:
        stmt = stmt.where(VaForms.form_id == form_id)
    return db.session.scalars(stmt).all()


def backfill_attachment_cache(
    *,
    project_id: str | None = None,
    site_id: str | None = None,
    form_id: str | None = None,
    log_progress=None,
) -> dict:
    """Backfill va_submission_attachments from existing local files.

    Scans submission attachment fields in va_data, checks whether the
    referenced file exists in the form's media directory, and creates or
    refreshes cache rows in va_submission_attachments.

    Also assigns storage_name and renames files on disk for rows that
    don't yet have a storage_name (storage_name IS NULL).
    """
    totals = {
        "forms_scanned": 0,
        "submissions_scanned": 0,
        "attachments_created": 0,
        "attachments_updated": 0,
        "attachments_skipped": 0,
        "missing_files": 0,
    }

    for va_form in _scoped_forms(project_id=project_id, site_id=site_id, form_id=form_id):
        totals["forms_scanned"] += 1
        form_media_dir = os.path.join(
            current_app.config["APP_DATA"],
            va_form.form_id,
            "media",
        )
        submissions = db.session.scalars(
            sa.select(VaSubmissions).where(VaSubmissions.va_form_id == va_form.form_id)
        ).all()
        totals["submissions_scanned"] += len(submissions)
        if log_progress:
            log_progress(
                f"[{va_form.form_id}] attachment backfill scanning {len(submissions)} submission(s)"
            )

        for submission in submissions:
            refs, missing_count = _submission_attachment_refs(submission, form_media_dir)
            totals["missing_files"] += missing_count
            if not refs:
                continue

            existing = {
                row.filename: row
                for row in db.session.scalars(
                    sa.select(VaSubmissionAttachments).where(
                        VaSubmissionAttachments.va_sid == submission.va_sid
                    )
                ).all()
            }

            for ref in refs:
                if ref["filename"] == _AUDIT_CSV:
                    continue

                row = existing.get(ref["filename"])
                if row is None:
                    # New row — assign storage_name and rename file
                    updated_ref = _assign_storage_name_and_rename(form_media_dir, ref)
                    for attempt in range(3):
                        try:
                            db.session.add(
                                VaSubmissionAttachments(
                                    va_sid=submission.va_sid,
                                    filename=updated_ref["filename"],
                                    local_path=updated_ref["local_path"],
                                    mime_type=updated_ref["mime_type"],
                                    storage_name=updated_ref["storage_name"],
                                    etag=None,
                                    exists_on_odk=True,
                                    last_downloaded_at=updated_ref["last_downloaded_at"],
                                )
                            )
                            db.session.flush()
                            totals["attachments_created"] += 1
                            break
                        except IntegrityError as exc:
                            db.session.rollback()
                            if "ix_va_submission_attachments_storage_name" in str(exc) and attempt < 2:
                                updated_ref["storage_name"] = _generate_storage_name(ref["filename"])
                                new_path = os.path.join(form_media_dir, updated_ref["storage_name"])
                                if os.path.exists(updated_ref["local_path"]):
                                    os.rename(updated_ref["local_path"], new_path)
                                updated_ref["local_path"] = new_path
                            else:
                                raise
                    continue

                changed = False

                # Assign storage_name if missing (pre-migration row)
                if row.storage_name is None:
                    updated_ref = _assign_storage_name_and_rename(form_media_dir, ref)
                    row.storage_name = updated_ref["storage_name"]
                    row.local_path = updated_ref["local_path"]
                    changed = True
                else:
                    if row.local_path != ref["local_path"] and row.local_path != os.path.join(form_media_dir, row.storage_name):
                        row.local_path = ref["local_path"]
                        changed = True

                if row.mime_type != ref["mime_type"]:
                    row.mime_type = ref["mime_type"]
                    changed = True
                if row.exists_on_odk is not True:
                    row.exists_on_odk = True
                    changed = True
                if row.last_downloaded_at is None:
                    row.last_downloaded_at = ref["last_downloaded_at"]
                    changed = True

                if changed:
                    totals["attachments_updated"] += 1
                else:
                    totals["attachments_skipped"] += 1

        db.session.commit()
        if log_progress:
            log_progress(
                f"[{va_form.form_id}] attachment backfill done: "
                f"{totals['attachments_created']} created, "
                f"{totals['attachments_updated']} updated"
            )

    return totals
