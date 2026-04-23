"""CRUD routes for stored ODK connections."""

import sqlalchemy as sa
from flask import jsonify, request
from flask_login import current_user

from app import db
from app.decorators import role_required
from app.models import MasOdkConnections, VaStatuses
from app.http.responses import json_error as _json_error
from app.routes.admin import admin
from app.routes.admin_sections import odk_connections as odk_routes


@admin.get("/api/odk-connections")
@role_required("admin")
def admin_odk_connections_list():
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    conns = db.session.scalars(
        sa.select(MasOdkConnections).order_by(MasOdkConnections.connection_name)
    ).all()
    result = [
        odk_routes._serialize_odk_connection(
            conn,
            odk_routes._get_connection_project_ids(conn.connection_id),
        )
        for conn in conns
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
        base_url = odk_routes._validate_odk_base_url(base_url)
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
        odk_routes.log.error(
            "ODK pepper not available for connection creation: %s",
            exc,
        )
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
    return jsonify(
        {"connection": odk_routes._serialize_odk_connection(conn, [])}
    ), 201


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
            base_url = odk_routes._validate_odk_base_url(base_url)
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
            odk_routes.log.error(
                "ODK pepper not available for connection update: %s",
                exc,
            )
            return _json_error("Server configuration error. Contact an administrator.", 500)

        if payload.get("username"):
            username = (payload["username"] or "").strip()
            if not username:
                return _json_error("username cannot be empty.", 400)
            conn.username_enc, conn.username_salt = encrypt_credential(username, pepper)

        if payload.get("password"):
            conn.password_enc, conn.password_salt = encrypt_credential(
                payload["password"],
                pepper,
            )

    if "status" in payload:
        try:
            conn.status = VaStatuses(payload["status"])
        except ValueError:
            return _json_error("Invalid status.", 400)

    db.session.commit()
    project_ids = odk_routes._get_connection_project_ids(connection_id)
    return jsonify(
        {"connection": odk_routes._serialize_odk_connection(conn, project_ids)}
    )


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
