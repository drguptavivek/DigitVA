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
import tempfile
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
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


def _stream_central_response(record: AttachmentRecord, result):
    """Proxy Central's body with DigitVA's own headers, teeing it into the store.

    The body is read in bounded chunks and never buffered whole, and the
    upstream response is closed both when the generator finishes and when the
    client disconnects.
    """
    upstream = result.response

    def upstream_chunks():
        try:
            for chunk in upstream.iter_content(chunk_size=ATTACHMENT_STREAM_CHUNK_SIZE):
                if chunk:
                    yield chunk
        finally:
            upstream.close()

    response = current_app.response_class(
        stream_with_context(_store_write(record, upstream_chunks())),
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
