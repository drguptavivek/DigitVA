"""Data-manager CSV exports in the DigitVA object store.

The VM this runs on is small and its disk is the scarce resource. An export is
*derived* data — a data manager can always ask for it again — so with
``ATTACHMENT_STORE=s3`` the CSV is written straight to the same private bucket
the attachments use, under
``exports/<export_kind>/<user_id>/<UTC timestamp>_<filter hash>.csv``, and
delivered as a short-lived presigned ``attachment`` download. The app server
keeps no export file at all. On the local store the same key layout is written
under ``APP_DATA/exports/`` and served by the app, exactly as before.

The key carries everything the two readers need, which is why there is no
second index and no separate cache prefix:

* the **filter hash** — sha256 over the export kind, the user and the filter
  values — is what makes an object reusable, so ``export_cache_lookup`` is one
  bounded listing of ``exports/<kind>/<user_id>/`` rather than a second store;
* the **UTC timestamp** is what ``prune_exports`` orders and ages by, so a
  clock skew on an object's ``LastModified`` cannot hide a stale export.

An export is PHI-reduced but not PHI-free: it carries payload data for the
submissions a data manager can already see. Every object is written with SSE
and ``private, no-store``, the ``user_id`` is part of the key so a lookup can
only ever reach that user's own objects, and the presigned URL is signed for
one redirect and never stored, cached or logged.

Retention is ``EXPORT_RETENTION_HOURS`` (default 24) and deletion is the point:
unlike attachments, backups and SmartVA runs, nothing here is an archive.

Baseline: ``docs/current-state/data-manager-dashboard.md``, *Exports*.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from flask import current_app

from app.services.attachment_store import (
    AttachmentStoreError,
    get_attachment_store,
)
from config import ATTACHMENT_STORE_S3

log = logging.getLogger(__name__)

# Key prefix inside the store. Sits beside the attachment, SmartVA run and
# backup keys in the same bucket, which is what lets one IAM user cover them
# all. This is the one prefix whose objects are deliberately short-lived.
EXPORT_KEY_ROOT = "exports/"

EXPORT_CONTENT_TYPE = "text/csv; charset=utf-8"

# ``<YYYYmmddTHHMMSSZ>_<16 hex>.csv`` — timestamp first so a plain lexical sort
# of a listing is newest-last, and the hash second so a cache lookup is a
# suffix test on the name.
EXPORT_NAME_RE = re.compile(r"^(\d{8}T\d{6}Z)_([0-9a-f]{16})\.csv$")
EXPORT_TS_FORMAT = "%Y%m%dT%H%M%SZ"

# Half a sha256 is far more than enough to key a per-user, per-kind cache and
# keeps the object name readable in a bucket listing.
FILTER_HASH_LENGTH = 16

# Default retention when EXPORT_RETENTION_HOURS is missing or unusable.
DEFAULT_RETENTION_HOURS = 24

# Excel will not read a UTF-8 CSV without it. Written into the object rather
# than added by the response, so the S3 and local paths deliver the same bytes.
UTF8_BOM = "﻿"

# Bytes moved per read when copying the stored CSV back out.
CHUNK_SIZE = 64 * 1024


class ExportStoreError(RuntimeError):
    """An export could not be written to or read from the store."""


@dataclass(frozen=True)
class ExportRef:
    """One stored export. A key, never a path — the S3 store has no path."""

    key: str
    size_bytes: int
    sha256: str
    created_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class ExportPruneOutcome:
    """What one ``prune_exports`` call removed."""

    store: str
    max_age_hours: int
    pruned: int
    kept: int
    skipped_reason: str | None = None


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def export_retention_hours() -> int:
    """``EXPORT_RETENTION_HOURS``, clamped to at least one hour.

    A misconfigured ``0`` would delete an export the moment it was written, so
    it is clamped rather than obeyed.
    """
    try:
        return max(1, int(current_app.config.get("EXPORT_RETENTION_HOURS", DEFAULT_RETENTION_HOURS)))
    except (TypeError, ValueError):
        return DEFAULT_RETENTION_HOURS


def export_store_name() -> str:
    return get_attachment_store().name


def filter_hash(*, export_kind: str, user_id, filters: dict) -> str:
    """The cache identity of one export: kind, user and every filter value.

    Canonical JSON so that two requests differing only in key order or in an
    absent-versus-empty filter hash the same way the old on-disk cache did.
    """
    payload = {
        "kind": export_kind,
        "user_id": str(user_id),
        "filters": {str(key): filters.get(key) for key in sorted(filters)},
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:FILTER_HASH_LENGTH]


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def write_export(*, export_kind: str, user_id, filters: dict, csv_text: str) -> ExportRef:
    """Store one CSV export and return the reference to it.

    The CSV is streamed to a bounded temporary file first — never handed to the
    store as one in-memory body — so the only whole copy in this process is the
    string the export query already built. The temporary file is removed on
    every path, including a failed upload.
    """
    created_at = datetime.now(timezone.utc)
    key = _export_key(
        export_kind=export_kind,
        user_id=user_id,
        digest=filter_hash(export_kind=export_kind, user_id=user_id, filters=filters),
        created_at=created_at,
    )

    tmp_dir = current_app.config.get("DB_BACKUP_TMP_DIR") or tempfile.gettempdir()
    handle, tmp_path = tempfile.mkstemp(prefix="dm_export_", suffix=".csv", dir=tmp_dir)
    os.close(handle)
    try:
        size_bytes, digest = _write_temp_csv(tmp_path, csv_text)
        _put(key, tmp_path)
    finally:
        _remove_quietly(tmp_path)

    return ExportRef(
        key=key,
        size_bytes=size_bytes,
        sha256=digest,
        created_at=created_at,
        expires_at=created_at + timedelta(hours=export_retention_hours()),
    )


def export_cache_lookup(*, export_kind: str, user_id, filters: dict, ttl_seconds: int):
    """The newest still-fresh export for this kind, user and filter set.

    One bounded listing of ``exports/<kind>/<user_id>/`` — at most the objects
    one user made for one export kind inside the retention window. Returns None
    when the TTL is disabled, nothing matches, or the store cannot be listed;
    a miss only costs a recomputation.
    """
    if ttl_seconds <= 0:
        return None
    digest = filter_hash(export_kind=export_kind, user_id=user_id, filters=filters)
    prefix = _user_prefix(export_kind=export_kind, user_id=user_id)
    now = datetime.now(timezone.utc)

    newest = None
    try:
        # Iterated inside the try: the listing is lazy, so a store failure
        # surfaces here rather than at the call.
        for key, created_at, entry_digest, size_bytes in _list_exports(prefix):
            if entry_digest != digest:
                continue
            if (now - created_at).total_seconds() > ttl_seconds:
                continue
            if newest is None or created_at > newest.created_at:
                newest = ExportRef(
                    key=key,
                    size_bytes=size_bytes or 0,
                    sha256="",
                    created_at=created_at,
                    expires_at=created_at + timedelta(hours=export_retention_hours()),
                )
    except (AttachmentStoreError, OSError):
        log.warning("export store: could not list the export prefix; serving a fresh export")
        return None
    return newest


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def presigned_download_url(ref: ExportRef, filename: str) -> str | None:
    """Sign a short-lived ``attachment`` GET for one export. S3 only.

    ``ATTACHMENT_PRESIGN_EXPIRY_SECONDS`` decides the lifetime. The filename is
    sanitised before it is signed into the response headers, so nothing a
    caller passes can inject a second header directive. Returns None on the
    local store, where the app serves the file itself.
    """
    store = get_attachment_store()
    if store.name != ATTACHMENT_STORE_S3:
        return None
    return store.presigned_key_url(
        ref.key,
        content_type=EXPORT_CONTENT_TYPE,
        filename=safe_filename(filename),
        disposition="attachment",
    )


def export_local_path(ref: ExportRef) -> str | None:
    """The on-disk path of one export on the local store, or None on S3."""
    store = get_attachment_store()
    if store.name == ATTACHMENT_STORE_S3:
        return None
    path = os.path.realpath(os.path.join(_local_root(), ref.key))
    if not path.startswith(_local_root() + os.sep) or not os.path.isfile(path):
        return None
    return path


def safe_filename(filename: str) -> str:
    """A download filename reduced to characters that cannot break a header."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", (filename or "").strip())
    return cleaned[:120] or "export.csv"


