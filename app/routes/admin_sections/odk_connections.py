import logging

from flask import current_app, jsonify, render_template, request
from flask_login import current_user
import sqlalchemy as sa

from app import db
from app.decorators import role_required
from app.models import MapProjectOdk, MasOdkConnections, VaProjectMaster, VaStatuses
from app.routes.admin import _serialize_odk_connection, admin
from app.routes.admin_support.http import json_error as _json_error
from app.routes.admin_support.odk import (
    get_connection_project_ids as _get_connection_project_ids,
    get_odk_client_for_connection as _get_odk_client_for_connection,
    validate_odk_base_url as _validate_odk_base_url,
)
from app.services.odk_connection_guard_service import (
    OdkConnectionCooldownError,
    guarded_odk_call,
)

log = logging.getLogger(__name__)


@admin.get("/panels/odk-connections")
@role_required("admin")
def admin_panel_odk_connections():
    return render_template("admin/panels/odk_connections.html")


@admin.get("/api/odk-connections")
@role_required("admin")
def admin_odk_connections_list():
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    conns = db.session.scalars(
        sa.select(MasOdkConnections).order_by(MasOdkConnections.connection_name)
    ).all()
    result = [
        _serialize_odk_connection(c, _get_connection_project_ids(c.connection_id))
        for c in conns
    ]
    return jsonify({"connections": result})


@admin.post("/api/odk-connections")
@role_required("admin")
def admin_odk_connections_create():
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    payload = request.get_json(silent=True) or {}
    connection_name = (payload.get("connection_name") or "").strip()
    base_url = (payload.get("base_url") or "").strip().rstrip("/")
    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""

    if not connection_name:
        return _json_error("connection_name is required.", 400)
    if not base_url:
        return _json_error("base_url is required.", 400)
    try:
        base_url = _validate_odk_base_url(base_url)
    except ValueError as exc:
        return _json_error(f"Invalid base_url: {exc}", 400)
    if not username:
        return _json_error("username is required.", 400)
    if not password:
        return _json_error("password is required.", 400)

    existing = db.session.scalar(
        sa.select(MasOdkConnections).where(
            MasOdkConnections.connection_name == connection_name
        )
    )
    if existing:
        return _json_error("A connection with that name already exists.", 400)

    from app.utils.credential_crypto import encrypt_credential, get_odk_pepper

    try:
        pepper = get_odk_pepper()
    except RuntimeError as exc:
        log.error("ODK pepper not available for connection creation: %s", exc)
        return _json_error("Server configuration error. Contact an administrator.", 500)

    username_enc, username_salt = encrypt_credential(username, pepper)
    password_enc, password_salt = encrypt_credential(password, pepper)

    conn = MasOdkConnections(
        connection_name=connection_name,
        base_url=base_url,
        username_enc=username_enc,
        username_salt=username_salt,
        password_enc=password_enc,
        password_salt=password_salt,
        status=VaStatuses.active,
        notes=(payload.get("notes") or "").strip() or None,
    )
    db.session.add(conn)
    db.session.commit()
    return jsonify({"connection": _serialize_odk_connection(conn, [])}), 201


@admin.put("/api/odk-connections/<uuid:connection_id>")
@role_required("admin")
def admin_odk_connections_update(connection_id):
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    conn = db.session.get(MasOdkConnections, connection_id)
    if not conn:
        return _json_error("Connection not found.", 404)

    payload = request.get_json(silent=True) or {}

    if "connection_name" in payload:
        name = (payload["connection_name"] or "").strip()
        if not name:
            return _json_error("connection_name cannot be empty.", 400)
        dup = db.session.scalar(
            sa.select(MasOdkConnections).where(
                MasOdkConnections.connection_name == name,
                MasOdkConnections.connection_id != connection_id,
            )
        )
        if dup:
            return _json_error("A connection with that name already exists.", 400)
        conn.connection_name = name

    if "base_url" in payload:
        base_url = (payload["base_url"] or "").strip()
        if not base_url:
            return _json_error("base_url cannot be empty.", 400)
        try:
            base_url = _validate_odk_base_url(base_url)
        except ValueError as exc:
            return _json_error(f"Invalid base_url: {exc}", 400)
        conn.base_url = base_url

    if "notes" in payload:
        conn.notes = (payload["notes"] or "").strip() or None

    if payload.get("username") or payload.get("password"):
        from app.utils.credential_crypto import encrypt_credential, get_odk_pepper

        try:
            pepper = get_odk_pepper()
        except RuntimeError as exc:
            log.error("ODK pepper not available for connection update: %s", exc)
            return _json_error("Server configuration error. Contact an administrator.", 500)

        if payload.get("username"):
            username = (payload["username"] or "").strip()
            if not username:
                return _json_error("username cannot be empty.", 400)
            conn.username_enc, conn.username_salt = encrypt_credential(username, pepper)

        if payload.get("password"):
            conn.password_enc, conn.password_salt = encrypt_credential(
                payload["password"], pepper
            )

    if "status" in payload:
        try:
            conn.status = VaStatuses(payload["status"])
        except ValueError:
            return _json_error("Invalid status.", 400)

    db.session.commit()
    project_ids = _get_connection_project_ids(connection_id)
    return jsonify({"connection": _serialize_odk_connection(conn, project_ids)})


