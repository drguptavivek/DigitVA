"""Files uploaded for a web intake draft: audio narration, images, documents.

Policy: docs/policy/web-intake.md, "Attachments"; storage rules:
docs/policy/attachment-storage.md. Reference: docs/current-state/api-v1.md.

A file is uploaded while the interview is still a draft (no submission id yet),
so it waits in ``va_web_intake_attachments`` keyed by the draft and the UUID the
page generated for it. Submit copies the rows the answers name into
``va_submission_attachments`` (``link_to_submission``); the bytes are never
copied, both rows point at the same stored object.

Who may upload to a draft is not decided here: the caller passes a draft it got
from ``web_intake_service.get_draft`` (the one ownership predicate).
"""

from __future__ import annotations

import hashlib
import logging
import re
import uuid
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import db
from app.models import (
    VaDeathRegister,
    VaSubmissionAttachments,
    VaWebIntakeAttachment,
    VaWebIntakeDraft,
    VaWebIntakeDraftSection,
)
from app.services import attachment_service
from app.services import case_transition_service as cases
from app.services.attachment_store import AttachmentStoreError
from app.services.case_transition_service import WebIntakeError

log = logging.getLogger(__name__)

#: One file, in bytes (owner, 2026-10-06).
MAX_BYTES = 25 * 1024 * 1024
#: An ``.amr`` upload is converted by SoX in the request, so it is capped lower:
#: AMR is a 12 kbps speech codec, 5 MB is hours of recording.
AMR_MAX_BYTES = 5 * 1024 * 1024
#: Files one draft may hold: the form has about 37 attachment slots; the cap
#: only bounds a runaway client.
MAX_PER_DRAFT = 60
_CHUNK = 1024 * 1024
#: Enough of the head to recognise every accepted container.
_HEAD_BYTES = 64

#: The prefix of the page's client-local reference (``uri``), shared with
#: ``web_intake_service.ATTACHMENT_REFERENCE_PREFIX``.
REFERENCE_PREFIX = "who-va-attachment:"
#: The payload value of an uploaded file: ``<client attachment id><ext>``.
_FILENAME = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.[a-z0-9]{1,5}")


def detect_type(head: bytes) -> tuple[str, str] | None:
    """``(mime type, extension)`` of an accepted file from its leading bytes, or
    None. The extension and the ``Content-Type`` the browser sent are never
    consulted: they are hints a client controls.

    The accepted list is the owner's (2026-10-06): audio webm, wav, amr, mp3,
    m4a; images jpeg, png; PDF. An ISO base media file (``ftyp``) is accepted
    as m4a on its brand alone, which cannot tell an audio-only file from a
    video one; the serving headers (``nosniff``, an attachment type) are what
    keep such a file inert.
    """
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", ".jpg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", ".png"
    if head.startswith(b"%PDF-"):
        return "application/pdf", ".pdf"
    if head.startswith(b"#!AMR"):
        return "audio/amr", ".amr"
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "audio/wav", ".wav"
    if head.startswith(b"\x1a\x45\xdf\xa3") and b"webm" in head:
        return "audio/webm", ".webm"
    if head[4:8] == b"ftyp" and head[8:12] in _M4A_BRANDS:
        return "audio/mp4", ".m4a"
    if head.startswith(b"ID3") or (len(head) > 1 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0 and head[1] & 0x06 != 0):
        return "audio/mpeg", ".mp3"
    return None


_M4A_BRANDS = frozenset({b"M4A ", b"M4B ", b"mp42", b"mp41", b"isom", b"iso2", b"iso5", b"iso6", b"dash"})


def reference_id(value: object) -> uuid.UUID | None:
    """The client attachment id a draft answer's reference names, or None.

    The package's reference is an object ``{id, uri: "who-va-attachment:<id>",
    ...}``; the older string form is the prefixed id alone.
    """
    if isinstance(value, dict):
        value = value.get("id") or value.get("uri")
    if not isinstance(value, str):
        return None
    try:
        return uuid.UUID(value.removeprefix(REFERENCE_PREFIX))
    except ValueError:
        return None


