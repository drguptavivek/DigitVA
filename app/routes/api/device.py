"""Device API for the Android collection app (Path B), under /api/v1/device.

Contract: .tasks/2026-09-30-android-collection-app.md ("API contract").
Policy: docs/policy/field-data-collection.md. Rules live in
``device_auth_service`` (enrolment, sessions, tokens) and
``web_intake_service`` (uploads); this layer parses and serializes.

No cookies: every call after sign-in carries ``Authorization: Bearer``,
authenticated by the ``authenticate_bearer`` hook in app/__init__.py (the
same credential every /api/v1 route accepts), and this blueprint refuses
any other kind of authentication (a browser's session cookie included). Errors are
``{"error": ..., "code": ...}``. Request bodies are capped (``_body_limit``)
before anything reads them, the rate limiter's key functions included.
"""

import uuid
from contextlib import contextmanager
from datetime import UTC, datetime

from flask import Blueprint, g, jsonify, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError
from werkzeug.exceptions import RequestEntityTooLarge

from app import csrf, db, limiter
from app.decorators import role_required
from app.models import AuthDevice, VaProjectMaster
from app.routes.api.instruments import translations_response
from app.routes.api.organization import (
    form_options_payload,
    served_instrument_locales,
    units_payload,
)
from app.services import device_auth_service as devices
from app.services import web_intake_service as intake_svc
from app.services.site_maintenance_service import should_block_non_admin_after_cutoff
from app.services.user_account_service import canonical_mobile
from app.utils.who_va_bundle import who_va_bundle_version

bp = Blueprint("device", __name__)
csrf.exempt(bp)

#: Endpoints reachable without a device session (they create one).
_UNAUTHENTICATED = devices.UNAUTHENTICATED_ENDPOINTS
#: Bearer endpoints open while the terms are pending (onboarding policy 5.4).
_TERMS_EXEMPT = frozenset({"end_session", "accept_terms"})

#: Request body caps: one interview upload; the outstanding-work report (up
#: to OUTSTANDING_MAX_IDS case ids, draft UUIDs and registration UUIDs, about
#: 150 KB at worst, also accepted on refresh); every other (small) call.
SUBMISSION_MAX_BYTES = 2 * 1024 * 1024
REPORT_MAX_BYTES = 256 * 1024
BODY_MAX_BYTES = 16 * 1024
_REPORT_ENDPOINTS = frozenset({"report_outstanding", "refresh_session"})

#: WebIntakeError carries a status only; the contract wants a machine code.
_INTAKE_CODES = {400: "invalid_request", 403: "forbidden", 404: "not_found", 409: "conflict", 422: "invalid_interview"}


def _error(message, code, status_code):
    return jsonify({"error": message, "code": code}), status_code


def _body_limit() -> int:
    """Cap this request's body (idempotent). Runs before the first read,
    wherever that is: the limiter's key functions read the body in an
    app-level hook that runs before this blueprint's own."""
    endpoint = (request.endpoint or "").rsplit(".", 1)[-1]
    if endpoint == "submit_interview":
        limit = SUBMISSION_MAX_BYTES
    elif endpoint in _REPORT_ENDPOINTS:
        limit = REPORT_MAX_BYTES
    else:
        limit = BODY_MAX_BYTES
    request.max_content_length = limit
    return limit


def _body() -> dict:
    _body_limit()
    try:
        body = request.get_json(silent=True)
    except RecursionError:  # absurdly nested JSON within the size cap
        return {}
    return body if isinstance(body, dict) else {}


def _body_key(name):
    """Rate-limit key from a JSON body field (per device, per account). An
    oversized body gives an empty key here; the blueprint hook answers 413.
    A sign-in identifier without ``@`` keys on its canonical mobile number,
    so spacing or a ``+91`` prefix does not buy a fresh bucket."""
    def key():
        try:
            value = _body().get(name)
        except RequestEntityTooLarge:
            value = None
        text = str(value).strip().lower()[:128] if value else ""
        if name == "email" and text and "@" not in text:
            text = canonical_mobile(text) or text
        return f"device-{name}:{text}"
    return key


@bp.before_request
def _refuse_oversized_body():
    limit = _body_limit()
    if request.content_length is not None and request.content_length > limit:
        return _error("The request body is too large.", "payload_too_large", 413)
    return None


