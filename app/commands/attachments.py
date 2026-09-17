"""CLI for attachment delivery settings and the local -> S3 cutover.

The per-project Central-fetch flag is the rollout switch for Phase 4a of
``docs/planning/s3-attachment-plan.md``. Delivery always reads DigitVA's own
store first; the flag decides only what happens on a store miss — with it off
a miss is a 404 exactly as before, with it on the original is fetched from the
project's own ODK Central connection, streamed to the browser, and written
into the store.

``s3-upload`` and ``local-quarantine`` are the cutover pair. Neither ever
deletes an attachment: the upload copies local blobs into the bucket and
verifies them, and the quarantine only *moves* verified local files aside so
an operator can remove them by hand after a retention window. See
``docs/policy/attachment-storage.md``.
"""

import hashlib
import mimetypes
import os
from concurrent.futures import ThreadPoolExecutor

import click
import sqlalchemy as sa

from app import db
from app.models import VaProjectMaster
from app.models.va_submission_attachments import VaSubmissionAttachments
from app.models.va_submissions import VaSubmissions
from app.services import attachment_service as svc
from app.services.attachment_store import (
    DEFAULT_CONTENT_TYPE,
    LocalAttachmentStore,
    StoreTarget,
    get_attachment_store,
)


@click.group("attachments")
def attachments_group():
    """Attachment delivery commands."""
    pass


@attachments_group.command("central-fetch")
@click.argument("project_id")
@click.option(
    "--enable",
    "action",
    flag_value="enable",
    help="Self-heal attachment store misses from ODK Central for this project.",
)
@click.option(
    "--disable",
    "action",
    flag_value="disable",
    help="Return this project to store-only delivery (a miss is a 404).",
)
@click.option(
    "--status",
    "action",
    flag_value="status",
    default=True,
    help="Report the current setting (default).",
)
def central_fetch(project_id, action):
    """Show or change Central self-heal on attachment store misses for PROJECT_ID."""
    project_id = (project_id or "").strip().upper()
    project = db.session.get(VaProjectMaster, project_id)
    if project is None:
        raise click.ClickException(f"Project '{project_id}' not found.")

    if action in ("enable", "disable"):
        project.attachment_central_fetch_enabled = action == "enable"
        db.session.commit()

    click.echo(
        f"{project.project_id}: attachment_central_fetch_enabled="
        f"{project.attachment_central_fetch_enabled}"
    )


# ---------------------------------------------------------------------------
# Local -> S3 cutover
# ---------------------------------------------------------------------------

# Rows are read in keyset pages so the tool never loads the whole table, and
# so an interrupted run resumes from where it stopped.
_PAGE_SIZE = 200
_HASH_CHUNK_SIZE = 1024 * 1024

# Quarantine destination under each form's media directory. Files are moved
# here, never removed; the retention delete is a manual, documented step.
QUARANTINE_DIRNAME = ".s3-uploaded"


def _require_s3_store():
    store = get_attachment_store()
    if store.name != svc.STORE_STATE_S3:
        raise click.ClickException(
            "ATTACHMENT_STORE is not 's3'. Set ATTACHMENT_STORE=s3 (with the "
            "S3_* variables) before running the cutover commands."
        )
    return store


def _content_type_for(row) -> str:
    """The MIME to store the blob under.

    ``.amr`` rows hold an MP3 derivative, so the derivative's type wins for
    them; every other row is its original. A missing, malformed, or literal
    ``"null"`` value is discarded by ``safe_mime_type`` and the type is guessed
    from the storage name before falling back to a generic binary type.
    """
    is_audio = (row.filename or "").lower().endswith(".amr")
    preferred = row.derivative_mime_type if is_audio else row.source_mime_type
    for candidate in (preferred, row.mime_type):
        resolved = svc.safe_mime_type(candidate)
        if resolved:
            return resolved
    guessed, _ = mimetypes.guess_type(row.storage_name or "")
    return guessed or DEFAULT_CONTENT_TYPE


