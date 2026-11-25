"""What every intake route shares: the blueprint, its request hooks and
error handlers, and the request parsers (digitva-r8nh.9 split
``app/routes/api/intake.py`` into this package; see ``__init__``).
"""
import logging
import sys
import uuid
from contextlib import contextmanager

import sqlalchemy as sa
from flask import Blueprint, g, request
from flask_login import current_user
from werkzeug.exceptions import RequestEntityTooLarge

from app import db
from app.models import (
    VaDeathRegister,
    VaWebIntakeDraft,
)
from app.routes.api.request_helpers import (
    error,
    intake_error,
)
from app.services import collection_gate, training_scope
from app.services import consent_service as consent_svc
from app.services import death_identifier_service as identifiers_svc
from app.services import device_auth_service as devices
from app.services import offline_coding_import_service as offline_import
from app.services import web_intake_attachment_service as attachments_svc
from app.services import web_intake_service as intake_svc

bp = Blueprint("intake_api", __name__)
#: The package's name, as before the split: log readers filter on it.
log = logging.getLogger("app.routes.api.intake")


def _pkg():
    """The ``app.routes.api.intake`` package, looked up at call time. Code
    here reads the names tests patch on it (``pii_scope``,
    ``should_redact_pii``, ``visit_notes_for``, ``_supervised_body``) through
    this, so such a patch still reaches them (as ``web_intake.facade()``).
    Imported lazily: the package imports these modules."""
    from app.routes.api import intake

    return intake


#: Request body caps: one interview upload; the outstanding-work report (up
#: to OUTSTANDING_MAX_IDS case ids, draft UUIDs and registration UUIDs, about
#: 150 KB at worst); every other (small) call. Draft saves and submits are
#: bounded by the service's answer checks, not here.
SUBMISSION_MAX_BYTES = 2 * 1024 * 1024
REPORT_MAX_BYTES = 256 * 1024
BODY_MAX_BYTES = 16 * 1024
#: One attachment's raw body (``put_attachment``): ``MAX_BYTES``, 50 MB per file.
ATTACHMENT_MAX_BYTES = attachments_svc.MAX_BYTES

#: The register form's fields.
_REGISTER_FIELDS = intake_svc.REGISTER_FIELDS


def _body_limit():
    endpoint = (request.endpoint or "").rsplit(".", 1)[-1]
    if endpoint in ("submit_interview", "sync_draft", "revise_submission", "save_draft", "submit_draft"):
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


_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


@bp.before_request
def _keep_training_apart():
    """A write names a project, a death, a draft or a submission; refuse it
    when that is across the training/real line of the request (``?training=1``
    or not), 409 ``training_scope``. The phone app sends no ``training``, so
    it works real projects only: training is an Expo-web surface
    (docs/policy/training-demo-project.md, "Separation from real work")."""
    if request.method not in _WRITE_METHODS:
        return None
    training_scope.resolve("interview")
    body = request.get_json(silent=True) if request.is_json else None
    named = {**(body if isinstance(body, dict) else {}), **(request.view_args or {})}
    project_ids = set()
    raw_project = named.get("project_id")
    if isinstance(raw_project, str) and raw_project.strip():
        project_ids.add(raw_project.strip().upper())
    # Every id an existing row is found by: the server's own and the device's
    # idempotency keys (a replay finds, and may rewrite, the stored row).
    for name, model, column in (
        ("death_id", VaDeathRegister, "death_id"),
        ("draft_id", VaWebIntakeDraft, "draft_id"),
        ("client_draft_id", VaWebIntakeDraft, "client_draft_id"),
        ("client_death_id", VaDeathRegister, "client_death_id"),
    ):
        try:
            key = uuid.UUID(str(named[name]))
        except (KeyError, ValueError):
            continue
        project = db.session.scalar(sa.select(model.project_id).where(getattr(model, column) == key))
        if project:
            project_ids.add(project)
    va_sid = named.get("va_sid")
    if isinstance(va_sid, str) and not training_scope.sid_allowed(va_sid):
        return error("This case is not available in this area.", "training_scope", 409)
    if not all(training_scope.keeps_project(project_id) for project_id in project_ids):
        return error("This case is not available in this area.", "training_scope", 409)
    return None


#: The draft writes whose refusals are logged (``_log_draft_refusal``).
_LOGGED_DRAFT_WRITES = frozenset({"save_draft", "submit_draft"})


def _note_refusal_site(frame) -> None:
    """Remember where this request was refused (``function:line``) for
    ``_log_draft_refusal``: the code alone does not tell apart the many
    ``invalid_request`` / ``conflict`` checks behind one route."""
    g.intake_refusal_at = f"{frame.f_code.co_name}:{frame.f_lineno}"