@bp.before_request
def _require_device_session():
    endpoint = (request.endpoint or "").rsplit(".", 1)[-1]
    if endpoint in _UNAUTHENTICATED:
        return None
    user = current_user._get_current_object()  # runs the bearer request loader
    session = g.get("device_session")
    if session is None or not user.is_authenticated or user.user_id != session.user_id:
        return _error("Authentication required.", "unauthorized", 401)
    if not user.is_admin() and should_block_non_admin_after_cutoff():
        return _error("Site is under maintenance.", "maintenance", 403)
    if not user.pw_reset_t_and_c and endpoint not in _TERMS_EXEMPT:
        return _error("Accept the terms of use to continue.", "terms_required", 403)
    return None


@bp.errorhandler(RequestEntityTooLarge)
def _too_large(_exc):
    return _error("The request body is too large.", "payload_too_large", 413)


@bp.errorhandler(devices.DeviceAuthError)
def _device_auth_error(exc):
    db.session.rollback()
    return _error(str(exc), exc.code, exc.status_code)


@bp.errorhandler(intake_svc.WebIntakeError)
def _intake_error(exc):
    db.session.rollback()
    return _error(str(exc), _INTAKE_CODES.get(exc.status_code, "invalid_request"), exc.status_code)


# ---------------------------------------------------------------------------
# Enrolment and sessions (no bearer token yet)
# ---------------------------------------------------------------------------


@bp.post("/enroll")
@limiter.limit("10 per minute")
def enroll():
    p = _body()
    device, secret = devices.enrol_device(
        p.get("code"), device_name=p.get("device_name"), platform=p.get("platform"),
        app_version=p.get("app_version"),
    )
    project = db.session.get(VaProjectMaster, device.project_id)
    db.session.commit()
    return jsonify({
        "device_id": str(device.device_id),
        "device_secret": secret,
        "project": {"project_id": project.project_id, "name": project.project_name},
        "server_time": datetime.now(UTC).isoformat(),
    }), 201


@bp.post("/sessions")
@limiter.limit("10 per minute")
@limiter.limit("10 per minute", key_func=_body_key("device_id"))
@limiter.limit("20 per hour", key_func=_body_key("email"))
def open_session():
    """Interviewer sign-in on an enrolled device; the ``email`` field takes an
    email or a mobile number (docs/policy/mobile-sign-in.md). Rate limits match the web
    password step (docs/policy/authentication-factors.md section 1), per IP,
    per device and per account; the device credential replaces the CAPTCHA."""
    p = _body()
    issued, user = devices.open_session(
        device_id=p.get("device_id"), device_secret=p.get("device_secret"),
        email=p.get("email"), password=p.get("password"), otp=p.get("otp"),
    )
    db.session.commit()
    return jsonify(devices.serialize_tokens(issued, user)), 201


@bp.post("/sessions/refresh")
@limiter.limit("30 per minute")
def refresh_session():
    """Rotate the refresh token, presented with the device's id and secret;
    optional ``count``/``unique_ids``/``client_draft_ids``/``client_death_ids`` record the
    outstanding-work report in the same call. The session lasts while the
    worker has an interviewer grant in at least one project."""
    p = _body()
    issued, user = devices.refresh_session(
        p.get("refresh_token"), device_id=p.get("device_id"), device_secret=p.get("device_secret"),
    )
    # Pending terms refuse data calls (policy 5.4); the report is one.
    if "count" in p and user.pw_reset_t_and_c:
        devices.record_outstanding(
            issued.session, p.get("count"), p.get("unique_ids"), p.get("client_draft_ids"), p.get("client_death_ids")
        )
    db.session.commit()
    return jsonify(devices.serialize_tokens(issued, user)), 200


# ---------------------------------------------------------------------------
# Bearer-authenticated
# ---------------------------------------------------------------------------


@bp.delete("/sessions/current")
@login_required
def end_session():
    """Sign-out. ``login_required``, not the interviewer role: an interviewer
    whose grant was withdrawn must still be able to sign out."""
    devices.end_session(g.device_session)
    db.session.commit()
    return "", 204


