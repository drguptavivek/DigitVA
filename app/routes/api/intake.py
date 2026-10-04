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
from werkzeug.exceptions import RequestEntityTooLarge

from app import db, limiter
from app.decorators import role_required
from app.models import AuthDevice, VaSubmissionPayloadVersion
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
from app.services import web_intake_service as intake_svc

bp = Blueprint("intake_api", __name__)

#: Request body caps: one interview upload; the outstanding-work report (up
#: to OUTSTANDING_MAX_IDS case ids, draft UUIDs and registration UUIDs, about
#: 150 KB at worst); every other (small) call. Draft saves and submits are
#: bounded by the service's answer checks, not here.
SUBMISSION_MAX_BYTES = 2 * 1024 * 1024
REPORT_MAX_BYTES = 256 * 1024
BODY_MAX_BYTES = 16 * 1024
_UNCAPPED = frozenset({"save_draft", "submit_draft"})

#: The register form's fields.
_REGISTER_FIELDS = (
    "deceased_name", "deceased_sex", "abha_number", "abha_address", "date_of_birth", "date_of_birth_partial",
    "age_years", "date_of_death", "place_of_death", "address", "address_house_street",
    "address_village_ward", "address_landmark", "informant_name", "informant_phone",
    "informant_phone_2", "remarks", "father_name", "mother_name",
)


def _body_limit():
    endpoint = (request.endpoint or "").rsplit(".", 1)[-1]
    if endpoint in _UNCAPPED:
        return None
    if endpoint in ("submit_interview", "sync_draft", "revise_submission"):
        limit = SUBMISSION_MAX_BYTES
    elif endpoint == "report_outstanding":
        limit = REPORT_MAX_BYTES
    else:
        limit = BODY_MAX_BYTES
    request.max_content_length = limit
    return limit


@bp.before_request
def _refuse_oversized_body():
    limit = _body_limit()
    if limit is not None and request.content_length is not None and request.content_length > limit:
        return error("The request body is too large.", "payload_too_large", 413)
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


def _case_body(death, unit_name, my_draft_id, other_draft_started_at=None, my_submission=False) -> dict:
    """The case with its full contact details (``serialize_case_detail``), this
    API's links, and the ``prefill`` an interview started offline needs, only
    when the caller may start or resume the interview (``case_prefill``);
    otherwise the key is absent."""
    body = intake_svc.serialize_case_detail(
        current_user, death, unit_name, my_draft_id, other_draft_started_at, my_submission
    )
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
@limiter.limit("120 per minute")
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
@role_required("interviewer")
def list_deaths():
    project_id = request.args.get("project_id", "")
    site_id = request.args.get("site_id", "")
    status = request.args.get("status") or None
    if not project_id or not site_id:
        return error("project_id and site_id are required.", "invalid_request", 400)
    deaths = intake_svc.list_deaths(current_user, project_id=project_id, site_id=site_id, status=status)
    return jsonify({"deaths": [intake_svc.serialize_death(d) for d in deaths]})


@bp.post("/deaths")
@role_required("interviewer")
def register_death():
    """Register a death. Body: ``project_id``, ``site_id``, ``org_unit_id`` and
    the register form's fields, optional ``client_death_id`` (UUID): an offline
    registration is idempotent on it, a resend returns the same case with 200.
    Replies ``{"case": <detail>}``, as ``GET /cases/<id>``."""
    p = parse_body()
    client_death_id = _client_id(p, "client_death_id")
    site_id = _site_id(p)
    project_id = request_project_id(p)

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
    draft = intake_svc.lock_draft_for_browser_write(intake_svc.get_draft(current_user, draft_id, for_update=True))
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
    draft = intake_svc.get_draft(current_user, draft_id, for_update=True)
    intake_svc.discard_draft(draft, current_user)
    db.session.commit()
    return jsonify({"draft": intake_svc.serialize_draft(draft)})


@bp.post("/drafts/<draft_id>/submit")
@role_required("interviewer")
def submit_draft(draft_id):
    p = parse_body()
    draft = intake_svc.lock_draft_for_browser_write(intake_svc.get_draft(current_user, draft_id, for_update=True))
    # Same stale-tab guard as autosave: a tab that missed the phone's newer
    # version must not submit its own silently.
    if p.get("if_updated_at") is not None and intake_svc.draft_is_stale(draft, p["if_updated_at"]):
        return error(intake_svc.SYNC_MESSAGE, "draft_stale", 409)
    submission = intake_svc.submit_draft(draft, current_user, completion=p.get("completion") or {})
    if submission is None:
        # A teammate's complete submission won: this copy is kept, not routed.
        db.session.commit()
        return jsonify(
            {"va_sid": None, "draft": intake_svc.serialize_draft(draft), "superseded": True, "validation_err": None}
        )
    # Re-derived server/client disagreements (beads digitva-cal.2), never
    # blocking: surfaced here so a field problem is debuggable, not just
    # logged. No answer value is ever in these entries.
    version = db.session.get(VaSubmissionPayloadVersion, submission.active_payload_version_id)
    validation_err = version.validation_err if version else []
    db.session.commit()
    return jsonify(
        {
            "va_sid": submission.va_sid,
            "draft": intake_svc.serialize_draft(draft),
            "superseded": False,
            "validation_err": validation_err,
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


def _existing_upload_reply(existing, answers_sha256):
    """A resend of a stored upload: 200 with the first result when the
    answers are the same, 409 ``hash_mismatch`` with the stored result when
    they differ (or the stored row predates hashing)."""
    stored = intake_svc.serialize_device_upload(existing)
    if existing.answers_sha256 == answers_sha256:
        return jsonify(stored), 200
    return error(
        "That client_draft_id was already uploaded with different answers.", "hash_mismatch", 409, stored=stored
    )


@bp.post("/submissions")
@role_required("interviewer")
def submit_interview():
    """One completed interview, idempotent on ``client_draft_id``: a resend
    with the same ``answers_sha256`` returns the first result with 200; a
    resend with other answers is 409 ``hash_mismatch`` carrying the stored
    result. A bearer request records its device on the interview; a cookie
    request has none."""
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
    existing = intake_svc.find_device_upload(current_user, client_draft_id)
    if existing is not None:
        return _existing_upload_reply(existing, answers_sha256)
    session = g.get("device_session")
    device = db.session.get(AuthDevice, session.device_id) if session is not None else None
    try:
        draft = intake_svc.submit_device_interview(
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
        return _existing_upload_reply(existing, answers_sha256)
    return jsonify(intake_svc.serialize_device_upload(draft)), 201


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
    ``outcome_regression`` / ``answers_hash_*`` / ``invalid_interview``."""
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
    started each. Query: ``state``, ``flagged``, ``limit``, ``cursor``."""
    flagged_raw = (request.args.get("flagged") or "").lower()
    if flagged_raw not in _TRUE + _FALSE:
        return error("flagged must be true or false.", "invalid_request", 400)
    states = [s for s in (request.args.get("state") or "").split(",") if s]
    try:
        limit = int(request.args.get("limit") or intake_svc.WORKLIST_PAGE_DEFAULT)
    except ValueError:
        return error("limit must be a whole number.", "invalid_request", 400)
    result = intake_svc.list_supervised_cases(
        current_user,
        states=states,
        flagged=flagged_raw in _TRUE,
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