# ---------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------

def prune_exports(*, max_age_hours: int | None = None) -> ExportPruneOutcome:
    """Delete every export older than the retention window, in either store.

    Age comes from the UTC timestamp in the object's own name, so a clock skew
    on ``LastModified`` cannot reorder or hide anything. A listing that fails
    skips the prune entirely — nothing is deleted on a partial view of the
    store. Exports are derived data, so unlike a backup there is no "always
    keep the last one" floor.
    """
    store = get_attachment_store()
    hours = max(1, int(max_age_hours)) if max_age_hours is not None else export_retention_hours()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    pruned = 0
    kept = 0
    try:
        # Iterated inside the try for the same reason as the lookup. ``_delete``
        # never raises, so nothing else in this loop can land here.
        for key, created_at, _digest, _size in _list_exports(EXPORT_KEY_ROOT):
            if created_at >= cutoff:
                kept += 1
            elif _delete(key):
                pruned += 1
            else:
                kept += 1
    except (AttachmentStoreError, OSError):
        log.warning("export store: could not list the export prefix; prune stopped")
        return ExportPruneOutcome(
            store=store.name,
            max_age_hours=hours,
            pruned=pruned,
            kept=kept,
            skipped_reason="listing_failed",
        )

    if pruned:
        log.info("export store: pruned %d export(s) older than %dh", pruned, hours)
    return ExportPruneOutcome(store=store.name, max_age_hours=hours, pruned=pruned, kept=kept)


