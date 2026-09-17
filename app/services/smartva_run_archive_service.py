"""Archival of SmartVA run directories to the DigitVA object store.

A SmartVA run directory is a *working* area: the SmartVA CLI is a binary that
needs real files on real disk while it runs, and ``smartva_service`` copies the
finished workspace to ``APP_SMARTVA_RUNS/<project>/<form>/<run-uuid>/`` so an
operator can inspect what the binary saw. Nothing in the app reads it after
that — every figure DigitVA shows comes from ``va_smartva_run_outputs`` and
``va_smartva_results`` — which is exactly what makes the directory safe to move
off the VM.

So it is moved. With ``ATTACHMENT_STORE=s3`` a completed run is uploaded to the
same private bucket the attachments use, under
``smartva_runs/<project_id>/<form_id>/<form_run_id>/<relative path>``, verified
against a single listing of that prefix, and only then removed from disk (after
``SMARTVA_RUNS_KEEP_LOCAL_DAYS``, default 0). On the local store nothing
happens at all: runs stay where they are, exactly as before.

These files carry full VA payloads. They are PHI. The bucket is private, every
object is written with SSE and ``no-store``, and — unlike attachments — a
SmartVA run object is **never presigned and never served to a browser**. The
only way back to one is an operator with bucket credentials.

Policy baseline: ``docs/policy/smartva-generation-policy.md``.
"""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa

from app import db
from app.models import VaSmartvaFormRun
from app.services.attachment_store import (
    DEFAULT_CONTENT_TYPE,
    AttachmentStoreError,
    get_attachment_store,
)
from config import ATTACHMENT_STORE_S3

log = logging.getLogger(__name__)

# Key prefix inside the store. Sits beside the attachment keys in the same
# bucket, which is what lets the existing digitva-s3 IAM user cover both.
ARCHIVE_KEY_ROOT = "smartva_runs/"

# Rows walked per page by the backlog sweep. Keyset-paginated on the primary
# key so a long sweep never holds a large result set or a long transaction.
ARCHIVE_PAGE_SIZE = 50

