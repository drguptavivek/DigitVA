"""Bounded first-party app performance telemetry (digitva-yv2n).

Only coarse daily counters are kept in Redis. The random batch UUID is a
retry key, never a device identifier; no request body or clinical payload is
logged or stored.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import UTC, date, datetime, timedelta

import sqlalchemy as sa
from flask import current_app, has_app_context

from app import cache, db
from app.models import AuthDevice, AuthDeviceSession, VaProjectMaster, VaStatuses
from app.services.project_country_service import parse_project_country

RETENTION_SECONDS = 90 * 24 * 60 * 60
MAX_BODY_BYTES = 8 * 1024
MAX_CELL_COUNT = 1024
MIN_REPORT_BATCHES = 20
MAX_REPORT_DAYS = 31

_APP_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_ROOT_KEYS = frozenset({
    "schema", "batch_id", "day", "app_version", "variant", "platform", "device_type",
    "ram_bucket", "core_bucket", "manufacturer", "metrics",
})
_METRIC_KEYS = frozenset({"foreground_ms", "launches", "crashes", "errors"})
_ENUMS = {
    "variant": frozenset({"collect", "plus"}),
    "platform": frozenset({"android"}),
    "device_type": frozenset({"phone", "tablet", "emulator", "other"}),
    "ram_bucket": frozenset({"unknown", "lt2", "2_3", "4_5", "6_7", "8_11", "12plus"}),
    "core_bucket": frozenset({"unknown", "1_2", "3_4", "5_8", "9plus"}),
    "manufacturer": frozenset({
        "unknown", "samsung", "google", "xiaomi", "oneplus", "motorola", "oppo", "vivo", "apple", "other",
    }),
}
_METRIC_LIMITS = {
    "foreground_ms": 86_400_000,
    "launches": 1_000,
    "crashes": 1_000,
    "errors": 1_000,
}


class AppTelemetryError(ValueError):
    """A safe API refusal with a fixed machine code and HTTP status."""

    def __init__(self, message: str, code: str = "invalid_request", status: int = 400):
        super().__init__(message)
        self.code = code
        self.status = status


_INGEST = """
local dedup = KEYS[1]
local index = KEYS[2]
local cell = KEYS[3]
if redis.call('EXISTS', dedup) == 1 then return 0 end
if redis.call('EXISTS', cell) == 0 then
  if redis.call('SCARD', index) >= tonumber(ARGV[1]) then return -1 end
  redis.call('SADD', index, ARGV[2])
end
redis.call('SET', dedup, '1', 'EX', ARGV[3])
redis.call('HSET', cell,
  'day', ARGV[4], 'app_version', ARGV[5], 'variant', ARGV[6],
  'platform', ARGV[7], 'device_type', ARGV[8], 'ram_bucket', ARGV[9],
  'core_bucket', ARGV[10], 'manufacturer', ARGV[11], 'country', ARGV[12], 'state', ARGV[13])
