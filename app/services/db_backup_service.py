"""Database dumps to the DigitVA object store.

The VM this runs on is small and its disk is the scarce resource. Postgres
itself stays on it, but a dump does not: with ``ATTACHMENT_STORE=s3`` a nightly
``pg_dump -Fc`` is streamed to a single temporary file, uploaded to the same
private bucket the attachments use under
``db-backups/<db_name>/pg_dump_<db>_<UTC timestamp>.dump``, verified, and the
temporary file is removed. The VM keeps no dump history at all — the history is
``va_db_backups`` rows, and retention (``DB_BACKUP_KEEP_DAILY``) is applied to
the objects in the bucket.

On the local store the same dump is written to ``DB_BACKUP_LOCAL_DIR`` and
pruned there the same way, so ``flask backups db-dump`` is still a useful
command in development.

A dump is the whole database: every payload, every narrative, every ODK
credential ciphertext. It is PHI and more. The bucket is private, every object
is written with SSE and ``no-store``, and a backup object is **never presigned
and never served to a browser** — the only way back to one is an operator with
bucket credentials running ``flask backups db-download``. The database password
reaches ``pg_dump`` through ``PGPASSWORD`` in its environment and never appears
in an argument vector, a log line or an API response.

Runbook and retention: ``docs/current-state/backup.md``.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

import sqlalchemy as sa
from flask import current_app

from app import db
from app.models import VaDbBackup
from app.services.attachment_store import (
    AttachmentStoreError,
    get_attachment_store,
)
from config import ATTACHMENT_STORE_LOCAL, ATTACHMENT_STORE_S3

log = logging.getLogger(__name__)

# Key prefix inside the store. Sits beside the attachment and SmartVA run keys
# in the same bucket, which is what lets one IAM user cover all three.
BACKUP_KEY_ROOT = "db-backups/"

# Everything is uploaded with a single ``put_object``: one atomic write, no
# multipart state to clean up after a failure, and an ETag that is a plain MD5
# we can verify. S3 caps that call at 5 GiB, so a dump larger than this is a
# clear failure rather than a truncated object. Today's dump is ~30 MB.
PUT_OBJECT_MAX_BYTES = 4_500_000_000

# Bytes moved per read while streaming pg_dump's stdout to disk.
DUMP_CHUNK_SIZE = 1024 * 1024

# Backups listed by the overview and the admin panel.
OVERVIEW_LIMIT = 10

# ``pg_dump_<db>_<YYYYmmddTHHMMSSZ>.dump`` — the same name the manual
# scripts/manual-db-dump.sh produces, so the two are interchangeable.
DUMP_NAME_RE = re.compile(r"^pg_dump_.+_(\d{8}T\d{6}Z)\.dump$")

DUMP_CONTENT_TYPE = "application/octet-stream"

# Short failure categories written to ``error_code`` and shown to an admin.
# Never a path, a key, a connection string or a message from pg_dump.
ERROR_PG_DUMP_MISSING = "pg_dump_missing"
ERROR_PG_DUMP_FAILED = "pg_dump_failed"
ERROR_PG_DUMP_TIMEOUT = "pg_dump_timeout"
ERROR_DUMP_EMPTY = "dump_empty"
ERROR_DUMP_TOO_LARGE = "dump_too_large"
ERROR_UPLOAD_FAILED = "upload_failed"
ERROR_VERIFY_MISMATCH = "verify_mismatch"
ERROR_LOCAL_WRITE_FAILED = "local_write_failed"


class DbBackupError(RuntimeError):
    """A backup operation the caller asked for could not be completed."""


@dataclass(frozen=True)
class BackupOutcome:
    """What one ``create_db_backup`` call did. No credentials, ever."""

    backup_id: str
    status: str
    store: str
    object_key: str | None
    size_bytes: int
    sha256: str | None
    error_code: str | None

    @property
    def ok(self) -> bool:
        return self.status == VaDbBackup.STATUS_SUCCESS


@dataclass(frozen=True)
class PruneOutcome:
    """What one ``prune_db_backups`` call removed, and what it kept."""

    store: str
    keep_daily: int
    kept: int
    pruned: int
    pruned_keys: list[str] = field(default_factory=list)
    skipped_reason: str | None = None

    @property
    def ok(self) -> bool:
        return self.skipped_reason is None


def backup_store_name() -> str:
    """``s3`` or ``local`` — where a dump made right now would go."""
    return get_attachment_store().name


def dump_key_prefix() -> str:
    """``db-backups/<db_name>/`` — the store-relative prefix for this database."""
    return f"{BACKUP_KEY_ROOT}{_database_name()}/"


def create_db_backup(*, triggered_by: str, user_id=None) -> BackupOutcome:
    """Dump the application database and put it where the retention policy wants.

    ``triggered_by`` is one of ``VaDbBackup.TRIGGER_*`` and is recorded on the
    row. ``user_id`` is the admin who pressed the button, if any.

    The row is written ``running`` before ``pg_dump`` starts, so an interrupted
    run leaves evidence. The dump streams from ``pg_dump``'s stdout into one
    temporary file under ``DB_BACKUP_TMP_DIR`` while its size, sha256 and md5
    are computed in the same pass; the temporary file is removed in a
    ``finally`` whatever happens. On the S3 store the object is verified by a
    HEAD on its size and — a single ``put_object`` always yields a plain MD5
    ETag — on that ETag, and any failure after the upload deletes the object so
    a half-verified dump never sits in the bucket pretending to be a backup.

    Returns a ``BackupOutcome`` and raises nothing the caller has to handle: a
    failure is recorded as ``failed`` with a short ``error_code``.
    """
    store = get_attachment_store()
    started = datetime.now(timezone.utc)
    row = VaDbBackup(
        backup_id=uuid.uuid4(),
        started_at=started,
        triggered_by=triggered_by,
        triggered_user_id=user_id,
        status=VaDbBackup.STATUS_RUNNING,
        store=store.name,
    )
    db.session.add(row)
    db.session.commit()

    object_key = f"{dump_key_prefix()}{_dump_filename(started)}"
    tmp_dir = current_app.config["DB_BACKUP_TMP_DIR"]
    os.makedirs(tmp_dir, exist_ok=True)
    tmp_path = os.path.join(tmp_dir, f".db_backup_{row.backup_id.hex}.dump")

    try:
        try:
            size_bytes, sha256, md5 = _stream_pg_dump(tmp_path)
        except DbBackupError as exc:
            return _record_failure(row, str(exc))

        if store.name == ATTACHMENT_STORE_S3:
            error_code = _upload_and_verify(store, object_key, tmp_path, size_bytes, md5)
        else:
            object_key = _dump_filename(started)
            error_code = _place_local(tmp_path, object_key)

        if error_code:
            return _record_failure(row, error_code)
        return _record_success(row, object_key, size_bytes, sha256)
    finally:
        _remove_quietly(tmp_path)


def prune_db_backups(*, keep_daily: int | None = None) -> PruneOutcome:
    """Delete every dump beyond the newest ``keep_daily``, in either store.

    Ordering is by the UTC timestamp in the dump's own name, newest first, so a
    clock skew on the object's ``LastModified`` cannot reorder history. At least
    one dump is always kept: ``keep_daily`` is clamped to 1, which makes a
    misconfigured ``DB_BACKUP_KEEP_DAILY=0`` a no-op rather than a wipe.

    A listing that fails skips the prune entirely — nothing is deleted on a
    partial view of the store. Rows for deleted objects become ``pruned``.
    """
    store = get_attachment_store()
    keep = max(
        int(
            keep_daily
            if keep_daily is not None
            else current_app.config["DB_BACKUP_KEEP_DAILY"]
        ),
        1,
    )

    try:
        names = _list_dump_names(store)
    except (AttachmentStoreError, OSError):
        log.warning("db backup: could not list the backup store; nothing pruned")
        return PruneOutcome(
            store=store.name,
            keep_daily=keep,
            kept=0,
            pruned=0,
            skipped_reason="listing_failed",
        )

    ordered = sorted(names, key=_dump_sort_key, reverse=True)
    doomed = ordered[keep:]
    pruned: list[str] = []
    for name in doomed:
        if _delete_dump(store, name):
            pruned.append(name)

    if pruned:
        _mark_rows_pruned(pruned)

    return PruneOutcome(
        store=store.name,
        keep_daily=keep,
        kept=len(ordered) - len(pruned),
        pruned=len(pruned),
        pruned_keys=pruned,
    )


def db_backup_overview() -> dict:
    """Recent backups, the last success and failure, total bytes, retention.

    Three bounded queries: the ten most recent rows, one aggregate over the
    successful ones, and one lookup of the most recent failure. Never a
    credential, a host, or anything beyond the object key an operator needs to
    name a dump in ``flask backups db-download``.
    """
    recent = list(
        db.session.scalars(
            sa.select(VaDbBackup)
            .order_by(VaDbBackup.started_at.desc())
            .limit(OVERVIEW_LIMIT)
        ).all()
    )

    totals = db.session.execute(
        sa.select(
            sa.func.count().label("backups"),
            sa.func.coalesce(sa.func.sum(VaDbBackup.size_bytes), 0).label("bytes"),
        ).where(VaDbBackup.status == VaDbBackup.STATUS_SUCCESS)
    ).one()

    last_failure = db.session.scalars(
        sa.select(VaDbBackup)
        .where(VaDbBackup.status == VaDbBackup.STATUS_FAILED)
        .order_by(VaDbBackup.started_at.desc())
        .limit(1)
    ).first()

    last_success = next(
        (row for row in recent if row.status == VaDbBackup.STATUS_SUCCESS), None
    ) or db.session.scalars(
        sa.select(VaDbBackup)
        .where(VaDbBackup.status == VaDbBackup.STATUS_SUCCESS)
        .order_by(VaDbBackup.started_at.desc())
        .limit(1)
    ).first()

    return {
        "store": backup_store_name(),
        "key_prefix": dump_key_prefix(),
        "local_dir": (
            current_app.config["DB_BACKUP_LOCAL_DIR"]
            if backup_store_name() == ATTACHMENT_STORE_LOCAL
            else None
        ),
        "keep_daily": int(current_app.config["DB_BACKUP_KEEP_DAILY"]),
        "daily_time": current_app.config["DB_BACKUP_DAILY_TIME"],
        "successful_backups": int(totals.backups),
        "total_bytes": int(totals.bytes),
        "last_success": _serialize(last_success),
        "last_failure": _serialize(last_failure),
        "recent": [_serialize(row) for row in recent],
    }


def download_db_backup(key: str, dest_path: str) -> dict:
    """Fetch one dump out of the store to ``dest_path`` and verify its sha256.

    ``key`` is an ``object_key`` exactly as ``db_backup_overview`` reports it.
    The checksum is the one recorded when the dump was made: a dump this app
    has no record of cannot be verified, so it is refused rather than handed to
    a restore that would trust it. A mismatch removes the downloaded file.

    Returns ``{"path", "size_bytes", "sha256"}``; raises ``DbBackupError`` with
    a message an operator can act on.
    """
    key = (key or "").strip()
    if not key:
        raise DbBackupError("A backup object key is required.")

    recorded = db.session.scalars(
        sa.select(VaDbBackup)
        .where(
            VaDbBackup.object_key == key,
            VaDbBackup.status.in_(
                (VaDbBackup.STATUS_SUCCESS, VaDbBackup.STATUS_PRUNED)
            ),
            VaDbBackup.sha256.is_not(None),
        )
        .order_by(VaDbBackup.started_at.desc())
        .limit(1)
    ).first()
    if recorded is None:
        raise DbBackupError(
            "No recorded checksum for that backup key, so its bytes cannot be "
            "verified. Restore it by hand only if you trust its provenance."
        )

    dest_path = os.path.abspath(dest_path)
    os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)

    store = get_attachment_store()
    try:
        if store.name == ATTACHMENT_STORE_S3:
            store.get_key(key, dest_path)
        else:
            _copy_local_dump(key, dest_path)
    except (AttachmentStoreError, OSError) as exc:
        _remove_quietly(dest_path)
        raise DbBackupError("Could not read that backup from the store.") from exc

    size_bytes, sha256 = _hash_file(dest_path)
    if sha256 != recorded.sha256:
        _remove_quietly(dest_path)
        raise DbBackupError(
            "Checksum mismatch: the downloaded dump does not match the sha256 "
            "recorded when it was created. The file has been removed."
        )
    return {"path": dest_path, "size_bytes": size_bytes, "sha256": sha256}


# ---------------------------------------------------------------------------
# pg_dump
# ---------------------------------------------------------------------------

def _stream_pg_dump(tmp_path: str) -> tuple[int, str, str]:
    """Run ``pg_dump -Fc`` to ``tmp_path``, hashing as the bytes go past.

    stdout is consumed in bounded chunks so a large dump never lands in memory;
    stderr goes to a file of its own so neither pipe can fill and deadlock the
    other. Raises ``DbBackupError(error_code)`` on any failure.
    """
    argv, env = _pg_dump_command()
    timeout = int(current_app.config["DB_BACKUP_TIMEOUT_SECONDS"])
    sha = hashlib.sha256()
    md5 = hashlib.md5()
    size = 0

    with tempfile.TemporaryFile() as stderr_file:
        try:
            process = subprocess.Popen(
                argv, stdout=subprocess.PIPE, stderr=stderr_file, env=env
            )
        except FileNotFoundError as exc:
            raise DbBackupError(ERROR_PG_DUMP_MISSING) from exc

        try:
            with open(tmp_path, "wb") as handle:
                while True:
                    chunk = process.stdout.read(DUMP_CHUNK_SIZE)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > PUT_OBJECT_MAX_BYTES:
                        raise DbBackupError(ERROR_DUMP_TOO_LARGE)
                    sha.update(chunk)
                    md5.update(chunk)
                    handle.write(chunk)
            returncode = process.wait(timeout=timeout)
        except DbBackupError:
            _terminate(process)
            log.error(
                "db backup: dump exceeded the %d byte single-request limit; "
                "aborted before any upload",
                PUT_OBJECT_MAX_BYTES,
            )
            raise
        except subprocess.TimeoutExpired as exc:
            _terminate(process)
            raise DbBackupError(ERROR_PG_DUMP_TIMEOUT) from exc
        except OSError as exc:
            _terminate(process)
            raise DbBackupError(ERROR_PG_DUMP_FAILED) from exc
        finally:
            if process.stdout is not None:
                process.stdout.close()

        if returncode != 0:
            log.error(
                "db backup: pg_dump exited %s — %s",
                returncode,
                _tail(stderr_file),
            )
            raise DbBackupError(ERROR_PG_DUMP_FAILED)

    if size == 0:
        log.error("db backup: pg_dump produced an empty dump")
        raise DbBackupError(ERROR_DUMP_EMPTY)
    return size, sha.hexdigest(), md5.hexdigest()


def _pg_dump_command() -> tuple[list[str], dict]:
    """The argument vector and environment for ``pg_dump``.

    The password is the one thing that never goes in the vector: it is passed
    through ``PGPASSWORD`` in a copy of the environment, which is also why this
    builds a list rather than a shell string. ``--no-owner``/``--no-privileges``
    match ``scripts/manual-db-restore.sh``, so either dump restores the same way.
    With no ``--file`` the custom-format archive goes to stdout, which is what
    lets the caller hash it in the same pass that writes it.
    """
    url = sa.engine.make_url(current_app.config["SQLALCHEMY_DATABASE_URI"])
    argv = [
        "pg_dump",
        "--format=custom",
        "--no-owner",
        "--no-privileges",
        "--dbname",
        url.database or "",
    ]
    if url.host:
        argv += ["--host", url.host]
    if url.port:
        argv += ["--port", str(url.port)]
    if url.username:
        argv += ["--username", url.username]

    env = os.environ.copy()
    password = url.password
    if password:
        env["PGPASSWORD"] = password
    else:
        env.pop("PGPASSWORD", None)
    return argv, env


def _terminate(process) -> None:
    """Stop a pg_dump that must not keep running. Never raises."""
    try:
        process.kill()
        process.wait(timeout=10)
    except Exception:  # noqa: BLE001 - teardown must not mask the real failure
        log.warning("db backup: could not stop pg_dump cleanly", exc_info=True)


def _tail(stderr_file, limit: int = 500) -> str:
    """The last ``limit`` characters pg_dump wrote to stderr, for the log.

    pg_dump never echoes ``PGPASSWORD``; what lands here is a connection or
    permission error. Truncated so a runaway diagnostic cannot flood the log.
    """
    try:
        stderr_file.seek(0)
        return stderr_file.read().decode("utf-8", "replace")[-limit:].strip()
    except OSError:
        return ""


# ---------------------------------------------------------------------------
# Placing the dump
# ---------------------------------------------------------------------------

def _upload_and_verify(store, object_key, tmp_path, size_bytes, md5) -> str | None:
    """Put the dump in the bucket and confirm it arrived whole.

    Returns None on success or a short error code. On any failure the object is
    deleted, so the bucket never holds a dump this function did not verify.
    """
    try:
        store.put_key(object_key, tmp_path, content_type=DUMP_CONTENT_TYPE)
    except AttachmentStoreError:
        log.warning("db backup: upload failed")
        _delete_quietly(store, object_key)
        return ERROR_UPLOAD_FAILED
    except Exception:  # noqa: BLE001 - a transport error must still record failed
        log.warning("db backup: store error during upload", exc_info=True)
        _delete_quietly(store, object_key)
        return ERROR_UPLOAD_FAILED

    head = store.head_key(object_key)
    if head is None or int(head.get("ContentLength") or 0) != size_bytes:
        log.error("db backup: uploaded object did not verify by size")
        _delete_quietly(store, object_key)
        return ERROR_VERIFY_MISMATCH

    # A single put_object yields an ETag that is the plain MD5 of the body. A
    # dash means the object was assembled from parts, which this code never
    # does, so only the single-part form is checked.
    etag = (head.get("ETag") or "").strip('"')
    if etag and "-" not in etag and etag != md5:
        log.error("db backup: uploaded object did not verify by ETag")
        _delete_quietly(store, object_key)
        return ERROR_VERIFY_MISMATCH
    return None


def _place_local(tmp_path: str, filename: str) -> str | None:
    """Move the dump into ``DB_BACKUP_LOCAL_DIR``. Returns None or an error code."""
    target_dir = current_app.config["DB_BACKUP_LOCAL_DIR"]
    try:
        os.makedirs(target_dir, exist_ok=True)
        # Same filesystem in every deployment, but a rename across devices
        # raises; copy2 + unlink is what shutil.move does and is safe either way.
        shutil.move(tmp_path, os.path.join(target_dir, filename))
    except OSError:
        log.warning("db backup: could not write the dump to the local backup dir")
        return ERROR_LOCAL_WRITE_FAILED
    return None


def _delete_quietly(store, object_key: str) -> None:
    try:
        store.delete_key(object_key)
    except Exception:  # noqa: BLE001 - best effort cleanup of a failed upload
        log.warning("db backup: could not remove a failed upload", exc_info=True)


# ---------------------------------------------------------------------------
# Listing and pruning
# ---------------------------------------------------------------------------

def _list_dump_names(store) -> list[str]:
    """Every dump this database has in the store, as ``object_key`` values."""
    if store.name == ATTACHMENT_STORE_S3:
        prefix = dump_key_prefix()
        absolute = store.absolute_key(prefix)
        return [
            key[len(store.key_prefix):]
            for key, _size, _etag in store.iter_keys(absolute)
            if key.startswith(absolute) and DUMP_NAME_RE.match(key.rsplit("/", 1)[-1])
        ]
    local_dir = current_app.config["DB_BACKUP_LOCAL_DIR"]
    if not os.path.isdir(local_dir):
        return []
    return [name for name in os.listdir(local_dir) if DUMP_NAME_RE.match(name)]


def _delete_dump(store, key: str) -> bool:
    """Remove one dump from whichever store holds it. Never raises."""
    try:
        if store.name == ATTACHMENT_STORE_S3:
            store.delete_key(key)
        else:
            os.remove(os.path.join(current_app.config["DB_BACKUP_LOCAL_DIR"], key))
    except FileNotFoundError:
        return False
    except (AttachmentStoreError, OSError):
        log.warning("db backup: could not prune a dump", exc_info=True)
        return False
    return True


def _mark_rows_pruned(keys: list[str]) -> None:
    """Flag the rows whose object is gone, so the panel stops offering it."""
    db.session.execute(
        sa.update(VaDbBackup)
        .where(
            VaDbBackup.object_key.in_(keys),
            VaDbBackup.status == VaDbBackup.STATUS_SUCCESS,
        )
        .values(status=VaDbBackup.STATUS_PRUNED, pruned_at=datetime.now(timezone.utc))
    )
    db.session.commit()


def _dump_sort_key(key: str):
    """The UTC timestamp inside a dump's name; its whole name as a tiebreak."""
    match = DUMP_NAME_RE.match(key.rsplit("/", 1)[-1])
    return (match.group(1) if match else "", key)


