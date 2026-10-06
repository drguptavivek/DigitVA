"""Web intake for every client (docs/policy/api-v1.md), either credential.

``/api/v1/intake``: cases, death register, drafts, offline uploads and the
supervisor list. Thin handlers over ``app.services.web_intake_service``.
Access is decided per request from the caller's grants (``role_required``,
and per case in the service); the browser cookie needs ``X-CSRFToken`` on a
state change, a device bearer token needs none. Errors are
``{"error", "code"}``. Reference: docs/current-state/device-collection-api.md.
Policy: docs/policy/web-intake.md, docs/policy/field-data-collection.md.
"""
import hashlib
import hmac
import json
import re
import uuid
from contextlib import contextmanager

from flask import Blueprint, g, jsonify, request, url_for
from flask_login import current_user
from sqlalchemy.exc import IntegrityError
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge

from app import db, limiter, talisman
from app.decorators import role_required
from app.models import AuthDevice, VaSubmissionPayloadVersion, VaSubmissions
from app.routes.api.request_helpers import (
    error,
    intake_error,
    interviewer_context,
    parse_body,
    request_project_id,
    require_project,
)
from app.services import case_transition_service as case_svc
from app.services import device_auth_service as devices
from app.services import attachment_service
from app.services import interview_send_back_service as send_back_svc
from app.services import web_intake_attachment_service as attachments_svc
from app.services import web_intake_service as intake_svc
from app.services.authz.actions import DEATH_REGISTERING_ROLES

bp = Blueprint("intake_api", __name__)

#: Request body caps: one interview upload; the outstanding-work report (up
#: to OUTSTANDING_MAX_IDS case ids, draft UUIDs and registration UUIDs, about
#: 150 KB at worst); every other (small) call. Draft saves and submits are
#: bounded by the service's answer checks, not here.
SUBMISSION_MAX_BYTES = 2 * 1024 * 1024
REPORT_MAX_BYTES = 256 * 1024
BODY_MAX_BYTES = 16 * 1024
#: One attachment's raw body (``put_attachment``): the owner's 25 MB per file.
ATTACHMENT_MAX_BYTES = attachments_svc.MAX_BYTES
_UNCAPPED = frozenset({"save_draft", "submit_draft"})

#: The register form's fields.
_REGISTER_FIELDS = intake_svc.REGISTER_FIELDS


def _body_limit():
    endpoint = (request.endpoint or "").rsplit(".", 1)[-1]
    if endpoint in _UNCAPPED:
        return None
    if endpoint in ("submit_interview", "sync_draft", "revise_submission"):
        limit = SUBMISSION_MAX_BYTES
    elif endpoint == "report_outstanding":
        limit = REPORT_MAX_BYTES
    elif endpoint == "put_attachment":
        limit = ATTACHMENT_MAX_BYTES
    else:
        limit = BODY_MAX_BYTES
    request.max_content_length = limit
    return limit


@bp.before_request
def _refuse_oversized_body():
    limit = _body_limit()
    if limit is not None and request.content_length is not None and request.content_length > limit:
        return error("The request body is too large.", "payload_too_large", 413)
    if request.endpoint and request.endpoint.endswith(".put_attachment") and request.content_length is None:
        # A file's size must be declared: the cap is checked before a byte is read.
        return error("Content-Length is required.", "length_required", 411)
    return None


@bp.after_request
def _no_store(response):
    # Intake carries identifiers and questionnaire answers, errors included.
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.errorhandler(RequestEntityTooLarge)
def _too_large(_exc):
    return error("The request body is too large.", "payload_too_large", 413)


@bp.errorhandler(devices.DeviceAuthError)
def _project_or_client_error(exc):
    db.session.rollback()
    return error(str(exc), exc.code, exc.status_code)


@bp.errorhandler(intake_svc.WebIntakeError)
def _intake_error(exc):
    db.session.rollback()
    return intake_error(exc)


def _client_id(p: dict, name: str) -> uuid.UUID | None:
    """The client-generated idempotency id, None when the request has none (a
    browser call); malformed is 400."""
    if p.get(name) in (None, ""):
        return None
    try:
        return uuid.UUID(str(p.get(name)))
    except ValueError:
        raise devices.DeviceAuthError(f"{name} must be a UUID.", "invalid_request", 400) from None


