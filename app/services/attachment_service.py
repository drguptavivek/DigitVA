"""Attachment module boundary.

Every decision about a submission attachment — who may receive it, whether its
bytes are present, and how they are delivered — goes through this module.
Routes, render code, sync tasks, admin telemetry, and the integrity script call
these functions; none of them touch the attachment filesystem directly.

``docs/planning/s3-attachment-plan.md`` Phase 3 created the interface so that
source changes stay inside this module. Phase 4a fills it in: DigitVA keeps its
own permanent copy of every attachment and serves from that store, and ODK
Central — the source of truth for existence and content — is consulted only to
fill a store miss, per project and behind a flag. The store itself lives in
``app/services/attachment_store.py`` — local files or a DigitVA-owned S3
bucket, selected by ``ATTACHMENT_STORE``. Only delivery knows the difference,
and only because it must choose between sending a file and issuing a redirect.

Policy baseline: ``docs/policy/attachment-storage.md``.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import tempfile
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import sqlalchemy as sa
from flask import abort, current_app, g, redirect, send_file, stream_with_context

from app import db, cache as flask_cache
from app.models import (
    VaAllocations,
    VaCoderReview,
    VaFinalAssessments,
    VaForms,
    VaProjectMaster,
    VaStatuses,
    VaSubmissions,
)
from app.models.va_submission_attachments import VaSubmissionAttachments
from app.services.odk_retirement_service import MISSING_IN_ODK

log = logging.getLogger(__name__)

# The serving-route record cache holds the attachment *record* (ownership, path,
# MIME), never a locator that can expire. Authorization is never cached.
ATTACHMENT_RECORD_CACHE_TIMEOUT = 3600

# Truthy, non-URL marker returned to visibility-check callers (va_sid=None) that
# only test category non-emptiness and never render the value.
ATTACHMENT_PRESENT_MARKER = "__attachment_present__"

AUDIT_FILENAME = "audit.csv"
ORPHAN_DIRNAME = ".orphaned"

# Legacy permission-dict keys that are role-scoped elsewhere; any other key in
# the dict is a non-scoped legacy grant (mirrors VaUsers.has_va_form_access).
_SCOPED_LEGACY_ROLES = {"coder", "reviewer", "sitepi"}

# ---------------------------------------------------------------------------
# Readiness vocabularies (Phase 2 columns on va_submission_attachments)
#
# These name the states the plan's "Availability and Completeness Semantics"
# section defines. Phase 2 only stores them; Phase 4 is where delivery and
# repair start deciding on them instead of on disk existence.
# ---------------------------------------------------------------------------

# Source = the original attachment, owned by ODK Central.
SOURCE_UNKNOWN = "unknown"        # never observed
SOURCE_LISTED = "listed"          # named by Central's attachment list only
SOURCE_AVAILABLE = "available"    # a content response was actually observed
SOURCE_MISSING = "missing"        # Central reports not-found; repair may run
SOURCE_RETIRED = "retired"        # submission gone from ODK: never probe/repair
SOURCE_ERROR = "error"            # last observation failed

SOURCE_STATES = frozenset({
    SOURCE_UNKNOWN, SOURCE_LISTED, SOURCE_AVAILABLE,
    SOURCE_MISSING, SOURCE_RETIRED, SOURCE_ERROR,
})

# Error *categories* only. Upstream free text is never stored.
SOURCE_ERROR_NOT_FOUND = "not_found"
SOURCE_ERROR_AUTH = "auth"
SOURCE_ERROR_THROTTLED = "throttled"
SOURCE_ERROR_TRANSIENT = "transient"
SOURCE_ERROR_INVALID_REDIRECT = "invalid_redirect"
SOURCE_ERROR_UNKNOWN = "unknown"

SOURCE_ERROR_CODES = frozenset({
    SOURCE_ERROR_NOT_FOUND, SOURCE_ERROR_AUTH, SOURCE_ERROR_THROTTLED,
    SOURCE_ERROR_TRANSIENT, SOURCE_ERROR_INVALID_REDIRECT, SOURCE_ERROR_UNKNOWN,
})

# Derivative = the MP3 made from AMR narration. NULL for every non-audio row.
DERIVATIVE_PENDING = "pending"
DERIVATIVE_READY = "ready"
DERIVATIVE_STALE = "stale"        # source validator moved on; rebuild needed
DERIVATIVE_ERROR = "error"        # conversion failed (plan Finding 5)

DERIVATIVE_STATES = frozenset({
    DERIVATIVE_PENDING, DERIVATIVE_READY, DERIVATIVE_STALE, DERIVATIVE_ERROR,
})

DERIVATIVE_ERROR_CONVERSION_FAILED = "conversion_failed"

DERIVATIVE_MIME_TYPE = "audio/mpeg"

# Local copy under APP_DATA/<form_id>/media/.
LOCAL_PRESENT = "present"
LOCAL_RETAINED = "retained"       # archival copy; never retired or quarantined
LOCAL_QUARANTINED = "quarantined"
LOCAL_ABSENT = "absent"

LOCAL_FALLBACK_STATES = frozenset({
    LOCAL_PRESENT, LOCAL_RETAINED, LOCAL_QUARANTINED, LOCAL_ABSENT,
})

# Which store holds the row's object. ``local`` rows keep a file under
# APP_DATA; ``s3`` rows have an object in the DigitVA bucket and a NULL
# ``local_path``; ``absent`` rows have no object anywhere yet.
STORE_STATE_LOCAL = "local"
STORE_STATE_S3 = "s3"
STORE_STATE_ABSENT = "absent"

STORE_STATES = frozenset({STORE_STATE_LOCAL, STORE_STATE_S3, STORE_STATE_ABSENT})

# readiness() reads whole submissions at a time; a caller passing a very long
# sid list is batched rather than issuing one unbounded IN (...).
READINESS_BATCH_SIZE = 500


@dataclass(frozen=True)
class AttachmentRecord:
    """Identity and delivery metadata for one attachment row.

    ``filename`` is the attachment's original ODK name — the identity Central
    addresses it by — and is distinct from the opaque ``storage_name`` the
    browser sees. ``source_mime_type`` is the validated type of the original;
    ``mime_type`` keeps its historical meaning (the locally stored blob's type,
    which for ``.amr`` rows is the MP3 derivative's).
    """

    va_sid: str
    va_form_id: str
    storage_name: str
    filename: str
    local_path: str | None
    mime_type: str | None
    source_mime_type: str | None = None


# ---------------------------------------------------------------------------
# Record resolution
# ---------------------------------------------------------------------------

def _record_cache_key(storage_name: str) -> str:
    return f"att:{storage_name}"


def resolve_attachment_record(storage_name: str) -> AttachmentRecord | None:
    """Resolve an opaque storage_name to its owning submission and metadata.

    Only rows with ``exists_on_odk=True`` resolve. Cache entries written before
    ``va_sid`` and ``filename`` were part of the record are treated as misses,
    so ownership is always known before authorization runs and the original
    ODK filename is always known before Central is addressed.
    """
    cached = flask_cache.get(_record_cache_key(storage_name))
    if cached and cached.get("va_sid") and cached.get("va_form_id") and cached.get("filename"):
        return AttachmentRecord(
            va_sid=cached["va_sid"],
            va_form_id=cached["va_form_id"],
            storage_name=storage_name,
            filename=cached["filename"],
            local_path=cached.get("local_path"),
            mime_type=cached.get("mime_type"),
            source_mime_type=cached.get("source_mime_type"),
        )

    row = db.session.execute(
        sa.select(
            VaSubmissionAttachments.va_sid,
            VaSubmissions.va_form_id,
            VaSubmissionAttachments.filename,
            VaSubmissionAttachments.local_path,
            VaSubmissionAttachments.mime_type,
            VaSubmissionAttachments.source_mime_type,
        )
        .join(VaSubmissions, VaSubmissions.va_sid == VaSubmissionAttachments.va_sid)
        .where(VaSubmissionAttachments.storage_name == storage_name)
        .where(VaSubmissionAttachments.exists_on_odk.is_(True))
    ).first()
    if not row:
        return None
    return AttachmentRecord(
        va_sid=row.va_sid,
        va_form_id=row.va_form_id,
        storage_name=storage_name,
        filename=row.filename,
        local_path=row.local_path,
        mime_type=row.mime_type,
        source_mime_type=row.source_mime_type,
    )


def cache_attachment_record(record: AttachmentRecord) -> None:
    payload = asdict(record)
    payload.pop("storage_name", None)
    flask_cache.set(
        _record_cache_key(record.storage_name),
        payload,
        timeout=ATTACHMENT_RECORD_CACHE_TIMEOUT,
    )


def invalidate_attachment_record(storage_name: str) -> None:
    flask_cache.delete(_record_cache_key(storage_name))


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------

def _user_holds_submission(user_id, va_sid: str) -> bool:
    """Coder-scope entitlement: active allocation, or the user's own active
    coder outcome on this submission (the same rule the coder ``vaview`` page
    applies through ``va_permission_ensureviewable``)."""
    allocation_exists = sa.exists().where(
        VaAllocations.va_sid == va_sid,
        VaAllocations.va_allocated_to == user_id,
        VaAllocations.va_allocation_status == VaStatuses.active,
    )
    final_exists = sa.exists().where(
        VaFinalAssessments.va_sid == va_sid,
        VaFinalAssessments.va_finassess_by == user_id,
        VaFinalAssessments.va_finassess_status == VaStatuses.active,
    )
    review_exists = sa.exists().where(
        VaCoderReview.va_sid == va_sid,
        VaCoderReview.va_creview_by == user_id,
        VaCoderReview.va_creview_status == VaStatuses.active,
    )
    return bool(
        db.session.scalar(
            sa.select(sa.or_(allocation_exists, final_exists, review_exists))
        )
    )


def can_access_submission_attachment(user, *, va_form_id: str, va_sid: str) -> bool:
    """Role matrix for attachment delivery — see docs/policy/attachment-storage.md.

    Evaluated fresh on every delivery; the result is never cached. Possession
    of a storage_name token grants nothing on its own.
    """
    if not va_form_id or not va_sid:
        return False
    if user.is_admin():
        return True
    if user.has_data_manager_form_access(va_form_id):
        return True
    if user.is_site_pi(va_form_id):
        return True
    # Reviewer section views are read-only per form (see the reviewer ``vaview``
    # validator), so reviewer attachment access follows the same form scope.
    if user.is_reviewer(va_form_id):
        return True
    if user.is_coder(va_form_id) or user.is_coding_tester(va_form_id):
        return _user_holds_submission(user.user_id, va_sid)
    for legacy_role, va_forms in (user.permission or {}).items():
        if legacy_role in _SCOPED_LEGACY_ROLES:
            continue
        if va_form_id in va_forms:
            return True
    return False


# ---------------------------------------------------------------------------
# Local presence (Phase 3: disk-backed; Phase 4 replaces the internals)
# ---------------------------------------------------------------------------

def local_attachment_file_exists(path: str | None) -> bool:
    return bool(path) and os.path.exists(path)


def resolve_local_attachment_path(
    *,
    app_data_root: str | None,
    form_id: str,
    local_path: str | None,
    storage_name: str | None,
    include_audit: bool = False,
) -> str | None:
    """Return a real attachment file path if the local blob exists.

    Preference order:
      1. storage_name under APP_DATA/<form_id>/media/
      2. legacy local_path fallback

    Shared artifacts like audit.csv are not treated as attachment blobs unless
    ``include_audit`` is set.
    """
    if storage_name and app_data_root:
        disk_path = os.path.join(app_data_root, form_id, "media", storage_name)
        if os.path.exists(disk_path):
            return os.path.abspath(disk_path)
    if local_path and os.path.exists(local_path):
        if not include_audit and os.path.basename(local_path).lower() == AUDIT_FILENAME:
            return None
        return os.path.abspath(local_path)
    return None


def resolve_attachment_presence(
    *,
    app_data_root: str | None,
    form_id: str,
    local_path: str | None,
    storage_name: str | None,
    store_state: str | None,
    include_audit: bool = False,
) -> str | None:
    """Return an opaque presence identity for one row, or None when absent.

    This is the bulk-presence definition, routed through the store rather than
    through the filesystem:

    * ``store_state='s3'`` — presence is the stored state itself and the
      identity is the object key. The bulk paths deliberately **trust
      ``store_state`` and never HEAD each row**: a per-row HEAD would turn one
      dashboard render into thousands of network calls. Object-level truth is
      the integrity script's job (``--store s3``), not a request path's.
    * anything else — the historical disk resolution, whose identity is the
      absolute file path.

    Callers only ever test the result for truthiness or deduplicate it, so the
    identity's shape is not part of the contract.
    """
    if store_state == STORE_STATE_S3:
        if not storage_name:
            return None
        if not include_audit and (storage_name or "").lower() == AUDIT_FILENAME:
            return None
        from app.services.attachment_store import get_attachment_store

        return get_attachment_store().key_for(
            AttachmentRecord(
                va_sid="", va_form_id=form_id, storage_name=storage_name,
                filename="", local_path=None, mime_type=None,
            )
        )
    return resolve_local_attachment_path(
        app_data_root=app_data_root,
        form_id=form_id,
        local_path=local_path,
        storage_name=storage_name,
        include_audit=include_audit,
    )


def present_attachment_files_by_submission(
    form_id: str,
    *,
    target_sids: list[str] | None = None,
) -> dict[str, set[str]]:
    """Bulk readiness read: deduplicated present attachment identities per submission.

    Reads attachment rows once and resolves presence for each; no network calls
    and no per-row store probe (see ``resolve_attachment_presence``).
    """
    app_data_root = current_app.config.get("APP_DATA")
    stmt = (
        sa.select(
            VaSubmissionAttachments.va_sid,
            VaSubmissionAttachments.local_path,
            VaSubmissionAttachments.storage_name,
            VaSubmissionAttachments.store_state,
        )
        .select_from(VaSubmissionAttachments)
        .join(VaSubmissions, VaSubmissions.va_sid == VaSubmissionAttachments.va_sid)
        .where(
            VaSubmissions.va_form_id == form_id,
            VaSubmissionAttachments.exists_on_odk.is_(True),
        )
    )
    if target_sids:
        stmt = stmt.where(VaSubmissionAttachments.va_sid.in_(target_sids))

    present_files_by_sid: dict[str, set[str]] = {}
    for row in db.session.execute(stmt).mappings().all():
        identity = resolve_attachment_presence(
            app_data_root=app_data_root,
            form_id=form_id,
            local_path=row["local_path"],
            storage_name=row["storage_name"],
            store_state=row["store_state"],
        )
        if not identity:
            continue
        present_files_by_sid.setdefault(row["va_sid"], set()).add(identity)
    return present_files_by_sid


def is_attachment_present_for_form(va_form_id: str, filename: str) -> bool:
    """Visibility check used when no submission identity is available.

    Mirrors the historical render-layer rule: an ``.amr`` field is visible when
    its ``.mp3`` derivative is present under the form's media directory.

    With the S3 store there is no file to stat, so presence is the stored
    ``store_state`` of any row for that form and filename. The render loop asks
    about a handful of distinct attachment fields per category, so the answer
    is memoised per request and each miss costs one ``LIMIT 1`` lookup on the
    form index rather than a query per field per row.
    """
    from app.services.attachment_store import get_attachment_store

    if get_attachment_store().name != STORE_STATE_S3:
        if filename.lower().endswith(".amr"):
            filename = filename[: -len(".amr")] + ".mp3"
        disk_path = os.path.join(current_app.config["APP_DATA"], va_form_id, "media", filename)
        return os.path.exists(disk_path)

    memo_key = (va_form_id, filename)
    memo = getattr(g, "_attachment_form_presence", None)
    if memo is None:
        memo = g._attachment_form_presence = {}
    if memo_key in memo:
        return memo[memo_key]

    # An .amr field is visible through its MP3 derivative, which is stored
    # against the .amr row: match either spelling.
    base, _, ext = filename.rpartition(".")
    candidates = {filename}
    if ext.lower() in ("amr", "mp3") and base:
        candidates |= {f"{base}.amr", f"{base}.mp3"}

    present = bool(db.session.scalar(
        sa.select(sa.literal(1))
        .select_from(VaSubmissionAttachments)
        .join(VaSubmissions, VaSubmissions.va_sid == VaSubmissionAttachments.va_sid)
        .where(
            VaSubmissions.va_form_id == va_form_id,
            VaSubmissionAttachments.filename.in_(sorted(candidates)),
            VaSubmissionAttachments.exists_on_odk.is_(True),
            VaSubmissionAttachments.store_state == STORE_STATE_S3,
        )
        .limit(1)
    ))
    memo[memo_key] = present
    return present


def scan_local_media_files(app_data: Path) -> tuple[int, list[Path]]:
    """Inventory live files under APP_DATA/*/media, skipping quarantined subtrees."""
    total = 0
    files: list[Path] = []
    if not app_data.exists():
        return total, files

    for media_dir in app_data.glob("*/media"):
        if not media_dir.is_dir():
            continue
        for root, dirs, filenames in os.walk(media_dir):
            dirs[:] = [d for d in dirs if d != ORPHAN_DIRNAME]
            root_path = Path(root)
            if ORPHAN_DIRNAME in root_path.parts:
                continue
            for filename in filenames:
                total += 1
                files.append((root_path / filename).resolve(strict=False))
    return total, files


def remove_local_file_if_present(path: str | None) -> bool:
    """Remove a local attachment blob; return whether a file was removed."""
    if not path:
        return False
    try:
        os.remove(path)
    except FileNotFoundError:
        return False
    return True


# ---------------------------------------------------------------------------
# Readiness (Phase 2 state; the Phase 4 contract)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Readiness:
    """Stored readiness of one attachment row — no disk, no network.

    Source and derivative are reported separately and each carries its own
    observation time, so an old observation is never presented as a current
    probe. ``derivative_state`` is ``None`` for every non-audio row.
    """

    va_sid: str
    filename: str
    storage_name: str | None
    local_path: str | None
    mime_type: str | None
    exists_on_odk: bool
    source_state: str
    source_verified_at: datetime | None
    source_error_code: str | None
    derivative_state: str | None
    derivative_verified_at: datetime | None
    local_fallback_state: str
    store_state: str


def readiness(va_sids: list[str]) -> dict[str, list[Readiness]]:
    """Bulk readiness read for the given submissions, keyed by ``va_sid``.

    This is the Phase 4 contract from the plan's **Module Boundary**: callers
    (repair maps, admin telemetry, render) ask for state and never for a file.
    It performs no filesystem and no Central/S3 access, and issues one query per
    ``READINESS_BATCH_SIZE`` submissions. Submissions with no attachment rows are
    absent from the result rather than mapped to an empty list.

    Phase 2 only stores the columns; nothing decides on them yet, so this is
    additive to ``present_attachment_files_by_submission()`` rather than a
    replacement for it.
    """
    unique_sids = list(dict.fromkeys(sid for sid in va_sids if sid))
    if not unique_sids:
        return {}

    by_sid: dict[str, list[Readiness]] = {}
    for start in range(0, len(unique_sids), READINESS_BATCH_SIZE):
        batch = unique_sids[start:start + READINESS_BATCH_SIZE]
        rows = db.session.execute(
            sa.select(
                VaSubmissionAttachments.va_sid,
                VaSubmissionAttachments.filename,
                VaSubmissionAttachments.storage_name,
                VaSubmissionAttachments.local_path,
                VaSubmissionAttachments.mime_type,
                VaSubmissionAttachments.exists_on_odk,
                VaSubmissionAttachments.source_state,
                VaSubmissionAttachments.source_verified_at,
                VaSubmissionAttachments.source_error_code,
                VaSubmissionAttachments.derivative_state,
                VaSubmissionAttachments.derivative_verified_at,
                VaSubmissionAttachments.local_fallback_state,
                VaSubmissionAttachments.store_state,
            )
            .where(VaSubmissionAttachments.va_sid.in_(batch))
            .order_by(
                VaSubmissionAttachments.va_sid,
                VaSubmissionAttachments.filename,
            )
        ).all()
        for row in rows:
            by_sid.setdefault(row.va_sid, []).append(Readiness(**row._mapping))
    return by_sid


def mark_audio_derivative_stale(va_sid: str, filename: str) -> None:
    """Mark one audio row's MP3 as needing a rebuild.

    Called when the source ETag the derivative was built from no longer matches
    (plan Finding 6). Rows without a derivative — every non-audio attachment —
    are untouched, so this can never invent a derivative state.
    """
    db.session.execute(
        sa.update(VaSubmissionAttachments)
        .where(
            VaSubmissionAttachments.va_sid == va_sid,
            VaSubmissionAttachments.filename == filename,
            VaSubmissionAttachments.derivative_state.is_not(None),
        )
        .values(derivative_state=DERIVATIVE_STALE, derivative_verified_at=None)
    )


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------

def safe_mime_type(mime_type: str | None) -> str | None:
    """Return a usable MIME value or None so the sender guesses from the name.

    Upstream metadata is copied without validation and Central can emit a
    literal ``"null"`` (plan Finding 9); never forward that to a browser.
    """
    if not mime_type:
        return None
    candidate = mime_type.split(";")[0].strip()
    if not candidate or candidate.lower() == "null" or "/" not in candidate:
        return None
    return candidate


def apply_no_store_policy(response):
    """PHI attachment bytes must not reach the browser disk cache (Finding 11)."""
    response.cache_control.private = True
    response.cache_control.no_store = True
    response.cache_control.max_age = 0
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response




# ---------------------------------------------------------------------------
# DigitVA's own attachment store
#
# DigitVA keeps a permanent copy of every attachment it has delivered —
# originals and MP3 derivatives alike — and that copy is the read path. ODK
# Central stays the source of truth for existence and content, but it is only
# consulted to *fill* the store, never on every request.
#
# The store is reached exclusively through ``attachment_store``. The helpers
# below adapt it to delivery: reading one object, teeing a Central fetch into
# it, and recording where the object landed.
# ---------------------------------------------------------------------------

# Bounded read/write size for proxied and persisted bodies; large media is
# never buffered whole.
ATTACHMENT_STREAM_CHUNK_SIZE = 64 * 1024


def _store_media_dir(record: AttachmentRecord) -> str:
    from app.services.attachment_store import LocalAttachmentStore

    return LocalAttachmentStore().media_dir(record)


def _store_exists(record: AttachmentRecord) -> str | None:
    """Local-store lookup: the stored file's path, or None.

    Thin delegation to ``LocalAttachmentStore.open_local_path``; kept under its
    original name for callers that specifically want a filesystem path.
    Delivery asks the *selected* store instead.
    """
    from app.services.attachment_store import LocalAttachmentStore

    return LocalAttachmentStore().open_local_path(record)


def _store_open(record: AttachmentRecord, path: str):
    """Serve one locally stored object, with DigitVA's own cache policy.

    ``send_file`` keeps ``Range`` support, which is what audio playback uses.
    """
    return apply_no_store_policy(
        send_file(path, mimetype=safe_mime_type(record.mime_type))
    )


def _store_redirect(record: AttachmentRecord, store):
    """Redirect to a freshly signed, short-lived GET for the stored object.

    The DigitVA route stays the only URL in any page: the signed URL exists
    for the duration of this one redirect, is never rendered, stored, cached,
    or logged, and carries its own ``no-store`` policy both in the signature
    and on the object. The redirect itself is marked ``no-store`` so a browser
    re-issues the authorized request instead of replaying a stale signature.
    Range requests are answered by the bucket directly.
    """
    url = store.presigned_url(
        record,
        content_type=safe_mime_type(record.mime_type),
        filename=_content_disposition_filename(record.storage_name),
    )
    if url is None:
        return None
    return apply_no_store_policy(redirect(url, code=302))


def _serve_from_store(record: AttachmentRecord, store):
    """Serve a store hit, however the selected store delivers bytes."""
    path = store.open_local_path(record)
    if path is not None:
        return _store_open(record, path)
    return _store_redirect(record, store)


def _store_write(record: AttachmentRecord, chunks):
    """Tee ``chunks`` into the selected store while they stream to the client.

    Yields every chunk through unchanged, so the browser is not made to wait
    for the write.

    Local store: the object is written to a temporary name in the same
    directory and renamed only after the last chunk.

    S3 store: the chunks are spooled to a bounded temporary file — one
    ``ATTACHMENT_STREAM_CHUNK_SIZE`` buffer in memory at a time, never the
    whole body — and uploaded with a single ``put_object`` once the body is
    complete. ``put_object`` replaces a key atomically, so an abandoned or
    failed fetch leaves no object at all and never a partial one. The
    temporary file is removed on both paths.

    The row is pointed at the stored object afterwards; if that write fails the
    object is still found by ``storage_name`` on the next request, so delivery
    is never blocked on it.
    """
    from app.services.attachment_store import AttachmentStoreError, get_attachment_store

    if not record.storage_name:
        yield from chunks
        return

    store = get_attachment_store()
    if store.name != STORE_STATE_S3:
        media_dir = _store_media_dir(record)
        target = os.path.join(media_dir, record.storage_name)
        os.makedirs(media_dir, exist_ok=True)
        tmp_path = os.path.join(media_dir, f".tmp_{uuid.uuid4().hex}")

        handle = open(tmp_path, "wb")
        completed = False
        try:
            for chunk in chunks:
                handle.write(chunk)
                yield chunk
            handle.close()
            handle = None
            os.replace(tmp_path, target)
            completed = True
        finally:
            if handle is not None:
                handle.close()
            if not completed:
                remove_local_file_if_present(tmp_path)

        _mark_stored(record, local_path=target, store_state=STORE_STATE_LOCAL)
        return

    spool = tempfile.NamedTemporaryFile(prefix="digitva_att_", delete=False)
    tmp_path = spool.name
    completed = False
    try:
        try:
            for chunk in chunks:
                spool.write(chunk)
                yield chunk
            spool.close()
            spool = None
            store.put(
                record, tmp_path,
                content_type=safe_mime_type(record.mime_type) or safe_mime_type(
                    record.source_mime_type
                ),
            )
            completed = True
        finally:
            if spool is not None:
                spool.close()
            remove_local_file_if_present(tmp_path)
    except AttachmentStoreError:
        log.warning(
            "attachment store: could not persist the fetched object for sid=%s",
            record.va_sid,
        )
        return

    if completed:
        _mark_stored(record, local_path=None, store_state=STORE_STATE_S3)


def _mark_stored(record: AttachmentRecord, *, local_path: str | None,
                 store_state: str) -> None:
    """Point the row at the newly stored object. Best effort by design.

    An S3-stored row keeps no file on this app server, so ``local_path`` is
    NULL and the local copy is recorded as absent. A ``retained`` archival copy
    is never downgraded here: delivery refuses to fetch for a retired
    submission, so this path cannot reach one.
    """
    values = {"local_path": local_path, "store_state": store_state}
    values["local_fallback_state"] = (
        LOCAL_PRESENT if store_state == STORE_STATE_LOCAL else LOCAL_ABSENT
    )
    try:
        db.session.execute(
            sa.update(VaSubmissionAttachments)
            .where(
                VaSubmissionAttachments.va_sid == record.va_sid,
                VaSubmissionAttachments.filename == record.filename,
                VaSubmissionAttachments.local_fallback_state != LOCAL_RETAINED,
            )
            .values(**values)
        )
        db.session.commit()
        invalidate_attachment_record(record.storage_name)
    except Exception:
        db.session.rollback()
        log.warning(
            "attachment store: could not record the stored object for sid=%s",
            record.va_sid, exc_info=True,
        )


def deliver_local_attachment(record: AttachmentRecord):
    """Serve an attachment from DigitVA's store after the caller authorized it.

    ``deliver()`` is the entry point routes use; this is the store-only branch,
    kept for callers that must never reach Central. A store miss evicts the
    record cache and reports not-found.
    """
    from app.services.attachment_store import get_attachment_store

    store = get_attachment_store()
    if not store.exists(record):
        invalidate_attachment_record(record.storage_name)
        abort(404)
    response = _serve_from_store(record, store)
    if response is None:
        invalidate_attachment_record(record.storage_name)
        abort(404)
    cache_attachment_record(record)
    return response


def deliver_legacy_media(record: AttachmentRecord):
    """Serve a pre-``storage_name`` attachment addressed by its ODK filename.

    Backs the deprecated ``/media`` route: the same store and the same cache
    policy, but nothing is written to the record cache because the key would
    be a guessable filename rather than an opaque token.
    """
    from app.services.attachment_store import get_attachment_store

    store = get_attachment_store()
    if not store.exists(record):
        abort(404)
    response = _serve_from_store(record, store)
    if response is None:
        abort(404)
    return response


# ---------------------------------------------------------------------------
# Delivery (plan Phase 4a)
# ---------------------------------------------------------------------------

# How long a client is asked to wait after a transient Central failure with no
# stored object to serve.
ATTACHMENT_UNAVAILABLE_RETRY_AFTER_SECONDS = 5

# One log line and one counter per delivery, so operators can see how often
# the store misses and Central has to fill it.
OUTCOME_LOCAL = "local"
OUTCOME_CENTRAL_STREAM = "central_stream"
OUTCOME_CENTRAL_REDIRECT_FOLLOWED = "central_redirect_followed"
OUTCOME_UNAVAILABLE = "unavailable"
OUTCOME_ERROR = "error"

DELIVERY_OUTCOMES = (
    OUTCOME_LOCAL,
    OUTCOME_CENTRAL_STREAM,
    OUTCOME_CENTRAL_REDIRECT_FOLLOWED,
    OUTCOME_UNAVAILABLE,
    OUTCOME_ERROR,
)

_delivery_counters_lock = threading.Lock()
_delivery_counters: dict[str, int] = {outcome: 0 for outcome in DELIVERY_OUTCOMES}


def delivery_counters() -> dict[str, int]:
    """Per-process delivery outcome counts since start. Never persisted."""
    with _delivery_counters_lock:
        return dict(_delivery_counters)


def reset_delivery_counters() -> None:
    with _delivery_counters_lock:
        for outcome in DELIVERY_OUTCOMES:
            _delivery_counters[outcome] = 0


def _record_delivery(record: AttachmentRecord, outcome: str, started_at: float, *,
                     error_code: str | None = None):
    """Count and log one delivery. No URLs, headers, or payloads are logged."""
    with _delivery_counters_lock:
        _delivery_counters[outcome] = _delivery_counters.get(outcome, 0) + 1
    log.info(
        "attachment delivery outcome=%s latency_ms=%d sid=%s form=%s error=%s",
        outcome,
        int((time.monotonic() - started_at) * 1000),
        record.va_sid,
        record.va_form_id,
        error_code or "-",
    )


@dataclass(frozen=True)
class _DeliveryContext:
    """Stored facts that decide whether a store miss may reach Central."""

    central_fetch_enabled: bool
    retired: bool


def _delivery_context(record: AttachmentRecord) -> _DeliveryContext:
    """One bounded read of the project flag and the submission's retirement."""
    row = db.session.execute(
        sa.select(
            VaProjectMaster.attachment_central_fetch_enabled,
            VaSubmissions.va_sync_issue_code,
            VaSubmissionAttachments.local_fallback_state,
        )
        .select_from(VaSubmissionAttachments)
        .join(VaSubmissions, VaSubmissions.va_sid == VaSubmissionAttachments.va_sid)
        .join(VaForms, VaForms.form_id == VaSubmissions.va_form_id)
        .join(
            VaProjectMaster,
            VaProjectMaster.project_id == VaForms.project_id,
            isouter=True,
        )
        .where(
            VaSubmissionAttachments.va_sid == record.va_sid,
            VaSubmissionAttachments.filename == record.filename,
        )
    ).first()
    if row is None:
        return _DeliveryContext(central_fetch_enabled=False, retired=False)
    return _DeliveryContext(
        central_fetch_enabled=bool(row.attachment_central_fetch_enabled),
        # A retired submission has been purged from ODK: never contact Central,
        # serve the retained archival copy or nothing
        # (docs/policy/odk-retired-submissions.md).
        retired=(
            row.va_sync_issue_code == MISSING_IN_ODK
            or row.local_fallback_state == LOCAL_RETAINED
        ),
    )


def _is_audio_derivative(record: AttachmentRecord) -> bool:
    """True when the stored object is a DigitVA-owned MP3, not a Central original.

    Central holds the AMR, not the MP3, so a missing derivative cannot be
    self-healed by a straight fetch; sync rebuilds it (Phase 5).
    """
    return (record.filename or "").lower().endswith(".amr")


def _content_disposition_filename(storage_name: str) -> str:
    """Opaque storage names only; anything else degrades to a fixed name."""
    if re.fullmatch(r"[A-Za-z0-9._-]{1,128}", storage_name or ""):
        return storage_name
    return "attachment"


def _iter_central_body(result):
    """Bounded chunks of a Central fetch body, closing the response at the end.

    The one reader of a Central response, shared by request-path delivery and
    by background repair, so neither buffers a body whole or leaks a socket.
    """
    upstream = result.response
    try:
        for chunk in upstream.iter_content(chunk_size=ATTACHMENT_STREAM_CHUNK_SIZE):
            if chunk:
                yield chunk
    finally:
        upstream.close()


def _stream_central_response(record: AttachmentRecord, result):
    """Proxy Central's body with DigitVA's own headers, teeing it into the store.

    The body is read in bounded chunks and never buffered whole, and the
    upstream response is closed both when the generator finishes and when the
    client disconnects.
    """
    upstream = result.response

    response = current_app.response_class(
        stream_with_context(_store_write(record, _iter_central_body(result))),
        mimetype=result.mime_type or "application/octet-stream",
    )
    response.headers["Content-Disposition"] = (
        f'inline; filename="{_content_disposition_filename(record.storage_name)}"'
    )
    if result.content_length is not None:
        response.headers["Content-Length"] = str(result.content_length)
    response.call_on_close(upstream.close)
    return apply_no_store_policy(response)


def _unavailable_response(retry_after: int = ATTACHMENT_UNAVAILABLE_RETRY_AFTER_SECONDS):
    """503 with a short retry hint; the caller decides nothing from the body."""
    response = current_app.response_class(
        "Attachment temporarily unavailable. Please retry.",
        status=503,
        mimetype="text/plain",
    )
    response.headers["Retry-After"] = str(retry_after)
    return apply_no_store_policy(response)


def deliver(record: AttachmentRecord):
    """Deliver one authorized attachment, DigitVA's own store first.

    Authorization is **not** re-derived here: the route has already applied
    ``can_access_submission_attachment()``, and possession of a token proves
    nothing. This function only decides where the bytes come from.

    Order (docs/policy/attachment-storage.md, *Delivery*):

    1. DigitVA's store has the object -> serve it. Central is not contacted.
       The local store sends the file; the S3 store answers with a ``302`` to
       a short-lived presigned GET;
    2. store miss, and the submission is retired, the row is an audio
       derivative, or the project's Central-fetch flag is off -> 404, exactly
       as before;
    3. store miss otherwise -> fetch the original from the project's own ODK
       Central connection, stream it to the browser and write it into the
       store on the way past;
    4. a failed fetch follows the outcome table: not-found is 404, a transient
       or throttled failure is 503 with a retry hint, and an auth,
       configuration, or invalid-redirect failure is 502 — never a silent
       success, so a misconfiguration cannot look like normal operation.
    """
    from app.services.attachment_store import get_attachment_store

    started_at = time.monotonic()

    store = get_attachment_store()
    if store.exists(record):
        response = _serve_from_store(record, store)
        if response is not None:
            cache_attachment_record(record)
            _record_delivery(record, OUTCOME_LOCAL, started_at)
            return response

    context = _delivery_context(record)
    if context.retired or not context.central_fetch_enabled or _is_audio_derivative(record):
        invalidate_attachment_record(record.storage_name)
        _record_delivery(record, OUTCOME_UNAVAILABLE, started_at)
        abort(404)

    from app.services import attachment_source_central as central

    result = central.fetch(record)
    central.record_fetch_state(record, result)

    if result.ok:
        cache_attachment_record(record)
        response = _stream_central_response(record, result)
        _record_delivery(
            record,
            OUTCOME_CENTRAL_REDIRECT_FOLLOWED if result.redirect_followed
            else OUTCOME_CENTRAL_STREAM,
            started_at,
        )
        return response

    if result.outcome == central.FETCH_NOT_FOUND:
        invalidate_attachment_record(record.storage_name)
        _record_delivery(record, OUTCOME_UNAVAILABLE, started_at,
                         error_code=result.error_code)
        abort(404)

    if result.outcome in (central.FETCH_TRANSIENT, central.FETCH_THROTTLED):
        _record_delivery(record, OUTCOME_UNAVAILABLE, started_at,
                         error_code=result.error_code)
        return _unavailable_response()

    # auth, unconfigured, invalid redirect, unknown: a configuration or safety
    # failure. Reporting it as "missing" would hide it indefinitely.
    _record_delivery(record, OUTCOME_ERROR, started_at, error_code=result.error_code)
    abort(502)


# ---------------------------------------------------------------------------
# Ingest
#
# Sync downloads an attachment's bytes to a temporary file and hands them to
# this module. Everything that happens next — AMR→MP3 conversion, the store
# write, the opaque storage name, the readiness state the row should carry,
# and the removal of every temporary file on every path — is decided here, so
# no sync module knows where an attachment lives or how a derivative is made.
# ---------------------------------------------------------------------------

class AmrConversionError(RuntimeError):
    """AMR→MP3 conversion failed; the attachment is recorded as an error."""


def is_audio_attachment(filename: str) -> bool:
    """True for narration audio, whose stored blob is an MP3 derivative."""
    return (filename or "").lower().endswith(".amr")


def generate_storage_name(original_filename: str) -> str:
    """A unique opaque storage name (uuid4 hex + lowercase ext).

    ``.amr`` becomes ``.mp3`` because the stored blob is the derivative.
    """
    ext = os.path.splitext(original_filename or "")[1].lower()
    if ext == ".amr":
        ext = ".mp3"
    return uuid.uuid4().hex + ext


def _form_media_dir(va_form_id: str) -> str:
    from app.services.attachment_store import LocalAttachmentStore, StoreTarget

    return LocalAttachmentStore().media_dir(
        StoreTarget(va_form_id=va_form_id, storage_name=None)
    )


def new_ingest_temp_path(va_form_id: str) -> str:
    """A private temp path for one download, on the same filesystem as the store.

    Downloads land here first so a partial body is never mistaken for a stored
    object. The caller writes the body and then hands the path to
    ``ingest_download()``, which consumes or removes it.
    """
    media_dir = _form_media_dir(va_form_id)
    os.makedirs(media_dir, exist_ok=True)
    return os.path.join(media_dir, f".tmp_{uuid.uuid4().hex}")


def _convert_amr_to_mp3(amr_path: str, form_id: str, output_path: str | None = None) -> str:
    """Convert an .amr file to .mp3. Returns the .mp3 path.

    Uses SoX with smart bitrate: probes source via soxi, then targets 2x
    the source bitrate (capped 16–64 kbps). AMR-NB speech (~12 kbps) ends
    up at 24 kbps — optimal quality for the source without bloated output.

    If output_path is provided, write the .mp3 there (and delete amr_path).
    Otherwise derive the output path by replacing the .amr extension.

    On failure raises AmrConversionError. The source file is left for the
    caller's temp cleanup and no partial .mp3 is kept, so a failed
    conversion can never be recorded as a successful derivative.
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
        except Exception as probe_err:
            log.warning(
                "AMR→MP3 [%s]: soxi probe failed for %s, using default %dkbps — %s",
                form_id, os.path.basename(amr_path), target_bitrate, probe_err,
            )

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
        log.error(
            "AMR→MP3 conversion failed [%s/%s]: %s",
            form_id, os.path.basename(amr_path), e,
            exc_info=True,
        )
        try:
            remove_local_file_if_present(mp3_path)
        except OSError:
            pass
        raise AmrConversionError(
            f"AMR→MP3 conversion failed for {os.path.basename(amr_path)}"
        ) from e


@dataclass(frozen=True)
class IngestResult:
    """What one ingested download makes the attachment row become.

    ``state_values`` is the readiness state implied by the ingest — the source
    and derivative vocabularies of this module — ready to be assigned onto the
    row. The DB write itself stays with the caller, which owns the PK-safe
    upsert.
    """

    storage_name: str
    local_path: str | None
    store_state: str
    mime_type: str | None
    etag: str | None
    downloaded_at: datetime
    state_values: dict


def _ingest_state_values(
    *, filename: str, mime_type: str | None, etag: str | None,
    downloaded_at: datetime, store_state: str,
) -> dict:
    """Source/derivative state implied by one successful ingest.

    A successful download is the only evidence that the source is *available*;
    the MP3 written for an ``.amr`` attachment is recorded against the source
    ETag it was built from so a later sync can tell a stale derivative apart.
    """
    values = {
        "source_state": SOURCE_AVAILABLE,
        "source_verified_at": downloaded_at,
        "source_error_code": None,
        # The ORIGINAL's validated MIME; ``mime_type`` keeps its own meaning.
        "source_mime_type": mime_type,
        "store_state": store_state,
    }
    if store_state == STORE_STATE_S3:
        # Nothing was written to this app server's disk for an s3 row.
        values["local_fallback_state"] = LOCAL_ABSENT
    if is_audio_attachment(filename):
        values.update({
            "derivative_state": DERIVATIVE_READY,
            "derivative_mime_type": DERIVATIVE_MIME_TYPE,
            "derivative_source_validator": etag,
            "derivative_verified_at": downloaded_at,
            "derivative_error_code": None,
        })
    return values


def ingest_download(
    *,
    va_sid: str,
    va_form_id: str,
    filename: str,
    temp_path: str,
    mime_type: str | None,
    etag: str | None,
    downloaded_at: datetime,
    storage_name: str | None = None,
) -> IngestResult:
    """Take one freshly downloaded temp file into DigitVA's store.

    Converts ``.amr`` narration to MP3, writes the blob to the selected store
    (a file under the form's media directory, or a single atomic ``put`` into
    the bucket), and returns the storage name, the store it landed in and the
    readiness state the row should carry.

    ``storage_name`` is generated unless the caller is rebuilding an existing
    object in place (repair), in which case its own name is reused so no
    delivery token rotates.

    Requires an app context: the store and the media directory are resolved
    from the app config. Every temporary file — the download, and the
    intermediate MP3 on the S3 path — is removed on success and on failure, so
    a conversion error leaves no partial object and no orphan temp file.
    Raises ``AmrConversionError`` on a failed conversion and
    ``AttachmentStoreError`` on a failed store write; the caller records the
    explicit derivative error state and leaves the previous blob alone.
    """
    from app.services.attachment_store import StoreTarget, get_attachment_store

    resolved_name = storage_name or generate_storage_name(filename)
    is_audio = is_audio_attachment(filename)
    store = get_attachment_store()
    cleanup_paths = {temp_path}
    local_path: str | None = None

    try:
        if store.name != STORE_STATE_S3:
            media_dir = _form_media_dir(va_form_id)
            os.makedirs(media_dir, exist_ok=True)
            final_path = os.path.join(media_dir, resolved_name)
            if is_audio:
                local_path = _convert_amr_to_mp3(
                    temp_path, va_form_id, output_path=final_path
                )
            else:
                os.replace(temp_path, final_path)
                local_path = final_path
            store_state = STORE_STATE_LOCAL
        else:
            upload_path = temp_path
            content_type = mime_type
            if is_audio:
                # Convert into a second temp file; the AMR temp is consumed by SoX.
                upload_path = _convert_amr_to_mp3(
                    temp_path,
                    va_form_id,
                    output_path=os.path.join(
                        _form_media_dir(va_form_id), f".tmp_{uuid.uuid4().hex}.mp3"
                    ),
                )
                cleanup_paths.add(upload_path)
                content_type = DERIVATIVE_MIME_TYPE
            store.put(
                StoreTarget(va_form_id=va_form_id, storage_name=resolved_name),
                upload_path,
                content_type=content_type,
            )
            store_state = STORE_STATE_S3
    finally:
        for path in cleanup_paths:
            if path and path != local_path:
                try:
                    remove_local_file_if_present(path)
                except OSError:
                    log.warning("attachment ingest: temp cleanup failed for sid=%s", va_sid)

    return IngestResult(
        storage_name=resolved_name,
        local_path=local_path,
        store_state=store_state,
        mime_type=mime_type,
        etag=etag,
        downloaded_at=downloaded_at,
        state_values=_ingest_state_values(
            filename=filename,
            mime_type=mime_type,
            etag=etag,
            downloaded_at=downloaded_at,
            store_state=store_state,
        ),
    )


def mark_removed_on_odk(va_sid: str, filename: str) -> dict:
    """Row values for an attachment Central no longer holds.

    ``exists_on_odk=false`` means the source is gone upstream; the local blob
    and any derivative record are deliberately left alone (the policy never
    deletes an attachment DigitVA already has).
    """
    log.debug("attachment ingest: no longer on ODK sid=%s file=%s", va_sid, filename)
    return {"source_state": SOURCE_MISSING}


def attachment_present(
    *,
    va_form_id: str,
    local_path: str | None,
    storage_name: str | None,
    store_state: str | None,
) -> bool:
    """Whether DigitVA's store already holds this row's blob.

    The single-row form of ``present_attachment_files_by_submission()`` and the
    readiness source for sync's ``304`` self-heal decision: sync never stats a
    file or reads ``store_state`` itself. ``audit.csv`` counts here, because
    sync maintains it like any other attachment.

    Outside an app context — the bare-thread sync fallback — only the legacy
    ``local_path`` can be answered, since both the media root and the selected
    store come from the app config.
    """
    from flask import has_app_context

    if not has_app_context():
        return local_attachment_file_exists(local_path)
    return bool(
        resolve_attachment_presence(
            app_data_root=current_app.config.get("APP_DATA"),
            form_id=va_form_id,
            local_path=local_path,
            storage_name=storage_name,
            store_state=store_state,
            include_audit=True,
        )
    )


def discard_ingest_temp_file(temp_path: str | None) -> None:
    """Remove a download temp file the ingest never took ownership of.

    Sync calls this only when the download itself failed; once
    ``ingest_download()`` has been handed the path, the service owns it.
    """
    if not temp_path:
        return
    try:
        remove_local_file_if_present(temp_path)
    except OSError:
        log.warning("attachment ingest: temp cleanup failed", exc_info=True)


def cleanup_superseded(*, stale_paths=(), stale_objects=()) -> None:
    """Remove blobs a fresh ingest has replaced, after the rows are flushed.

    ``stale_paths`` are ``(old_local_path, new_local_path)`` pairs and
    ``stale_objects`` are ``(form_id, old_storage_name)`` pairs for rows whose
    blob lives in the object store. In both cases the row already points at the
    new blob, and the old one is removed only when no live row still references
    it. A failure is logged and left alone: the blob becomes an orphan that
    ``attachment integrity`` reports, and it never fails a sync.
    """
    seen_paths = set()
    for old_local_path, new_local_path in stale_paths or ():
        if (
            not old_local_path
            or old_local_path == new_local_path
            or old_local_path in seen_paths
        ):
            continue
        seen_paths.add(old_local_path)
        in_use = db.session.scalar(
            sa.select(sa.func.count())
            .select_from(VaSubmissionAttachments)
            .where(
                VaSubmissionAttachments.local_path == old_local_path,
                VaSubmissionAttachments.exists_on_odk.is_(True),
            )
        )
        if in_use and int(in_use) > 0:
            continue
        try:
            remove_local_file_if_present(old_local_path)
        except OSError:
            log.warning(
                "Could not remove stale attachment file: %s", old_local_path, exc_info=True
            )

    if not stale_objects:
        return
    from app.services.attachment_store import StoreTarget, get_attachment_store

    store = get_attachment_store()
    if store.name != STORE_STATE_S3:
        return
    seen_objects = set()
    for va_form_id, old_storage_name in stale_objects:
        if not old_storage_name or (va_form_id, old_storage_name) in seen_objects:
            continue
        seen_objects.add((va_form_id, old_storage_name))
        in_use = db.session.scalar(
            sa.select(sa.func.count())
            .select_from(VaSubmissionAttachments)
            .where(
                VaSubmissionAttachments.storage_name == old_storage_name,
                VaSubmissionAttachments.exists_on_odk.is_(True),
            )
        )
        if in_use and int(in_use) > 0:
            continue
        try:
            store.delete(
                StoreTarget(va_form_id=va_form_id, storage_name=old_storage_name)
            )
        except Exception:
            log.warning(
                "Could not remove a superseded attachment object for form %s",
                va_form_id, exc_info=True,
            )


# ---------------------------------------------------------------------------
# Repair
#
# Plan Phase 5: a row whose stored object is missing, or whose MP3 derivative
# is stale, is rebuilt from ODK Central — the same fetch-and-store path
# delivery uses to self-heal, run without a client waiting. A retired
# submission is never probed, and a project with Central fetch switched off
# reports that rather than reaching the network.
# ---------------------------------------------------------------------------

REPAIR_NOT_NEEDED = "not_needed"
REPAIR_REPAIRED = "repaired"
REPAIR_DERIVATIVE_REBUILT = "derivative_rebuilt"
REPAIR_RETIRED = "retired"
REPAIR_CENTRAL_DISABLED = "central_disabled"
REPAIR_UNKNOWN_ROW = "unknown_row"
REPAIR_MISSING = "missing"
REPAIR_TRANSIENT = "transient"
REPAIR_ERROR = "error"

REPAIR_OUTCOMES = (
    REPAIR_NOT_NEEDED, REPAIR_REPAIRED, REPAIR_DERIVATIVE_REBUILT,
    REPAIR_RETIRED, REPAIR_CENTRAL_DISABLED, REPAIR_UNKNOWN_ROW,
    REPAIR_MISSING, REPAIR_TRANSIENT, REPAIR_ERROR,
)


@dataclass(frozen=True)
class RepairOutcome:
    """What one repair attempt did. ``error_code`` is a category, never text."""

    outcome: str
    error_code: str | None = None

    @property
    def repaired(self) -> bool:
        return self.outcome in (REPAIR_REPAIRED, REPAIR_DERIVATIVE_REBUILT)


@dataclass(frozen=True)
class _RepairContext:
    """Stored facts that decide whether a row may be repaired at all."""

    central_fetch_enabled: bool
    retired: bool
    derivative_state: str | None


def _repair_context(record: AttachmentRecord) -> _RepairContext | None:
    """One bounded read of the project flag, retirement, and derivative state."""
    row = db.session.execute(
        sa.select(
            VaProjectMaster.attachment_central_fetch_enabled,
            VaSubmissions.va_sync_issue_code,
            VaSubmissionAttachments.local_fallback_state,
            VaSubmissionAttachments.derivative_state,
            VaSubmissionAttachments.source_state,
        )
        .select_from(VaSubmissionAttachments)
        .join(VaSubmissions, VaSubmissions.va_sid == VaSubmissionAttachments.va_sid)
        .join(VaForms, VaForms.form_id == VaSubmissions.va_form_id)
        .join(
            VaProjectMaster,
            VaProjectMaster.project_id == VaForms.project_id,
            isouter=True,
        )
        .where(
            VaSubmissionAttachments.va_sid == record.va_sid,
            VaSubmissionAttachments.filename == record.filename,
        )
    ).first()
    if row is None:
        return None
    return _RepairContext(
        central_fetch_enabled=bool(row.attachment_central_fetch_enabled),
        retired=(
            row.va_sync_issue_code == MISSING_IN_ODK
            or row.local_fallback_state == LOCAL_RETAINED
            or row.source_state == SOURCE_RETIRED
        ),
        derivative_state=row.derivative_state,
    )


def _repair_outcome_for_fetch(outcome: str) -> str:
    from app.services import attachment_source_central as central

    if outcome == central.FETCH_NOT_FOUND:
        return REPAIR_MISSING
    if outcome in (central.FETCH_TRANSIENT, central.FETCH_THROTTLED):
        return REPAIR_TRANSIENT
    return REPAIR_ERROR


def _rebuild_audio_derivative(record: AttachmentRecord, result) -> RepairOutcome:
    """Rebuild one MP3 from the AMR original Central just handed us.

    Central holds the AMR, never the MP3, so a missing or stale derivative can
    only be repaired by fetching the original and converting it again. The
    rebuilt object keeps the row's existing ``storage_name``, so no delivery
    token rotates and nothing else has to be invalidated.
    """
    temp_path = new_ingest_temp_path(record.va_form_id)
    try:
        with open(temp_path, "wb") as handle:
            for chunk in _iter_central_body(result):
                handle.write(chunk)
        etag = (result.response.headers.get("ETag")
                or result.response.headers.get("etag"))
        ingested = ingest_download(
            va_sid=record.va_sid,
            va_form_id=record.va_form_id,
            filename=record.filename,
            temp_path=temp_path,
            mime_type=safe_mime_type(result.mime_type) or record.source_mime_type,
            etag=etag,
            downloaded_at=datetime.now(timezone.utc),
            storage_name=record.storage_name,
        )
    except AmrConversionError:
        remove_local_file_if_present(temp_path)
        db.session.execute(
            sa.update(VaSubmissionAttachments)
            .where(
                VaSubmissionAttachments.va_sid == record.va_sid,
                VaSubmissionAttachments.filename == record.filename,
            )
            .values(
                derivative_state=DERIVATIVE_ERROR,
                derivative_error_code=DERIVATIVE_ERROR_CONVERSION_FAILED,
            )
        )
        db.session.commit()
        return RepairOutcome(REPAIR_ERROR, error_code=DERIVATIVE_ERROR_CONVERSION_FAILED)

    values = dict(ingested.state_values)
    values["local_path"] = ingested.local_path
    if ingested.store_state == STORE_STATE_LOCAL:
        values["local_fallback_state"] = LOCAL_PRESENT
    db.session.execute(
        sa.update(VaSubmissionAttachments)
        .where(
            VaSubmissionAttachments.va_sid == record.va_sid,
            VaSubmissionAttachments.filename == record.filename,
            VaSubmissionAttachments.local_fallback_state != LOCAL_RETAINED,
        )
        .values(**values)
    )
    db.session.commit()
    invalidate_attachment_record(record.storage_name)
    return RepairOutcome(REPAIR_DERIVATIVE_REBUILT)


def repair_attachment(record: AttachmentRecord) -> RepairOutcome:
    """Restore one attachment's bytes from ODK Central. No response, no client.

    * a retired submission is never probed — ``retired``;
    * a row whose object is present and whose derivative is ready needs
      nothing — ``not_needed``;
    * with the project's ``attachment_central_fetch_enabled`` off, nothing
      reaches the network — ``central_disabled``;
    * a missing original is fetched and written into the store through the
      same ``_store_write`` tee delivery uses — ``repaired``;
    * a ``pending``/``stale``/``error`` MP3 is rebuilt from the AMR original —
      ``derivative_rebuilt``;
    * a failed fetch keeps the fetch's own category: ``missing`` (Central says
      not-found), ``transient`` (retry later), ``error`` (auth, configuration,
      or an invalid redirect — never silently treated as missing).

    ``attachment_source_central.record_fetch_state()`` persists what the
    attempt proved about the source in every case, so a run that repairs
    nothing still moves the row's observation forward.
    """
    from app.services.attachment_store import AttachmentStoreError, get_attachment_store

    context = _repair_context(record)
    if context is None:
        return RepairOutcome(REPAIR_UNKNOWN_ROW)
    if context.retired:
        return RepairOutcome(REPAIR_RETIRED)

    is_audio = is_audio_attachment(record.filename)
    object_missing = not get_attachment_store().exists(record)
    derivative_unready = is_audio and context.derivative_state != DERIVATIVE_READY
    if not object_missing and not derivative_unready:
        return RepairOutcome(REPAIR_NOT_NEEDED)
    if not context.central_fetch_enabled:
        return RepairOutcome(REPAIR_CENTRAL_DISABLED)

    from app.services import attachment_source_central as central

    result = central.fetch(record)
    central.record_fetch_state(record, result)
    if not result.ok:
        return RepairOutcome(
            _repair_outcome_for_fetch(result.outcome), error_code=result.error_code
        )

    if is_audio:
        return _rebuild_audio_derivative(record, result)

    try:
        for _ in _store_write(record, _iter_central_body(result)):
            pass
    except AttachmentStoreError:
        return RepairOutcome(REPAIR_ERROR)
    if not get_attachment_store().exists(record):
        return RepairOutcome(REPAIR_ERROR)
    return RepairOutcome(REPAIR_REPAIRED)


# ---------------------------------------------------------------------------
# Readiness-driven completeness
#
# Plan Finding 4 and the retired-submission policy: whether a submission's
# attachments are complete is a question about stored state — source state,
# derivative state, store presence — not about counting files on a disk that
# an S3 deployment does not have.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SubmissionAttachmentState:
    """Readiness of one submission's attachments, as completeness sees it.

    ``ready_count`` counts attachment blobs DigitVA can actually serve;
    ``unready`` names the ones it cannot. ``audit.csv`` is excluded from both,
    matching the historical presence definition. A ``retired`` submission is
    complete by policy: ODK has purged it and nothing may be fetched again.
    """

    va_sid: str
    retired: bool
    ready_count: int
    unready: tuple[str, ...]


def attachment_state_by_submission(
    form_id: str,
    *,
    target_sids: list[str] | None = None,
) -> dict[str, SubmissionAttachmentState]:
    """Bulk readiness-based completeness input for one form.

    One bounded query over the form's attachment rows — no filesystem walk, no
    Central or S3 call, and no per-row probe (see ``resolve_attachment_presence``
    for why an ``s3`` row's presence is its stored ``store_state``).

    A row counts as ready when its blob is present in the store and, for audio,
    its MP3 derivative is ``ready``. A row whose source Central reports gone
    (``missing``/``retired``) never blocks completeness, because no repair can
    ever satisfy it.
    """
    app_data_root = current_app.config.get("APP_DATA")
    stmt = (
        sa.select(
            VaSubmissionAttachments.va_sid,
            VaSubmissionAttachments.filename,
            VaSubmissionAttachments.local_path,
            VaSubmissionAttachments.storage_name,
            VaSubmissionAttachments.store_state,
            VaSubmissionAttachments.source_state,
            VaSubmissionAttachments.derivative_state,
            VaSubmissions.va_sync_issue_code,
        )
        .select_from(VaSubmissionAttachments)
        .join(VaSubmissions, VaSubmissions.va_sid == VaSubmissionAttachments.va_sid)
        .where(
            VaSubmissions.va_form_id == form_id,
            VaSubmissionAttachments.exists_on_odk.is_(True),
        )
    )
    if target_sids:
        stmt = stmt.where(VaSubmissionAttachments.va_sid.in_(target_sids))

    ready: dict[str, set[str]] = {}
    unready: dict[str, list[str]] = {}
    retired: dict[str, bool] = {}
    for row in db.session.execute(stmt).mappings().all():
        va_sid = row["va_sid"]
        retired[va_sid] = (
            retired.get(va_sid, False) or row["va_sync_issue_code"] == MISSING_IN_ODK
        )
        if (row["filename"] or "").lower() == AUDIT_FILENAME:
            continue
        if row["source_state"] in (SOURCE_MISSING, SOURCE_RETIRED):
            continue
        identity = resolve_attachment_presence(
            app_data_root=app_data_root,
            form_id=form_id,
            local_path=row["local_path"],
            storage_name=row["storage_name"],
            store_state=row["store_state"],
        )
        derivative_ok = row["derivative_state"] in (None, DERIVATIVE_READY)
        if identity and derivative_ok:
            ready.setdefault(va_sid, set()).add(identity)
        else:
            unready.setdefault(va_sid, []).append(row["filename"])

    return {
        va_sid: SubmissionAttachmentState(
            va_sid=va_sid,
            retired=is_retired,
            ready_count=len(ready.get(va_sid, ())),
            unready=tuple(sorted(unready.get(va_sid, ()))),
        )
        for va_sid, is_retired in retired.items()
    }


def repair_candidates(
    form_id: str,
    *,
    target_sids: list[str] | None = None,
    limit: int = 200,
) -> list[AttachmentRecord]:
    """Attachment rows of one form that ``repair_attachment()`` could fix.

    Bounded by ``limit`` and ordered so repeated runs make progress in a stable
    order. Retired submissions are excluded here as well as inside
    ``repair_attachment()``, so a retired row never costs a store probe.
    """
    states = attachment_state_by_submission(form_id, target_sids=target_sids)
    wanted = {
        (va_sid, filename)
        for va_sid, state in states.items()
        if not state.retired
        for filename in state.unready
    }
    if not wanted:
        return []

    rows = db.session.execute(
        sa.select(
            VaSubmissionAttachments.va_sid,
            VaSubmissionAttachments.filename,
            VaSubmissionAttachments.storage_name,
            VaSubmissionAttachments.local_path,
            VaSubmissionAttachments.mime_type,
            VaSubmissionAttachments.source_mime_type,
        )
        .where(
            VaSubmissionAttachments.va_sid.in_(sorted({sid for sid, _ in wanted})),
            VaSubmissionAttachments.storage_name.is_not(None),
        )
        .order_by(VaSubmissionAttachments.va_sid, VaSubmissionAttachments.filename)
    ).all()
    candidates = [
        AttachmentRecord(
            va_sid=row.va_sid,
            va_form_id=form_id,
            storage_name=row.storage_name,
            filename=row.filename,
            local_path=row.local_path,
            mime_type=row.mime_type,
            source_mime_type=row.source_mime_type,
        )
        for row in rows
        if (row.va_sid, row.filename) in wanted
    ]
    return candidates[:limit]


# ---------------------------------------------------------------------------
# Operator overview
#
# What the admin "Attachment Management" panel and ``flask attachments
# overview`` both read. Bulk aggregates only: every figure is a GROUP BY over
# indexed columns, nothing is resolved per row, and nothing here touches the
# filesystem, the bucket, or ODK Central.
# ---------------------------------------------------------------------------

# Only the most recent error categories are interesting, and only as counts.
OVERVIEW_ERROR_CATEGORY_LIMIT = 10


def _overview_scope(stmt, project_ids):
    if project_ids:
        stmt = stmt.where(VaForms.project_id.in_(project_ids))
    return stmt


def _overview_state_counts(project_ids) -> dict[str, dict]:
    """Per-form counts of every readiness state, in one grouped query."""
    columns = {
        "source_state": VaSubmissionAttachments.source_state,
        "derivative_state": VaSubmissionAttachments.derivative_state,
        "store_state": VaSubmissionAttachments.store_state,
        "local_fallback_state": VaSubmissionAttachments.local_fallback_state,
    }
    per_form: dict[str, dict] = {}
    for label, column in columns.items():
        stmt = (
            sa.select(
                VaForms.form_id,
                VaForms.project_id,
                column.label("state"),
                sa.func.count().label("rows"),
            )
            .select_from(VaSubmissionAttachments)
            .join(VaSubmissions, VaSubmissions.va_sid == VaSubmissionAttachments.va_sid)
            .join(VaForms, VaForms.form_id == VaSubmissions.va_form_id)
            .group_by(VaForms.form_id, VaForms.project_id, column)
        )
        for row in db.session.execute(_overview_scope(stmt, project_ids)).all():
            form = per_form.setdefault(
                row.form_id,
                {
                    "form_id": row.form_id,
                    "project_id": row.project_id,
                    "source_state": {},
                    "derivative_state": {},
                    "store_state": {},
                    "local_fallback_state": {},
                    "retired_rows": 0,
                    "awaiting_s3": 0,
                },
            )
            form[label][row.state or "unset"] = int(row.rows or 0)
    return per_form


def _overview_retired_counts(project_ids) -> dict[str, int]:
    """Attachment rows belonging to submissions retired from ODK, per form."""
    stmt = (
        sa.select(VaForms.form_id, sa.func.count().label("rows"))
        .select_from(VaSubmissionAttachments)
        .join(VaSubmissions, VaSubmissions.va_sid == VaSubmissionAttachments.va_sid)
        .join(VaForms, VaForms.form_id == VaSubmissions.va_form_id)
        .where(VaSubmissions.va_sync_issue_code == MISSING_IN_ODK)
        .group_by(VaForms.form_id)
    )
    return {
        row.form_id: int(row.rows or 0)
        for row in db.session.execute(_overview_scope(stmt, project_ids)).all()
    }


def _overview_awaiting_s3(project_ids) -> dict[str, int]:
    """Rows whose blob is not yet in the bucket, per form. Empty on local."""
    from app.services.attachment_store import get_attachment_store

    if get_attachment_store().name != STORE_STATE_S3:
        return {}
    stmt = (
        sa.select(VaForms.form_id, sa.func.count().label("rows"))
        .select_from(VaSubmissionAttachments)
        .join(VaSubmissions, VaSubmissions.va_sid == VaSubmissionAttachments.va_sid)
        .join(VaForms, VaForms.form_id == VaSubmissions.va_form_id)
        .where(
            VaSubmissionAttachments.exists_on_odk.is_(True),
            VaSubmissionAttachments.store_state != STORE_STATE_S3,
        )
        .group_by(VaForms.form_id)
    )
    return {
        row.form_id: int(row.rows or 0)
        for row in db.session.execute(_overview_scope(stmt, project_ids)).all()
    }


def _overview_error_categories(project_ids) -> list[dict]:
    """Source error categories and how many rows carry each. Counts, not rows."""
    stmt = (
        sa.select(
            VaSubmissionAttachments.source_error_code.label("category"),
            sa.func.count().label("rows"),
            sa.func.max(VaSubmissionAttachments.source_verified_at).label("last_seen"),
        )
        .select_from(VaSubmissionAttachments)
        .join(VaSubmissions, VaSubmissions.va_sid == VaSubmissionAttachments.va_sid)
        .join(VaForms, VaForms.form_id == VaSubmissions.va_form_id)
        .where(VaSubmissionAttachments.source_error_code.is_not(None))
        .group_by(VaSubmissionAttachments.source_error_code)
        .order_by(sa.func.count().desc())
        .limit(OVERVIEW_ERROR_CATEGORY_LIMIT)
    )
    return [
        {
            "category": row.category,
            "rows": int(row.rows or 0),
            "last_seen": row.last_seen.isoformat() if row.last_seen else None,
        }
        for row in db.session.execute(_overview_scope(stmt, project_ids)).all()
    ]


def _overview_projects(project_ids) -> list[dict]:
    """Projects in scope and their Central self-heal switch."""
    stmt = sa.select(
        VaProjectMaster.project_id,
        VaProjectMaster.attachment_central_fetch_enabled,
    ).order_by(VaProjectMaster.project_id)
    if project_ids:
        stmt = stmt.where(VaProjectMaster.project_id.in_(project_ids))
    return [
        {
            "project_id": row.project_id,
            "attachment_central_fetch_enabled": bool(
                row.attachment_central_fetch_enabled
            ),
        }
        for row in db.session.execute(stmt).all()
    ]


def attachment_management_overview(project_ids: list[str] | None = None) -> dict:
    """Everything the Attachment Management panel shows, in five bulk queries.

    ``project_ids`` scopes every figure to those projects; ``None`` is all of
    them. The result is JSON-ready and contains no submission identifiers, no
    filenames, no URLs — only the projects in scope with their Central
    self-heal switch, per-form counts by state, the process's delivery
    counters, and source error categories.
    """
    from app.services.attachment_store import get_attachment_store

    scope = [p for p in (project_ids or []) if p]
    forms = _overview_state_counts(scope)
    for form_id, retired_rows in _overview_retired_counts(scope).items():
        if form_id in forms:
            forms[form_id]["retired_rows"] = retired_rows
    for form_id, awaiting in _overview_awaiting_s3(scope).items():
        if form_id in forms:
            forms[form_id]["awaiting_s3"] = awaiting

    store = get_attachment_store()
    return {
        "store": store.name,
        "project_ids": scope,
        "projects": _overview_projects(scope),
        "forms": [forms[form_id] for form_id in sorted(forms)],
        "delivery_counters": delivery_counters(),
        "source_error_categories": _overview_error_categories(scope),
    }


# ---------------------------------------------------------------------------
# Integrity
#
# The DB and the store must agree: every row that claims a blob has one, and
# every blob is claimed by a row. Both sides are read in bounded pages, and
# nothing is ever deleted — an orphan local file can be *moved* into a
# quarantine subtree, and an orphan key is only reported.
# ---------------------------------------------------------------------------

INTEGRITY_PAGE_SIZE = 500


def _normalized_local_path(app_data: Path, raw_path: str | None) -> Path | None:
    if not raw_path:
        return None
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = app_data / candidate
    return candidate.resolve(strict=False)


def orphan_quarantine_destination(source_path: Path) -> Path:
    """Where one orphan file is moved to, under ``<media>/.orphaned/``.

    The relative path below ``media`` is preserved, and an existing
    destination is never overwritten — a numeric suffix is added instead.
    """
    try:
        media_root = next(
            parent for parent in source_path.parents if parent.name == "media"
        )
    except StopIteration as exc:
        raise ValueError(f"Path is not under a media directory: {source_path}") from exc
    relative_path = source_path.relative_to(media_root)
    destination = media_root / ORPHAN_DIRNAME / relative_path
    destination.parent.mkdir(parents=True, exist_ok=True)

    if not destination.exists():
        return destination

    suffix = "".join(destination.suffixes)
    stem = destination.name[: -len(suffix)] if suffix else destination.name
    counter = 1
    while True:
        candidate = destination.with_name(f"{stem}.{counter}{suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def quarantine_orphan_files(orphan_files) -> list[tuple[Path, Path]]:
    """Move orphan files aside. Nothing is deleted; the move is reversible."""
    moved: list[tuple[Path, Path]] = []
    for source_path in orphan_files:
        destination = orphan_quarantine_destination(source_path)
        source_path.replace(destination)
        moved.append((source_path, destination))
    return moved


def local_integrity_check(
    *,
    form_id: str | None = None,
    quarantine_orphans: bool = False,
) -> dict:
    """Compare attachment rows against the files under ``APP_DATA/*/media``.

    Reports rows with no file, files no row references, and rows pointing
    outside ``APP_DATA``. With ``quarantine_orphans`` the orphan files are
    moved into ``.orphaned/`` rather than removed.
    """
    app_data = Path(current_app.config["APP_DATA"]).resolve(strict=False)
    stmt = (
        sa.select(
            VaSubmissionAttachments.va_sid,
            VaSubmissionAttachments.filename,
            VaSubmissionAttachments.local_path,
            VaSubmissionAttachments.exists_on_odk,
            VaSubmissions.va_form_id,
        )
        .join(VaSubmissions, VaSubmissions.va_sid == VaSubmissionAttachments.va_sid)
        .order_by(
            VaSubmissions.va_form_id,
            VaSubmissionAttachments.va_sid,
            VaSubmissionAttachments.filename,
        )
    )
    if form_id:
        stmt = stmt.where(VaSubmissions.va_form_id == form_id)

    referenced_paths: set[str] = set()
    missing_rows: list[dict] = []
    outside_app_data_rows: list[dict] = []
    row_count = 0

    for row in db.session.execute(stmt).mappings().yield_per(INTEGRITY_PAGE_SIZE):
        row_count += 1
        norm_path = _normalized_local_path(app_data, row["local_path"])
        if norm_path is not None:
            referenced_paths.add(str(norm_path))
            if not str(norm_path).startswith(str(app_data) + os.sep):
                outside_app_data_rows.append({
                    "va_sid": row["va_sid"],
                    "form_id": row["va_form_id"],
                    "filename": row["filename"],
                    "local_path": row["local_path"],
                })
        if row["exists_on_odk"] is not True:
            continue
        if norm_path is None:
            missing_rows.append({
                "reason": "local_path_null",
                "va_sid": row["va_sid"],
                "form_id": row["va_form_id"],
                "filename": row["filename"],
                "local_path": None,
            })
        elif not local_attachment_file_exists(str(norm_path)):
            missing_rows.append({
                "reason": "file_missing",
                "va_sid": row["va_sid"],
                "form_id": row["va_form_id"],
                "filename": row["filename"],
                "local_path": str(norm_path),
            })

    disk_file_count, disk_files = scan_local_media_files(app_data)
    orphan_paths = [p for p in disk_files if str(p) not in referenced_paths]
    moved_orphans: list[tuple[Path, Path]] = []
    if quarantine_orphans and orphan_paths:
        moved_orphans = quarantine_orphan_files(orphan_paths)
        disk_file_count, disk_files = scan_local_media_files(app_data)
        orphan_paths = [p for p in disk_files if str(p) not in referenced_paths]

    return {
        "store": STORE_STATE_LOCAL,
        "app_data": str(app_data),
        "form_id": form_id,
        "rows_scanned": row_count,
        "disk_files_scanned": disk_file_count,
        "missing_rows": missing_rows,
        "orphan_paths": orphan_paths,
        "outside_app_data_rows": outside_app_data_rows,
        "moved_orphans": moved_orphans,
        "clean": not missing_rows and not orphan_paths,
    }


def s3_integrity_check(*, form_id: str | None = None) -> dict:
    """Compare the rows recorded as S3-stored against what the bucket holds.

    Rows are streamed and keys are listed one page at a time, so neither a
    large table nor a large bucket is materialised. Nothing is written or
    deleted. Raises ``AttachmentStoreError`` when the process is not on the S3
    store, because there would be no bucket to compare against.
    """
    from app.services.attachment_store import (
        AttachmentStoreError,
        StoreTarget,
        get_attachment_store,
    )

    store = get_attachment_store()
    if store.name != STORE_STATE_S3:
        raise AttachmentStoreError(
            "ATTACHMENT_STORE is not 's3'; nothing to check against a bucket."
        )

    stmt = (
        sa.select(
            VaSubmissionAttachments.va_sid,
            VaSubmissionAttachments.filename,
            VaSubmissionAttachments.storage_name,
            VaSubmissionAttachments.store_state,
            VaSubmissions.va_form_id,
        )
        .join(VaSubmissions, VaSubmissions.va_sid == VaSubmissionAttachments.va_sid)
        .where(VaSubmissionAttachments.exists_on_odk.is_(True))
        .order_by(VaSubmissions.va_form_id, VaSubmissionAttachments.va_sid)
    )
    if form_id:
        stmt = stmt.where(VaSubmissions.va_form_id == form_id)

    expected: dict[str, tuple[str, str, str]] = {}
    not_yet_uploaded: list[tuple[str, str, str]] = []
    row_count = 0
    for row in db.session.execute(stmt).yield_per(INTEGRITY_PAGE_SIZE):
        row_count += 1
        if not row.storage_name:
            continue
        if row.store_state != STORE_STATE_S3:
            not_yet_uploaded.append((row.va_form_id, row.va_sid, row.filename))
            continue
        key = store.key_for(
            StoreTarget(va_form_id=row.va_form_id, storage_name=row.storage_name)
        )
        expected[key] = (row.va_form_id, row.va_sid, row.filename)

    present_keys: set[str] = set()
    for key, _size, _etag in store.iter_keys():
        present_keys.add(key)

    missing = [(key, meta) for key, meta in expected.items() if key not in present_keys]
    orphans = sorted(present_keys - set(expected))
    return {
        "store": STORE_STATE_S3,
        "key_prefix": store.key_prefix or "",
        "form_id": form_id,
        "rows_scanned": row_count,
        "keys_listed": len(present_keys),
        "missing_objects": missing,
        "orphan_keys": orphans,
        "awaiting_cutover": not_yet_uploaded,
        "clean": not missing and not orphans,
    }


def integrity_check_summary(*, form_id: str | None = None) -> dict:
    """Counts-only integrity summary for the selected store.

    What the admin action and the Celery task record: no paths, no submission
    identifiers, no keys — those stay in the CLI report an operator runs.
    """
    from app.services.attachment_store import get_attachment_store

    if get_attachment_store().name == STORE_STATE_S3:
        report = s3_integrity_check(form_id=form_id)
        return {
            "store": STORE_STATE_S3,
            "form_id": form_id,
            "rows_scanned": report["rows_scanned"],
            "keys_listed": report["keys_listed"],
            "missing_objects": len(report["missing_objects"]),
            "orphan_keys": len(report["orphan_keys"]),
            "awaiting_cutover": len(report["awaiting_cutover"]),
            "clean": report["clean"],
        }
    report = local_integrity_check(form_id=form_id)
    return {
        "store": STORE_STATE_LOCAL,
        "form_id": form_id,
        "rows_scanned": report["rows_scanned"],
        "disk_files_scanned": report["disk_files_scanned"],
        "missing_files": len(report["missing_rows"]),
        "orphan_files": len(report["orphan_paths"]),
        "outside_app_data": len(report["outside_app_data_rows"]),
        "clean": report["clean"],
    }


# ---------------------------------------------------------------------------
# Migration (local -> S3 cutover)
#
# The pair behind ``flask attachments s3-upload`` / ``local-quarantine``.
# Neither ever deletes an attachment: the upload copies local blobs into the
# bucket and verifies what landed, and the quarantine only *moves* verified
# local files aside so an operator can remove them after a retention window.
# ---------------------------------------------------------------------------

# Rows are read in keyset pages so the tools never load the whole table, and
# so an interrupted run resumes from where it stopped.
MIGRATION_PAGE_SIZE = 200
_HASH_CHUNK_SIZE = 1024 * 1024

# Quarantine destination under each form's media directory. Files are moved
# here, never removed; the retention delete is a manual, documented step.
QUARANTINE_DIRNAME = ".s3-uploaded"


def require_s3_store():
    """The selected store, or an error naming the configuration to change."""
    from app.services.attachment_store import AttachmentStoreError, get_attachment_store

    store = get_attachment_store()
    if store.name != STORE_STATE_S3:
        raise AttachmentStoreError(
            "ATTACHMENT_STORE is not 's3'. Set ATTACHMENT_STORE=s3 (with the "
            "S3_* variables) before running the cutover commands."
        )
    return store


def migration_content_type(row) -> str:
    """The MIME to store one row's blob under.

    ``.amr`` rows hold an MP3 derivative, so the derivative's type wins for
    them; every other row is its original. A missing, malformed, or literal
    ``"null"`` value is discarded by ``safe_mime_type`` and the type is guessed
    from the storage name before falling back to a generic binary type.
    """
    import mimetypes

    from app.services.attachment_store import DEFAULT_CONTENT_TYPE

    preferred = (
        row.derivative_mime_type
        if is_audio_attachment(row.filename)
        else row.source_mime_type
    )
    for candidate in (preferred, row.mime_type):
        resolved = safe_mime_type(candidate)
        if resolved:
            return resolved
    guessed, _ = mimetypes.guess_type(row.storage_name or "")
    return guessed or DEFAULT_CONTENT_TYPE


def _file_md5(path: str) -> str:
    # MD5 because that is what a single-part S3 ETag is; not a security hash.
    import hashlib

    digest = hashlib.md5(usedforsecurity=False)
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(_HASH_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _upload_candidate_page(form_id, after, page_size):
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
            VaSubmissionAttachments.store_state != STORE_STATE_S3,
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
    from app.services.attachment_store import StoreTarget

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


def s3_upload_backlog(
    *,
    form_id: str | None = None,
    dry_run: bool = False,
    limit: int = 0,
    workers: int = 4,
    on_progress=None,
) -> dict:
    """Copy local attachment blobs into the S3 store and point the rows at them.

    Idempotent and resumable: rows already recorded as ``store_state='s3'`` are
    not revisited, and a row whose object is already present with the right
    size is verified rather than re-uploaded. Bounded memory — every blob is
    streamed from its file. Local files are never deleted.

    Attachments of submissions retired from ODK are uploaded too: the object
    becomes their archive copy. ``on_progress`` is called with a message after
    each page so a CLI can report without this function knowing about one.
    """
    from concurrent.futures import ThreadPoolExecutor

    from app.services.attachment_store import LocalAttachmentStore, StoreTarget

    store = require_s3_store()
    local_store = LocalAttachmentStore()
    counts = {"scanned": 0, "uploaded": 0, "would_upload": 0, "failed": 0}
    failures: list[str] = []
    planned: list[str] = []
    after = None

    while True:
        page_size = MIGRATION_PAGE_SIZE
        if limit:
            remaining = limit - counts["scanned"]
            if remaining <= 0:
                break
            page_size = min(page_size, remaining)
        rows = _upload_candidate_page(form_id, after, page_size)
        if not rows:
            break
        after = (rows[-1].va_sid, rows[-1].filename)
        counts["scanned"] += len(rows)

        if dry_run:
            counts["would_upload"] += len(rows)
            planned.extend(
                f"{row.va_form_id}/{row.storage_name} as {migration_content_type(row)}"
                for row in rows
            )
            continue

        # Local paths are resolved here, on the thread that holds the app
        # context; the workers only move bytes.
        plans = [
            (
                row,
                migration_content_type(row),
                local_store.open_local_path(StoreTarget(
                    va_form_id=row.va_form_id,
                    storage_name=row.storage_name,
                    local_path=row.local_path,
                )),
            )
            for row in rows
        ]
        with ThreadPoolExecutor(max_workers=min(max(workers, 1), len(plans))) as pool:
            outcomes = list(pool.map(
                lambda plan: _upload_one(store, plan[0], plan[1], plan[2]),
                plans,
            ))

        for (row, _content_type, _path), error in zip(plans, outcomes, strict=True):
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
                .values(store_state=STORE_STATE_S3, local_path=None)
            )
            invalidate_attachment_record(row.storage_name)
            counts["uploaded"] += 1
        db.session.commit()
        if on_progress:
            on_progress(
                f"... scanned={counts['scanned']} uploaded={counts['uploaded']} "
                f"failed={counts['failed']}"
            )

    return {**counts, "failures": failures, "planned": planned}


def quarantine_local_copies(
    *,
    form_id: str | None = None,
    dry_run: bool = False,
    include_retained: bool = False,
    on_message=None,
) -> dict:
    """Move the local files of verified S3-stored rows into ``media/.s3-uploaded/``.

    Nothing is deleted. Each file is moved only after its object is confirmed
    present in the bucket, so the copy count never drops below one. Removing
    the quarantined files after the retention window is a manual ``rm``, by
    design. ``retained`` archival copies of retired submissions are skipped
    unless ``include_retained`` is set.
    """
    from app.services.attachment_store import LocalAttachmentStore, StoreTarget

    store = require_s3_store()
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
            VaSubmissionAttachments.store_state == STORE_STATE_S3,
            VaSubmissionAttachments.storage_name.is_not(None),
        )
        .order_by(VaSubmissionAttachments.va_sid, VaSubmissionAttachments.filename)
    )
    if form_id:
        stmt = stmt.where(VaSubmissions.va_form_id == form_id)
    if not include_retained:
        stmt = stmt.where(
            VaSubmissionAttachments.local_fallback_state != LOCAL_RETAINED
        )

    counts = {"moved": 0, "would_move": 0, "skipped_no_object": 0, "no_local_file": 0}
    for row in db.session.execute(stmt).yield_per(MIGRATION_PAGE_SIZE):
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
            if on_message:
                on_message(
                    f"! no object yet for {row.va_form_id}/{row.storage_name}; "
                    "left in place"
                )
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
            .values(local_fallback_state=LOCAL_QUARANTINED)
        )
        counts["moved"] += 1
        if counts["moved"] % MIGRATION_PAGE_SIZE == 0:
            db.session.commit()
    db.session.commit()
    return counts


def set_project_central_fetch(project_id: str, enabled: bool | None = None) -> bool:
    """Read or set one project's Central self-heal flag. Returns the value.

    The rollout switch for the Central fetch on a store miss: with it off a
    miss is a 404 exactly as before, so disabling is always a safe rollback.
    Raises ``LookupError`` for an unknown project.
    """
    project = db.session.get(VaProjectMaster, (project_id or "").strip().upper())
    if project is None:
        raise LookupError(f"Project '{project_id}' not found.")
    if enabled is not None:
        project.attachment_central_fetch_enabled = bool(enabled)
        db.session.commit()
        log.info(
            "attachment central-fetch flag project=%s enabled=%s",
            project.project_id, project.attachment_central_fetch_enabled,
        )
    return bool(project.attachment_central_fetch_enabled)