# ---------------------------------------------------------------------------
# Rows and helpers
# ---------------------------------------------------------------------------

def _database_name() -> str:
    return sa.engine.make_url(current_app.config["SQLALCHEMY_DATABASE_URI"]).database or "db"


def _dump_filename(started: datetime) -> str:
    return (
        f"pg_dump_{_database_name()}_"
        f"{started.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.dump"
    )


def _record_success(row, object_key, size_bytes, sha256) -> BackupOutcome:
    row.status = VaDbBackup.STATUS_SUCCESS
    row.completed_at = datetime.now(timezone.utc)
    row.object_key = object_key
    row.size_bytes = size_bytes
    row.sha256 = sha256
    row.error_code = None
    db.session.add(row)
    db.session.commit()
    log.info(
        "db backup: %s dump of %d bytes stored (backup_id=%s)",
        row.store,
        size_bytes,
        row.backup_id,
    )
    return BackupOutcome(
        backup_id=str(row.backup_id),
        status=row.status,
        store=row.store,
        object_key=object_key,
        size_bytes=size_bytes,
        sha256=sha256,
        error_code=None,
    )


def _record_failure(row, error_code: str) -> BackupOutcome:
    row.status = VaDbBackup.STATUS_FAILED
    row.completed_at = datetime.now(timezone.utc)
    row.error_code = error_code
    row.object_key = None
    row.size_bytes = None
    row.sha256 = None
    db.session.add(row)
    db.session.commit()
    log.error("db backup: failed (%s, backup_id=%s)", error_code, row.backup_id)
    return BackupOutcome(
        backup_id=str(row.backup_id),
        status=row.status,
        store=row.store,
        object_key=None,
        size_bytes=0,
        sha256=None,
        error_code=error_code,
    )