@bp.post("/terms")
@login_required
@limiter.limit("5 per minute", key_func=lambda: str(g.device_session.user_id))
def accept_terms():
    """The app's terms screen (onboarding policy 5.4): records the acceptance
    exactly as the web terms page does. Body ``{"accept_terms": true}``;
    anything else is 400 ``invalid_request``. ``login_required`` like
    sign-out: open to any signed-in account, before any role check."""
    from app.services.user_account_service import accept_terms as record_acceptance

    if _body().get("accept_terms") is not True:
        return _error("Please accept the terms of use.", "invalid_request", 400)
    record_acceptance(current_user._get_current_object(), via="device")
    db.session.commit()
    return jsonify({"message": "Terms accepted.", "terms_accepted": True})


@bp.get("/bootstrap")
@role_required("interviewer")
def bootstrap():
    """The intake bootstrap: ``projects`` has one entry per project this
    interviewer may collect in, with its sites, form options and offline
    prefill policy. Every other call names one of them as ``project_id``.
    No CSRF fields: there is no cookie session here."""
    by_project: dict[str, list] = {}
    for entry in _interviewer_context():
        by_project.setdefault(entry["project_id"], []).append(entry)
    projects = []
    for project_id, sites in by_project.items():
        # Already in the session's identity map: interviewer_context loaded it.
        authorized = db.session.get(VaProjectMaster, project_id)
        projects.append({
            "project_id": project_id,
            "project_name": authorized.project_name,
            "web_intake_mode": sites[0]["web_intake_mode"],
            "sites": sites,
            "form_options": form_options_payload(authorized),
            "prefill_policy": intake_svc.prefill_policy(current_user, project_id),
        })
    return jsonify({
        "user": {"user_id": str(current_user.user_id), "name": current_user.name},
        "instrument_version": who_va_bundle_version(),
        "projects": projects,
    })


@bp.post("/submissions")
@role_required("interviewer")
def submit_interview():
    """One completed interview, idempotent on ``client_draft_id``: a resend
    returns the first result with 200."""
    p = _body()
    try:
        client_draft_id = uuid.UUID(str(p.get("client_draft_id")))
    except ValueError:
        return _error("client_draft_id must be a UUID.", "invalid_request", 400)
    site_id = p.get("site_id")
    if not isinstance(site_id, str) or not site_id.strip():
        return _error("site_id is required.", "invalid_request", 400)
    envelope = p.get("draft")
    completion = p.get("completion")
    if not isinstance(completion, dict):
        # The package's completion result carries valid/issues beside data.
        completion = envelope if isinstance(envelope, dict) else {}

    project_id = _request_project_id(p)
    existing = intake_svc.find_device_upload(current_user, client_draft_id)
    if existing is not None:
        return jsonify(intake_svc.serialize_device_upload(existing)), 200
    device = db.session.get(AuthDevice, g.device_session.device_id)
    try:
        draft = intake_svc.submit_device_interview(
            current_user,
            project_id=project_id,
            client_draft_id=client_draft_id,
            site_id=site_id.strip(),
            org_unit_id=p.get("org_unit_id") or None,
            death_id=p.get("death_id") or None,
            envelope=envelope,
            completion=completion,
            device_id=device.device_id,
        )
        db.session.commit()
    except IntegrityError:
        # A concurrent resend of the same client_draft_id won the unique index.
        db.session.rollback()
        existing = intake_svc.find_device_upload(current_user, client_draft_id)
        if existing is None:
            raise
        return jsonify(intake_svc.serialize_device_upload(existing)), 200
    return jsonify(intake_svc.serialize_device_upload(draft)), 201


@bp.post("/outstanding")
@role_required("interviewer")
def report_outstanding():
    p = _body()
    devices.record_outstanding(
        g.device_session, p.get("count"), p.get("unique_ids"), p.get("client_draft_ids"), p.get("client_death_ids")
    )
    db.session.commit()
    return "", 204


def _interviewer_context() -> list[dict]:
    """``interviewer_context`` of the caller, computed once per request. Kept
    in the WSGI environ, not ``g``, which can outlive the request (as
    ``authz.resolve_grants``)."""
    context = request.environ.get("digitva.interviewer_context")
    if context is None:
        context = request.environ["digitva.interviewer_context"] = intake_svc.interviewer_context(current_user)
    return context