# ---------------------------------------------------------------------------
# Store access
# ---------------------------------------------------------------------------

def _export_key(*, export_kind: str, user_id, digest: str, created_at: datetime) -> str:
    return (
        f"{_user_prefix(export_kind=export_kind, user_id=user_id)}"
        f"{created_at.strftime(EXPORT_TS_FORMAT)}_{digest}.csv"
    )


def _user_prefix(*, export_kind: str, user_id) -> str:
    """``exports/<kind>/<user_id>/`` — both segments reduced to safe characters.

    ``export_kind`` is a literal chosen by the route and ``user_id`` is a UUID
    from the session, but both are sanitised anyway: a key segment is the only
    thing standing between a caller's value and another user's prefix.
    """
    return f"{EXPORT_KEY_ROOT}{_segment(export_kind)}/{_segment(user_id)}/"


def _segment(value) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip())
    if not cleaned or cleaned in (".", ".."):
        raise ExportStoreError("An export key segment must not be empty.")
    return cleaned[:80]


def _write_temp_csv(tmp_path: str, csv_text: str) -> tuple[int, str]:
    """Write the CSV (BOM first) to *tmp_path*, returning its size and sha256."""
    digest = hashlib.sha256()
    size = 0
    with open(tmp_path, "wb") as handle:
        for chunk in _encoded_chunks(csv_text):
            handle.write(chunk)
            digest.update(chunk)
            size += len(chunk)
    return size, digest.hexdigest()


def _encoded_chunks(csv_text: str):
    """The BOM then the CSV, encoded in bounded slices rather than one buffer."""
    yield UTF8_BOM.encode("utf-8")
    for start in range(0, len(csv_text), CHUNK_SIZE):
        yield csv_text[start:start + CHUNK_SIZE].encode("utf-8")


def _put(key: str, tmp_path: str) -> None:
    store = get_attachment_store()
    if store.name == ATTACHMENT_STORE_S3:
        store.put_key(key, tmp_path, content_type=EXPORT_CONTENT_TYPE)
        return
    target = os.path.join(_local_root(), key)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    staging = f"{target}.tmp.{os.getpid()}"
    try:
        with open(tmp_path, "rb") as source, open(staging, "wb") as handle:
            while True:
                chunk = source.read(CHUNK_SIZE)
                if not chunk:
                    break
                handle.write(chunk)
        os.replace(staging, target)
    except OSError as exc:
        _remove_quietly(staging)
        raise ExportStoreError("Export store write failed.") from exc


def _list_exports(prefix: str):
    """``(key, created_at, filter hash, size)`` for every export under *prefix*.

    Names that do not match ``EXPORT_NAME_RE`` are ignored rather than guessed
    at, so a stray object in the prefix is never deleted by the prune.
    """
    store = get_attachment_store()
    if store.name == ATTACHMENT_STORE_S3:
        absolute = store.absolute_key(prefix)
        for key, size, _etag in store.iter_keys(absolute):
            if not key.startswith(absolute):
                continue
            relative = key[len(store.key_prefix):]
            parsed = _parse_name(relative)
            if parsed is not None:
                yield (relative, parsed[0], parsed[1], size)
        return

    root = _local_root()
    base = os.path.join(root, prefix)
    for dirpath, _dirnames, filenames in os.walk(base):
        for name in filenames:
            parsed = _parse_name(name)
            if parsed is None:
                continue
            path = os.path.join(dirpath, name)
            try:
                size = os.path.getsize(path)
            except OSError:
                continue
            yield (os.path.relpath(path, root), parsed[0], parsed[1], size)


def _parse_name(key: str):
    """``(created_at, filter hash)`` from an export key, or None."""
    match = EXPORT_NAME_RE.match(key.rsplit("/", 1)[-1])
    if match is None:
        return None
    try:
        created_at = datetime.strptime(match.group(1), EXPORT_TS_FORMAT).replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return None
    return created_at, match.group(2)


def _delete(key: str) -> bool:
    """Remove one export from whichever store holds it. Never raises."""
    store = get_attachment_store()
    try:
        if store.name == ATTACHMENT_STORE_S3:
            store.delete_key(key)
        else:
            os.remove(os.path.join(_local_root(), key))
    except FileNotFoundError:
        return False
    except (AttachmentStoreError, OSError):
        log.warning("export store: could not prune an export", exc_info=True)
        return False
    return True


def _local_root() -> str:
    app_data = current_app.config.get("APP_DATA") or os.path.join(
        current_app.instance_path, "data"
    )
    return os.path.realpath(app_data)


def _remove_quietly(path: str | None) -> None:
    if not path:
        return
    try:
        os.remove(path)
    except FileNotFoundError:
        return
    except OSError:
        log.warning("export store: could not remove a temporary file", exc_info=True)