# Content types SmartVA actually produces. Anything else is stored as opaque
# bytes rather than guessed at.
_CONTENT_TYPES = {
    ".csv": "text/csv",
    ".txt": "text/plain",
    ".log": "text/plain",
    ".json": "application/json",
    ".png": "image/png",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

# Short failure categories written to ``archive_error_code``. Never a path, a
# key, a bucket name or a message from the transport.
ERROR_STORE_UNAVAILABLE = "store_unavailable"
ERROR_WALK_FAILED = "walk_failed"
ERROR_UPLOAD_FAILED = "upload_failed"
ERROR_VERIFY_MISMATCH = "verify_mismatch"
ERROR_LOCAL_DELETE_FAILED = "local_delete_failed"


@dataclass(frozen=True)
class ArchiveOutcome:
    """What one ``archive_form_run`` call did. Counts only, no paths."""

    form_run_id: str
    state: str
    file_count: int
    archived_bytes: int
    key_prefix: str | None
    error_code: str | None
    local_deleted: bool

    @property
    def ok(self) -> bool:
        return self.state != VaSmartvaFormRun.ARCHIVE_STATE_FAILED


def content_type_for(relpath: str) -> str:
    """The MIME one archived run file is stored under, by extension."""
    return _CONTENT_TYPES.get(os.path.splitext(relpath)[1].lower(), DEFAULT_CONTENT_TYPE)


def archive_key_prefix_for(form_run: VaSmartvaFormRun) -> str:
    """``smartva_runs/<project_id>/<form_id>/<form_run_id>/``, store-relative."""
    return (
        f"{ARCHIVE_KEY_ROOT}{form_run.project_id}/"
        f"{form_run.form_id}/{form_run.form_run_id}/"
    )


def archiving_enabled() -> bool:
    """True only on the S3 store. The local store archives nothing, ever."""
    return get_attachment_store().name == ATTACHMENT_STORE_S3


def archive_form_run(
    form_run: VaSmartvaFormRun,
    *,
    delete_local: bool = True,
) -> ArchiveOutcome:
    """Archive one completed run directory and record the result on the row.

    Idempotent and resumable: an object that is already present with the right
    size is verified rather than re-uploaded, so re-running after a partial
    failure costs one LIST plus the files that are genuinely missing. Safe to
    call on a run that is already archived — it becomes the retention sweep
    that removes the local copy once ``SMARTVA_RUNS_KEEP_LOCAL_DAYS`` has
    passed.

    ``delete_local`` is the caller's *permission* to remove the directory, not
    an instruction: the keep-days window still has to have elapsed. Nothing is
    ever deleted unless every file is confirmed in the store first, and any
    failure leaves the directory alone and records ``failed``.

    Returns an ``ArchiveOutcome``; raises nothing the caller has to handle.
    """
    from app.services.smartva_service import resolve_form_run_disk_path

    if not archiving_enabled():
        return _outcome(form_run, VaSmartvaFormRun.ARCHIVE_STATE_LOCAL)

    run_dir = resolve_form_run_disk_path(form_run.disk_path)
    if not run_dir or not os.path.isdir(run_dir):
        return _record_absent(form_run)

    try:
        files = _walk_run_dir(run_dir)
    except OSError:
        log.warning("smartva archive: could not read a run directory", exc_info=True)
        return _record_failure(form_run, ERROR_WALK_FAILED)

    if not files:
        return _record_absent(form_run)

    key_prefix = archive_key_prefix_for(form_run)
    store = get_attachment_store()

    try:
        present = _existing_objects(store, key_prefix)
        for relpath, abspath, size in files:
            if present.get(relpath) == size:
                continue
            store.put_key(
                f"{key_prefix}{relpath}",
                abspath,
                content_type=content_type_for(relpath),
            )
        missing = _verify(store, key_prefix, files)
    except AttachmentStoreError:
        log.warning(
            "smartva archive: store write failed for form=%s", form_run.form_id
        )
        return _record_failure(form_run, ERROR_UPLOAD_FAILED)
    except Exception:
        log.warning("smartva archive: store error", exc_info=True)
        return _record_failure(form_run, ERROR_STORE_UNAVAILABLE)

    if missing:
        log.warning(
            "smartva archive: %d file(s) unverified for form=%s",
            missing,
            form_run.form_id,
        )
        return _record_failure(form_run, ERROR_VERIFY_MISMATCH)

    file_count = len(files)
    total_bytes = sum(size for _relpath, _abspath, size in files)
    local_deleted = False
    if delete_local and _keep_window_elapsed(form_run):
        try:
            shutil.rmtree(run_dir)
            local_deleted = True
        except OSError:
            log.warning(
                "smartva archive: verified archive but could not remove the local "
                "run directory for form=%s",
                form_run.form_id,
                exc_info=True,
            )
            _record_state(
                form_run,
                VaSmartvaFormRun.ARCHIVE_STATE_ARCHIVED,
                key_prefix=key_prefix,
                file_count=file_count,
                archived_bytes=total_bytes,
                error_code=ERROR_LOCAL_DELETE_FAILED,
            )
            return _outcome(
                form_run,
                VaSmartvaFormRun.ARCHIVE_STATE_ARCHIVED,
                file_count=file_count,
                archived_bytes=total_bytes,
                key_prefix=key_prefix,
                error_code=ERROR_LOCAL_DELETE_FAILED,
            )

    _record_state(
        form_run,
        VaSmartvaFormRun.ARCHIVE_STATE_ARCHIVED,
        key_prefix=key_prefix,
        file_count=file_count,
        archived_bytes=total_bytes,
        error_code=None,
        clear_disk_path=local_deleted,
    )
    return _outcome(
        form_run,
        VaSmartvaFormRun.ARCHIVE_STATE_ARCHIVED,
        file_count=file_count,
        archived_bytes=total_bytes,
        key_prefix=key_prefix,
        local_deleted=local_deleted,
    )


def archive_run_backlog(
    *,
    form_id: str | None = None,
    dry_run: bool = False,
    limit: int = 0,
    delete_local: bool = False,
    on_progress=None,
) -> dict:
    """Archive the run directories that are still only on this VM.

    Idempotent and resumable: candidates are the rows that are not yet
    ``archived``, plus archived rows whose local copy is still on disk waiting
    out the keep-days window. Keyset-paginated, one page in memory at a time,
    committed per page so an interrupted sweep keeps everything it finished.

    ``on_progress`` is called with a counts-only message after each page, so a
    CLI or a Celery task can report without this function knowing about either.
    """
    counts = {
        "scanned": 0,
        "archived": 0,
        "would_archive": 0,
        "absent": 0,
        "deleted_local": 0,
        "failed": 0,
    }
    failures: list[str] = []

    if not archiving_enabled():
        counts["store"] = get_attachment_store().name
        return {**counts, "failures": failures, "skipped_local_store": True}

    after = None
    while True:
        page_size = ARCHIVE_PAGE_SIZE
        if limit:
            remaining = limit - counts["scanned"]
            if remaining <= 0:
                break
            page_size = min(page_size, remaining)

        rows = _candidate_page(form_id, after, page_size)
        if not rows:
            break
        after = rows[-1].form_run_id
        counts["scanned"] += len(rows)

        if dry_run:
            counts["would_archive"] += len(rows)
        else:
            for form_run in rows:
                outcome = archive_form_run(form_run, delete_local=delete_local)
                if outcome.state == VaSmartvaFormRun.ARCHIVE_STATE_ARCHIVED:
                    counts["archived"] += 1
                    if outcome.local_deleted:
                        counts["deleted_local"] += 1
                elif outcome.state == VaSmartvaFormRun.ARCHIVE_STATE_ABSENT:
                    counts["absent"] += 1
                else:
                    counts["failed"] += 1
                    failures.append(
                        f"{form_run.form_id}/{form_run.form_run_id}: "
                        f"{outcome.error_code}"
                    )
            db.session.commit()

        if on_progress:
            on_progress(
                f"... scanned={counts['scanned']} archived={counts['archived']} "
                f"absent={counts['absent']} failed={counts['failed']}"
            )

    counts["store"] = ATTACHMENT_STORE_S3
    return {**counts, "failures": failures, "skipped_local_store": False}


def smartva_archive_overview(*, form_id: str | None = None) -> dict:
    """Counts by archive state, bytes still on this VM, and the last failure.

    One grouped query for the states, one bounded query for the most recent
    failure category, and one filesystem walk of the run directories in scope
    for the local byte total. Counts and a category only — never a path, a key
    or a submission identifier.
    """
    form_id = (form_id or "").strip() or None

    state_query = sa.select(
        VaSmartvaFormRun.archive_state,
        sa.func.count().label("runs"),
    ).group_by(VaSmartvaFormRun.archive_state)
    if form_id:
        state_query = state_query.where(VaSmartvaFormRun.form_id == form_id)
    counts = {
        state: int(runs)
        for state, runs in db.session.execute(state_query).all()
    }

    failure_query = (
        sa.select(
            VaSmartvaFormRun.archive_error_code,
            VaSmartvaFormRun.run_completed_at,
        )
        .where(VaSmartvaFormRun.archive_state == VaSmartvaFormRun.ARCHIVE_STATE_FAILED)
        .order_by(VaSmartvaFormRun.run_started_at.desc())
        .limit(1)
    )
    if form_id:
        failure_query = failure_query.where(VaSmartvaFormRun.form_id == form_id)
    failure_row = db.session.execute(failure_query).first()

    local_runs, local_bytes = _local_footprint(form_id)

    from flask import current_app

    return {
        "store": get_attachment_store().name,
        "key_prefix": ARCHIVE_KEY_ROOT,
        "keep_local_days": int(current_app.config["SMARTVA_RUNS_KEEP_LOCAL_DAYS"]),
        "form_id": form_id,
        "counts": {
            state: counts.get(state, 0) for state in VaSmartvaFormRun.ARCHIVE_STATES
        },
        "total_runs": sum(counts.values()),
        "local_run_dirs": local_runs,
        "local_bytes": local_bytes,
        "last_failure": (
            {
                "error_code": failure_row[0],
                "run_completed_at": (
                    failure_row[1].isoformat() if failure_row[1] else None
                ),
            }
            if failure_row
            else None
        ),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _walk_run_dir(run_dir: str) -> list[tuple[str, str, int]]:
    """Every file under the run directory as (relative key, path, size)."""
    files: list[tuple[str, str, int]] = []
    for dirpath, _dirnames, filenames in os.walk(run_dir):
        for filename in filenames:
            abspath = os.path.join(dirpath, filename)
            if not os.path.isfile(abspath) or os.path.islink(abspath):
                continue
            relpath = os.path.relpath(abspath, run_dir).replace(os.sep, "/")
            files.append((relpath, abspath, os.path.getsize(abspath)))
    return files


def _existing_objects(store, key_prefix: str) -> dict[str, int]:
    """One paginated LIST of the run's prefix as {relative key: size}."""
    absolute = store.absolute_key(key_prefix)
    return {
        key[len(absolute):]: int(size or 0)
        for key, size, _etag in store.iter_keys(absolute)
        if key.startswith(absolute)
    }


def _verify(store, key_prefix: str, files: list[tuple[str, str, int]]) -> int:
    """Re-list the prefix and count the files that are not there at full size."""
    present = _existing_objects(store, key_prefix)
    return sum(1 for relpath, _abspath, size in files if present.get(relpath) != size)


def _keep_window_elapsed(form_run: VaSmartvaFormRun) -> bool:
    """True when the local copy of this run may go.

    0 keep-days means the directory goes as soon as the archive is verified.
    Otherwise the window runs from the run's completion — the point at which
    the directory stopped being interesting to anybody debugging it.
    """
    from flask import current_app

    keep_days = int(current_app.config["SMARTVA_RUNS_KEEP_LOCAL_DAYS"])
    if keep_days <= 0:
        return True
    completed = form_run.run_completed_at or form_run.run_started_at
    if completed is None:
        return False
    if completed.tzinfo is None:
        completed = completed.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - completed >= timedelta(days=keep_days)


def _candidate_page(form_id: str | None, after, page_size: int):
    """One keyset page of runs whose directory may still be on this VM."""
    query = sa.select(VaSmartvaFormRun).where(
        sa.or_(
            VaSmartvaFormRun.archive_state.in_(
                (
                    VaSmartvaFormRun.ARCHIVE_STATE_LOCAL,
                    VaSmartvaFormRun.ARCHIVE_STATE_FAILED,
                )
            ),
            sa.and_(
                VaSmartvaFormRun.archive_state
                == VaSmartvaFormRun.ARCHIVE_STATE_ARCHIVED,
                VaSmartvaFormRun.disk_path.is_not(None),
            ),
        ),
        VaSmartvaFormRun.run_completed_at.is_not(None),
    )
    if form_id:
        query = query.where(VaSmartvaFormRun.form_id == form_id)
    if after is not None:
        query = query.where(VaSmartvaFormRun.form_run_id > after)
    return list(
        db.session.scalars(
            query.order_by(VaSmartvaFormRun.form_run_id).limit(page_size)
        ).all()
    )


def _local_footprint(form_id: str | None) -> tuple[int, int]:
    """(run directories, bytes) still on this VM for the scope.

    Walks only the ``<project>/<form>/`` subtrees of the forms in scope, so a
    per-form view never walks the whole base directory.
    """
    from flask import current_app

    base = current_app.config["APP_SMARTVA_RUNS"]
    if not base or not os.path.isdir(base):
        return 0, 0

    pair_query = sa.select(
        VaSmartvaFormRun.project_id, VaSmartvaFormRun.form_id
    ).distinct()
    if form_id:
        pair_query = pair_query.where(VaSmartvaFormRun.form_id == form_id)
    roots = [
        os.path.join(base, project_id, form)
        for project_id, form in db.session.execute(pair_query).all()
    ]

    run_dirs = 0
    total_bytes = 0
    for root in roots:
        if not os.path.isdir(root):
            continue
        for entry in os.scandir(root):
            if not entry.is_dir(follow_symlinks=False):
                continue
            run_dirs += 1
            for dirpath, _dirnames, filenames in os.walk(entry.path):
                for filename in filenames:
                    path = os.path.join(dirpath, filename)
                    try:
                        total_bytes += os.path.getsize(path)
                    except OSError:
                        continue
    return run_dirs, total_bytes


def _record_state(
    form_run: VaSmartvaFormRun,
    state: str,
    *,
    key_prefix: str | None = None,
    file_count: int | None = None,
    archived_bytes: int | None = None,
    error_code: str | None = None,
    clear_disk_path: bool = False,
) -> None:
    form_run.archive_state = state
    form_run.archive_key_prefix = key_prefix
    form_run.archive_file_count = file_count
    form_run.archive_bytes = archived_bytes
    form_run.archive_error_code = error_code
    form_run.archived_at = (
        datetime.now(timezone.utc)
        if state == VaSmartvaFormRun.ARCHIVE_STATE_ARCHIVED
        else None
    )
    if clear_disk_path:
        form_run.disk_path = None
    db.session.add(form_run)
    db.session.flush()


def _record_absent(form_run: VaSmartvaFormRun) -> ArchiveOutcome:
    """No directory to archive. Not a failure — and never a deletion."""
    if form_run.archive_state == VaSmartvaFormRun.ARCHIVE_STATE_ARCHIVED:
        return _outcome(
            form_run,
            VaSmartvaFormRun.ARCHIVE_STATE_ARCHIVED,
            file_count=form_run.archive_file_count or 0,
            archived_bytes=form_run.archive_bytes or 0,
            key_prefix=form_run.archive_key_prefix,
        )
    _record_state(form_run, VaSmartvaFormRun.ARCHIVE_STATE_ABSENT)
    return _outcome(form_run, VaSmartvaFormRun.ARCHIVE_STATE_ABSENT)


def _record_failure(form_run: VaSmartvaFormRun, error_code: str) -> ArchiveOutcome:
    """Record why an archive did not happen. The local directory stays put."""
    _record_state(
        form_run, VaSmartvaFormRun.ARCHIVE_STATE_FAILED, error_code=error_code
    )
    return _outcome(
        form_run, VaSmartvaFormRun.ARCHIVE_STATE_FAILED, error_code=error_code
    )


def _outcome(
    form_run: VaSmartvaFormRun,
    state: str,
    *,
    file_count: int = 0,
    archived_bytes: int = 0,
    key_prefix: str | None = None,
    error_code: str | None = None,
    local_deleted: bool = False,
) -> ArchiveOutcome:
    return ArchiveOutcome(
        form_run_id=str(form_run.form_run_id),
        state=state,
        file_count=file_count,
        archived_bytes=archived_bytes,
        key_prefix=key_prefix,
        error_code=error_code,
        local_deleted=local_deleted,
    )