def _serialize(row) -> dict | None:
    if row is None:
        return None
    return {
        "backup_id": str(row.backup_id),
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "triggered_by": row.triggered_by,
        "status": row.status,
        "store": row.store,
        "object_key": row.object_key,
        "size_bytes": row.size_bytes,
        "sha256": row.sha256,
        "error_code": row.error_code,
        "pruned_at": row.pruned_at.isoformat() if row.pruned_at else None,
    }


def _copy_local_dump(key: str, dest_path: str) -> None:
    """Copy one dump out of ``DB_BACKUP_LOCAL_DIR``.

    ``key`` is a bare file name on the local store; it is resolved inside that
    directory and rejected if it escapes, so an operator's typo (or a crafted
    row) cannot read an arbitrary file.
    """
    local_dir = os.path.realpath(current_app.config["DB_BACKUP_LOCAL_DIR"])
    source = os.path.realpath(os.path.join(local_dir, key))
    if not source.startswith(local_dir + os.sep) or not os.path.isfile(source):
        raise DbBackupError("That backup is not in the local backup directory.")
    shutil.copyfile(source, dest_path)


def _hash_file(path: str) -> tuple[int, str]:
    """(size, sha256) of a file, read in bounded chunks."""
    sha = hashlib.sha256()
    size = 0
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(DUMP_CHUNK_SIZE)
            if not chunk:
                break
            size += len(chunk)
            sha.update(chunk)
    return size, sha.hexdigest()


def _remove_quietly(path: str | None) -> None:
    if not path:
        return
    try:
        os.remove(path)
    except FileNotFoundError:
        return
    except OSError:
        log.warning("db backup: could not remove a temporary file", exc_info=True)
