"""Drafts: browser and phone drafts, their attachments, the browser submit. Part of the intake API package (``__init__``)."""
import uuid

from flask import jsonify, request
from flask_login import current_user
from sqlalchemy.exc import IntegrityError
from werkzeug.exceptions import HTTPException

from app import db, limiter, talisman
from app.decorators import role_required
from app.models import (
    VaDeathRegister,
    VaSubmissionPayloadVersion,
    VaSubmissions,
)
from app.routes.api.intake._common import _client_id, _refuse, _site_id, _stale_extra, bp, log
from app.routes.api.intake.uploads import _SHA256_HEX, _parse_upload_answers
from app.routes.api.request_helpers import (
    error,
    parse_body,
    request_project_id,
)
from app.services import attachment_service, training_scope
from app.services import consent_service as consent_svc
from app.services import intake_revision_access as revision_access
from app.services import web_intake_attachment_service as attachments_svc
from app.services import web_intake_service as intake_svc
from app.services.interview_intake_gate import check_refusal_transition

# ---------------------------------------------------------------------------
# Drafts
# ---------------------------------------------------------------------------


@bp.get("/drafts")
@role_required("interviewer")
def list_drafts():
    training_scope.resolve("interview")
    status = request.args.get("status", "draft") or None
    return jsonify({"drafts": intake_svc.serialize_drafts(intake_svc.list_drafts(current_user, status=status))})


@bp.post("/drafts")
@role_required("interviewer")
def start_draft():
    """Open (or return) the caller's draft of a case, 201. Without ``death_id``
    the phone's direct start may send ``client_draft_id`` (UUID): the draft is
    then the one ``POST /submissions`` with that id completes (so files PUT to
    it are on the submission); a repeat returns it with 200, another
    interviewer's or an uploaded id or another project/site/unit is 409."""
    p = parse_body()
    project_id = str(p.get("project_id") or "")
    site_id = str(p.get("site_id") or "")
    org_unit_id = p.get("org_unit_id") or None
    death_id = p.get("death_id") or None
    if p.get("client_draft_id") is not None and not death_id:
        client_draft_id = _client_id(p, "client_draft_id")
        if client_draft_id is None:
            return error("client_draft_id must be a UUID.", "invalid_request", 400)
        try:
            draft, created = intake_svc.start_attachment_draft(
                current_user, project_id=project_id, site_id=site_id, org_unit_id=org_unit_id,
                client_draft_id=client_draft_id,
            )
            db.session.commit()
        except IntegrityError:
            # A concurrent start with the same client_draft_id won the unique index.
            db.session.rollback()
            draft, created = intake_svc.start_attachment_draft(
                current_user, project_id=project_id, site_id=site_id, org_unit_id=org_unit_id,
                client_draft_id=client_draft_id,
            )
        return jsonify({"draft": intake_svc.serialize_draft(draft)}), 201 if created else 200
    # The browser's start (no client id): a direct start is a new start and
    # meets the collection gate; a registered case's interview never does.
    draft = intake_svc.start_draft(
        current_user, project_id=project_id, site_id=site_id, org_unit_id=org_unit_id, death_id=death_id,
        enforce_collection_gate=True,
    )
    db.session.commit()
    return jsonify({"draft": intake_svc.serialize_draft(draft)}), 201


@bp.get("/drafts/<draft_id>")
@role_required("interviewer", "interview_supervisor")
def get_draft(draft_id):
    """The caller's own draft, or the submitted draft of a case whose
    interview the caller may correct as a supervisor
    (``draft_reachable_by``: the case's current submission only)."""
    training_scope.resolve("interview")
    draft = revision_access.draft_reachable_by(current_user, draft_id)
    return jsonify(
        {
            "draft": intake_svc.serialize_draft(draft),
            "last_change": intake_svc.last_change(draft, current_user),
            "envelope": intake_svc.load_draft_envelope(draft),
            "prefill": draft.prefill or {},
            # The hash of the exact answers text held now (null for a browser
            # draft); a revision must start from these answers.
            "answers_sha256": draft.answers_sha256,
            # Attachment ids the server already holds; the phone shows them as
            # "Saved on server" instead of asking for a re-record.
            "server_attachments": attachments_svc.held_ids(draft.draft_id),
        }
    )