def _file_md5(path: str) -> str:
    # MD5 because that is what a single-part S3 ETag is; not a security hash.
    digest = hashlib.md5(usedforsecurity=False)
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(_HASH_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _candidate_page(form_id, after, page_size):
    """One keyset page of rows whose blob is not yet recorded as being in S3."""
    stmt = (
        sa.select(
            VaSubmissionAttachments.va_sid,
            VaSubmissionAttachments.filename,
            VaSubmissionAttachments.storage_name,
            VaSubmissionAttachments.local_path,
            VaSubmissionAttachments.mime_type,
            VaSubmissionAttachments.source_mime_type,
            VaSubmissionAttachments.derivative_mime_type,
            VaSubmissions.va_form_id,
        )
        .join(VaSubmissions, VaSubmissions.va_sid == VaSubmissionAttachments.va_sid)
        .where(
            VaSubmissionAttachments.exists_on_odk.is_(True),
            VaSubmissionAttachments.storage_name.is_not(None),
            VaSubmissionAttachments.store_state != svc.STORE_STATE_S3,
        )
        .order_by(VaSubmissionAttachments.va_sid, VaSubmissionAttachments.filename)
        .limit(page_size)
    )
    if form_id:
        stmt = stmt.where(VaSubmissions.va_form_id == form_id)
    if after is not None:
        stmt = stmt.where(
            sa.tuple_(
                VaSubmissionAttachments.va_sid, VaSubmissionAttachments.filename
            ) > sa.tuple_(sa.literal(after[0]), sa.literal(after[1]))
        )
    return db.session.execute(stmt).all()


def _upload_one(store, row, content_type, path):
    """Upload one row's blob and verify what landed. Returns an error or None.

    Runs on a worker thread: filesystem and network only, never the ORM
    session and never the app context, so ``path`` is resolved by the caller.
    Verification is size plus, for a single-part upload, the ETag against the
    local MD5 — a partial or truncated object is a failure, not a silent
    success.
    """
    if path is None:
        return "no local file"
    target = StoreTarget(
        va_form_id=row.va_form_id,
        storage_name=row.storage_name,
        local_path=row.local_path,
    )

    try:
        local_size = os.path.getsize(path)
        key = store.key_for(target)
        head = store.head(key)
        if head is None or head.get("ContentLength") != local_size:
            store.put(target, path, content_type=content_type)
            head = store.head(key)

        if head is None:
            return "object missing after upload"
        if head.get("ContentLength") != local_size:
            return f"size mismatch (local {local_size}, stored {head.get('ContentLength')})"
        etag = (head.get("ETag") or "").strip('"')
        if etag and "-" not in etag and etag != _file_md5(path):
            return "ETag does not match the local file"
    except OSError:
        return "local file could not be read"
    except Exception as exc:
        return f"upload failed ({type(exc).__name__})"
    return None


@attachments_group.command("s3-upload")
@click.option("--form-id", default=None, help="Limit to one form_id.")
@click.option("--dry-run", is_flag=True, help="Report what would be uploaded; write nothing.")
@click.option("--limit", type=int, default=0, help="Stop after N rows (0 = no limit).")
@click.option("--workers", type=int, default=4, help="Parallel uploads (default 4).")
def s3_upload(form_id, dry_run, limit, workers):
    """Copy local attachment blobs into the S3 store and point the rows at them.

    Idempotent and resumable: rows already recorded as ``store_state='s3'`` are
    not revisited, and a row whose object is already present with the right
    size is verified rather than re-uploaded. Bounded memory — every blob is
    streamed from its file. Local files are never deleted; use
    ``local-quarantine`` and then a manual removal after the retention window.

    Attachments of submissions retired from ODK are uploaded too: the object
    becomes their archive copy.
    """
    store = _require_s3_store()
    local_store = LocalAttachmentStore()
    if workers < 1:
        raise click.ClickException("--workers must be at least 1.")

    counts = {"scanned": 0, "uploaded": 0, "would_upload": 0, "failed": 0}
    failures: list[str] = []
    after = None

    while True:
        page_size = _PAGE_SIZE
        if limit:
            remaining = limit - counts["scanned"]
            if remaining <= 0:
                break
            page_size = min(page_size, remaining)
        rows = _candidate_page(form_id, after, page_size)
        if not rows:
            break
        after = (rows[-1].va_sid, rows[-1].filename)
        counts["scanned"] += len(rows)

        if dry_run:
            counts["would_upload"] += len(rows)
            for row in rows:
                click.echo(
                    f"would upload {row.va_form_id}/{row.storage_name} "
                    f"as {_content_type_for(row)}"
                )
            continue

        # Local paths are resolved here, on the thread that holds the app
        # context; the workers only move bytes.
        plans = [
            (
                row,
                _content_type_for(row),
                local_store.open_local_path(StoreTarget(
                    va_form_id=row.va_form_id,
                    storage_name=row.storage_name,
                    local_path=row.local_path,
                )),
            )
            for row in rows
        ]
        with ThreadPoolExecutor(max_workers=min(workers, len(plans))) as pool:
            outcomes = list(pool.map(
                lambda plan: _upload_one(store, plan[0], plan[1], plan[2]),
                plans,
            ))

        for (row, _, _path), error in zip(plans, outcomes, strict=True):
            if error:
                counts["failed"] += 1
                failures.append(f"{row.va_form_id}/{row.storage_name}: {error}")
                continue
            db.session.execute(
                sa.update(VaSubmissionAttachments)
                .where(
                    VaSubmissionAttachments.va_sid == row.va_sid,
                    VaSubmissionAttachments.filename == row.filename,
                )
                .values(store_state=svc.STORE_STATE_S3, local_path=None)
            )
            svc.invalidate_attachment_record(row.storage_name)
            counts["uploaded"] += 1
        db.session.commit()
        click.echo(
            f"... scanned={counts['scanned']} uploaded={counts['uploaded']} "
            f"failed={counts['failed']}"
        )

    click.echo(
        f"s3-upload: scanned={counts['scanned']} uploaded={counts['uploaded']} "
        f"would_upload={counts['would_upload']} failed={counts['failed']}"
    )
    for failure in failures[:50]:
        click.echo(f"- {failure}")
    if counts["failed"]:
        raise SystemExit(1)


@attachments_group.command("local-quarantine")
@click.option("--form-id", default=None, help="Limit to one form_id.")
@click.option("--dry-run", is_flag=True, help="Report what would move; move nothing.")
@click.option(
    "--include-retained",
    is_flag=True,
    help=(
        "Also move the archival copies of submissions retired from ODK. Off by "
        "default because the policy keeps those local files."
    ),
)
def local_quarantine(form_id, dry_run, include_retained):
    """Move the local files of verified S3-stored rows into media/.s3-uploaded/.

    Nothing is deleted. Each file is moved only after its object is confirmed
    present in the bucket, so the copy count never drops below one. Removing
    the quarantined files after the retention window is a manual ``rm``, by
    design — see docs/current-state/runtime-and-operations.md.
    """
    store = _require_s3_store()
    local_store = LocalAttachmentStore()

    stmt = (
        sa.select(
            VaSubmissionAttachments.va_sid,
            VaSubmissionAttachments.filename,
            VaSubmissionAttachments.storage_name,
            VaSubmissionAttachments.local_path,
            VaSubmissionAttachments.local_fallback_state,
            VaSubmissions.va_form_id,
        )
        .join(VaSubmissions, VaSubmissions.va_sid == VaSubmissionAttachments.va_sid)
        .where(
            VaSubmissionAttachments.store_state == svc.STORE_STATE_S3,
            VaSubmissionAttachments.storage_name.is_not(None),
        )
        .order_by(VaSubmissionAttachments.va_sid, VaSubmissionAttachments.filename)
    )
    if form_id:
        stmt = stmt.where(VaSubmissions.va_form_id == form_id)
    if not include_retained:
        stmt = stmt.where(
            VaSubmissionAttachments.local_fallback_state != svc.LOCAL_RETAINED
        )

    counts = {"moved": 0, "would_move": 0, "skipped_no_object": 0, "no_local_file": 0}
    for row in db.session.execute(stmt).yield_per(_PAGE_SIZE):
        target = StoreTarget(
            va_form_id=row.va_form_id,
            storage_name=row.storage_name,
            local_path=row.local_path,
        )
        path = local_store.open_local_path(target)
        if path is None:
            counts["no_local_file"] += 1
            continue
        if not store.exists(target):
            counts["skipped_no_object"] += 1
            click.echo(f"! no object yet for {row.va_form_id}/{row.storage_name}; left in place")
            continue
        if dry_run:
            counts["would_move"] += 1
            continue

        quarantine_dir = os.path.join(
            local_store.media_dir(target), QUARANTINE_DIRNAME
        )
        os.makedirs(quarantine_dir, exist_ok=True)
        os.replace(path, os.path.join(quarantine_dir, row.storage_name))
        db.session.execute(
            sa.update(VaSubmissionAttachments)
            .where(
                VaSubmissionAttachments.va_sid == row.va_sid,
                VaSubmissionAttachments.filename == row.filename,
            )
            .values(local_fallback_state=svc.LOCAL_QUARANTINED)
        )
        counts["moved"] += 1
        if counts["moved"] % _PAGE_SIZE == 0:
            db.session.commit()
    db.session.commit()

    click.echo(
        f"local-quarantine: moved={counts['moved']} would_move={counts['would_move']} "
        f"skipped_no_object={counts['skipped_no_object']} "
        f"no_local_file={counts['no_local_file']}"
    )


def init_app(app):
    """Register attachment CLI commands with the Flask app."""
    app.cli.add_command(attachments_group)
