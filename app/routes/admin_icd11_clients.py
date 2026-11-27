"""Admin JSON API and panel for ICD-11 client API tokens (digitva-ddpf).

Hangs off the ``admin`` blueprint like app/routes/admin_devices.py. Admin
only. Browser-originated, so the global CSRF hook applies (``X-CSRFToken``).
Rules live in app/services/icd11_client_auth.py; policy:
docs/policy/icd11-client-api.md.
"""

from flask import jsonify, render_template, request
from flask_login import current_user

from app import db
from app.decorators import role_required
from app.routes._json import _json_error
from app.routes.admin import admin
from app.services import icd11_client_auth as clients


@admin.get("/panels/icd11-api-clients")
@role_required("admin")
def admin_panel_icd11_api_clients():
    return render_template("admin/panels/icd11_api_clients.html", scopes=clients.SCOPES)


@admin.get("/api/icd11-api-clients")
@role_required("admin")
def admin_list_icd11_api_clients():
    return jsonify(clients.list_clients())


@admin.post("/api/icd11-api-clients")
@role_required("admin")
def admin_issue_icd11_api_client():
    """Issue a client token. The token is in this response only; the server
    keeps its SHA-256 digest. Body: ``name``, ``scopes``, ``expires_in_days``
    (default 90). 400 names the bad ``field``."""
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        payload = {}
    try:
        row, token = clients.issue_client(
            payload.get("name"), payload.get("scopes"), payload.get("expires_in_days"), current_user,
        )
    except clients.Icd11ClientInputError as exc:
        db.session.rollback()
        return jsonify({"error": str(exc), "field": exc.field}), 400
    db.session.commit()
    response = jsonify({"client": clients.describe_client(row), "token": token})
    response.headers["Cache-Control"] = "no-store"
    return response, 201


@admin.post("/api/icd11-api-clients/<uuid:client_id>/revoke")
@role_required("admin")
def admin_revoke_icd11_api_client(client_id):
    """Revoke a client token; idempotent. 404 for an unknown id."""
    try:
        row = clients.revoke_client(client_id, current_user)
    except clients.Icd11ClientNotFound:
        db.session.rollback()
        return _json_error("ICD-11 API client not found.", 404)
    db.session.commit()
    return jsonify({"client": clients.describe_client(row)})