@contextmanager
def _content_refusals(code):
    """A content refusal (400) from the intake service always answers 422
    *code*, with or without a client id: the same rule for every client (the
    app reopens an offline item for editing, a page shows the message).
    Malformed requests stay 400 ``invalid_request``."""
    try:
        yield
    except intake_svc.WebIntakeError as exc:
        if exc.status_code != 400:
            raise
        raise devices.DeviceAuthError(str(exc), code, 422) from None


def _site_id(p: dict) -> str:
    site_id = p.get("site_id")
    if not isinstance(site_id, str) or not site_id.strip():
        raise devices.DeviceAuthError("site_id is required.", "invalid_request", 400)
    return site_id.strip()


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------


@bp.get("/cases")
@role_required("interviewer")
@limiter.limit("120 per minute")
def list_cases():
    """Team cases in the caller's interviewer scope (the worklist):
    ``web_intake_service.worklist_page``. Query: ``project_id`` (optional
    filter), ``mine``, ``state``, ``limit``, ``cursor``. The app downloads its
    active cases with ``state=`` and then each case's detail."""
    project_id = request_project_id(required=False)
    return jsonify(intake_svc.worklist_page(current_user, request.args, project_id=project_id, context=interviewer_context()))


def _reporter_only() -> bool:
    """The caller is a death_reporter and no interviewer (an interview
    supervisor or data manager correcting a death keeps the full body)."""
    return current_user.is_death_reporter() and not current_user.is_interviewer()


def _reporter_view(death) -> bool:
    """Whether the reply about *death* is the reporter's registration-only
    shape: the caller holds a death_reporter grant and no interviewer grant
    of theirs reaches this case (so a both-roles user gets the interview's
    prefill and links only where they interview)."""
    return current_user.is_death_reporter() and not intake_svc.interviewer_reaches(current_user, death)


def _case_body(death, unit_name, my_draft_id, other_draft_started_at=None, my_submission=False,
               other_complete_interview=False, ready_for_coding=False) -> dict:
    """The case with its full contact details (``serialize_case_detail``), this
    API's links, and the ``prefill`` an interview started offline needs, only
    when the caller may start or resume the interview (``case_prefill``);
    otherwise the key is absent."""
    body = intake_svc.serialize_case_detail(
        current_user, death, unit_name, my_draft_id, other_draft_started_at, my_submission,
        other_complete_interview, ready_for_coding,
    )
    if _reporter_view(death):
        # A death_reporter registers and corrects; the interview, the contact
        # attempts and the visit are not theirs, so no prefill, no link to a
        # route that answers 403, and nothing about other interviewers' drafts
        # (digitva-t6q).
        for key in ("other_draft_active", "other_draft_started_at"):
            body.pop(key, None)
        body["links"] = {"update": url_for(".update_death", death_id=death.death_id)}
        return body
    prefill = intake_svc.case_prefill(current_user, death, my_draft_id)
    if prefill is not None:
        body["prefill"] = prefill
    links = {
        "self": url_for(".case_detail", death_id=death.death_id),
        "attempts": url_for(".log_attempt", death_id=death.death_id),
        "visit": url_for(".set_visit", death_id=death.death_id),
        "start_interview": url_for(".start_draft"),
    }
    if my_draft_id:
        links["form"] = url_for("intake.form_page", draft_id=my_draft_id)
    body["links"] = links
    return body


def _case_reply(death, status=200):
    """The one reply of every single-case action: ``{"case": <detail>}``."""
    return jsonify({"case": _case_body(*intake_svc.case_row(current_user, death))}), status


@bp.get("/cases/<death_id>")
@role_required("interviewer")
# A device downloads its active cases one detail call each after the list, so
# the budget covers a large worklist; each call is one indexed case read
# (digitva-p6fs.33).
@limiter.limit("600 per minute")
def case_detail(death_id):
    """One case with its full contact details (and prefill, when the caller may
    start or resume it), visible exactly as
    the worklist would list it (any project of the caller's, any state);
    otherwise 404. Starting or resuming the interview is
    ``POST links.start_interview`` with the case's project, site and id."""
    row = intake_svc.get_case_detail(current_user, death_id, context=interviewer_context())
    return jsonify({"case": _case_body(*row)})


@bp.get("/cases/<death_id>/possible-duplicates")
@role_required("interviewer")
def possible_duplicates(death_id):
    """Cases in the caller's reach that may be the same death (a warning;
    never blocks submit, never merges). Out-of-scope ids read as 404."""
    death = intake_svc.get_death(current_user, death_id)
    return jsonify({"possible_duplicates": intake_svc.possible_duplicates(current_user, death)})


