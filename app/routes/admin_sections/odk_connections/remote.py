"""Remote ODK lookup and connection-test routes."""

from flask import current_app, jsonify
from flask_login import current_user

from app import db
from app.decorators import role_required
from app.models import MasOdkConnections
from app.http.responses import json_error as _json_error
from app.routes.admin import admin
from app.routes.admin_sections import odk_connections as odk_routes
from app.utils.credential_crypto import decrypt_credential, get_odk_pepper


@admin.post("/api/odk-connections/<uuid:connection_id>/test")
@role_required("admin")
def admin_odk_connections_test(connection_id):
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    conn = db.session.get(MasOdkConnections, connection_id)
    if not conn:
        return _json_error("Connection not found.", 404)

    try:
        pepper = get_odk_pepper()
        username = decrypt_credential(conn.username_enc, conn.username_salt, pepper)
        password = decrypt_credential(conn.password_enc, conn.password_salt, pepper)
    except (RuntimeError, ValueError) as exc:
        return _json_error(f"Credential decryption failed: {exc}", 500)

    try:
        import requests as http

        resp = odk_routes.guarded_odk_call(
            lambda: http.post(
                f"{conn.base_url}/v1/sessions",
                json={"email": username, "password": password},
                timeout=current_app.config.get(
                    "ODK_CONNECTION_TEST_TIMEOUT_SECONDS",
                    10,
                ),
            ),
            connection_id=conn.connection_id,
        )
        if resp.status_code == 200:
            return jsonify({"ok": True, "message": "Authentication successful."})
        return jsonify(
            {"ok": False, "message": f"ODK returned HTTP {resp.status_code}."}
        ), 200
    except odk_routes.OdkConnectionCooldownError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 200
    except Exception as exc:
        odk_routes.log.error("ODK connection test failed: %s", exc, exc_info=True)
        return (
            jsonify(
                {"ok": False, "message": "Connection test failed. Check server logs."}
            ),
            200,
        )


@admin.get("/api/odk-connections/<uuid:connection_id>/odk-projects")
@role_required("admin")
def admin_odk_list_odk_projects(connection_id):
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    conn = db.session.get(MasOdkConnections, connection_id)
    if not conn:
        return _json_error("Connection not found.", 404)

    try:
        client = odk_routes._get_odk_client_for_connection(conn)
        projects = odk_routes.guarded_odk_call(
            lambda: client.projects.list(),
            client=client,
        )
        return jsonify(
            {
                "odk_projects": [
                    {"id": project.id, "name": project.name}
                    for project in projects
                ]
            }
        )
    except Exception as exc:
        return _json_error(f"Failed to fetch ODK projects: {exc}", 502)


@admin.get("/api/odk-connections/<uuid:connection_id>/odk-projects/<int:odk_project_id>/forms")
@role_required("admin")
def admin_odk_list_forms(connection_id, odk_project_id):
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    conn = db.session.get(MasOdkConnections, connection_id)
    if not conn:
        return _json_error("Connection not found.", 404)

    try:
        client = odk_routes._get_odk_client_for_connection(conn)
        forms = odk_routes.guarded_odk_call(
            lambda: client.forms.list(project_id=odk_project_id),
            client=client,
        )
        return jsonify(
            {
                "forms": [
                    {
                        "xmlFormId": form.xmlFormId,
                        "name": form.name,
                        "version": form.version,
                    }
                    for form in forms
                ]
            }
        )
    except Exception as exc:
        return _json_error(f"Failed to fetch forms: {exc}", 502)
