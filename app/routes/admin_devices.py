"""Admin JSON API for collection devices: enrolment codes, device list, revoke,
and registering a never-online station from its enrolment file.

Hangs off the ``admin`` blueprint (``/admin/api/...``) like
app/routes/admin_translations.py. Admin only: whether project PIs may also
issue codes is an open owner decision (.tasks/2026-09-30-android-collection-app.md).
Browser-originated, so the global CSRFProtect applies (``X-CSRFToken``).
Rules live in app/services/device_auth_service.py and
app/services/device_signing_service.py.
"""

from flask import jsonify, request
from flask_login import current_user

from app import db
from app.decorators import role_required
from app.models import AuthDevice
from app.routes.admin import _json_error, admin
from app.services import device_auth_service as devices
from app.services import device_signing_service as signing
from app.services.totp_service import provisioning_qr_svg


@admin.post("/api/projects/<project_id>/device-enrolments")
@role_required("admin")
def admin_create_device_enrolment(project_id):
    """Issue an enrolment code. The code (and the QR carrying it) is in this
    response only; the server keeps its hash. Body: ``expires_in_minutes``
    (default 60), ``max_uses`` (default 1)."""
    payload = request.get_json(silent=True) or {}
    try:
        row, code = devices.create_enrolment_code(
            project_id,
            actor=current_user,
            expires_in_minutes=payload.get("expires_in_minutes"),
            max_uses=payload.get("max_uses"),
        )
    except devices.DeviceAuthError as exc:
        db.session.rollback()
        return _json_error(str(exc), exc.status_code)
    db.session.commit()
    qr_payload = devices.enrolment_qr_payload(row, code)
    response = jsonify({
        "code": code,
        "qr_payload": qr_payload,
        "qr_svg": provisioning_qr_svg(qr_payload),
        "expires_at": row.expires_at.isoformat(),
        "max_uses": row.max_uses,
    })
    response.headers["Cache-Control"] = "no-store"
    return response, 201


@admin.get("/api/projects/<project_id>/devices")
@role_required("admin")
def admin_list_devices(project_id):
    return jsonify({"devices": devices.list_project_devices(project_id)})


@admin.post("/api/projects/<project_id>/station-registrations")
@role_required("admin")
def admin_register_station(project_id):
    """Register a never-online offline station from its enrolment file. Body:
    ``name`` and ``enrolment_file`` ``{device_id, signing_public_key,
    app_version}``. No device secret is issued; the station only signs
    bundles. 201 with the device id and ``signing_key_id``; 400 malformed
    file or bad key, 404 project, 409 device id already registered."""
    payload = request.get_json(silent=True) or {}
    try:
        device = signing.register_pasted_station(
            project_id, payload.get("enrolment_file"), name=payload.get("name"), actor=current_user,
        )
    except devices.DeviceAuthError as exc:
        db.session.rollback()
        return _json_error(str(exc), exc.status_code)
    db.session.commit()
    return jsonify({"device_id": str(device.device_id), "signing_key_id": device.signing_key_id}), 201


@admin.post("/api/devices/<uuid:device_id>/revoke")
@role_required("admin")
def admin_revoke_device(device_id):
    """Revoke a device and end every interviewer session on it. Idempotent.
    Optional body ``revoked_compromised`` (boolean, default false): the
    device was lost or stolen, so every bundle it signed is refused."""
    payload = request.get_json(silent=True) or {}
    compromised = payload.get("revoked_compromised", False)
    if not isinstance(compromised, bool):
        return _json_error("revoked_compromised must be true or false.", 400)
    device = db.session.get(AuthDevice, device_id)
    if device is None:
        return _json_error("Device not found.", 404)
    ended = devices.revoke_device(device, actor=current_user, compromised=compromised)
    db.session.commit()
    return jsonify({"device_id": str(device.device_id), "sessions_ended": ended,
                    "revoked_compromised": device.revoked_compromised})