@bp.post("/cases/<death_id>/flags")
@role_required("interviewer")
def flag_case(death_id):
    """Flag a case as a possible duplicate or for cancellation (a supervisor
    confirms or rejects it). Body: ``kind``, ``reason``, ``duplicate_of``."""
    p = parse_body()
    death = intake_svc.flag_death(
        current_user,
        death_id,
        kind=str(p.get("kind") or ""),
        reason=p.get("reason") if isinstance(p.get("reason"), str) else None,
        duplicate_of=p.get("duplicate_of") or None,
    )
    db.session.commit()
    return _case_reply(death)


@bp.post("/cases/<death_id>/visit")
@role_required("interviewer")
def set_visit(death_id):
    """Set (or clear, with ``null``) the case's next visit. Idempotent by
    value, so no client id: a resend sets the same date. Body:
    ``next_visit_at`` (ISO date-time with timezone)."""
    p = parse_body()
    with _content_refusals("invalid_visit"):
        death = intake_svc.set_visit(current_user, death_id, next_visit_at=p.get("next_visit_at"))
    db.session.commit()
    return _case_reply(death)


@bp.post("/cases/<death_id>/attempts")
@role_required("interviewer")
def log_attempt(death_id):
    """Log a contact attempt. Body: ``outcome``, optional ``next_visit_at``,
    optional ``client_attempt_id`` (UUID): an offline attempt is idempotent on
    it, a resend returns the case with 200 and logs nothing."""
    p = parse_body()
    client_attempt_id = _client_id(p, "client_attempt_id")
    if client_attempt_id is not None:
        existing = intake_svc.find_device_attempt(current_user, death_id, client_attempt_id)
        if existing is not None:
            return _case_reply(existing)
    try:
        with _content_refusals("invalid_attempt"):
            death = intake_svc.log_contact_attempt(
                current_user, death_id, outcome=str(p.get("outcome") or ""),
                next_visit_at=p.get("next_visit_at"), client_attempt_id=client_attempt_id,
            )
        db.session.commit()
    except IntegrityError:
        # A concurrent resend of the same client_attempt_id won the unique index.
        db.session.rollback()
        existing = intake_svc.find_device_attempt(current_user, death_id, client_attempt_id) if client_attempt_id else None
        if existing is None:
            raise
        return _case_reply(existing)
    return _case_reply(death, 201)


@bp.post("/cases/<death_id>/pause")
@role_required("interviewer")
def pause_interview(death_id):
    """Pause an in-progress interview. Body: ``reason`` (a code), optional
    ``next_visit_at``. Resume is ``POST /drafts`` with the case."""
    p = parse_body()
    death = intake_svc.pause_interview(
        current_user, death_id, reason=str(p.get("reason") or ""), next_visit_at=p.get("next_visit_at"),
    )
    db.session.commit()
    return _case_reply(death)


# ---------------------------------------------------------------------------
# Death register
# ---------------------------------------------------------------------------


@bp.get("/deaths")
@role_required("interviewer", "death_reporter")
def list_deaths():
    """The death register of one project-site (an interviewer: ``project_id``
    and ``site_id`` required), or, for a death_reporter without interviewer
    rights, the deaths they registered across their reach: optional
    ``project_id``, ``site_id``, ``limit``, ``cursor``; replies ``{"deaths",
    "next_cursor"}`` (``web_intake_service.reported_deaths_page``). A user who
    holds both roles asks for that list with ``registered=mine``."""
    registered = request.args.get("registered")
    if registered not in (None, "", "mine"):
        return error("registered must be mine.", "invalid_request", 400)
    if _reporter_only() or (registered == "mine" and current_user.is_death_reporter()):
        return jsonify(intake_svc.reported_deaths_page(current_user, request.args))
    project_id = request.args.get("project_id", "")
    site_id = request.args.get("site_id", "")
    status = request.args.get("status") or None
    if not project_id or not site_id:
        return error("project_id and site_id are required.", "invalid_request", 400)
    deaths = intake_svc.list_deaths(current_user, project_id=project_id, site_id=site_id, status=status)
    return jsonify({"deaths": [intake_svc.serialize_death(d) for d in deaths]})