def _request_project_id(p: dict | None = None) -> str:
    """The ``project_id`` the request names (query string, or the JSON body
    *p* of a POST): required (400 ``invalid_request``), and one of the
    interviewer's projects (403 ``project_forbidden``, alike whether it
    exists or not). The device's enrolment project plays no part."""
    raw = (request.args if p is None else p).get("project_id")
    if raw in (None, "") or not isinstance(raw, str):
        raise devices.DeviceAuthError("project_id is required.", "invalid_request", 400)
    project_id = raw.strip()
    if not any(e["project_id"] == project_id for e in _interviewer_context()):
        raise devices.DeviceAuthError("You have no interviewer access in that project.", "project_forbidden", 403)
    return project_id


@bp.get("/units")
@role_required("interviewer")
@limiter.limit("120 per minute")
def units():
    """The request project's organization units this interviewer may pick
    (``project_id``, required):
    the ``/api/v1/organization/<project>/units?role=interviewer`` body, scoped
    by interviewer grants only (a unit grant sees its subtree, plus ancestors
    as ``selectable: false`` context; a project grant or a site grant the whole
    tree, the same rule as the create-time check, ``intake_svc.reachable_unit_ids``)."""
    project_id = _request_project_id()
    reachable = intake_svc.reachable_unit_ids(current_user, project_id)
    if reachable is not None and not reachable:
        return _error("You have no organization units in this project.", "forbidden", 403)
    return jsonify(units_payload(project_id, reachable))


@bp.get("/instruments/<instrument_code>/translations/<locale>")
@role_required("interviewer")
@limiter.limit("120 per minute")
def instrument_translations(instrument_code, locale):
    """One locale's questionnaire strings: the ``/api/v1/instruments`` body
    and ETag, only for the instrument and locales the request project
    serves (its form options' default form type and ``available_locales``);
    ``project_id`` required."""
    code = (instrument_code or "").strip().upper()
    locale = (locale or "").strip()
    project = db.session.get(VaProjectMaster, _request_project_id())
    served_code, served_locales = served_instrument_locales(project)
    if code != served_code or locale not in served_locales:
        return _error("Translation not found.", "not_found", 404)
    response = translations_response(code, locale)
    if isinstance(response, tuple):  # the shared endpoint's 404
        return _error("Translation not found.", "not_found", 404)
    return response


# ---------------------------------------------------------------------------
# Offline cases (phase 3, digitva-kmk.4)
# ---------------------------------------------------------------------------

#: The register form's fields (app/routes/intake.py ``api_register_death``).
_REGISTER_FIELDS = (
    "deceased_name", "deceased_sex", "abha_number", "abha_address", "date_of_birth", "date_of_birth_partial",
    "age_years", "date_of_death", "place_of_death", "address", "address_house_street",
    "address_village_ward", "address_landmark", "informant_name", "informant_phone",
    "informant_phone_2", "remarks", "father_name", "mother_name",
)


def _client_id(p: dict, name: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(p.get(name)))
    except ValueError:
        raise devices.DeviceAuthError(f"{name} must be a UUID.", "invalid_request", 400) from None


@contextmanager
def _unprocessable(code):
    """A content refusal (400) from the intake service becomes 422 *code*,
    which the app answers by reopening the item for editing."""
    try:
        yield
    except intake_svc.WebIntakeError as exc:
        if exc.status_code != 400:
            raise
        raise devices.DeviceAuthError(str(exc), code, 422) from None


def _no_store(response):
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.get("/cases")
@role_required("interviewer")
@limiter.limit("120 per minute")
def list_cases():
    """The browser worklist (``/intake/api/cases``) of one project:
    ``web_intake_service.worklist_page`` with the same query (``mine``,
    ``state``, ``limit``, ``cursor``) and body, plus required ``project_id``.
    The app downloads its active cases with ``state=`` and then each case's
    detail (docs/policy/field-data-collection.md)."""
    project_id = _request_project_id()
    return _no_store(jsonify(
        intake_svc.worklist_page(current_user, request.args, project_id=project_id, context=_interviewer_context())
    ))


