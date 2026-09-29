"""Admin JSON API for collection devices: enrolment codes, device list, revoke.

Hangs off the ``admin`` blueprint (``/admin/api/...``) like
app/routes/admin_translations.py. Admin only: whether project PIs may also
issue codes is an open owner decision (.tasks/2026-09-30-android-collection-app.md).
Browser-originated, so the global CSRFProtect applies (``X-CSRFToken``).
Rules live in app/services/device_auth_service.py.
"""

import json

from flask import current_app, jsonify, request
from flask_login import current_user

from app import db
from app.decorators import role_required
from app.models import AuthDevice
from app.routes.admin import _json_error, admin
from app.services import device_auth_service as devices
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
    qr_payload = json.dumps(
        {"v": 1, "server": current_app.config["DEVICE_PUBLIC_URL"], "enroll": code, "project": row.project_id},
        separators=(",", ":"),
    )
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


@admin.post("/api/devices/<uuid:device_id>/revoke")
@role_required("admin")
def admin_revoke_device(device_id):
    """Revoke a device and end every interviewer session on it. Idempotent."""
    device = db.session.get(AuthDevice, device_id)
    if device is None:
        return _json_error("Device not found.", 404)
    ended = devices.revoke_device(device, actor=current_user)
    db.session.commit()
    return jsonify({"device_id": str(device.device_id), "sessions_ended": ended})
