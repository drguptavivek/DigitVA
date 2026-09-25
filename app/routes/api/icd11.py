"""ICD-11 API — /api/v1/icd11/

Resources:
  GET coding-search/<va_sid>?q=   selectable ICD-11 MMS categories for one
                                  death's coding screen, filtered by its age
                                  and sex policy. Refused for a project whose
                                  ICD classification is icd10
                                  (docs/policy/va-form-project-configuration.md,
                                  "5. ICD classification").
"""

import json
import time
from urllib.parse import parse_qsl, urlencode

from flask import Blueprint, Response, jsonify, request
from flask_login import current_user

from app import csrf
from app.decorators.role_required import role_required
from app.routes.api.icd10 import _error, _require_coding_or_reviewing_access
from app.services import coding_search_telemetry_service
from app.services.icd11_mms_service import (
    build_icd11_provenance,
    search_icd11_mms,
    validate_icd11_mms_coding_value_for_submission,
)
from app.services.icd_coding_value import (
    extract_icd11_code_expression,
    get_icd_classification_for_submission,
)
from app.services.who_icd_api import (
    WhoIcdApiUnavailable,
    proxy_who_icd_request,
)

bp = Blueprint("icd11_api", __name__)

_WHO_PROXY_MAX_QUERY_LENGTH = 4096
_WHO_PROXY_MAX_BODY_LENGTH = 128 * 1024
_WHO_PROXY_SENSITIVE_QUERY_KEYS = {
    "access_token",
    "api-key",
    "apikey",
    "authorization",
    "client_secret",
    "token",
}


def _who_proxy_response(upstream: Response) -> Response:
    """Return only JSON and non-sensitive headers from the WHO response."""
    try:
        json.loads(upstream.content)
    except (TypeError, ValueError):
        error, status = _error("ICD-11 service returned an invalid response.", 503)
        error.status_code = status
        return error
    response = Response(upstream.content, status=upstream.status_code)
    content_type = upstream.headers.get("Content-Type", "application/json")
    response.headers["Content-Type"] = (
        content_type if content_type.lower().startswith("application/json") else "application/json"
    )
    for name in ("API-Version", "Vary"):
        value = upstream.headers.get(name)
        if value:
            response.headers[name] = value
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def _validate_who_proxy_query() -> None:
    query = request.query_string
    if len(query) > _WHO_PROXY_MAX_QUERY_LENGTH:
        raise ValueError("WHO ICD API query is too large.")
    try:
        pairs = parse_qsl(query.decode("ascii"), keep_blank_values=True)
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError("WHO ICD API query is malformed.") from exc
    if any(key.lower() in _WHO_PROXY_SENSITIVE_QUERY_KEYS for key, _ in pairs):
        raise ValueError("Credentials are not accepted by the WHO ICD API proxy.")


@bp.route("/who-api/<va_sid>/<path:resource>", methods=["GET", "POST"])
@csrf.exempt
@role_required("coder", "coding_tester", "reviewer", "admin")
def who_icd_api_proxy(va_sid: str, resource: str):
    """Proxy the read-only WHO ECT calls through the authenticated session.

    ECT sends POST searches without a DigitVA CSRF header.  This endpoint is
    therefore exempt from CSRF because it only reads the fixed local WHO API;
    the submission access and project classification checks still apply.  The
    selection-check endpoint below remains a normal CSRF-protected POST.
    """

    body = b""
    content_type = None
    if request.method == "POST":
        if request.content_length is None or request.content_length > _WHO_PROXY_MAX_BODY_LENGTH:
            return _error("WHO ICD API request body is too large.", 400)
        if request.mimetype == "multipart/form-data":
            if not resource.endswith("/search") or request.files:
                return _error("WHO ICD API form requests are limited to search.", 415)
            # Flask's request middleware may already have parsed ECT's FormData,
            # leaving no raw body. Re-encode the read-only fields for WHO.
            fields = list(request.form.items(multi=True))
            if len(fields) > 32:
                return _error("WHO ICD API search has too many fields.", 400)
            body = urlencode(fields).encode("utf-8")
            content_type = "application/x-www-form-urlencoded"
        else:
            body = request.get_data(cache=True, as_text=False)
            content_type = request.content_type if body else None
        if len(body) > _WHO_PROXY_MAX_BODY_LENGTH:
            return _error("WHO ICD API request body is too large.", 400)

    err = _require_coding_or_reviewing_access(va_sid)
    if err:
        return err
    if get_icd_classification_for_submission(va_sid) == "icd10":
        return _error("This project codes in ICD-11.", 400)

    try:
        _validate_who_proxy_query()
        # ECT's analytics call carries the search text and selected code.  The
        # local deployment already has analytics disabled, so discard it here
        # too.  Do this after query/body bounds checks, without forwarding it.
        if resource.rstrip("/") == "analytics/clientanalytics":
            return Response(status=204)
        if body and request.mimetype not in {"application/json", "multipart/form-data"}:
            return _error("WHO ICD API search content type is unsupported.", 415)
        upstream = proxy_who_icd_request(
            resource,
            method=request.method,
            query_string=request.query_string,
            body=body,
            content_type=content_type,
        )
    except ValueError as exc:
        return _error(str(exc), 400)
    except WhoIcdApiUnavailable:
        return _error("ICD-11 service unavailable.", 503)
    return _who_proxy_response(upstream)