@bp.post("/deaths")
@role_required("interviewer", "death_reporter")
def register_death():
    """Register a death (an interviewer or a death_reporter). Body: ``project_id``, ``site_id``, ``org_unit_id`` and
    the register form's fields, optional ``client_death_id`` (UUID): an offline
    registration is idempotent on it, a resend returns the same case with 200.
    Replies ``{"case": <detail>}``, as ``GET /cases/<id>``."""
    p = parse_body()
    client_death_id = _client_id(p, "client_death_id")
    site_id = _site_id(p)
    project_id = request_project_id(p, roles=DEATH_REGISTERING_ROLES)

    if client_death_id is not None:
        existing = intake_svc.find_device_registration(current_user, project_id, client_death_id)
        if existing is not None:
            return _case_reply(existing)
    try:
        with _content_refusals("invalid_registration"):
            if any(isinstance(p.get(k), (dict, list)) for k in _REGISTER_FIELDS):
                raise intake_svc.WebIntakeError("Registration fields must be text or numbers.")
            death = intake_svc.register_death(
                current_user,
                project_id=project_id,
                site_id=site_id,
                org_unit_id=p.get("org_unit_id") or None,
                client_death_id=client_death_id,
                **{k: p.get(k) for k in _REGISTER_FIELDS},
            )
        db.session.commit()
    except IntegrityError:
        # A concurrent resend of the same client_death_id won the unique index.
        db.session.rollback()
        existing = (
            intake_svc.find_device_registration(current_user, project_id, client_death_id)
            if client_death_id else None
        )
        if existing is None:
            raise
        return _case_reply(existing)
    return _case_reply(death, 201)


@bp.patch("/deaths/<death_id>")
@role_required("interviewer", "interview_supervisor", "data_manager", "death_reporter")
def update_death(death_id):
    """Correct a registered death until an interview of it is completed. Body:
    only the register form's fields to change (an unknown key is 422), optional ``if_updated_at`` (the
    ``updated_at`` of the last reply seen; a newer one is 409 ``death_stale``).
    Replies ``{"case": <detail>}``. 404 out of reach; 409 ``case_completed`` /
    ``details_pending``; 422 ``invalid_death``."""
    p = parse_body()
    # Every other key goes on: the service refuses an unknown field by name.
    changes = {k: v for k, v in p.items() if k != "if_updated_at"}
    with _content_refusals("invalid_death"):
        if any(isinstance(v, (dict, list)) for v in changes.values()):
            raise intake_svc.WebIntakeError("Fields must be text or numbers.")
        death = intake_svc.update_death(current_user, death_id, changes, if_updated_at=p.get("if_updated_at"))
    db.session.commit()
    return _case_reply(death)


# ---------------------------------------------------------------------------
# Drafts
# ---------------------------------------------------------------------------


@bp.get("/drafts")
@role_required("interviewer")
def list_drafts():
    status = request.args.get("status", "draft") or None
    return jsonify({"drafts": [intake_svc.serialize_draft(d) for d in intake_svc.list_drafts(current_user, status=status)]})


@bp.post("/drafts")
@role_required("interviewer")
def start_draft():
    p = parse_body()
    draft = intake_svc.start_draft(
        current_user,
        project_id=str(p.get("project_id") or ""),
        site_id=str(p.get("site_id") or ""),
        org_unit_id=p.get("org_unit_id") or None,
        death_id=p.get("death_id") or None,
    )
    db.session.commit()
    return jsonify({"draft": intake_svc.serialize_draft(draft)}), 201


@bp.get("/drafts/<draft_id>")
@role_required("interviewer")
def get_draft(draft_id):
    draft = intake_svc.get_draft(current_user, draft_id)
    return jsonify(
        {
            "draft": intake_svc.serialize_draft(draft),
            "envelope": intake_svc.load_draft_envelope(draft),
            "prefill": draft.prefill or {},
            # The hash of the exact answers text held now (null for a browser
            # draft); a revision must start from these answers.
            "answers_sha256": draft.answers_sha256,
        }
    )


@bp.patch("/drafts/<draft_id>")
@role_required("interviewer")
def save_draft(draft_id):
    """Browser autosave. Optional ``if_updated_at``: the ``draft.updated_at`` of
    the last reply the page saw; a newer saved version (the phone's sync) is
    409 ``draft_stale`` and nothing is written."""
    p = parse_body()
    draft = intake_svc.lock_draft_for_browser_write(intake_svc.get_draft(current_user, draft_id, require_open=True))
    if p.get("if_updated_at") is not None and intake_svc.draft_is_stale(draft, p["if_updated_at"]):
        return error(intake_svc.SYNC_MESSAGE, "draft_stale", 409)
    written = intake_svc.save_draft_sections(
        draft,
        sections=p.get("sections") or {},
        meta=p.get("meta") or None,
        current_section=p.get("current_section"),
        actor=current_user,
    )
    db.session.commit()
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
    )
    db.session.commit()
    return jsonify(reply)