def pending_filenames(draft_id: uuid.UUID, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    """``{client attachment id: filename}`` of the draft's uploaded files among *ids*."""
    if not ids:
        return {}
    rows = db.session.execute(
        sa.select(VaWebIntakeAttachment.client_attachment_id, VaWebIntakeAttachment.filename).where(
            VaWebIntakeAttachment.draft_id == draft_id,
            VaWebIntakeAttachment.client_attachment_id.in_(ids),
        )
    ).all()
    return {cid: filename for cid, filename in rows}


def get_upload(draft_id: uuid.UUID, client_attachment_id: uuid.UUID) -> VaWebIntakeAttachment | None:
    return db.session.get(VaWebIntakeAttachment, (draft_id, client_attachment_id))


def _read_head(stream) -> bytes:
    head = b""
    while len(head) < _HEAD_BYTES:
        chunk = stream.read(_HEAD_BYTES - len(head))
        if not chunk:
            break
        head += chunk
    return head


def _refuse_changed_upload(existing: VaWebIntakeAttachment, content_length: int | None, client_sha256: str | None) -> None:
    """409 when a retried id carries a different file: another size, or, when
    the client sent its checksum, another SHA-256."""
    if (content_length is not None and existing.size_bytes != content_length) or (
        client_sha256 is not None and existing.sha256 != client_sha256
    ):
        raise WebIntakeError("That attachment id already holds a different file.", 409, "attachment_id_conflict")


def _held_count(draft_id: uuid.UUID) -> int:
    return db.session.scalar(
        sa.select(sa.func.count()).select_from(VaWebIntakeAttachment).where(VaWebIntakeAttachment.draft_id == draft_id)
    )


def _discard_blob(local_path: str | None, form_id: str, storage_name: str) -> None:
    attachment_service.cleanup_superseded(stale_paths=[(local_path, None)], stale_objects=[(form_id, storage_name)])


def store_upload(
    draft: VaWebIntakeDraft, client_attachment_id: uuid.UUID, stream, content_length: int, client_sha256: str | None = None
) -> tuple[VaWebIntakeAttachment, bool]:
    """Store one uploaded file for an open *draft*; ``(row, created)``.

    Idempotent by ``client_attachment_id``: an id already stored returns its
    row (``created`` False) and stores nothing; a different size, or a
    different SHA-256 when the client sent *client_sha256* (lower-case hex),
    under the same id is 409 ``attachment_id_conflict``. The body is read in
    bounded chunks from *stream* and never held whole. Raises
    ``WebIntakeError``: 400 ``checksum_mismatch`` (the body is not what the
    client hashed), 409, 413 (over 25 MB, or an ``.amr`` over 5 MB), 415 for a
    type outside the list, 422 ``empty_attachment`` / ``audio_conversion_failed``
    / ``attachment_limit``, 503 when the store fails. The caller commits.

    The draft row is locked only for the final count and insert, so the
    per-draft cap holds under parallel uploads without holding a lock across
    a 25 MB body.
    """
    existing = get_upload(draft.draft_id, client_attachment_id)
    if existing is not None:
        _refuse_changed_upload(existing, content_length, client_sha256)
        return existing, False
    if content_length <= 0:
        raise WebIntakeError("The file is empty.", 422, "empty_attachment")
    if content_length > MAX_BYTES:
        raise WebIntakeError("The file is larger than 25 MB.", 413, "payload_too_large")
    # A fast refusal before the body is read; the authoritative count is below.
    if _held_count(draft.draft_id) >= MAX_PER_DRAFT:
        raise WebIntakeError("This interview already holds the most files it may.", 422, "attachment_limit")

    head = _read_head(stream)
    detected = detect_type(head)
    if detected is None:
        raise WebIntakeError(
            "Only audio (webm, wav, amr, mp3, m4a), images (jpeg, png) and PDF files are accepted.",
            415, "unsupported_media_type",
        )
    mime, ext = detected
    if ext == ".amr" and content_length > AMR_MAX_BYTES:
        raise WebIntakeError("An AMR recording may be at most 5 MB.", 413, "payload_too_large")
    filename = f"{client_attachment_id}{ext}"

    temp_path = attachment_service.new_ingest_temp_path(draft.form_id)
    digest = hashlib.sha256(head)
    total = len(head)
    try:
        with open(temp_path, "wb") as handle:
            handle.write(head)
            while True:
                chunk = stream.read(_CHUNK)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_BYTES:
                    raise WebIntakeError("The file is larger than 25 MB.", 413, "payload_too_large")
                digest.update(chunk)
                handle.write(chunk)
        if total != content_length:
            raise WebIntakeError("The upload ended before the whole file arrived.", 400, "invalid_request")
        if client_sha256 is not None and digest.hexdigest() != client_sha256:
            raise WebIntakeError("The file arrived changed; send it again.", 400, "checksum_mismatch")
    except BaseException:
        attachment_service.discard_ingest_temp_file(temp_path)
        raise

    now = datetime.now(UTC)
    sha256 = digest.hexdigest()
    try:
        ingested = attachment_service.ingest_download(
            va_sid=f"web-draft:{draft.draft_id}",
            va_form_id=draft.form_id,
            filename=filename,
            temp_path=temp_path,
            mime_type=mime,
            etag=sha256,
            downloaded_at=now,
        )
    except attachment_service.AmrConversionError as exc:
        raise WebIntakeError("The recording could not be converted.", 422, "audio_conversion_failed") from exc
    except AttachmentStoreError as exc:
        log.error("web intake attachment store failed | draft=%s", draft.draft_id, exc_info=True)
        raise WebIntakeError("The file could not be stored. Try again.", 503, "unavailable") from exc

    # Lock the draft row for the recount and the insert: parallel uploads (and
    # a discard) serialise here, for the length of two statements.
    locked = db.session.get(VaWebIntakeDraft, draft.draft_id, with_for_update=True, populate_existing=True)
    if locked.status != "draft":
        _discard_blob(ingested.local_path, draft.form_id, ingested.storage_name)
        raise WebIntakeError("This draft is no longer editable.", 409)
    if _held_count(draft.draft_id) >= MAX_PER_DRAFT:
        _discard_blob(ingested.local_path, draft.form_id, ingested.storage_name)
        raise WebIntakeError("This interview already holds the most files it may.", 422, "attachment_limit")

    row = VaWebIntakeAttachment(
        draft_id=draft.draft_id,
        client_attachment_id=client_attachment_id,
        filename=filename,
        storage_name=ingested.storage_name,
        local_path=ingested.local_path,
        store_state=ingested.store_state,
        mime_type=mime,
        size_bytes=total,
        sha256=sha256,
        created_at=now,
    )
    try:
        # A savepoint: a concurrent identical upload that committed first makes
        # this insert fail, and only this insert is rolled back.
        with db.session.begin_nested():
            db.session.add(row)
    except IntegrityError:
        _discard_blob(ingested.local_path, draft.form_id, ingested.storage_name)
        winner = get_upload(draft.draft_id, client_attachment_id)
        if winner is None:
            raise
        _refuse_changed_upload(winner, content_length, client_sha256)
        return winner, False
    log.info("web intake attachment stored | draft=%s | type=%s | bytes=%d", draft.draft_id, mime, total)
    return row, True


_BLOBS_TO_DELETE = "web_intake_blobs_to_delete"


def _delete_upload_rows(rows_and_forms: list[tuple[VaWebIntakeAttachment, str]]) -> None:
    """Delete the rows and queue their objects for ``delete_committed_blobs``
    (the discard path, where the caller's request commits).

    The objects wait in ``session.info`` and go only after the caller's
    commit, so a commit that fails leaves rows that still point at objects
    that still exist (and a rollback drops the queue). Flushes. The purge does
    not use this: it holds the case lock and removes objects before the commit
    (``_purge_batch``).
    """
    queue = db.session().info.setdefault(_BLOBS_TO_DELETE, [])
    for row, form_id in rows_and_forms:
        queue.append((row.local_path, form_id, row.storage_name))
        db.session.delete(row)
    db.session.flush()


def delete_committed_blobs() -> None:
    """Remove the objects ``_delete_upload_rows`` queued; call it right after
    the commit that deleted their rows. Both this and the purge remove an
    object through ``_discard_blob`` -> ``cleanup_superseded``, which still
    leaves an object any submission row holds and logs a failure (with the
    storage token) instead of raising: the object becomes an orphan that
    ``attachment integrity`` reports."""
    for local_path, form_id, storage_name in db.session().info.pop(_BLOBS_TO_DELETE, ()):
        _discard_blob(local_path, form_id, storage_name)


@sa.event.listens_for(Session, "after_soft_rollback")
def _drop_queued_blobs(session, previous_transaction):
    if previous_transaction.parent is None:
        session.info.pop(_BLOBS_TO_DELETE, None)


def delete_draft_uploads(draft: VaWebIntakeDraft) -> int:
    """Delete the files uploaded for *draft* that no submission holds, and
    their stored objects; returns how many. For a discarded draft: its files
    would otherwise sit in the store, personal data nobody can reach. A file a
    submission already links (same ``storage_name``) keeps its object. Flushes;
    the caller commits, then calls ``delete_committed_blobs``."""
    rows = db.session.scalars(
        sa.select(VaWebIntakeAttachment).where(VaWebIntakeAttachment.draft_id == draft.draft_id)
    ).all()
    _delete_upload_rows([(row, draft.form_id) for row in rows])
    return len(rows)


#: Owner decision 2026-10-06 (digitva-i9lb): uploads of an open draft untouched
#: this long, and uploads no answer of their draft references any more, go.
UPLOAD_RETENTION_DAYS = 30
#: Files per transaction, and transactions per run: a run deletes at most
#: ``PURGE_BATCH * PURGE_MAX_BATCHES`` files, the backlog goes on tomorrow.
PURGE_BATCH = 500
PURGE_MAX_BATCHES = 20
PURGE_ACTION = "draft_attachments_purged"
PURGE_REASON_IDLE = "idle_30d"
PURGE_REASON_UNREFERENCED = "unreferenced_30d"


def _candidates(cutoff: datetime, draft_ids: set[uuid.UUID] | None = None):
    """The expired uploads (see ``_purge_batch``), oldest first, at most
    ``PURGE_BATCH``, with the draft's form, case, owner and idle flag; limited
    to *draft_ids* when given. Index: ``ix_va_web_intake_attachments_created_at``."""
    up, draft = VaWebIntakeAttachment, VaWebIntakeDraft
    # ponytail: substring test on the section JSON, ~15 small sections per draft; a
    # reference nested in another structure still counts (keeps the file).
    referenced = sa.exists().where(
        VaWebIntakeDraftSection.draft_id == up.draft_id,
        sa.func.strpos(sa.cast(VaWebIntakeDraftSection.data, sa.Text), sa.cast(up.client_attachment_id, sa.Text)) > 0,
    )
    linked = sa.exists().where(VaSubmissionAttachments.storage_name == up.storage_name)
    idle = draft.updated_at < cutoff
    stmt = (
        sa.select(up, draft.form_id, draft.death_id, draft.user_id, idle)
        .join(draft, draft.draft_id == up.draft_id)
        .where(draft.status == "draft", up.created_at < cutoff, ~linked, sa.or_(idle, ~referenced))
        .order_by(up.created_at, up.draft_id, up.client_attachment_id)
        .limit(PURGE_BATCH)
        .execution_options(populate_existing=True)
    )
    if draft_ids is not None:
        stmt = stmt.where(draft.draft_id.in_(draft_ids))
    return stmt


def _lock_cases(case_ids: set[uuid.UUID]) -> dict[uuid.UUID, VaDeathRegister]:
    """Lock the cases among *case_ids* nobody else holds (``SKIP LOCKED``, in
    id order); a case in use is left to the next run."""
    if not case_ids:
        return {}
    return {
        d.death_id: d
        for d in db.session.scalars(
            sa.select(VaDeathRegister)
            .where(VaDeathRegister.death_id.in_(case_ids))
            .order_by(VaDeathRegister.death_id)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
    }


def _lock_drafts(draft_ids: set[uuid.UUID]) -> set[uuid.UUID]:
    """Lock the drafts among *draft_ids* nobody else holds; returns those."""
    if not draft_ids:
        return set()
    return set(db.session.scalars(
        sa.select(VaWebIntakeDraft.draft_id)
        .where(VaWebIntakeDraft.draft_id.in_(draft_ids))
        .order_by(VaWebIntakeDraft.draft_id)
        .with_for_update(skip_locked=True)
    ))


def _purge_batch(cutoff: datetime) -> int:
    """Delete up to ``PURGE_BATCH`` expired uploads in one transaction; returns
    the files deleted.

    A file is expired when it is older than *cutoff*, its draft is still open
    (``draft``), no submission row holds its object, and either the draft's
    last answer save is older than *cutoff* or no section of the draft names
    the file's id. Draft rows and answers are never touched; oldest first.

    Locks are taken in the order every case writer (save, submit, discard)
    uses: the case rows first, then the draft rows. Both are ``SKIP LOCKED``, so
    the purge never waits (it cannot deadlock) and leaves a case or draft in use
    to the next run. The candidates are then read again under the locks. Submit
    links a file to its submission under the same case lock, so with the lock
    held no link can appear: the purge removes each object (``_discard_blob``
    still keeps one a submission row holds), then deletes the rows and one
    audit row per draft, then commits. If the commit fails the rows remain, the
    next run selects them again and deletes them (an object already gone is
    tolerated), so no committed row ever points at a deleted object and no
    object is orphaned.
    """
    first = db.session.execute(_candidates(cutoff)).all()
    if not first:
        return 0
    deaths = _lock_cases({death_id for _row, _form, death_id, *_ in first if death_id})
    # A draft with no case has no case lock to take; its own row lock is all there is.
    lockable = {row.draft_id for row, _form, death_id, *_ in first if death_id is None or death_id in deaths}
    held = _lock_drafts(lockable)
    rows = db.session.execute(_candidates(cutoff, held)).all() if held else []
    if not rows:
        db.session.rollback()  # releases the locks taken
        return 0

    per_draft: dict[uuid.UUID, dict] = {}
    for row, form_id, death_id, user_id, is_idle in rows:
        entry = per_draft.setdefault(row.draft_id, {"death_id": death_id, "user_id": user_id, "idle": is_idle, "files": 0})
        entry["files"] += 1
        _discard_blob(row.local_path, form_id, row.storage_name)
        db.session.delete(row)
    db.session.flush()

    for draft_id, entry in per_draft.items():
        death = deaths.get(entry["death_id"])
        if death is None:
            # ponytail: no case, no audit table to write; the log is the record.
            log.info("web intake upload purge: draft without a case, no audit row | draft=%s | files=%d", draft_id, entry["files"])
            continue
        reason = PURGE_REASON_IDLE if entry["idle"] else PURGE_REASON_UNREFERENCED
        # The row needs an actor (the column is NOT NULL): the draft's interviewer.
        cases.record_system_action(
            death, actor_user_id=entry["user_id"], action=PURGE_ACTION, reason=f"{reason}: {entry['files']} file(s)",
        )
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return len(rows)


def purge_expired_uploads(now: datetime | None = None) -> dict[str, int]:
    """Delete web intake uploads past the retention (``UPLOAD_RETENTION_DAYS``):
    those of a draft untouched that long, and those no answer references any
    more once older than that. Bounded: ``PURGE_MAX_BATCHES`` batches of
    ``PURGE_BATCH``. Never deletes a file a submission holds or a draft.
    Commits per batch; a failed batch raises with earlier ones kept. Returns
    ``{"files": n, "batches": n}``; the caller logs counts only."""
    cutoff = (now or datetime.now(UTC)) - timedelta(days=UPLOAD_RETENTION_DAYS)
    files = batches = 0
    while batches < PURGE_MAX_BATCHES:
        deleted = _purge_batch(cutoff)
        if not deleted:
            break
        files += deleted
        batches += 1
        if deleted < PURGE_BATCH:
            break
    return {"files": files, "batches": batches}


def _blob_mime(row: VaWebIntakeAttachment) -> str:
    """The type of the stored object: an ``.amr`` upload is stored as its MP3."""
    return attachment_service.DERIVATIVE_MIME_TYPE if attachment_service.is_audio_attachment(row.filename) else row.mime_type


def serving_record(row: VaWebIntakeAttachment, va_form_id: str) -> attachment_service.AttachmentRecord:
    """The delivery record of an uploaded file, for ``deliver_legacy_media``
    (which, unlike ``deliver``, writes nothing to the record cache: the same
    token must later resolve to the submission that owns it)."""
    return attachment_service.AttachmentRecord(
        va_sid=f"web-draft:{row.draft_id}",
        va_form_id=va_form_id,
        storage_name=row.storage_name,
        filename=row.filename,
        local_path=row.local_path,
        mime_type=_blob_mime(row),
        source_mime_type=row.mime_type,
    )


def link_to_submission(va_sid: str, draft_id: uuid.UUID, payload: dict) -> int:
    """Give submission *va_sid* the uploaded files its *payload* names.

    The payload's attachment answers hold the uploaded files' filenames
    (``build_web_payload``); each becomes a ``va_submission_attachments`` row
    over the same stored object, ``exists_on_odk`` true (for a web form, "live";
    the only flag ``resolve_attachment_record`` resolves). Existing rows are
    left alone, so a revision that keeps a file changes nothing. Returns the
    number of files the payload names. Flushes; the caller commits.
    """
    names = {v for v in payload.values() if isinstance(v, str) and _FILENAME.fullmatch(v)}
    if not names:
        return 0
    rows = db.session.scalars(
        sa.select(VaWebIntakeAttachment).where(
            VaWebIntakeAttachment.draft_id == draft_id, VaWebIntakeAttachment.filename.in_(names)
        )
    ).all()
    for row in rows:
        values = {
            "va_sid": va_sid,
            "filename": row.filename,
            "local_path": row.local_path,
            "mime_type": _blob_mime(row),
            "etag": row.sha256,
            "exists_on_odk": True,
            "last_downloaded_at": row.created_at,
            "storage_name": row.storage_name,
            **attachment_service._ingest_state_values(
                filename=row.filename, mime_type=row.mime_type, etag=row.sha256,
                downloaded_at=row.created_at, store_state=row.store_state,
            ),
        }
        db.session.execute(pg_insert(VaSubmissionAttachments).values(**values).on_conflict_do_nothing())
    db.session.flush()
    return len(rows)