def _case_body(death, unit_name, my_draft_id) -> dict:
    """The device's case body: the browser detail's ``case``
    (``serialize_case_detail``), plus ``prefill`` for an interview started
    offline, and this API's links."""
    body = intake_svc.serialize_case_detail(current_user, death, unit_name, my_draft_id)
    body["prefill"] = intake_svc.case_prefill(current_user, death)
    body["links"] = {
        "self": url_for(".case_detail", death_id=death.death_id),
        "attempts": url_for(".log_attempt", death_id=death.death_id),
        "visit": url_for(".set_visit", death_id=death.death_id),
    }
    return body


@bp.get("/cases/<death_id>")
@role_required("interviewer")
@limiter.limit("120 per minute")
def case_detail(death_id):
    """One case with its full contact details and prefill, visible as the
    worklist would list it, in any of the interviewer's projects; otherwise
    404. The app keeps it offline only while the case is active
    (docs/policy/field-data-collection.md)."""
    row = intake_svc.get_case_detail(current_user, death_id, context=_interviewer_context())
    return _no_store(jsonify({"case": _case_body(*row)}))


def _registered_case(death) -> dict:
    """A registration's reply: the case's detail body, as ``/cases/<id>``."""
    return _case_body(*intake_svc.case_row(current_user, death))


@bp.post("/deaths")
@role_required("interviewer")
def register_death():
    """A death registered offline, idempotent on ``client_death_id``: a
    resend returns the same case with 200. Body: ``site_id``,
    ``org_unit_id``, and the web register form's fields."""
    p = _body()
    client_death_id = _client_id(p, "client_death_id")
    site_id = p.get("site_id")
    if not isinstance(site_id, str) or not site_id.strip():
        return _error("site_id is required.", "invalid_request", 400)
    if any(isinstance(p.get(k), (dict, list)) for k in _REGISTER_FIELDS):
        return _error("Registration fields must be text or numbers.", "invalid_registration", 422)
    project_id = _request_project_id(p)
    existing = intake_svc.find_device_registration(current_user, project_id, client_death_id)
    if existing is not None:
        return _no_store(jsonify({"case": _registered_case(existing)})), 200
    try:
        with _unprocessable("invalid_registration"):
            death = intake_svc.register_death(
                current_user,
                project_id=project_id,
                site_id=site_id.strip(),
                org_unit_id=p.get("org_unit_id") or None,
                client_death_id=client_death_id,
                **{k: p.get(k) for k in _REGISTER_FIELDS},
            )
        db.session.commit()
    except IntegrityError:
        # A concurrent resend of the same client_death_id won the unique index.
        db.session.rollback()
        existing = intake_svc.find_device_registration(current_user, project_id, client_death_id)
        if existing is None:
            raise
        return _no_store(jsonify({"case": _registered_case(existing)})), 200
    return _no_store(jsonify({"case": _registered_case(death)})), 201


@bp.post("/cases/<death_id>/attempts")
@role_required("interviewer")
def log_attempt(death_id):
    """A contact attempt logged offline, idempotent on ``client_attempt_id``:
    a resend returns the case with 200 and logs nothing. Body: ``outcome``,
    optional ``next_visit_at``."""
    p = _body()
    client_attempt_id = _client_id(p, "client_attempt_id")
    existing = intake_svc.find_device_attempt(current_user, death_id, client_attempt_id)
    if existing is not None:
        return jsonify({"case": intake_svc.serialize_case_ack(existing)}), 200
    try:
        with _unprocessable("invalid_attempt"):
            death = intake_svc.log_contact_attempt(
                current_user, death_id, outcome=str(p.get("outcome") or ""),
                next_visit_at=p.get("next_visit_at"), client_attempt_id=client_attempt_id,
            )
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        existing = intake_svc.find_device_attempt(current_user, death_id, client_attempt_id)
        if existing is None:
            raise
        return jsonify({"case": intake_svc.serialize_case_ack(existing)}), 200
    return jsonify({"case": intake_svc.serialize_case_ack(death)}), 201


@bp.post("/cases/<death_id>/visit")
@role_required("interviewer")
def set_visit(death_id):
    """Set (or clear, with ``null``) a case's next visit. Idempotent by
    value, so no client id is stored: a resend sets the same date."""
    p = _body()
    with _unprocessable("invalid_visit"):
        death = intake_svc.set_visit(current_user, death_id, next_visit_at=p.get("next_visit_at"))
    db.session.commit()
    return jsonify({"case": intake_svc.serialize_case_ack(death)}), 200
