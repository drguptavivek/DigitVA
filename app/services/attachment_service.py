"""Attachment module boundary.

Every decision about a submission attachment — who may receive it, whether its
bytes are present, and how they are delivered — goes through this module.
Routes, render code, sync tasks, admin telemetry, and the integrity script call
these functions; none of them touch the attachment filesystem directly.

This is Phase 3 of ``docs/planning/s3-attachment-plan.md``: the interface exists
so that the Central/S3-backed implementation (Phase 4) is a change to this
module's internals rather than an edit across eight call sites. The current
implementation is entirely local-disk backed and behaviour-neutral relative to
the code it replaced.

Policy baseline: ``docs/policy/attachment-storage.md``.
"""

from __future__ import annotations

import logging
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import sqlalchemy as sa
from flask import abort, current_app, send_file

from app import db, cache as flask_cache
from app.models import (
    VaAllocations,
    VaCoderReview,
    VaFinalAssessments,
    VaStatuses,
    VaSubmissions,
)
from app.models.va_submission_attachments import VaSubmissionAttachments

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

# readiness() reads whole submissions at a time; a caller passing a very long
# sid list is batched rather than issuing one unbounded IN (...).
READINESS_BATCH_SIZE = 500


@dataclass(frozen=True)
class AttachmentRecord:
    """Identity and local delivery metadata for one attachment row."""

    va_sid: str
    va_form_id: str
    storage_name: str
    local_path: str | None
    mime_type: str | None


# ---------------------------------------------------------------------------
# Record resolution
# ---------------------------------------------------------------------------

def _record_cache_key(storage_name: str) -> str:
    return f"att:{storage_name}"


def resolve_attachment_record(storage_name: str) -> AttachmentRecord | None:
    """Resolve an opaque storage_name to its owning submission and metadata.

    Only rows with ``exists_on_odk=True`` resolve. Cache entries written before
    ``va_sid`` was part of the record are treated as misses so ownership is
    always known before authorization runs.
    """
    cached = flask_cache.get(_record_cache_key(storage_name))
    if cached and cached.get("va_sid") and cached.get("va_form_id"):
        return AttachmentRecord(
            va_sid=cached["va_sid"],
            va_form_id=cached["va_form_id"],
            storage_name=storage_name,
            local_path=cached.get("local_path"),
            mime_type=cached.get("mime_type"),
        )

    row = db.session.execute(
        sa.select(
            VaSubmissionAttachments.va_sid,
            VaSubmissions.va_form_id,
            VaSubmissionAttachments.local_path,
            VaSubmissionAttachments.mime_type,
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
        local_path=row.local_path,
        mime_type=row.mime_type,
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


def present_attachment_files_by_submission(
    form_id: str,
    *,
    target_sids: list[str] | None = None,
) -> dict[str, set[str]]:
    """Bulk readiness read: deduplicated present attachment file paths per submission.

    Reads attachment rows once and resolves presence for each; no network calls.
    """
    app_data_root = current_app.config.get("APP_DATA")
    stmt = (
        sa.select(
            VaSubmissionAttachments.va_sid,
            VaSubmissionAttachments.local_path,
            VaSubmissionAttachments.storage_name,
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
        resolved_path = resolve_local_attachment_path(
            app_data_root=app_data_root,
            form_id=form_id,
            local_path=row["local_path"],
            storage_name=row["storage_name"],
        )
        if not resolved_path:
            continue
        present_files_by_sid.setdefault(row["va_sid"], set()).add(resolved_path)
    return present_files_by_sid


def is_attachment_present_for_form(va_form_id: str, filename: str) -> bool:
    """Visibility check used when no submission identity is available.

    Mirrors the historical render-layer rule: an ``.amr`` field is visible when
    its ``.mp3`` derivative is present under the form's media directory.
    """
    if filename.lower().endswith(".amr"):
        filename = filename[: -len(".amr")] + ".mp3"
    disk_path = os.path.join(current_app.config["APP_DATA"], va_form_id, "media", filename)
    return os.path.exists(disk_path)


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


def deliver_local_attachment(record: AttachmentRecord):
    """Stream a locally stored attachment after the caller has authorized it.

    Path guard keeps delivery under APP_DATA/<form_id>/media/. A missing file
    evicts the record cache and reports not-found.
    """
    if not record.local_path:
        abort(404)
    media_base = os.path.realpath(
        os.path.join(current_app.config["APP_DATA"], record.va_form_id, "media")
    )
    resolved = os.path.realpath(record.local_path)
    if not resolved.startswith(media_base + os.sep):
        abort(404)
    if not os.path.isfile(resolved):
        invalidate_attachment_record(record.storage_name)
        abort(404)

    cache_attachment_record(record)
    response = send_file(resolved, mimetype=safe_mime_type(record.mime_type))
    return apply_no_store_policy(response)