@bp.patch("/drafts/<draft_id>")
@role_required("interviewer")
def save_draft(draft_id):
    """Browser autosave. Optional ``if_updated_at``: the ``draft.updated_at`` of
    the last reply the page saw; a newer saved version (the phone's sync) is
    409 ``draft_stale`` (with ``updated_at`` and ``last_change``) and nothing
    is written. ``overwrite: true`` is the interviewer's "Use my answers"
    after one: it needs the current ``if_updated_at``, keeps the version it
    replaces as a ``replaced`` row and empties every saved section the body
    leaves out, so the page's answers replace the draft whole."""
    p = parse_body()
    draft = intake_svc.lock_draft_for_browser_write(intake_svc.get_draft(current_user, draft_id, require_open=True))
    overwrite = p.get("overwrite") is True
    if p.get("if_updated_at") is not None and intake_svc.draft_is_stale(draft, p["if_updated_at"]):
        return _refuse(intake_svc.SYNC_MESSAGE, "draft_stale", 409, **_stale_extra(draft))
    if p.get("resume_refused") is True and p.get("if_updated_at") is None:
        return _refuse("Reload the draft before changing the refusal decision.", "draft_stale", 409)
    if overwrite and p.get("if_updated_at") is None:
        return _refuse("Reload the draft before replacing it with your answers.", "draft_stale", 409,
                       **_stale_extra(draft))
    sections = p.get("sections") or {}
    if isinstance(sections, dict):
        if len(sections) > 128:
            raise intake_svc.WebIntakeError("Too many draft sections.", 422, "invalid_interview")
        death = db.session.get(VaDeathRegister, draft.death_id) if draft.death_id else None
        combined = {}
        for answers in sections.values():
            if isinstance(answers, dict):
                for name, value in answers.items():
                    if name not in combined or consent_svc._filled(value):
                        combined[name] = value
        allowed, _ = consent_svc.strip_unconsented_answers(
            project_id=draft.project_id, death=death, client_draft_id=draft.client_draft_id, answers=combined,
        )
        sections = {
            name: {key: value for key, value in answers.items() if key in allowed}
            if isinstance(answers, dict) else answers
            for name, answers in sections.items()
        }
        combined = intake_svc._answers_of(draft)
        for answers in sections.values():
            if isinstance(answers, dict):
                combined.update(answers)
        if death is not None and consent_svc.case_refusal_hold(death) and not (draft.meta or {}).get("caseRefusalHold"):
            raise intake_svc.WebIntakeError("Another interview holds this case after a refusal.", 409, "consent_refused")
        released = intake_svc.release_who_refusal_hold(
            draft, answers=combined, base_updated_at=p.get("if_updated_at"),
            resume_refused=p.get("resume_refused") is True,
        )
        if not check_refusal_transition(death_id=draft.death_id, client_draft_id=draft.client_draft_id,
                                        answers=combined):
            if not released:
                intake_svc.check_refusal_resume(
                    draft, base_updated_at=p.get("if_updated_at"), resume_refused=p.get("resume_refused") is True,
                )
        if overwrite:
            log.info("intake draft overwritten by the browser | draft=%s | user=%s | replaced_version_kept=%s",
                     draft.draft_id, current_user.user_id, bool(draft.sections))
            sections = intake_svc.prepare_browser_overwrite(draft, sections)
    written = intake_svc.save_draft_sections(
        draft,
        sections=sections,
        meta=p.get("meta") or None,
        current_section=p.get("current_section"),
        actor=current_user,
        resume_refused=p.get("resume_refused") is True,
    )
    db.session.commit()
    attachments_svc.delete_committed_blobs()
    return jsonify({"saved_sections": written, "draft": intake_svc.serialize_draft(draft)})


@bp.post("/drafts/sync")
@role_required("interviewer")
def sync_draft():
    """The phone's in-progress interview, into the caller's one open draft of
    the case (web-intake.md "Parallel interviews"). Body: ``project_id``,
    ``site_id``, ``org_unit_id``, ``death_id`` (required), ``client_draft_id``
    (UUID), ``answers_json`` + ``answers_sha256`` (as ``/submissions``),
    ``draft`` (envelope meta), ``savedAt`` and ``deviceClockAt`` (ISO 8601 with
    offset, required), ``base_updated_at`` (``draft.updated_at`` of the phone's
    last download or sync reply, null if never). Replies 200
    ``{draft, kept: incoming|server, conflict, answers_sha256, message,
    envelope}`` (``envelope`` only when ``kept`` is ``server``). A resend is a
    no-op with the same reply; 422 ``invalid_interview`` /
    ``answers_hash_*`` store nothing."""
    p = parse_body()
    try:
        client_draft_id = uuid.UUID(str(p.get("client_draft_id")))
    except ValueError:
        return error("client_draft_id must be a UUID.", "invalid_request", 400)
    site_id = _site_id(p)
    envelope = p.get("draft")
    if not isinstance(envelope, dict):
        return error("draft must be an object.", "invalid_interview", 422)
    project_id = request_project_id(p)
    data, answers_sha256, refusal = _parse_upload_answers(p)
    if refusal is not None:
        return refusal
    reply = intake_svc.sync_device_draft(
        current_user, project_id=project_id, site_id=site_id, org_unit_id=p.get("org_unit_id") or None,
        death_id=p.get("death_id") or None, client_draft_id=client_draft_id, envelope=envelope,
        data=data, answers_sha256=answers_sha256, saved_at=p.get("savedAt"),
        device_clock_at=p.get("deviceClockAt"), base_updated_at=p.get("base_updated_at"),
        resume_refused=p.get("resume_refused") is True,
    )
    db.session.commit()
    attachments_svc.delete_committed_blobs()
    return jsonify(reply)


