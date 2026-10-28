"""The Users page API — /api/v1/users (digitva-75wn).

Browser session only. Gate: admin, project_pi or data_manager (the In-charge
passes as data_manager); who each sees is ``authz.user_list_filter`` inside
``user_directory_service``. A user outside the caller's scope is a 404
whether it exists or not. Policy: docs/policy/access-control-model.md
("Users page"), docs/policy/mobile-sign-in.md section 6.

The account upload and grant grid routes (digitva-cgmc) are admin only:
``user_admin_tools_service``; access-control-model.md ("Users page admin
tools"), account-onboarding-and-passwords.md ("Admin account upload").
"""

import logging
import uuid

from flask import Blueprint, jsonify, request
from flask_login import current_user

from app import db, limiter
from app.decorators import role_required
from app.routes.api.request_helpers import browser_session_only, error, parse_body
from app.services import sign_in_qr_service as sign_in_qr
from app.services import user_admin_tools_service as admin_tools
from app.services import user_directory_service as service

bp = Blueprint("users_api", __name__)
log = logging.getLogger(__name__)


@bp.before_request
def _require_browser_session():
    return browser_session_only()


def _no_store(body, status=200):
    response = jsonify(body)
    response.headers["Cache-Control"] = "no-store"
    return response, status


def _refused(exc: service.UserDirectoryError):
    return error(str(exc), exc.code, exc.status)


@bp.get("/<user_id>/devices")
@role_required("admin", "data_manager")
@limiter.limit("60 per minute")
def user_devices(user_id):
    """Live native-device pairs for a fully in-scope managed account."""
    try:
        return _no_store({"devices": service.list_user_devices(current_user, user_id)})
    except service.UserDirectoryError as exc:
        return _refused(exc)


@bp.delete("/<user_id>/devices/<uuid:device_id>")
@role_required("admin", "data_manager")
@limiter.limit("10 per minute")
def decommission_user_device(user_id, device_id):
    """End only this account's sessions on one device pair."""
    try:
        ended = service.decommission_user_device(
            current_user,
            user_id,
            device_id,
            actor=current_user._get_current_object(),
        )
    except service.UserDirectoryError as exc:
        return _refused(exc)
    db.session.commit()
    return _no_store({"decommissioned": True, "sessions_ended": ended, "current": False})


@bp.get("")
@role_required("admin", "project_pi", "data_manager")
@limiter.limit("120 per minute")
def list_users():
    """Query: ``q``, ``project``, ``unit``, ``role``, ``status``,
    ``enrolment``, ``created`` (today|yesterday), ``created_from``,
    ``created_to``, ``email_verified``, ``password_set``, ``passkey`` (yes|no),
    ``limit`` (max 100), ``offset``; see the service."""
    try:
        return _no_store(service.list_users(current_user, request.args))
    except service.UserDirectoryError as exc:
        return _refused(exc)


@bp.get("/<user_id>/activity")
@role_required("admin", "project_pi", "data_manager")
@limiter.limit("120 per minute")
def user_activity(user_id):
    try:
        return _no_store(service.user_activity(current_user, user_id))
    except service.UserDirectoryError as exc:
        return _refused(exc)


@bp.get("/<user_id>/status")
@role_required("admin", "project_pi", "data_manager")
@limiter.limit("120 per minute")
def user_status(user_id):
    """The Status popup payload (digitva-9npt); see ``service.user_status``.
    Same scope as the activity route; never a secret or a code."""
    try:
        return _no_store(service.user_status(current_user, user_id))
    except service.UserDirectoryError as exc:
        return _refused(exc)


@bp.get("/<user_id>/placement")
@role_required("admin", "project_pi", "data_manager")
@limiter.limit("120 per minute")
def user_placement(user_id):
    """The user's place in each project's organization tree, limited to what
    the viewer manages; see ``service.user_placement``. Same 404 rule as the
    status route."""
    try:
        return _no_store(service.user_placement(current_user, user_id))
    except service.UserDirectoryError as exc:
        return _refused(exc)


@bp.post("/<user_id>/enrolment-code")
@role_required("admin", "project_pi", "data_manager")
@limiter.limit("10 per minute")
def issue_enrolment_code(user_id):
    """Body: ``project_id``, ``delivery`` (show | email), optional
    ``expires_in_minutes`` and ``max_uses`` for show. The code is in this
    response only and is never logged."""
    try:
        body = service.issue_enrolment_code(current_user, user_id, parse_body())
    except service.UserDirectoryError as exc:
        return _refused(exc)
    log.info("users enrolment-code | by=%s | user=%s | emailed=%s",
             current_user.user_id, user_id, bool(body.get("emailed")))
    return _no_store(body, 201)


