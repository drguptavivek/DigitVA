"""Submission attachments over /api/v1 — the media URLs the renderer emits.

``/vaform/attachment`` and ``/vaform/media`` are cookie-only (a bearer opens
only /api/v1/), so a bearer client cannot load media from them. These two
routes apply the same authorization and delivery (``attachment_service``:
Range for audio, a 302 to a presigned URL on the S3 store, ``private,
no-store``, ``nosniff``) and answer failures as ``{error, code}``.
"""

from __future__ import annotations

from flask import Blueprint, make_response
from flask_login import current_user
from werkzeug.exceptions import HTTPException

from app.decorators import role_required
from app.routes.api.request_helpers import error as api_error
from app.services import attachment_service

bp = Blueprint("attachments_api", __name__)

_CODES = {
    400: "invalid_request",
    403: "forbidden",
    404: "not_found",
    416: "range_not_satisfiable",
    502: "upstream_error",
    503: "unavailable",
}
_MESSAGES = {
    400: "Invalid attachment request.",
    403: "You do not have access to this attachment.",
    404: "Attachment not found.",
    416: "The requested range is not satisfiable.",
    502: "The attachment source failed.",
    503: "Attachment temporarily unavailable. Please retry.",
}


def _refusal(status: int, retry_after: str | None = None):
    """``{error, code}`` for *status*, never stored by a cache."""
    response = make_response(api_error(_MESSAGES[status], _CODES[status], status))
    if retry_after:
        response.headers["Retry-After"] = retry_after
    return attachment_service.apply_no_store_policy(response)


def _deliver(deliver, record):
    """Delivery's response, or its 404 / 502 / 503 as JSON.

    Delivery raises 404 and 502 (and ``send_file`` a 416 for a ``Range`` past
    the end) and *returns* a plain-text 503 with a ``Retry-After``; any other
    status is not ours to translate.
    """
    try:
        response = deliver(record)
    except HTTPException as exc:
        if exc.code in (404, 416, 502, 503):
            return _refusal(exc.code)
        raise
    if response.status_code == 503:
        return _refusal(503, response.headers.get("Retry-After"))
    return response


# Everyone who may view a submission may receive its attachments; the
# submission-level VIEW check is attachment_service's. Role names stay
# literal at each decorator so role_required's decoration-time validation
# (and tests/test_role_required_validation.py) can vouch for them.


@bp.get("/<storage_name>")
@role_required(
    "coder", "coding_tester", "reviewer", "data_manager", "site_pi",
    "project_pi", "collaborator", "collaborator_pii", "admin",
)
def attachment(storage_name):
    """One attachment by its opaque ``storage_name`` token.

    200 the bytes (``Range`` honoured on the local store), or 302 to a
    short-lived presigned URL on the S3 store. Errors ``{error, code}``: 404
    ``not_found`` (bad token, no row, no bytes), 403 ``forbidden``, 502
    ``upstream_error``, 503 ``unavailable`` (with ``Retry-After``), 416
    ``range_not_satisfiable``.
    """
    record = attachment_service.authorize_token_attachment(current_user, storage_name)
    if isinstance(record, int):
        return _refusal(record)
    return _deliver(attachment_service.deliver, record)


@bp.get("/legacy/<va_form_id>/<va_filename>")
@role_required(
    "coder", "coding_tester", "reviewer", "data_manager", "site_pi",
    "project_pi", "collaborator", "collaborator_pii", "admin",
)
def legacy_attachment(va_form_id, va_filename):
    """A pre-``storage_name`` attachment by form id and ODK filename.

    As ``attachment``; additionally 400 ``invalid_request`` for a malformed
    form id or filename.
    """
    record = attachment_service.authorize_legacy_attachment(
        current_user, va_form_id, va_filename
    )
    if isinstance(record, int):
        return _refusal(record)
    return _deliver(attachment_service.deliver_legacy_media, record)