def _note_raise_site(exc: BaseException) -> None:
    tb = exc.__traceback__
    if tb is None:
        return
    while tb.tb_next is not None:
        tb = tb.tb_next
    _note_refusal_site(tb.tb_frame)


def _refuse(message, code, status_code, **extra):
    """``error`` for a refusal returned directly by a draft write handler."""
    _note_refusal_site(sys._getframe(1))
    return error(message, code, status_code, **extra)


def _stale_extra(draft) -> dict:
    """The optional fields of a 409 ``draft_stale`` (web-intake.md, "Stale
    browser saves"): the version that won and who changed it. Only the
    draft's owner reaches a stale check (``get_draft``)."""
    return {"updated_at": draft.updated_at.isoformat(), "last_change": intake_svc.last_change(draft, current_user)}


@bp.after_request
def _log_draft_refusal(response):
    """One warning per refused draft save or submit (400, 409, 422): the
    machine code, the check that refused it, the draft and user ids. Never the
    message or the body, which can carry field names and answers. Staging
    logs showed only the status of a browser retrying one refused save."""
    # Popped on every response: g can outlive a request (tests push one app context).
    refused_at = g.pop("intake_refusal_at", "-")
    endpoint = (request.endpoint or "").rsplit(".", 1)[-1]
    if endpoint not in _LOGGED_DRAFT_WRITES or response.status_code not in (400, 409, 422):
        return response
    body = response.get_json(silent=True)
    log.warning(
        "intake draft write refused | endpoint=%s | status=%s | reason=%s | at=%s | draft=%s | user=%s",
        endpoint, response.status_code, body.get("code") if isinstance(body, dict) else None,
        refused_at, (request.view_args or {}).get("draft_id"),
        getattr(current_user, "user_id", None),
    )
    return response


@bp.errorhandler(RequestEntityTooLarge)
def _too_large(_exc):
    return error("The request body is too large.", "payload_too_large", 413)


@bp.errorhandler(devices.DeviceAuthError)
def _project_or_client_error(exc):
    _note_raise_site(exc)
    db.session.rollback()
    fields = getattr(exc, "fields", None)
    return error(str(exc), exc.code, exc.status_code, **({"fields": fields} if fields else {}))


@bp.errorhandler(intake_svc.WebIntakeError)
def _intake_error(exc):
    _note_raise_site(exc)
    db.session.rollback()
    if isinstance(exc, collection_gate.CollectionClosed):
        return error(str(exc), exc.code, exc.status_code, **exc.gate)
    if exc.code == "refusal_stale" and getattr(exc, "draft_id", None):
        return error(str(exc), exc.code, exc.status_code, draft_id=exc.draft_id)
    return intake_error(exc)


@bp.errorhandler(offline_import.OfflineCodingError)
def _offline_coding_error(exc):
    _note_raise_site(exc)
    db.session.rollback()
    return error(str(exc), exc.code, exc.status_code)


@bp.errorhandler(consent_svc.ConsentError)
def _consent_error(exc):
    _note_raise_site(exc)
    db.session.rollback()
    return error(str(exc), exc.code, exc.status_code, **({"fields": exc.fields} if exc.fields else {}))


def _consent_channel() -> str:
    """``device`` for a bearer request, ``web`` for a browser cookie."""
    return "device" if g.get("device_session") is not None else "web"


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
        refusal = devices.DeviceAuthError(str(exc), code, 422)
        refusal.fields = exc.fields  # the questions to fix, e.g. identifiers.<code>
        raise refusal from None


def _identifiers_arg(p: dict) -> dict | None:
    """The body's ``identifiers`` object (``{type code: text}``), None when
    absent or null. Its own parser: the register fields refuse objects, this
    key is one. Checked here for shape, at most 50 codes and no raw value
    over 256 characters (before any normalisation); the type rules are the
    service's."""
    value = p.get("identifiers")
    if value is not None:
        identifiers_svc.check_limits(value)
    return value


def _carries_identifiers() -> bool:
    """Whether this request's body names registration numbers: the test that
    counts it against the per-user budget. Reads the body within the route's
    size cap (the limiter runs before the blueprint's own size check); an
    oversize or unreadable body is not counted here and is refused later."""
    limit = _body_limit()
    if limit is not None and request.content_length is not None and request.content_length > limit:
        return False
    body = request.get_json(silent=True)
    return isinstance(body, dict) and bool(body.get("identifiers"))


def _site_id(p: dict) -> str:
    site_id = p.get("site_id")
    if not isinstance(site_id, str) or not site_id.strip():
        raise devices.DeviceAuthError("site_id is required.", "invalid_request", 400)
    return site_id.strip()
