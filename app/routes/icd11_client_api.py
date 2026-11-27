"""ICD-11 client API, version 1: terminology for approved applications.

``/api/icd11-client/v1/``, outside ``/api/v1/`` on purpose: the device bearer
hook only reads ``/api/v1/``, so it never sees this namespace, and a client
token sent to ``/api/v1/`` is refused there as a bad device token.

The namespace is credential-blind: it never reads or writes the session
cookie (app/utils/bearer_session.py), the signed-in user is always anonymous
(app/hooks/auth.py), and each view is CSRF-exempt because no ambient
credential is read. ``client_scope`` names that exemption view by view
(api-v1.md rule 5) and authenticates the view's bearer token, after the
blueprint's per-IP and per-token rate limits. Every operation is a POST with
a small JSON body, so query text and codes never reach a URL or a log.

Policy: docs/policy/icd11-client-api.md. Reference:
docs/current-state/icd11-client-api.md.
"""

from __future__ import annotations

import json
import time
from functools import wraps

from flask import Blueprint, current_app, g, jsonify, request
from flask_limiter.errors import RateLimitExceeded
from flask_limiter.util import get_remote_address
from werkzeug.exceptions import HTTPException

from app import csrf, db, limiter
from app.services import icd11_client_api as terms
from app.services.icd11_client_auth import (
    Icd11ClientAuthError,
    authenticate,
    bearer_token,
    key_id_of,
    require_scope,
)
from app.services.device.tokens import hash_token
from app.services.icd11_postcoordination import (
    PostcoordinationError,
    code_details,
    postcoordination,
    postcoordination_options,
    search_terms,
    valid_subtree_uris,
)
from app.services.who_icd_api import DEFAULT_ICD11_RELEASE, WhoIcdApiUnavailable

bp = Blueprint("icd11_client_api", __name__)

MAX_BODY_BYTES = 8 * 1024
_RATE_KEY_ENVIRON = "digitva.icd11_client.rate_key"
_HTTP_CODES = {
    400: "MALFORMED_JSON",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    413: "PAYLOAD_TOO_LARGE",
    429: "RATE_LIMITED",
}


def _ip_rate_limit() -> str:
    return current_app.config.get("ICD11_CLIENT_IP_RATE_LIMIT") or "300 per minute"


def _token_rate_limit() -> str:
    return current_app.config.get("ICD11_CLIENT_RATE_LIMIT") or "120 per minute"


def _token_rate_key() -> str:
    """``icd11-client:<verifier>`` of a well-formed bearer, else the client IP.

    Keyed on the whole token's verifier, never the public ``key_id``: a
    forged secret behind a victim's key_id would otherwise spend the victim's
    bucket. A forged token gets a bucket of its own, and the per-IP limit
    caps how many of those one caller can open. Computed here rather than
    read from the authenticated client, so it holds whatever order the hooks
    run in, with no DB read. Memoised on the request's environ, not ``g``:
    the test harness keeps one ``g`` across requests.
    """
    key = request.environ.get(_RATE_KEY_ENVIRON)
    if key is None:
        token = bearer_token(request)
        key = f"icd11-client:{hash_token(token)}" if key_id_of(token) else get_remote_address()
        request.environ[_RATE_KEY_ENVIRON] = key
    return key


# Shared across every operation (one bucket each, not one per endpoint), and
# they override the app's default limits: a server-to-server caller must not
# share the anonymous per-IP bucket.
limiter.shared_limit(_ip_rate_limit, scope="icd11_client_ip", key_func=get_remote_address)(bp)
limiter.shared_limit(_token_rate_limit, scope="icd11_client_token", key_func=_token_rate_key)(bp)


def error(code: str, message: str, status: int, headers: dict | None = None):
    """The API's error envelope. A 401 names the Bearer scheme."""
    response = jsonify({"schema_version": 1, "error": {"code": code, "message": message}})
    response.status_code = status
    if status == 401:
        response.headers["WWW-Authenticate"] = 'Bearer error="invalid_token"'
    response.headers.update(headers or {})
    return response