@bp.post("/drafts/<draft_id>/discard")
@role_required("interviewer")
def discard_draft(draft_id):
    draft = intake_svc.get_draft(current_user, draft_id, require_open=True)
    intake_svc.discard_draft(draft, current_user)
    db.session.commit()
    attachments_svc.delete_committed_blobs()  # the files go only once the discard is committed
    return jsonify({"draft": intake_svc.serialize_draft(draft)})


# ---------------------------------------------------------------------------
# Attachments (audio narration, document images, files)
# ---------------------------------------------------------------------------


def _attachment_body(row, created):
    return {
        "attachment": {
            "id": str(row.client_attachment_id),
            "filename": row.filename,
            "mime_type": row.mime_type,
            "size": row.size_bytes,
            "created_at": row.created_at.isoformat(),
        },
        "created": created,
    }


@bp.put("/drafts/<draft_id>/attachments/<client_attachment_id>")
@role_required("interviewer")
@limiter.limit("120 per minute")
def put_attachment(draft_id, client_attachment_id):
    """Store one file for the caller's open draft: the raw body (send
    ``Content-Type: application/octet-stream``), at most ``MAX_BYTES`` (an AMR ``AMR_MAX_BYTES``),
    ``Content-Length`` required; optional ``X-Content-SHA256`` (hex) is checked
    against the body and, on a retried id, against the stored file. ``client_attachment_id`` is the UUID the page made for the file,
    the idempotency key: 201 ``{attachment, created: true}`` when stored, 200
    with the same record when already held (nothing stored again). The type is
    decided from the file's leading bytes (docs/policy/web-intake.md,
    "Attachments"). Errors: 404 a draft that is not the caller's, 409 a draft
    no longer open or ``attachment_id_conflict``, 411 ``length_required``, 413
    ``payload_too_large``, 415 ``unsupported_media_type``, 422
    ``empty_attachment`` / ``attachment_limit`` / ``audio_conversion_failed``,
    400 ``checksum_mismatch``, 503 ``unavailable``."""
    try:
        cid = uuid.UUID(client_attachment_id)
    except ValueError:
        return error("client_attachment_id must be a UUID.", "invalid_request", 400)
    claimed = request.headers.get("X-Content-SHA256")
    if claimed is not None and not _SHA256_HEX.fullmatch(claimed.strip()):
        return error("X-Content-SHA256 must be 64 hex characters.", "invalid_request", 400)
    draft = intake_svc.get_draft(current_user, draft_id, require_open=True)
    row, created = attachments_svc.store_upload(
        draft, cid, request.stream, request.content_length, claimed.strip().lower() if claimed else None
    )
    db.session.commit()
    return jsonify(_attachment_body(row, created)), 201 if created else 200


@bp.get("/drafts/<draft_id>/attachments/<client_attachment_id>")
# The page reads this with fetch().blob(); if the URL is ever opened as a
# document it must be inert: no scripts, no framing. Talisman sets the
# header after the view runs, so it is declared here, not on the response.
@talisman(content_security_policy={"sandbox": "", "default-src": "'none'"})
@role_required("interviewer")
@limiter.limit("300 per minute")
def get_attachment(draft_id, client_attachment_id):
    """The bytes of a file stored for the caller's own draft (so the form can
    show a file the device no longer holds). The draft may be any status of the
    caller's; the response is never cached. 404 for another interviewer's
    draft or an unknown file."""
    training_scope.resolve("interview")
    try:
        cid = uuid.UUID(client_attachment_id)
    except ValueError:
        return error("Attachment not found.", "not_found", 404)
    draft = intake_svc.get_draft(current_user, draft_id)
    row = attachments_svc.get_upload(draft.draft_id, cid)
    if row is None:
        return error("Attachment not found.", "not_found", 404)
    try:
        response = attachment_service.deliver_legacy_media(attachments_svc.serving_record(row, draft.form_id))
    except HTTPException as exc:
        if exc.code == 404:
            return error("Attachment not found.", "not_found", 404)
        raise
    # A PDF is downloaded, never rendered in the page's origin.
    if row.mime_type == "application/pdf":
        response.headers["Content-Disposition"] = f'attachment; filename="{row.filename}"'
    return response


