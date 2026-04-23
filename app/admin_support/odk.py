import ipaddress
import os
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

import sqlalchemy as sa
from flask import current_app

from app import db
from app.models import MapProjectOdk, MasOdkConnections, VaStatuses
from app.serializers import serialize_odk_connection
from app.services.odk_connection_guard_service import serialize_connection_guard_state

_BLOCKED_HOSTNAMES = frozenset({"localhost", "metadata.google.internal"})


def validate_odk_base_url(raw: str) -> str:
    try:
        parsed = urlparse(raw)
    except Exception:
        raise ValueError("Malformed URL.")
    if parsed.scheme not in ("http", "https"):
        raise ValueError("Only http and https schemes are allowed.")
    hostname = (parsed.hostname or "").lower()
    if not hostname:
        raise ValueError("URL must include a hostname.")
    if hostname in _BLOCKED_HOSTNAMES:
        raise ValueError("That hostname is not allowed.")
    try:
        addr = ipaddress.ip_address(hostname)
        if addr.is_loopback or addr.is_private or addr.is_link_local or addr.is_reserved:
            raise ValueError("Private, loopback, and link-local addresses are not allowed.")
    except ValueError as exc:
        if "not allowed" in str(exc) or "Malformed" in str(exc):
            raise
    return raw.rstrip("/")


def get_connection_project_ids(connection_id: uuid.UUID) -> list[str]:
    rows = db.session.scalars(
        sa.select(MapProjectOdk.project_id).where(MapProjectOdk.connection_id == connection_id)
    ).all()
    return sorted(rows)


def serialize_connection(conn) -> dict:
    return serialize_odk_connection(
        conn,
        get_connection_project_ids(conn.connection_id),
        serialize_connection_guard_state(conn),
    )


def odk_connection_alerts() -> list[dict]:
    now = datetime.now(timezone.utc)
    conns = db.session.scalars(
        sa.select(MasOdkConnections)
        .where(MasOdkConnections.status == VaStatuses.active)
        .order_by(MasOdkConnections.connection_name)
    ).all()

    alerts = []
    for conn in conns:
        guard = serialize_connection_guard_state(conn)
        if not (guard["cooldown_active"] or guard["consecutive_failure_count"] > 0):
            continue
        alerts.append(
            {
                "connection_id": str(conn.connection_id),
                "connection_name": conn.connection_name,
                "base_url": conn.base_url,
                "guard": guard,
                "cooldown_remaining_seconds": (
                    max(0, int((conn.cooldown_until - now).total_seconds()))
                    if conn.cooldown_until and conn.cooldown_until > now
                    else 0
                ),
            }
        )
    return alerts


def get_odk_client_for_connection(conn: MasOdkConnections):
    from app.utils.va_odk.va_odk_01_clientsetup import client_from_connection

    pyodk_dir = os.path.join(current_app.config.get("APP_RESOURCE"), "pyodk")
    return client_from_connection(conn, pyodk_dir)