redis.call('HINCRBY', cell, 'accepted_batches', 1)
redis.call('HINCRBY', cell, 'foreground_ms', ARGV[14])
redis.call('HINCRBY', cell, 'launches', ARGV[15])
redis.call('HINCRBY', cell, 'crashes', ARGV[16])
redis.call('HINCRBY', cell, 'errors', ARGV[17])
redis.call('EXPIRE', cell, ARGV[3])
redis.call('EXPIRE', index, ARGV[3])
return 1
"""


def _redis():
    if not has_app_context():
        return None
    try:
        return getattr(cache.cache, "_write_client", None)
    except Exception:  # noqa: BLE001 - telemetry is optional infrastructure
        return None


def _prefix() -> str:
    return current_app.config.get("APP_TELEMETRY_REDIS_PREFIX", "digitva:app-performance:")


def _day_key(day: date) -> str:
    return f"{_prefix()}day:{day.isoformat()}"


def _cell_key(day: date, cell_id: str) -> str:
    return f"{_prefix()}cell:{day.isoformat()}:{cell_id}"


def _dedup_key(batch_id: str) -> str:
    return f"{_prefix()}batch:{batch_id}"


def _parse_date(value) -> date:
    if not isinstance(value, str):
        raise AppTelemetryError("day must be YYYY-MM-DD.")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise AppTelemetryError("day must be YYYY-MM-DD.") from None
    today = datetime.now(UTC).date()
    if not today - timedelta(days=7) <= parsed <= today:
        raise AppTelemetryError("day must be today or within the last 7 days.")
    return parsed


def validate_batch(payload) -> dict:
    """Validate and normalize the exact public batch schema."""
    if not isinstance(payload, dict) or set(payload) != _ROOT_KEYS:
        raise AppTelemetryError("Telemetry batch has unknown or missing fields.")
    if type(payload["schema"]) is not int or payload["schema"] != 1:
        raise AppTelemetryError("schema must be 1.")
    try:
        batch_id = str(uuid.UUID(payload["batch_id"]))
    except (ValueError, TypeError, AttributeError):
        raise AppTelemetryError("batch_id must be a UUID.") from None
    version = payload["app_version"]
    if not isinstance(version, str) or len(version) > 20 or not _APP_VERSION.fullmatch(version):
        raise AppTelemetryError("app_version must be numeric semantic version text of at most 20 characters.")
    parsed = {"schema": 1, "batch_id": batch_id, "day": _parse_date(payload["day"]), "app_version": version}
    for key, allowed in _ENUMS.items():
        value = payload[key]
        if not isinstance(value, str) or value not in allowed:
            raise AppTelemetryError(f"{key} is not a supported value.")
        parsed[key] = value
    metrics = payload["metrics"]
    if not isinstance(metrics, dict) or set(metrics) != _METRIC_KEYS:
        raise AppTelemetryError("metrics has unknown or missing fields.")
    parsed["metrics"] = {}
    for key, limit in _METRIC_LIMITS.items():
        value = metrics[key]
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= limit:
            raise AppTelemetryError(f"metrics.{key} is outside its allowed range.")
        parsed["metrics"][key] = value
    return parsed


def _authorized_dimensions(session: AuthDeviceSession) -> tuple[str, str]:
    """Return canonical project country/state, never values from the client."""
    project = db.session.scalar(
        sa.select(VaProjectMaster)
        .join(AuthDevice, AuthDevice.project_id == VaProjectMaster.project_id)
        .where(AuthDevice.device_id == session.device_id, VaProjectMaster.project_status == VaStatuses.active)
    )
    country, problem = parse_project_country(project.project_country_iso3 if project else None)
    return (country if problem is None and country else "unknown", "unknown")


def ingest(user, session: AuthDeviceSession, payload) -> bool:
    """Validate and atomically accept one native-device batch.

    Returns ``True`` for a newly accepted batch and ``False`` for a duplicate.
    Redis outage and a full bounded day return retryable 503 errors.
    """
    batch = validate_batch(payload)
    client = _redis()
    if client is None:
        raise AppTelemetryError("Performance telemetry is temporarily unavailable.", "unavailable", 503)
    country, state = _authorized_dimensions(session)
    dimensions = (
        batch["day"].isoformat(), batch["app_version"], batch["variant"], batch["platform"],
        batch["device_type"], batch["ram_bucket"], batch["core_bucket"], batch["manufacturer"], country, state,
    )
    cell_id = hashlib.sha256("|".join(dimensions).encode("utf-8")).hexdigest()
    args = [
        MAX_CELL_COUNT, cell_id, RETENTION_SECONDS, *dimensions,
        *(batch["metrics"][key] for key in ("foreground_ms", "launches", "crashes", "errors")),
    ]
    try:
        result = int(client.eval(
            _INGEST,
            3,
            _dedup_key(batch["batch_id"]),
            _day_key(batch["day"]),
            _cell_key(batch["day"], cell_id),
            *args,
        ))
    except Exception as exc:  # noqa: BLE001 - Redis failure is retryable
        raise AppTelemetryError("Performance telemetry is temporarily unavailable.", "unavailable", 503) from exc
    if result < 0:
        raise AppTelemetryError("Performance telemetry is temporarily full; retry later.", "unavailable", 503)
    return result == 1


def _report_days(start: date | None, end: date | None) -> tuple[date, date]:
    today = datetime.now(UTC).date()
    end = end or today
    start = start or end - timedelta(days=6)
    if start > end or (end - start).days + 1 > MAX_REPORT_DAYS or end > today:
        raise AppTelemetryError("Report window must be at most 31 days and not in the future.")
    return start, end


def report(start: date | None = None, end: date | None = None) -> dict:
    """Read bounded daily cells and suppress groups smaller than 20 batches."""
    start, end = _report_days(start, end)
    client = _redis()
    if client is None:
        raise AppTelemetryError("Performance telemetry is temporarily unavailable.", "unavailable", 503)
    cells = []
    summary = {"accepted_batches": 0, "foreground_ms": 0, "launches": 0, "crashes": 0, "errors": 0}
    try:
        for offset in range((end - start).days + 1):
            day = start + timedelta(days=offset)
            cell_ids = client.smembers(_day_key(day))
            bounded_ids = list(cell_ids)[:MAX_CELL_COUNT]
            pipe = client.pipeline(transaction=False)
            for raw_id in bounded_ids:
                cell_id = raw_id.decode() if isinstance(raw_id, bytes) else str(raw_id)
                pipe.hgetall(_cell_key(day, cell_id))
            rows = pipe.execute()
            for raw_id, row in zip(bounded_ids, rows):
                if not row:
                    continue
                row = {
                    (key.decode() if isinstance(key, bytes) else str(key)):
                    (value.decode() if isinstance(value, bytes) else value)
                    for key, value in row.items()
                }
                count = int(row.get("accepted_batches", 0))
                for key in summary:
                    summary[key] += int(row.get(key, 0))
                if count < MIN_REPORT_BATCHES:
                    continue
                cells.append({
                    "day": row.get("day"), "app_version": row.get("app_version"),
                    "variant": row.get("variant"), "platform": row.get("platform"),
                    "device_type": row.get("device_type"), "ram_bucket": row.get("ram_bucket"),
                    "core_bucket": row.get("core_bucket"), "manufacturer": row.get("manufacturer"),
                    "country": row.get("country", "unknown"), "state": row.get("state", "unknown"),
                    "accepted_batches": count,
                    "metrics": {key: int(row.get(key, 0)) for key in _METRIC_LIMITS},
                })
    except Exception as exc:  # noqa: BLE001 - report outage is retryable
        raise AppTelemetryError("Performance telemetry is temporarily unavailable.", "unavailable", 503) from exc
    return {"from": start.isoformat(), "to": end.isoformat(), "cells": cells, "summary": summary}