def http_error(exc: HTTPException):
    """An HTTP error in the envelope. Also used by the app-level 404 and 405
    handlers, which see this namespace's unmatched paths (no blueprint)."""
    status = exc.code or 500
    if status >= 500:
        return error("INTERNAL_ERROR", "Internal server error.", status)
    headers = {}
    if status == 429:
        current = limiter.current_limit
        if current is not None:
            headers["Retry-After"] = str(max(1, int(current.reset_at - time.time())))
    code = _HTTP_CODES.get(status, "INVALID_INPUT")
    return error(code, exc.name, status, headers)


@bp.errorhandler(404)
@bp.errorhandler(405)
@bp.errorhandler(413)
@bp.errorhandler(429)
def _http_error_handler(exc):
    if isinstance(exc, RateLimitExceeded):
        # This handler shadows the app's, which logs breaches; keep that line.
        from app.logging.va_logger import error_logger

        error_logger.error(
            "rate_limited method=%s path=%s ip=%s", request.method, request.path, request.remote_addr
        )
    return http_error(exc)


@bp.errorhandler(Exception)
def _unhandled(exc):
    if isinstance(exc, HTTPException):
        return http_error(exc)
    # This handler shadows the app's: log and roll back as it would.
    from app.logging.va_logger import error_logger

    error_logger.error(
        "unhandled_exception method=%s path=%s ip=%s",
        request.method, request.path, request.remote_addr, exc_info=True,
    )
    db.session.rollback()
    return error("INTERNAL_ERROR", "Internal server error.", 500)


class _BadRequest(Exception):
    """Bad input found while reading the body; carries its error response."""

    def __init__(self, response):
        self.response = response


def client_scope(scope: str | None):
    """Authenticate the request's client token, then require ``scope``
    (None: any valid token). The client is ``g.icd11_client``; a
    ``_BadRequest`` raised by the view becomes its response. Exempts the view
    from CSRF: it reads no cookie, so there is nothing to forge."""
    def decorate(view):
        csrf.exempt(view)

        @wraps(view)
        def wrapped(*args, **kwargs):
            try:
                client = authenticate(request)
                if scope is not None:
                    require_scope(client, scope)
            except Icd11ClientAuthError as exc:
                return error(exc.code, str(exc), exc.status)
            g.icd11_client = client
            try:
                return view(*args, **kwargs)
            except _BadRequest as bad:
                return bad.response
        return wrapped
    return decorate


def _body(required: set[str], optional: frozenset[str] = frozenset()) -> dict:
    """The JSON object body: at most 8 KiB, ``schema_version`` 1, exactly
    ``required`` plus any of ``optional``. Raises ``_BadRequest``."""
    if (request.content_length or 0) > MAX_BODY_BYTES:
        raise _BadRequest(error("PAYLOAD_TOO_LARGE", "The request body is too large.", 413))
    data = request.get_data(cache=True)
    if len(data) > MAX_BODY_BYTES:
        raise _BadRequest(error("PAYLOAD_TOO_LARGE", "The request body is too large.", 413))
    try:
        payload = json.loads(data) if request.is_json else None
    except ValueError:
        payload = None
    if not isinstance(payload, dict):
        raise _BadRequest(error("MALFORMED_JSON", "A JSON object body is required.", 400))
    keys = set(payload)
    required = required | {"schema_version"}
    if payload.get("schema_version") != 1 or not required <= keys or keys - required - optional:
        raise _BadRequest(_invalid())
    return payload


def _invalid():
    return error("INVALID_INPUT", "The request is invalid.", 422)


def _query(payload) -> str:
    query = payload.get("query")
    if not isinstance(query, str) or not 2 <= len(query.strip()) <= 80:
        raise _BadRequest(_invalid())
    return query


def _code(payload, key: str = "code") -> str:
    code = payload.get(key)
    if not terms.valid_code(code):
        raise _BadRequest(_invalid())
    return code