@bp.post("/selection-check/<va_sid>")
@role_required("coder", "coding_tester", "reviewer", "admin")
def icd11_selection_check(va_sid: str):
    """Validate a WHO ECT selection before the assessment field is filled."""

    err = _require_coding_or_reviewing_access(va_sid)
    if err:
        return err
    if get_icd_classification_for_submission(va_sid) == "icd10":
        return _error("This project codes in ICD-11.", 400)

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return _error("A JSON selection is required.", 400)
    code = payload.get("code")
    title = payload.get("selectedText")
    if not isinstance(code, str) or not isinstance(title, str):
        return _error("The WHO selection must include code and selectedText.", 400)
    code = code.strip()
    title = " ".join(title.split())
    value = f"{code} {title}".strip()
    canonical_code = extract_icd11_code_expression(value)
    if not canonical_code or len(title) > 512 or len(value) > 1024:
        return _error("Select a valid ICD-11 code.", 400)
    try:
        validate_icd11_mms_coding_value_for_submission(va_sid, value)
        provenance = build_icd11_provenance(va_sid, value)
    except LookupError:
        return _error("Submission not found.", 404)
    except ValueError as exc:
        return _error(str(exc), 422)
    if not provenance:
        return _error("The ICD-11 code metadata is incomplete.", 422)
    return jsonify(
        {
            "code": canonical_code,
            "title": provenance["title"],
            "selectedText": provenance["selected_text"],
            "value": f"{canonical_code} {provenance['selected_text']}".strip(),
            "provenance": provenance,
        }
    )


@bp.get("/coding-search/<va_sid>")
@role_required("coder", "coding_tester", "reviewer", "admin")
def icd11_coding_search(va_sid: str):
    err = _require_coding_or_reviewing_access(va_sid)
    if err:
        return err
    if get_icd_classification_for_submission(va_sid) == "icd10":
        return _error("This project codes in ICD-11.", 400)

    search_id = coding_search_telemetry_service.resolve_search_id(
        request.args.get("search_id")
    )
    try:
        started = time.perf_counter()
        payload = search_icd11_mms(request.args.get("q", ""), va_sid=va_sid)
        latency_ms = round((time.perf_counter() - started) * 1000)
    except LookupError:
        return _error("Submission not found.", 404)
    # Response payload is built: recording happens now and cannot alter it.
    coding_search_telemetry_service.record_search_request(
        search_id=search_id,
        surface=coding_search_telemetry_service.SURFACE_ICD11,
        query_text=request.args.get("q", ""),
        payload=payload,
        latency_ms=latency_ms,
        user=current_user,
    )
    response = jsonify(payload)
    # The browser learns the id even when it did not send one, so the COD
    # save can forward it and the choice lands on the right search row.
    response.headers["X-Search-Id"] = str(search_id)
    return response
