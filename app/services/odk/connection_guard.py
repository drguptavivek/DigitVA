"""Shared pacing and cooldown guard for outbound ODK Central calls."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import time
import uuid

import requests
import sqlalchemy as sa
from flask import current_app

from app import db
from app.models.mas_odk_connections import MasOdkConnections


_RETRYABLE_ERROR_MARKERS = (
    "ConnectTimeout",
    "ConnectionError",
    "Max retries exceeded",
    "timed out",
    "HTTPSConnectionPool",
    "/v1/users/current",
    "Unauthorized",
    "Forbidden",
    "token",
    "expired",
    "auth",
)


class OdkConnectionCooldownError(RuntimeError):
    """Raised when a connection is temporarily blocked after repeated failures."""

    def __init__(
        self,
        connection_name: str,
        cooldown_until: datetime,
        last_failure_message: str | None = None,
    ):
        self.connection_name = connection_name
        self.cooldown_until = cooldown_until
        self.last_failure_message = last_failure_message or ""
        message = (
            f"ODK connection '{connection_name}' is in cooldown until "
            f"{cooldown_until.isoformat()}."
        )
        if self.last_failure_message:
            message = f"{message} Last failure: {self.last_failure_message}"
        super().__init__(message)


@dataclass(slots=True)
class OdkConnectionGuardSnapshot:
    """Operator-visible ODK connection guard state."""

    cooldown_until: datetime | None
    consecutive_failure_count: int
    last_failure_at: datetime | None
    last_failure_message: str | None
    last_success_at: datetime | None
    last_request_started_at: datetime | None

    @property
    def cooldown_active(self) -> bool:
        return bool(self.cooldown_until and self.cooldown_until > _utcnow())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _connection_uuid(connection_id) -> uuid.UUID | None:
    if connection_id is None:
        return None
    if isinstance(connection_id, uuid.UUID):
        return connection_id
    try:
        return uuid.UUID(str(connection_id))
    except (TypeError, ValueError):
        return None


def _threshold() -> int:
    return int(current_app.config.get("ODK_CONNECTION_FAILURE_THRESHOLD", 3))


def _cooldown_seconds() -> int:
    return int(current_app.config.get("ODK_CONNECTION_FAILURE_COOLDOWN_SECONDS", 300))


def _min_interval_seconds() -> float:
    return float(
        current_app.config.get("ODK_CONNECTION_MIN_REQUEST_INTERVAL_SECONDS", 0.5)
    )


def _row_to_snapshot(row) -> OdkConnectionGuardSnapshot:
    return OdkConnectionGuardSnapshot(
        cooldown_until=row.cooldown_until,
        consecutive_failure_count=row.consecutive_failure_count or 0,
        last_failure_at=row.last_failure_at,
        last_failure_message=row.last_failure_message,
        last_success_at=row.last_success_at,
        last_request_started_at=row.last_request_started_at,
    )


def snapshot_connection_guard_state(
    connection_id,
) -> OdkConnectionGuardSnapshot | None:
    """Return the latest shared guard state for an ODK connection."""
    conn_id = _connection_uuid(connection_id)
    if conn_id is None:
        return None
    with db.engine.connect() as connection:
        row = connection.execute(
            sa.select(
                MasOdkConnections.cooldown_until,
                MasOdkConnections.consecutive_failure_count,
                MasOdkConnections.last_failure_at,
                MasOdkConnections.last_failure_message,
                MasOdkConnections.last_success_at,
                MasOdkConnections.last_request_started_at,
            ).where(
                MasOdkConnections.connection_id == conn_id
            )
        ).mappings().first()
    if row is None:
        return None
    return OdkConnectionGuardSnapshot(
        cooldown_until=row["cooldown_until"],
        consecutive_failure_count=row["consecutive_failure_count"] or 0,
        last_failure_at=row["last_failure_at"],
        last_failure_message=row["last_failure_message"],
        last_success_at=row["last_success_at"],
        last_request_started_at=row["last_request_started_at"],
    )


def serialize_connection_guard_state(conn: MasOdkConnections) -> dict:
    """Return UI-safe ODK connection guard state for API responses."""
    snapshot = _row_to_snapshot(conn)
    return {
        "cooldown_active": snapshot.cooldown_active,
        "cooldown_until": (
            snapshot.cooldown_until.isoformat() if snapshot.cooldown_until else None
        ),
        "consecutive_failure_count": snapshot.consecutive_failure_count,
        "last_failure_at": (
            snapshot.last_failure_at.isoformat() if snapshot.last_failure_at else None
        ),
        "last_failure_message": snapshot.last_failure_message,
        "last_success_at": (
            snapshot.last_success_at.isoformat() if snapshot.last_success_at else None
        ),
        "last_request_started_at": (
            snapshot.last_request_started_at.isoformat()
            if snapshot.last_request_started_at
            else None
        ),
    }


def attach_connection_metadata(client, connection_id) -> None:
    """Tag a pyODK client/session with its shared ODK connection id."""
    conn_id = _connection_uuid(connection_id)
    if conn_id is None or client is None:
        return
    setattr(client, "_digitva_connection_id", conn_id)
    session = getattr(client, "session", None)
    if session is not None:
        setattr(session, "_digitva_connection_id", conn_id)


def get_client_connection_id(client) -> uuid.UUID | None:
    """Read the shared ODK connection id tagged onto a pyODK client/session."""
    if client is None:
        return None
    conn_id = getattr(client, "_digitva_connection_id", None)
    if conn_id is None:
        session = getattr(client, "session", None)
        conn_id = getattr(session, "_digitva_connection_id", None)
    return _connection_uuid(conn_id)


def is_retryable_odk_connectivity_error(exc: Exception) -> bool:
    """Return True when an ODK failure should count toward cooldown/backoff."""
    if isinstance(exc, OdkConnectionCooldownError):
        return False

    if isinstance(
        exc,
        (
            requests.exceptions.ConnectTimeout,
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
        ),
    ):
        return True

    status_code = getattr(getattr(exc, "response", None), "status_code", None)
    if status_code in (401, 403):
        return True

    message = str(exc)
    return any(marker in message for marker in _RETRYABLE_ERROR_MARKERS)


def reserve_odk_request_slot(connection_id) -> float:
    """Reserve the next allowed request slot for a connection and return wait time."""
    conn_id = _connection_uuid(connection_id)
    if conn_id is None:
        return 0.0

    min_interval = _min_interval_seconds()
    if min_interval <= 0:
        ensure_connection_not_in_cooldown(conn_id)
        return 0.0

    now = _utcnow()
    wait_seconds = 0.0

    with db.engine.begin() as connection:
        row = connection.execute(
            sa.select(
                MasOdkConnections.connection_name,
                MasOdkConnections.cooldown_until,
                MasOdkConnections.last_failure_message,
                MasOdkConnections.last_request_started_at,
            )
            .where(MasOdkConnections.connection_id == conn_id)
            .with_for_update()
        ).mappings().first()

        if row is None:
            return 0.0

        cooldown_until = row["cooldown_until"]
        if cooldown_until and cooldown_until > now:
            raise OdkConnectionCooldownError(
                row["connection_name"],
                cooldown_until,
                row["last_failure_message"],
            )

        reserved_for = now
        last_started = row["last_request_started_at"]
        if last_started is not None:
            next_allowed = last_started + timedelta(seconds=min_interval)
            if next_allowed > reserved_for:
                reserved_for = next_allowed

        connection.execute(
            sa.update(MasOdkConnections)
            .where(MasOdkConnections.connection_id == conn_id)
            .values(
                last_request_started_at=reserved_for,
                updated_at=now,
            )
        )
        wait_seconds = max(0.0, (reserved_for - now).total_seconds())

    return wait_seconds


def ensure_connection_not_in_cooldown(connection_id) -> None:
    """Fail fast when a connection is in cooldown."""
    conn_id = _connection_uuid(connection_id)
    if conn_id is None:
        return

    with db.engine.connect() as connection:
        row = connection.execute(
            sa.select(
                MasOdkConnections.connection_name,
                MasOdkConnections.cooldown_until,
                MasOdkConnections.last_failure_message,
            ).where(
                MasOdkConnections.connection_id == conn_id
            )
        ).mappings().first()
    if row is None:
        return

    if row["cooldown_until"] and row["cooldown_until"] > _utcnow():
        raise OdkConnectionCooldownError(
            row["connection_name"],
            row["cooldown_until"],
            row["last_failure_message"],
        )


def record_odk_connection_success(connection_id) -> None:
    """Reset shared failure state after a successful ODK request."""
    conn_id = _connection_uuid(connection_id)
    if conn_id is None:
        return

    now = _utcnow()
    with db.engine.begin() as connection:
        connection.execute(
            sa.update(MasOdkConnections)
            .where(MasOdkConnections.connection_id == conn_id)
            .values(
                consecutive_failure_count=0,
                cooldown_until=None,
                last_success_at=now,
                updated_at=now,
            )
        )


def record_odk_connection_failure(connection_id, exc: Exception) -> None:
    """Persist shared failure state and activate cooldown when threshold is met."""
    conn_id = _connection_uuid(connection_id)
    if conn_id is None:
        return
    if not is_retryable_odk_connectivity_error(exc):
        return

    now = _utcnow()
    cooldown_for = _cooldown_seconds()
    failure_message = str(exc)

    with db.engine.begin() as connection:
        row = connection.execute(
            sa.select(
                MasOdkConnections.consecutive_failure_count,
                MasOdkConnections.cooldown_until,
            )
            .where(MasOdkConnections.connection_id == conn_id)
            .with_for_update()
        ).mappings().first()
        if row is None:
            return

        failure_count = int(row["consecutive_failure_count"] or 0) + 1
        cooldown_until = row["cooldown_until"]
        if cooldown_for > 0 and failure_count >= _threshold():
            cooldown_until = now + timedelta(seconds=cooldown_for)

        connection.execute(
            sa.update(MasOdkConnections)
            .where(MasOdkConnections.connection_id == conn_id)
            .values(
                consecutive_failure_count=failure_count,
                cooldown_until=cooldown_until,
                last_failure_at=now,
                last_failure_message=failure_message[:1000],
                updated_at=now,
            )
        )


def guarded_odk_call(
    callback,
    *,
    client=None,
    connection_id=None,
):
    """Run an ODK call with shared cooldown, pacing, and failure tracking."""
    conn_id = _connection_uuid(connection_id) or get_client_connection_id(client)
    if conn_id is None:
        return callback()

    wait_seconds = reserve_odk_request_slot(conn_id)
    if wait_seconds > 0:
        time.sleep(wait_seconds)

    try:
        result = callback()
    except Exception as exc:
        record_odk_connection_failure(conn_id, exc)
        raise

    record_odk_connection_success(conn_id)
    return result