@bp.post("/drafts/<draft_id>/discard")
@role_required("interviewer")
def discard_draft(draft_id):
    draft = intake_svc.get_draft(current_user, draft_id, require_open=True)
    intake_svc.discard_draft(draft, current_user)
    db.session.commit()
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
    ``Content-Type: application/octet-stream``), at most 25 MB (an AMR 5 MB),
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
    if draft.status == "submitted":
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
        return error(intake_svc.SYNC_MESSAGE, "draft_stale", 409)
    # The case's winner is the caller's own earlier draft: this completion is a
    # correction of it (decided under the case lock), not a teammate's copy.
    folded = intake_svc.fold_into_own_submission(current_user, draft, completion=p.get("completion") or {})
    if folded is not None:
        return _correction_reply(*folded)
    submission = intake_svc.submit_draft(draft, current_user, completion=p.get("completion") or {})
    if submission is None:
        # A teammate's complete submission won: this copy is kept, not routed.
        db.session.commit()
        return jsonify(
            {"va_sid": None, "draft": intake_svc.serialize_draft(draft), "superseded": True, "validation_err": None,
             "can_code_now": False}
        )
    validation_err = _validation_err(submission.va_sid)
    db.session.commit()
    return jsonify(
        {
            "va_sid": submission.va_sid,
            "draft": intake_svc.serialize_draft(draft),
            "superseded": False,
            "validation_err": validation_err,
            "can_code_now": intake_svc.can_code_now(current_user, draft),
        }
    ), 201


# ---------------------------------------------------------------------------
# Offline upload
# ---------------------------------------------------------------------------


_SHA256_HEX = re.compile(r"[0-9a-fA-F]{64}")


def _parse_upload_answers(p):
    """The upload's answers and their hash, or an error reply.

    ``answers_json`` is the exact text the app hashed; it is hashed as
    received and only then parsed, so the stored hash is of the bytes the
    app meant to send. Returns ``(data, sha256_hex, None)`` or
    ``(None, None, reply)``."""
    answers_json, claimed = p.get("answers_json"), p.get("answers_sha256")
    if not isinstance(answers_json, str) or not isinstance(claimed, str) or not _SHA256_HEX.fullmatch(claimed):
        return None, None, error(
            "answers_json (the answers as JSON text) and answers_sha256 (64 hex characters) are required.",
            "answers_hash_required", 422,
        )
    raw = answers_json.encode("utf-8", "surrogatepass")
    if len(raw) > intake_svc.DEVICE_ANSWERS_MAX_BYTES:
        return None, None, error("answers_json is too large.", "invalid_interview", 422)
    digest = hashlib.sha256(raw).hexdigest()
    if not hmac.compare_digest(digest, claimed.lower()):
        return None, None, error("answers_sha256 does not match answers_json.", "answers_hash_invalid", 422)
    try:
        data = json.loads(answers_json)
    except (ValueError, RecursionError):
        data = None
    if not isinstance(data, dict):
        return None, None, error("answers_json must be a JSON object of answers.", "invalid_interview", 422)
    try:
        intake_svc.check_device_answers(data)
    except intake_svc.WebIntakeError as exc:
        return None, None, intake_error(exc)
    return data, digest, None


def _upload_reply(draft, *, kept, received_sha256, locked, status):
    """The upload result (``serialize_device_upload``, the coder version's
    hash in ``answers_sha256``) with whose answers the coder has (``kept``:
    ``incoming`` or ``server``), the hash the server received (the app deletes
    its copy when it equals what it sent) and whether coding is final or the
    case closed (``locked``), and ``can_code_now`` (a self-coding project's
    coder may code this case now: ``POST /coding/submissions/<va_sid>/code-now``)."""
    body = {
        **intake_svc.serialize_device_upload(draft), "kept": kept, "received_sha256": received_sha256, "locked": locked,
        "can_code_now": intake_svc.can_code_now(current_user, draft),
    }
    return jsonify(body), status