@admin.post("/api/odk-connections/<uuid:connection_id>/toggle")
@role_required("admin")
def admin_odk_connections_toggle(connection_id):
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    conn = db.session.get(MasOdkConnections, connection_id)
    if not conn:
        return _json_error("Connection not found.", 404)

    conn.status = (
        VaStatuses.deactive if conn.status == VaStatuses.active else VaStatuses.active
    )
    db.session.commit()
    return jsonify(
        {"connection_id": str(conn.connection_id), "status": conn.status.value}
    )


@admin.post("/api/odk-connections/<uuid:connection_id>/test")
@role_required("admin")
def admin_odk_connections_test(connection_id):
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    conn = db.session.get(MasOdkConnections, connection_id)
    if not conn:
        return _json_error("Connection not found.", 404)

    from app.utils.credential_crypto import decrypt_credential, get_odk_pepper

    try:
        pepper = get_odk_pepper()
        username = decrypt_credential(conn.username_enc, conn.username_salt, pepper)
        password = decrypt_credential(conn.password_enc, conn.password_salt, pepper)
    except (RuntimeError, ValueError) as exc:
        return _json_error(f"Credential decryption failed: {exc}", 500)

    try:
        import requests as http

        resp = guarded_odk_call(
            lambda: http.post(
                f"{conn.base_url}/v1/sessions",
                json={"email": username, "password": password},
                timeout=current_app.config.get(
                    "ODK_CONNECTION_TEST_TIMEOUT_SECONDS", 10
                ),
            ),
            connection_id=conn.connection_id,
        )
        if resp.status_code == 200:
            return jsonify({"ok": True, "message": "Authentication successful."})
        return jsonify(
            {"ok": False, "message": f"ODK returned HTTP {resp.status_code}."}
        ), 200
    except OdkConnectionCooldownError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 200
    except Exception as exc:
        log.error("ODK connection test failed: %s", exc, exc_info=True)
        return (
            jsonify(
                {"ok": False, "message": "Connection test failed. Check server logs."}
            ),
            200,
        )


@admin.get("/api/odk-connections/<uuid:connection_id>/projects")
@role_required("admin")
def admin_odk_connection_projects(connection_id):
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    conn = db.session.get(MasOdkConnections, connection_id)
    if not conn:
        return _json_error("Connection not found.", 404)

    return jsonify({"project_ids": _get_connection_project_ids(connection_id)})


@admin.post("/api/odk-connections/<uuid:connection_id>/assign-project")
@role_required("admin")
def admin_odk_assign_project(connection_id):
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    conn = db.session.get(MasOdkConnections, connection_id)
    if not conn:
        return _json_error("Connection not found.", 404)

    payload = request.get_json(silent=True) or {}
    project_id = (payload.get("project_id") or "").strip().upper()
    if not project_id:
        return _json_error("project_id is required.", 400)

    project = db.session.get(VaProjectMaster, project_id)
    if not project:
        return _json_error("Project not found.", 404)

    existing = db.session.scalar(
        sa.select(MapProjectOdk).where(MapProjectOdk.project_id == project_id)
    )
    if existing:
        if existing.connection_id == connection_id:
            return jsonify({"message": "Already assigned.", "project_id": project_id})
        existing.connection_id = connection_id
    else:
        db.session.add(MapProjectOdk(project_id=project_id, connection_id=connection_id))

    db.session.commit()
    return jsonify({"project_id": project_id, "connection_id": str(connection_id)}), 201


@admin.delete("/api/odk-connections/<uuid:connection_id>/assign-project/<project_id>")
@role_required("admin")
def admin_odk_unassign_project(connection_id, project_id):
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    mapping = db.session.scalar(
        sa.select(MapProjectOdk).where(
            MapProjectOdk.connection_id == connection_id,
            MapProjectOdk.project_id == project_id.upper(),
        )
    )
    if not mapping:
        return _json_error("Mapping not found.", 404)

    db.session.delete(mapping)
    db.session.commit()
    return jsonify({"message": "Project unassigned."})


@admin.get("/api/odk-connections/<uuid:connection_id>/odk-projects")
@role_required("admin")
def admin_odk_list_odk_projects(connection_id):
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    conn = db.session.get(MasOdkConnections, connection_id)
    if not conn:
        return _json_error("Connection not found.", 404)

    try:
        client = _get_odk_client_for_connection(conn)
        projects = guarded_odk_call(
            lambda: client.projects.list(),
            client=client,
        )
        return jsonify(
            {
                "odk_projects": [{"id": project.id, "name": project.name} for project in projects]
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
        client = _get_odk_client_for_connection(conn)
        forms = guarded_odk_call(
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
        return _json_error(f"Failed to fetch ODK forms: {exc}", 502)
