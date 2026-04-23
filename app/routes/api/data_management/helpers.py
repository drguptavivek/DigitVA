from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime

from flask import Response, current_app, request
from flask_login import current_user

from app import cache

log = logging.getLogger(__name__)
_CACHE_TTL = 300
_EXPORT_CACHE_TTL = 900
_EXPORT_FILTER_KEYS = (
    "search",
    "project",
    "site",
    "date_from",
    "date_to",
    "odk_status",
    "smartva",
    "age_group",
    "gender",
    "odk_sync",
    "workflow",
)


def cache_result(key: str, compute_fn, timeout: int = _CACHE_TTL):
    full_key = f"dm_analytics:{current_user.user_id}:{key}:{request.query_string.decode()}"
    try:
        data = cache.get(full_key)
    except Exception:
        data = None
    if data is not None and not isinstance(data, BaseException):
        return data

    data = compute_fn()
    try:
        cache.set(full_key, data, timeout=timeout)
    except Exception as exc:
        log.warning("Data-manager cache set failed (%s): %s", full_key, exc, exc_info=True)
    return data


def refresh_dm_dashboard_analytics(refresh_fn) -> None:
    """Refresh analytics and clear cache after workflow-mutating DM actions."""
    refresh_fn(concurrently=False)
    try:
        cache.clear()
    except Exception as exc:
        log.warning(
            "Data-manager cache clear failed after analytics refresh: %s",
            exc,
            exc_info=True,
        )


def export_filters_from_request() -> dict[str, str | None]:
    return {
        "search": request.args.get("search", ""),
        "project": request.args.get("project", ""),
        "site": request.args.get("site", ""),
        "date_from": request.args.get("date_from") or None,
        "date_to": request.args.get("date_to") or None,
        "odk_status": request.args.get("odk_status", ""),
        "smartva": request.args.get("smartva", ""),
        "age_group": request.args.get("age_group", ""),
        "gender": request.args.get("gender", ""),
        "odk_sync": request.args.get("odk_sync", ""),
        "workflow": request.args.get("workflow", ""),
    }


def _export_cache_ttl_seconds() -> int:
    value = current_app.config.get("DM_EXPORT_CACHE_TTL_SECONDS", _EXPORT_CACHE_TTL)
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return _EXPORT_CACHE_TTL


def _export_cache_dir() -> str:
    app_data = current_app.config.get("APP_DATA")
    if not app_data:
        app_data = os.path.join(current_app.instance_path, "data")
    directory = os.path.join(app_data, "exports", "cache")
    os.makedirs(directory, exist_ok=True)
    return directory


def _export_cache_key(export_kind: str, filters: dict[str, str | None]) -> str:
    payload = {
        "kind": export_kind,
        "user_id": str(current_user.user_id),
        "filters": {key: filters.get(key) for key in _EXPORT_FILTER_KEYS},
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _read_cached_export(cache_path: str, ttl_seconds: int) -> str | None:
    if ttl_seconds <= 0:
        return None
    try:
        stat = os.stat(cache_path)
    except OSError:
        return None
    age_seconds = max(0.0, datetime.utcnow().timestamp() - stat.st_mtime)
    if age_seconds > ttl_seconds:
        return None
    try:
        with open(cache_path, "r", encoding="utf-8", newline="") as handle:
            return handle.read()
    except OSError:
        return None


def _write_cached_export(cache_path: str, csv_text: str) -> None:
    temp_path = f"{cache_path}.tmp.{os.getpid()}"
    with open(temp_path, "w", encoding="utf-8", newline="") as handle:
        handle.write(csv_text)
    os.replace(temp_path, cache_path)


def _cleanup_export_cache(directory: str, ttl_seconds: int) -> None:
    retention_seconds = max(ttl_seconds * 4, 3600)
    cutoff = datetime.utcnow().timestamp() - retention_seconds
    try:
        names = os.listdir(directory)
    except OSError:
        return
    for name in names:
        if not name.endswith(".csv"):
            continue
        path = os.path.join(directory, name)
        try:
            if os.path.getmtime(path) < cutoff:
                os.remove(path)
        except OSError:
            continue


def _csv_response(csv_text: str, filename_prefix: str, cache_status: str) -> Response:
    filename = f"{filename_prefix}-{datetime.utcnow():%Y%m%d-%H%M%S}.csv"
    return Response(
        "\ufeff" + csv_text,
        content_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Export-Cache": cache_status,
        },
    )


def serve_cached_export_csv(export_kind: str, filename_prefix: str, export_fn) -> Response:
    filters = export_filters_from_request()
    ttl_seconds = _export_cache_ttl_seconds()
    cache_dir = _export_cache_dir()
    cache_key = _export_cache_key(export_kind, filters)
    cache_path = os.path.join(cache_dir, f"{cache_key}.csv")

    cached_csv = _read_cached_export(cache_path, ttl_seconds)
    if cached_csv is not None:
        return _csv_response(cached_csv, filename_prefix, cache_status="HIT")

    csv_text = export_fn(current_user, **filters)
    try:
        _write_cached_export(cache_path, csv_text)
        _cleanup_export_cache(cache_dir, ttl_seconds)
    except OSError as exc:
        log.warning("Export cache write failed (%s): %s", cache_path, exc)
        return _csv_response(csv_text, filename_prefix, cache_status="BYPASS")
    return _csv_response(csv_text, filename_prefix, cache_status="MISS")