@bp.post("/submissions")
@role_required("interviewer")
def submit_interview():
    """One completed interview, idempotent on ``client_draft_id``. The last
    completed version of the interviewer's own interview is the coder's
    (docs/policy/web-intake.md "Parallel interviews"): a resend with the same
    ``answers_sha256`` returns the first result with 200; one with other
    answers, or a second upload of a case the caller already submitted,
    becomes the coder's version when its completion time is not older, else
    it is kept as history. Never a hash conflict. Reply: the upload result
    plus ``kept`` (``incoming`` or ``server``), ``received_sha256`` and
    ``locked`` (coding final or case closed). A bearer request records its
    device on the interview; a cookie request has none."""
    p = parse_body()
    try:
        client_draft_id = uuid.UUID(str(p.get("client_draft_id")))
    except ValueError:
        return error("client_draft_id must be a UUID.", "invalid_request", 400)
    site_id = _site_id(p)
    envelope = p.get("draft")
    completion = p.get("completion")
    if not isinstance(completion, dict):
        # The package's completion result carries valid/issues beside data.
        completion = envelope if isinstance(envelope, dict) else {}
    if not isinstance(envelope, dict):
        return error("draft must be an object.", "invalid_interview", 422)

    project_id = request_project_id(p)
    data, answers_sha256, refusal = _parse_upload_answers(p)
    if refusal is not None:
        return refusal
    try:
        intake_svc.check_device_times(envelope)
    except intake_svc.WebIntakeError as exc:
        return error(str(exc), "invalid_interview", 422)

    def resend(existing):
        # The same hash is the first result again; other answers are a later
        # version of the interview.
        if existing.answers_sha256 == answers_sha256:
            closed = existing.status == "superseded"
            return _upload_reply(
                existing, kept="server" if closed else "incoming", received_sha256=answers_sha256, locked=closed, status=200
            )
        kept, locked = intake_svc.resubmit_device_interview(
            current_user, existing, envelope=envelope, data=data, answers_sha256=answers_sha256, completion=completion,
        )
        db.session.commit()
        return _upload_reply(existing, kept=kept, received_sha256=answers_sha256, locked=locked, status=200)

    existing = intake_svc.find_device_upload(current_user, client_draft_id)
    if existing is not None:
        return resend(existing)
    session = g.get("device_session")
    device = db.session.get(AuthDevice, session.device_id) if session is not None else None
    try:
        draft, kept, locked = intake_svc.submit_device_interview(
            current_user,
            project_id=project_id,
            client_draft_id=client_draft_id,
            site_id=site_id,
            org_unit_id=p.get("org_unit_id") or None,
            death_id=p.get("death_id") or None,
            envelope=envelope,
            data=data,
            answers_sha256=answers_sha256,
            completion=completion,
            device_id=device.device_id if device else None,
        )
        db.session.commit()
    except IntegrityError:
        # A concurrent resend of the same client_draft_id won the unique index.
        db.session.rollback()
        existing = intake_svc.find_device_upload(current_user, client_draft_id)
        if existing is None:
            raise
        return resend(existing)
    return _upload_reply(draft, kept=kept, received_sha256=answers_sha256, locked=locked, status=201)


@bp.post("/submissions/<va_sid>/revisions")
@role_required("interviewer")
def revise_submission(va_sid):
    """Revise the caller's own submitted interview (docs/policy/interview-revisions.md).

    Body: ``reason_code`` (``interviewer_correction``, ``respondent_correction``,
    ``more_information`` or ``finish_partial``), ``answers_json`` +
    ``answers_sha256`` (the complete answers, as ``/submissions``),
    ``completion`` (``{valid, issues}``), ``draft`` (envelope meta; only
    ``startedAt``/``completedAt`` are taken, checked as on upload). Replies 200
    ``{changed, va_sid, payload_version_id, answers_sha256, outcome,
    workflow_state}``; ``changed: false`` when the answers do not change the
    coding payload: no new version, release or routing, but raw answers that
    differ (only irrelevant ones were edited) are kept and ``answers_sha256``
    is the sent hash. 404 ``not_found`` unless the caller's own submitted
    interview; 409 ``revision_locked`` / ``case_already_submitted`` /
    ``case_closed`` / ``case_state_conflict``; 422 ``invalid_reason`` /
    ``answers_hash_*`` / ``invalid_interview``. A completed interview revised
    to a refusal or partial one is allowed: the case leaves coding. The
    server's own reason ``resubmitted`` is not accepted here."""
    p = parse_body()
    reason_code = p.get("reason_code")
    envelope = p.get("draft")
    completion = p.get("completion")
    if not isinstance(reason_code, str) or not isinstance(envelope, dict) or not isinstance(completion, dict):
        return error("reason_code, draft and completion are required.", "invalid_interview", 422)
    data, answers_sha256, refusal = _parse_upload_answers(p)
    if refusal is not None:
        return refusal
    try:
        intake_svc.check_device_times(envelope)
    except intake_svc.WebIntakeError as exc:
        return error(str(exc), "invalid_interview", 422)
    reply = intake_svc.revise_submission(
        current_user, va_sid, reason_code=reason_code, data=data, answers_sha256=answers_sha256,
        completion={"valid": completion.get("valid") is True,
                    "issues": completion.get("issues") if isinstance(completion.get("issues"), list) else []},
        envelope=envelope,
    )
    db.session.commit()
    return jsonify(reply)