def _qr_user_id(user_id):
    try:
        return uuid.UUID(user_id)
    except ValueError:
        raise sign_in_qr.SignInQrError("User not found.", 404, "not_found") from None


def _qr_refused(exc: sign_in_qr.SignInQrError):
    return error(str(exc), exc.code, exc.status)


@bp.post("/<user_id>/sign-in-qr")
@role_required("admin", "project_pi", "data_manager")
@limiter.limit("10 per minute")
def issue_sign_in_qr(user_id):
    """Body: ``delivery`` (show | email). Sign-in QR for a data collector or
    death reporter with no other role (mobile-sign-in.md section 8). ``show``:
    ``{code, qr_payload, qr_png (base64), expires_at}``, once; ``email``:
    ``{emailed: true, expires_at}``. The token is in this response only and
    is never logged."""
    try:
        body = sign_in_qr.issue(current_user, _qr_user_id(user_id), parse_body().get("delivery", "show"))
    except sign_in_qr.SignInQrError as exc:
        return _qr_refused(exc)
    log.info("users sign-in-qr issue | by=%s | user=%s | emailed=%s",
             current_user.user_id, user_id, bool(body.get("emailed")))
    return _no_store(body, 201)


@bp.get("/<user_id>/sign-in-qr")
@role_required("admin", "project_pi", "data_manager")
@limiter.limit("120 per minute")
def list_sign_in_qr(user_id):
    """The user's latest sign-in QRs: ``{items: [{status, issued_at,
    expires_at, redeemed_at}]}``; status is pending, expired, redeemed or
    revoked. Never the token."""
    try:
        return _no_store({"items": sign_in_qr.list_for_user(current_user, _qr_user_id(user_id))})
    except sign_in_qr.SignInQrError as exc:
        return _qr_refused(exc)


@bp.delete("/<user_id>/sign-in-qr")
@role_required("admin", "project_pi", "data_manager")
@limiter.limit("30 per minute")
def revoke_sign_in_qr(user_id):
    """Void the user's pending sign-in QR: ``{revoked: bool}``."""
    try:
        revoked = sign_in_qr.revoke(current_user, _qr_user_id(user_id))
    except sign_in_qr.SignInQrError as exc:
        return _qr_refused(exc)
    log.info("users sign-in-qr revoke | by=%s | user=%s | revoked=%s", current_user.user_id, user_id, revoked)
    return _no_store({"revoked": revoked})


# ---------------------------------------------------------------------------
# Admin tools (digitva-cgmc): account upload and the grant grid. Admin only;
# the service refuses anyone else 403 as well.
# ---------------------------------------------------------------------------

@bp.post("/import/preview")
@role_required("admin")
@limiter.limit("10 per minute")
def preview_account_upload():
    """Body: ``filename`` (.csv or .xlsx) and base64 ``content`` of a
    ``name, email, phone`` table. Classifies rows; writes nothing."""
    try:
        return _no_store(admin_tools.preview_upload(current_user, parse_body()))
    except service.UserDirectoryError as exc:
        return _refused(exc)


@bp.post("/import/apply")
@role_required("admin")
@limiter.limit("10 per minute")
def apply_account_upload():
    """The preview's body again; creates only the rows still ``new``."""
    try:
        return _no_store(admin_tools.apply_upload(current_user, parse_body()), 201)
    except service.UserDirectoryError as exc:
        return _refused(exc)


@bp.get("/grid")
@role_required("admin")
@limiter.limit("120 per minute")
def grant_grid():
    """Query: ``project`` (required), ``from``, ``to``, ``q``, ``role``,
    ``status``, ``limit`` (max 100), ``offset``; see the service."""
    try:
        return _no_store(admin_tools.list_grid(current_user, request.args))
    except service.UserDirectoryError as exc:
        return _refused(exc)


@bp.post("/<user_id>/grants")
@role_required("admin")
@limiter.limit("60 per minute")
def save_grant_grid_row(user_id):
    """Body: ``project_id``, ``unit``, ``roles`` and optional ``cadre_id``,
    ``name``, ``phone``, ``active``; see the service."""
    try:
        body = admin_tools.save_grid_row(current_user, user_id, parse_body(), request_ip=request.remote_addr)
    except service.UserDirectoryError as exc:
        return _refused(exc)
    return _no_store(body)
