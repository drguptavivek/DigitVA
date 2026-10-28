"""Own-server app performance telemetry API.

The parent API package mounts this blueprint at ``/analytics/app``. The write
endpoint accepts only native bearer sessions; the report is admin-only.
"""

from __future__ import annotations

import json
from datetime import date

from flask import Blueprint, g, jsonify, request
from flask_login import current_user, login_required

from app import limiter
from app.routes.api.request_helpers import error as api_error
from app.services import app_telemetry_service as telemetry
from app.services.authz import effective_roles

bp = Blueprint("app_telemetry", __name__)


def _device_key() -> str:
    session = g.get("device_session")
    return f"app-telemetry:{session.device_id}" if session is not None else "app-telemetry:anonymous"


def _body() -> dict:
    if request.content_length is not None and request.content_length > telemetry.MAX_BODY_BYTES:
        raise telemetry.AppTelemetryError("Telemetry batch is too large.", "payload_too_large", 413)
    raw = request.stream.read(telemetry.MAX_BODY_BYTES + 1)
    if len(raw) > telemetry.MAX_BODY_BYTES:
        raise telemetry.AppTelemetryError("Telemetry batch is too large.", "payload_too_large", 413)
    try:
        value = json.loads(raw)
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError):
        raise telemetry.AppTelemetryError("Telemetry batch must be a JSON object.") from None
    if not isinstance(value, dict):
        raise telemetry.AppTelemetryError("Telemetry batch must be a JSON object.")
    return value


def _native_device_required():
    if not g.get("bearer_auth") or g.get("device_session") is None:
        return api_error("Only an enrolled device session may submit telemetry.", "device_session_required", 403)
    return None


@bp.post("/batches")
@login_required
@limiter.limit("60 per minute", key_func=_device_key)
def submit_batch():
    # Record the account authorization decision on transport refusals too.
    effective_roles(current_user._get_current_object())
    refused = _native_device_required()
    if refused is not None:
        return refused
    try:
        accepted = telemetry.ingest(
            current_user._get_current_object(), g.device_session, _body()
        )
    except telemetry.AppTelemetryError as exc:
        return api_error(str(exc), exc.code, exc.status)
    return jsonify({"accepted": True, "duplicate": not accepted})


def _query_date(name: str, alias: str):
    value = request.args.get(name, request.args.get(alias))
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise telemetry.AppTelemetryError(f"{name} must be YYYY-MM-DD.") from None


@bp.get("/performance")
@login_required
@limiter.limit("30 per minute")
def performance():
    if "admin" not in effective_roles(current_user._get_current_object()):
        return api_error("Administrator access is required.", "forbidden", 403)
    try:
        result = telemetry.report(_query_date("from", "start"), _query_date("to", "end"))
    except telemetry.AppTelemetryError as exc:
        return api_error(str(exc), exc.code, exc.status)
    response = jsonify(result)
    response.headers["Cache-Control"] = "no-store"
    return response