@bp.post("/outstanding")
@role_required("interviewer")
def report_outstanding():
    """The app's report of unsent work, stored on its device session. A
    browser cookie has no device session: 403 ``device_session_required``."""
    session = g.get("device_session")
    if session is None:
        return error("Only a device session reports outstanding work.", "device_session_required", 403)
    p = parse_body()
    devices.record_outstanding(
        session, p.get("count"), p.get("unique_ids"), p.get("client_draft_ids"), p.get("client_death_ids")
    )
    db.session.commit()
    return "", 204


@bp.get("/projects/<project_id>/prefill-policy")
@role_required("interviewer")
def prefill_policy(project_id):
    """The offline prefill the server applies in the project, for an app that
    builds a draft before it can reach the server. One of the caller's
    projects only (403 ``project_forbidden``)."""
    require_project(project_id)
    return jsonify(intake_svc.prefill_policy(current_user, project_id))


# ---------------------------------------------------------------------------
# Supervision (digitva-vzk.5)
#
# The interview_supervisor or data_manager gate opens through
# authz.effective_roles, so an In-charge (site_pi at a unit) and a project_pi
# on a tree project pass it too; which cases the caller supervises is decided
# per case by case_transition_service.is_interview_supervisor_for, and a case
# outside that reach reads as 404.
# ---------------------------------------------------------------------------

_TRUE, _FALSE = intake_svc._TRUE, intake_svc._FALSE


def _reason(p):
    return p.get("reason") if isinstance(p.get("reason"), str) else None


def _supervisor_reply(death):
    """What a supervisor action returns: ``{"case": <supervisor row>}``, the
    shape of ``GET /supervision/cases`` (no informant contact details, no
    prefill): a supervisor need not hold an interviewer grant, so the
    interviewer's case detail is not theirs to read."""
    return jsonify({"case": intake_svc.serialize_supervised_row(current_user, *intake_svc.supervised_case_row(death))})


@bp.get("/supervision/cases")
@role_required("interview_supervisor", "data_manager")
def supervised_cases():
    """All cases in the caller's supervisor scope, with who registered and
    started each. Query: ``state``, ``flagged``, ``candidates`` (only cases
    with a second complete interview to choose), ``limit``, ``cursor``."""
    flagged_raw = (request.args.get("flagged") or "").lower()
    if flagged_raw not in _TRUE + _FALSE:
        return error("flagged must be true or false.", "invalid_request", 400)
    candidates_raw = (request.args.get("candidates") or "").lower()
    if candidates_raw not in _TRUE + _FALSE:
        return error("candidates must be true or false.", "invalid_request", 400)
    states = [s for s in (request.args.get("state") or "").split(",") if s]
    try:
        limit = int(request.args.get("limit") or intake_svc.WORKLIST_PAGE_DEFAULT)
    except ValueError:
        return error("limit must be a whole number.", "invalid_request", 400)
    result = intake_svc.list_supervised_cases(
        current_user,
        states=states,
        flagged=flagged_raw in _TRUE,
        candidates=candidates_raw in _TRUE,
        cursor=request.args.get("cursor") or None,
        limit=limit,
    )
    return jsonify(
        {
            "cases": [intake_svc.serialize_supervised_row(current_user, *row) for row in result["cases"]],
            "counts": result["counts"],
            "next_cursor": result["next_cursor"],
        }
    )


@bp.get("/supervision/cases/<death_id>")
@role_required("interview_supervisor", "data_manager", "admin")
def supervised_case_detail(death_id):
    """One supervised case (the list's row) with its ``candidates``: the other
    complete interviews a supervisor may choose, each ``{draft_id,
    interviewer_name, completed_at, outcome}``. Interviewers never see these
    names. 404 outside the caller's reach."""
    death = intake_svc.get_supervised_case(current_user, death_id)
    return jsonify({
        "case": intake_svc.serialize_supervised_row(current_user, *intake_svc.supervised_case_row(death)),
        "candidates": intake_svc.list_candidates(death),
    })


