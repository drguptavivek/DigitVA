"""Clinical DORIS preview API with signed, payload-bound process proof."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from urllib.parse import urlencode

import sqlalchemy as sa
from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user

from app import db
from app.decorators.role_required import role_required
from app.models import VaAllocation, VaAllocations, VaStatuses, VaSubmissions
from app.services.coding_service import get_project_for_submission
from app.services.doris_certificate import DorisCertificateError, expected_expression_uri
from app.services.doris_process_proof import generate_process_proof
from app.services.doris_processing import process_certificate
from app.services.submission_payload_version_service import get_active_payload_version
from app.services.who_icd_api import (
    DEFAULT_ICD11_RELEASE,
    WhoIcdApiUnavailable,
    get_icd11_codeinfo,
    proxy_who_icd_request,
)

bp = Blueprint("doris_clinical_api", __name__)
_TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class ClinicalDorisContext:
    role: str
    allocation_id: object
    payload_version_id: object


class ClinicalDorisAccessError(ValueError):
    def __init__(self, code: str, message: str, status_code: int):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _error(code: str, message: str, status_code: int, fields: list[dict] | None = None):
    payload = {"schema_version": 1, "error": {"code": code, "message": message}}
    if fields is not None:
        payload["error"]["fields"] = fields
    return jsonify(payload), status_code


def _clinical_context(va_sid: str, role: str) -> ClinicalDorisContext:
    if role not in {"coder", "reviewer"}:
        raise ClinicalDorisAccessError("INVALID_ROLE", "Role must be coder or reviewer.", 422)
    submission = db.session.get(VaSubmissions, va_sid)
    if submission is None:
        raise ClinicalDorisAccessError("NOT_FOUND", "Submission not found.", 404)

    if role == "reviewer":
        allowed = current_user.has_va_form_access(submission.va_form_id, "reviewer")
        allocation_for = VaAllocation.reviewing
    else:
        allowed = current_user.has_va_form_access(
            submission.va_form_id, "coder"
        ) or current_user.is_coding_tester(submission.va_form_id)
        allocation_for = VaAllocation.coding
    if not allowed:
        raise ClinicalDorisAccessError(
            "FORBIDDEN", f"{role.title()} access is required.", 403
        )

    allocation_id = db.session.scalar(
        sa.select(VaAllocations.va_allocation_id).where(
            VaAllocations.va_sid == va_sid,
            VaAllocations.va_allocated_to == current_user.user_id,
            VaAllocations.va_allocation_for == allocation_for,
            VaAllocations.va_allocation_status == VaStatuses.active,
        )
    )
    if allocation_id is None:
        raise ClinicalDorisAccessError(
            "ACTIVE_ALLOCATION_REQUIRED",
            f"Active {role} allocation required.",
            403,
        )

    project = get_project_for_submission(va_sid)
    if (
        project is None
        or project.masked_cod_required
        or project.cod_entry_mode != "doris"
        or project.icd_classification != "icd11"
    ):
        raise ClinicalDorisAccessError(
            "DORIS_NOT_ENABLED", "DORIS entry is not enabled for this project.", 409
        )

    active_payload = get_active_payload_version(va_sid)
    if (
        active_payload is None
        or submission.active_payload_version_id != active_payload.payload_version_id
    ):
        raise ClinicalDorisAccessError(
            "ACTIVE_PAYLOAD_REQUIRED", "An active submission payload is required.", 409
        )
    return ClinicalDorisContext(role, allocation_id, active_payload.payload_version_id)


def _active_role(va_sid: str) -> str:
    allocations = set(
        db.session.scalars(
            sa.select(VaAllocations.va_allocation_for).where(
                VaAllocations.va_sid == va_sid,
                VaAllocations.va_allocated_to == current_user.user_id,
                VaAllocations.va_allocation_status == VaStatuses.active,
            )
        )
    )
    if VaAllocation.reviewing in allocations:
        return "reviewer"
    if VaAllocation.coding in allocations:
        return "coder"
    raise ClinicalDorisAccessError(
        "ACTIVE_ALLOCATION_REQUIRED", "Active coding or reviewer allocation required.", 403
    )


def _require_terminology_context(va_sid: str):
    try:
        return _clinical_context(va_sid, _active_role(va_sid)), None
    except ClinicalDorisAccessError as exc:
        return None, _error(exc.code, exc.message, exc.status_code)


def _json_object() -> dict | None:
    if request.content_length is None or request.content_length > 32 * 1024:
        return None
    value = request.get_json(silent=True)
    return value if isinstance(value, dict) else None


def _plain_text(value: object) -> str:
    if isinstance(value, dict):
        value = value.get("@value") or value.get("label") or ""
    if isinstance(value, list):
        value = " ".join(item for item in value if isinstance(item, str))
    text = value if isinstance(value, str) else ""
    return html.unescape(_TAG_RE.sub("", text)).strip()


def _codeinfo_item(code: str) -> dict | None:
    info = get_icd11_codeinfo(code, release=DEFAULT_ICD11_RELEASE)
    if not isinstance(info, dict) or info.get("code") != code:
        return None
    uri = expected_expression_uri(code, DEFAULT_ICD11_RELEASE)
    if not uri:
        return None
    title = _plain_text(info.get("title") or info.get("label"))
    stem_uri = info.get("stemId")
    if not title and isinstance(stem_uri, str) and stem_uri.startswith("http://id.who.int/"):
        entity = proxy_who_icd_request(stem_uri.removeprefix("http://id.who.int/")).json()
        if isinstance(entity, dict):
            title = _plain_text(entity.get("title") or entity.get("label"))
    if not title:
        return None
    return {
        "code": code,
        "title": title,
        "uri": uri,
        "release": DEFAULT_ICD11_RELEASE,
        "postcoordination": any(separator in code for separator in "&/"),
    }


@bp.post("/terms/<va_sid>")
@role_required("coder", "coding_tester", "reviewer", "admin")
def clinical_terms(va_sid: str):
    _, error = _require_terminology_context(va_sid)
    if error:
        return error
    payload = _json_object()
    query = payload.get("query") if payload else None
    limit = payload.get("limit", 20) if payload else None
    if (
        payload is None
        or set(payload) - {"schema_version", "query", "limit", "cursor"}
        or payload.get("schema_version") != 1
        or not isinstance(query, str)
        or not 2 <= len(query.strip()) <= 80
        or isinstance(limit, bool)
        or not isinstance(limit, int)
        or not 1 <= limit <= 20
        or payload.get("cursor") is not None
    ):
        return _error("INVALID_INPUT", "The terminology request is invalid.", 422)
    body = urlencode(
        {
            "q": f"{query.strip()}%",
            "includePostcoordination": "true",
            "flatResults": "true",
            "highlightingEnabled": "true",
            "medicalCodingMode": "true",
        }
    ).encode()
    try:
        upstream = proxy_who_icd_request(
            f"icd/release/11/{DEFAULT_ICD11_RELEASE}/mms/search",
            method="POST",
            body=body,
            content_type="application/x-www-form-urlencoded",
        )
        raw = upstream.json()
    except (WhoIcdApiUnavailable, ValueError):
        return _error("WHO_API_UNAVAILABLE", "WHO ICD-11 service unavailable.", 503)
    entities = raw.get("destinationEntities") if isinstance(raw, dict) else None
    if not isinstance(entities, list):
        return _error("WHO_API_UNAVAILABLE", "WHO ICD-11 returned an invalid response.", 503)
    items = []
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        code = entity.get("theCode") or entity.get("code")
        uri = entity.get("id") or entity.get("uri") or entity.get("@id")
        title = _plain_text(entity.get("title") or entity.get("titleWithoutCodes"))
        if not all(isinstance(value, str) and value for value in (code, uri, title)):
            continue
        items.append(
            {
                "code": code,
                "title": title,
                "uri": uri,
                "release": DEFAULT_ICD11_RELEASE,
                "matching_text": _plain_text(
                    entity.get("matchingPVs") or entity.get("matchingText") or title
                ),
                "postcoordination": bool(
                    entity.get("isLeaf") is False or entity.get("postcoordination")
                ),
            }
        )
        if len(items) == limit:
            break
    return jsonify(
        schema_version=1,
        items=items,
        truncated=bool(raw.get("resultChopped")) or len(entities) > len(items),
        next_cursor=None,
    )


@bp.post("/codeinfo/<va_sid>")
@role_required("coder", "coding_tester", "reviewer", "admin")
def clinical_codeinfo(va_sid: str):
    _, error = _require_terminology_context(va_sid)
    if error:
        return error
    payload = _json_object()
    code = payload.get("code") if payload else None
    if (
        payload is None
        or set(payload) != {"schema_version", "code"}
        or payload.get("schema_version") != 1
        or not isinstance(code, str)
        or not code.strip()
        or len(code.strip()) > 128
    ):
        return _error("INVALID_INPUT", "The code request is invalid.", 422)
    try:
        item = _codeinfo_item(code.strip())
    except (WhoIcdApiUnavailable, ValueError):
        return _error("WHO_API_UNAVAILABLE", "WHO ICD-11 service unavailable.", 503)
    if item is None:
        return _error("CODE_NOT_FOUND", "Select a valid ICD-11 code.", 422)
    return jsonify(schema_version=1, item=item)


@bp.post("/selection-check/<va_sid>")
@role_required("coder", "coding_tester", "reviewer", "admin")
def clinical_selection_check(va_sid: str):
    _, error = _require_terminology_context(va_sid)
    if error:
        return error
    payload = _json_object()
    code = payload.get("code") if payload else None
    uri = payload.get("uri") if payload else None
    if (
        payload is None
        or set(payload) != {"schema_version", "code", "uri"}
        or payload.get("schema_version") != 1
        or not isinstance(code, str)
        or not isinstance(uri, str)
        or not code.strip()
        or len(code.strip()) > 128
        or not uri.strip()
        or len(uri.strip()) > 2048
    ):
        return _error("INVALID_INPUT", "The selected ICD-11 code is invalid.", 422)
    try:
        item = _codeinfo_item(code.strip())
    except (WhoIcdApiUnavailable, ValueError):
        return _error("WHO_API_UNAVAILABLE", "WHO ICD-11 service unavailable.", 503)
    if item is None or item["uri"] != uri.strip():
        return _error(
            "INVALID_SELECTION", "The selected code does not match its WHO URI.", 422
        )
    return jsonify(schema_version=1, item=item)


@bp.post("/process/<va_sid>")
@role_required("coder", "coding_tester", "reviewer", "admin")
def clinical_process(va_sid: str):
    """Process current browser state without saving a clinical draft."""

    payload = _json_object()
    if payload is None:
        return _error("MALFORMED_JSON", "A JSON process request is required.", 400)
    try:
        context = _clinical_context(va_sid, payload.get("role"))
    except ClinicalDorisAccessError as exc:
        return _error(exc.code, exc.message, exc.status_code)

    who_image_digest = str(current_app.config.get("DORIS_WHO_IMAGE_DIGEST") or "").strip()
    if not who_image_digest:
        return _error(
            "WHO_CONFIGURATION_UNAVAILABLE",
            "The pinned WHO processing image is not configured.",
            503,
        )
    process_payload = {
        key: payload.get(key)
        for key in ("schema_version", "client_revision", "certificate")
    }
    try:
        result = process_certificate(
            process_payload,
            release=DEFAULT_ICD11_RELEASE,
            who_image_digest=who_image_digest,
        )
    except DorisCertificateError as exc:
        fields = [{"path": field.path, "message": field.message} for field in exc.fields]
        return _error("INVALID_INPUT", "The DORIS certificate is invalid.", 422, fields)
    except ValueError:
        return _error("INVALID_INPUT", "The DORIS process request is invalid.", 422)
    except WhoIcdApiUnavailable:
        return _error("WHO_API_UNAVAILABLE", "WHO ICD-11 service unavailable.", 503)

    result["process_token"] = generate_process_proof(
        certificate_digest=result["certificate_digest"],
        result_digest=result["result_digest"],
        va_sid=va_sid,
        role=context.role,
        user_id=current_user.user_id,
        allocation_id=context.allocation_id,
        payload_version_id=context.payload_version_id,
        icd_release=result["icd_release"],
        who_image_digest=who_image_digest,
    )
    return jsonify(result)
