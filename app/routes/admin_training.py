"""Training sessions API and panel (Training & demo project, TRN01).

Thin HTTP layer over ``app.services.training_demo_service``; routes hang off
the ``admin`` blueprint (``/admin/api/training/...``). Admin only, every write
a POST with the X-CSRFToken header (the app-wide CSRF check). Policy:
docs/policy/training-demo-project.md.
"""
import logging

from flask import Response, jsonify, render_template, request
from flask_login import current_user

from app import limiter
from app.decorators import role_required
from app.models.mas_training import PARTICIPANT_ROLES
from app.routes.admin import _json_error, admin
from app.services import training_demo_service as service

log = logging.getLogger(__name__)

_API = "/api/training"
_STATUS = {
    "session_not_found": 404,
    "participant_not_found": 404,
    "unknown_user": 404,
    "project_missing": 409,
    "target_not_configured": 409,
    "already_participant": 409,
    "session_closed": 409,
    "no_free_coder_slot": 409,
    "coder_language_missing": 409,
    "session_unit_conflict": 409,
    "not_enough_source_cases": 409,
    "source_form_missing": 409,
    "report_forbidden": 403,
    "bulk_refused": 409,
}


def _fail(exc: service.TrainingDemoError):
    return _json_error(exc.message, _STATUS.get(exc.code, 400))


def _body() -> dict:
    payload = request.get_json(silent=True)
    return payload if isinstance(payload, dict) else {}


def _text(payload: dict, key: str, limit: int) -> str:
    value = payload.get(key)
    return value.strip()[:limit] if isinstance(value, str) else ""


def _roles(payload: dict) -> list:
    """``roles`` (a list) or the legacy single ``role``; the service validates the names."""
    roles = payload.get("roles")
    if isinstance(roles, list):
        return [r.strip()[:32] if isinstance(r, str) else "" for r in roles[:len(PARTICIPANT_ROLES) * 2]]
    return [_text(payload, "role", 32)]


@admin.get("/panels/training-sessions")
@role_required("admin")
def admin_panel_training_sessions():
    return render_template(
        "admin/panels/training_sessions.html",
        roles=PARTICIPANT_ROLES,
        configured=service.training_configured(),
    )


@admin.get(f"{_API}/sessions")
@role_required("admin")
def training_sessions_list():
    return jsonify({
        "configured": service.training_configured(),
        "sessions": service.list_training_sessions(),
    })


@admin.post(f"{_API}/sessions")
@role_required("admin")
@limiter.limit("10 per hour")
def training_sessions_create():
    """Create a session (200 copies take a few seconds)."""
    try:
        summary = service.create_training_session(_body().get("name"), current_user._get_current_object())
    except service.TrainingDemoError as exc:
        return _fail(exc)
    return jsonify(summary), 201


@admin.get(f"{_API}/sessions/<ref>")
@role_required("admin")
def training_session_detail(ref):
    try:
        return jsonify(service.get_training_session(ref))
    except service.TrainingDemoError as exc:
        return _fail(exc)


@admin.post(f"{_API}/sessions/<ref>/participants")
@role_required("admin")
def training_participant_add(ref):
    payload = _body()
    try:
        participant = service.add_participant(
            ref, _text(payload, "email", 254), _roles(payload), current_user._get_current_object()
        )
    except service.TrainingDemoError as exc:
        return _fail(exc)
    return jsonify(participant), 201


@admin.post(f"{_API}/sessions/<ref>/participants/remove")
@role_required("admin")
def training_participant_remove(ref):
    payload = _body()
    try:
        participant = service.remove_participant(
            ref, _text(payload, "user_id", 64), _text(payload, "role", 32), current_user._get_current_object()
        )
    except service.TrainingDemoError as exc:
        return _fail(exc)
    return jsonify(participant)


@admin.get(f"{_API}/sessions/<ref>/candidates")
@role_required("admin")
def training_candidates(ref):
    """Users who could be added: filtered by creation date and creator, bounded."""
    args = request.args
    try:
        limit = int(args.get("limit", "50"))
    except ValueError:
        return _json_error("A filter value is not valid.", 400)
    try:
        return jsonify(service.training_candidates(
            ref, current_user._get_current_object(),
            created_since=args.get("created_since", "")[:10], created_by=args.get("created_by", "me"),
            query=args.get("query", ""), limit=limit, tz_name=getattr(current_user, "timezone", None),
        ))
    except service.TrainingDemoError as exc:
        return _fail(exc)


@admin.post(f"{_API}/sessions/<ref>/participants/bulk")
@role_required("admin")
def training_participants_bulk(ref):
    """Preview (``dry_run``, the default) or apply adding many users in one or more roles."""
    payload = _body()
    user_ids = payload.get("user_ids")
    try:
        result = service.bulk_add_participants(
            ref, user_ids if isinstance(user_ids, list) else [], _roles(payload),
            current_user._get_current_object(), dry_run=payload.get("dry_run", True) is not False,
        )
    except service.TrainingDemoError as exc:
        return _fail(exc)
    if result.get("applied") is False:
        return jsonify({"error": service.MESSAGES["bulk_refused"], **result}), 409
    return jsonify(result)


@admin.get(f"{_API}/sessions/<ref>/graduation.csv")
@role_required("admin")
def training_graduation_csv(ref):
    """The session's participants as an organization users import CSV."""
    args = request.args
    try:
        body = service.graduation_csv(
            ref, current_user._get_current_object(), role=args.get("role", "")[:32],
            org_unit_code=args.get("org_unit_code", "")[:40], cadre_code=args.get("cadre_code", "")[:40],
        )
    except service.TrainingDemoError as exc:
        return _fail(exc)
    return Response(body, mimetype="text/csv", headers={
        "Content-Disposition": 'attachment; filename="training_graduation.csv"',
        "Cache-Control": "no-store",
    })


@admin.post(f"{_API}/sessions/<ref>/close")
@role_required("admin")
def training_session_close(ref):
    try:
        return jsonify(service.close_training_session(ref, current_user._get_current_object()))
    except service.TrainingDemoError as exc:
        return _fail(exc)


@admin.post(f"{_API}/sessions/<ref>/reopen")
@role_required("admin")
def training_session_reopen(ref):
    try:
        return jsonify(service.reopen_training_session(ref, current_user._get_current_object()))
    except service.TrainingDemoError as exc:
        return _fail(exc)