@bp.post("/supervision/cases/<death_id>/choose-interview")
@role_required("interview_supervisor", "data_manager", "admin")
def choose_interview(death_id):
    """Choose another interviewer's complete interview of a submitted case
    over the one it holds (docs/policy/web-intake.md, "Parallel interviews").
    Body: ``draft_id`` (a candidate from the case detail), ``reason_code``
    (``better_quality``, ``more_complete``, ``original_incorrect``,
    ``switch_back``). Coding restarts, the earlier COD stays as history; the
    other interview stays a candidate. 200 ``{"case": <supervisor row>}``; 404
    outside the caller's reach; 409 ``case_not_submitted`` / ``not_a_candidate``
    / ``form_mismatch`` / ``wrong_state`` (a reviewer session is live); 422
    ``invalid_reason``."""
    p = parse_body()
    death = intake_svc.choose_interview(current_user, death_id, p.get("draft_id"), p.get("reason_code"))
    db.session.commit()
    return _supervisor_reply(death)


@bp.post("/supervision/cases/<death_id>/resolve-flag")
@role_required("interview_supervisor", "data_manager")
def resolve_flag(death_id):
    """Confirm or reject the case's pending flag. Body: ``confirm`` (bool), ``reason``."""
    p = parse_body()
    if not isinstance(p.get("confirm"), bool):
        return error("confirm must be true or false.", "invalid_request", 400)
    death = intake_svc.get_supervised_case(current_user, death_id)
    case_svc.resolve_flag(death, actor=current_user, confirm=p["confirm"], reason=_reason(p))
    db.session.commit()
    return _supervisor_reply(death)


@bp.post("/supervision/cases/<death_id>/cancel")
@role_required("interview_supervisor", "data_manager")
def cancel_case(death_id):
    """Cancel a case outright (details pending, registered, scheduled, in
    progress or paused). Body: ``reason``."""
    p = parse_body()
    death = intake_svc.get_supervised_case(current_user, death_id)
    reason = _reason(p)
    if not (reason or "").strip():
        raise intake_svc.WebIntakeError("Give a reason for cancelling.")
    case_svc.transition(death, "cancelled", actor=current_user, action="supervisor_cancel", reason=reason)
    db.session.commit()
    return _supervisor_reply(death)


@bp.post("/supervision/cases/<death_id>/reopen")
@role_required("interview_supervisor", "data_manager")
def reopen_case(death_id):
    """Reopen a submitted, duplicate or cancelled case to its earlier state. Body: ``reason``."""
    p = parse_body()
    death = intake_svc.get_supervised_case(current_user, death_id)
    case_svc.reopen(death, actor=current_user, reason=_reason(p))
    db.session.commit()
    return _supervisor_reply(death)


@bp.post("/supervision/cases/<death_id>/duplicate")
@role_required("interview_supervisor", "data_manager")
def mark_duplicate(death_id):
    """Mark a case as a duplicate of another supervised case of the same
    project; confirmed at once unless the data-manager rule holds it as a
    pending flag. Needs no interviewer grant. Body: ``duplicate_of``, ``reason``."""
    p = parse_body()
    death = intake_svc.get_supervised_case(current_user, death_id)
    if not p.get("duplicate_of"):
        raise intake_svc.WebIntakeError("Name the case this one duplicates.")
    kept = intake_svc.get_supervised_case(current_user, p["duplicate_of"])
    case_svc.flag_case(death, actor=current_user, kind="duplicate", reason=_reason(p), duplicate_of=kept)
    db.session.commit()
    return _supervisor_reply(death)


@bp.post("/supervision/submissions/<va_sid>/reopen-for-revision")
@role_required("interview_supervisor", "data_manager", "admin")
def reopen_for_revision(va_sid):
    """Reopen a finalised web or device interview for its interviewer to
    revise (docs/policy/interview-revisions.md, rule 4). Body: ``reason_code``
    (``cod_review_requested``, ``new_information``, ``data_correction``). 200
    ``{va_sid, workflow_state, reason_code}``; the earlier COD stays until the
    revision arrives. An admin, or a supervisor or data manager whose
    supervision reach covers the interview's case (404 otherwise); 409
    ``not_web_submission`` / ``wrong_state``; 422 ``invalid_reason``."""
    reply = send_back_svc.reopen_for_revision(current_user, va_sid, reason_code=parse_body().get("reason_code"))
    db.session.commit()
    return jsonify(reply)