def _validation_err(va_sid):
    """The server's re-derived diagnostic of the submission's active payload
    (beads digitva-cal.2), never blocking: surfaced on a submit so a field
    problem is debuggable, not just logged. No answer value is ever in it."""
    submission = db.session.get(VaSubmissions, va_sid)
    version = db.session.get(VaSubmissionPayloadVersion, submission.active_payload_version_id)
    return version.validation_err if version else []


def _correction_reply(draft, reply):
    """The submit reply when a completion corrected the interview *draft*
    (the submitted draft that holds the case's submission); commits."""
    validation_err = _validation_err(draft.va_sid)
    db.session.commit()
    return jsonify(
        {
            "va_sid": draft.va_sid,
            "draft": intake_svc.serialize_draft(draft),
            "superseded": False,
            "validation_err": validation_err,
            "kept": reply["kept"],
            "locked": reply["locked"],
            "can_code_now": intake_svc.can_code_now(current_user, draft),
        }
    )


@bp.post("/drafts/<draft_id>/submit")
@role_required("interviewer")
def submit_draft(draft_id):
    p = parse_body()
    draft = intake_svc.get_draft(current_user, draft_id)
    completion = p.get("completion")
    if isinstance(completion, dict) and isinstance(completion.get("data"), dict):
        # Every branch below stores these answers; the browser cannot take a
        # consent yet (digitva-athy), so only one on file can cover them.
        consent_svc.apply_interview_consent(
            current_user, project_id=draft.project_id,
            death=db.session.get(VaDeathRegister, draft.death_id) if draft.death_id else None,
            client_draft_id=draft.client_draft_id, consent=None, answers=completion["data"], channel="web",
        )
        if check_refusal_transition(death_id=draft.death_id, client_draft_id=draft.client_draft_id,
                                    answers=completion["data"]):
            consent_svc.check_refusal_answers(completion["data"])
    if draft.status == "submitted":
        if (draft.meta or {}).get("interviewOutcome") == "refused":
            return _refuse("A submitted refusal cannot be changed here.", "consent_refused", 422)
        # A stale tab, or a second completion of an interview the phone or
        # this page already submitted: the later completion is a correction
        # (last completed version wins), decided before the draft write lock,
        # which refuses anything that is not an open draft.
        reply = intake_svc.resubmit_browser_draft(current_user, draft, completion=p.get("completion") or {})
        return _correction_reply(draft, reply)
    draft = intake_svc.lock_draft_for_browser_write(intake_svc.get_draft(current_user, draft_id, require_open=True))
    # Same stale-tab guard as autosave: a tab that missed the phone's newer
    # version must not submit its own silently.
    if p.get("if_updated_at") is not None and intake_svc.draft_is_stale(draft, p["if_updated_at"]):
        return _refuse(intake_svc.SYNC_MESSAGE, "draft_stale", 409, **_stale_extra(draft))
    if isinstance(completion, dict) and isinstance(completion.get("data"), dict):
        if not check_refusal_transition(death_id=draft.death_id, client_draft_id=draft.client_draft_id,
                                        answers=completion["data"]):
            intake_svc.check_refusal_resume(
                draft, base_updated_at=p.get("if_updated_at"), resume_refused=p.get("resume_refused") is True,
            )
    if (str(intake_svc._answers_of(draft).get("Id10013") or "").lower() == "no"
            and isinstance(completion, dict) and isinstance(completion.get("data"), dict)
            and str(completion["data"].get("Id10013") or "").lower() != "no"):
        return _refuse("Record the new consent decision before resuming the interview.", "consent_refused", 422)
    # The case's winner is the caller's own earlier draft: this completion is a
    # correction of it (decided under the case lock), not a teammate's copy.
    folded = intake_svc.fold_into_own_submission(current_user, draft, completion=p.get("completion") or {})
    if folded is not None:
        return _correction_reply(*folded)
    submission = intake_svc.submit_draft(draft, current_user, completion=p.get("completion") or {})
    if submission is None:
        # A teammate's complete submission won: this copy is kept, not routed.
        # A refused copy's uploads were queued for deletion; remove them after
        # the commit (objects another submission row holds are kept).
        db.session.commit()
        attachments_svc.delete_committed_blobs()
        return jsonify(
            {"va_sid": None, "draft": intake_svc.serialize_draft(draft), "superseded": True, "validation_err": None,
             "can_code_now": False}
        )
    validation_err = _validation_err(submission.va_sid)
    db.session.commit()
    attachments_svc.delete_committed_blobs()
    return jsonify(
        {
            "va_sid": submission.va_sid,
            "draft": intake_svc.serialize_draft(draft),
            "superseded": False,
            "validation_err": validation_err,
            "can_code_now": intake_svc.can_code_now(current_user, draft),
        }
    ), 201