def _respond(operation, *, not_found_status: int | None = None):
    """Run ``operation`` in a client guidance slot and wrap its dict result."""
    try:
        with terms.client_slot():
            result = operation()
    except PostcoordinationError as exc:
        status = not_found_status if exc.code == "CODE_NOT_FOUND" and not_found_status else exc.status
        return error(exc.code, str(exc), status)
    except (WhoIcdApiUnavailable, ValueError):
        return error("WHO_UNAVAILABLE", "ICD-11 terminology is unavailable.", 503)
    return jsonify({"schema_version": 1, "release": DEFAULT_ICD11_RELEASE, **result})


@bp.post("/client")
@client_scope(None)
def client_info():
    _body(set())
    client = g.icd11_client
    return jsonify({
        "schema_version": 1,
        "release": DEFAULT_ICD11_RELEASE,
        "client": {
            "name": client.name,
            "key_id": client.key_id,
            "scopes": list(client.scopes),
            "expires_at": client.expires_at.isoformat(),
        },
    })


@bp.post("/search")
@client_scope("icd11:search")
def search():
    payload = _body({"query"}, frozenset({"limit", "subtree_uris"}))
    query = _query(payload)
    limit = payload.get("limit", 20)
    subtree_uris = payload.get("subtree_uris")
    if (
        isinstance(limit, bool)
        or not isinstance(limit, int)
        or not 1 <= limit <= 20
        or not valid_subtree_uris(subtree_uris)
    ):
        return _invalid()

    def run():
        result = search_terms(query, limit=limit, subtree_uris=subtree_uris)
        items = [{**item, "browser_url": terms.browser_url(item["uri"])} for item in result["items"]]
        return {"items": items, "truncated": result["truncated"]}

    return _respond(run)


@bp.post("/words")
@client_scope("icd11:search")
def words():
    query = _query(_body({"query"}))
    return _respond(lambda: terms.search_words(query))


@bp.post("/codes/lookup")
@client_scope("icd11:lookup")
def lookup():
    code = _code(_body({"code"}))

    def run():
        item = terms.codeinfo_item(code)
        if item is None:
            raise PostcoordinationError("CODE_NOT_FOUND", "WHO does not recognise this code.", 404)
        return {"item": item}

    return _respond(run)


@bp.post("/codes/details")
@client_scope("icd11:lookup")
def details():
    code = _code(_body({"code"}))

    def run():
        try:
            result = code_details(code)
        except PostcoordinationError as exc:
            # The code's shape was checked above: an expression whose stem WHO
            # cannot resolve comes back as INVALID_INPUT, and is not found.
            if exc.code == "INVALID_INPUT":
                raise PostcoordinationError("CODE_NOT_FOUND", "WHO does not recognise this code.", 404) from exc
            raise
        return {**result, "browser_url": terms.browser_url(result["selected"]["uri"])}

    return _respond(run, not_found_status=404)


@bp.post("/postcoordination/axes")
@client_scope("icd11:postcoordination")
def axes():
    code = _code(_body({"code"}))

    def run():
        result = postcoordination(code)
        stem = result["stem"]
        return {**result, "stem": {**stem, "browser_url": terms.browser_url(stem["uri"])}}

    return _respond(run)


@bp.post("/postcoordination/values")
@client_scope("icd11:postcoordination")
def values():
    payload = _body({"stem_code", "axis_id", "parent_uri"})
    stem_code = _code(payload, "stem_code")
    axis_id, parent_uri = payload["axis_id"], payload["parent_uri"]
    if (
        not isinstance(axis_id, str) or not 1 <= len(axis_id) <= 64
        or not isinstance(parent_uri, str) or not 1 <= len(parent_uri) <= 400
    ):
        return _invalid()
    return _respond(lambda: postcoordination_options(stem_code, axis_id, parent_uri))


@bp.post("/expressions/validate")
@client_scope("icd11:validate")
def validate():
    code = _code(_body({"code"}))
    return _respond(lambda: terms.validate_expression(code))
