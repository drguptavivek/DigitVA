from __future__ import annotations

import time
from typing import Any

from flask import current_app

from app import cache


def _normalize_ip(ip_address: str | None) -> str | None:
    if not ip_address:
        return None
    normalized = ip_address.strip()
    return normalized or None


def _tracked_methods() -> set[str]:
    configured = current_app.config.get(
        "METHOD_NOT_ALLOWED_BAN_METHODS",
        ("POST", "PATCH"),
    )
    return {
        str(method).strip().upper()
        for method in configured
        if str(method).strip()
    }


def _counter_key(ip_address: str) -> str:
    prefix = current_app.config.get(
        "METHOD_NOT_ALLOWED_BAN_COUNTER_PREFIX",
        "digitva_method_not_allowed:count:",
    )
    return f"{prefix}{ip_address}"


def _ban_key(ip_address: str) -> str:
    prefix = current_app.config.get(
        "METHOD_NOT_ALLOWED_BAN_PREFIX",
        "digitva_method_not_allowed:ban:",
    )
    return f"{prefix}{ip_address}"


def abuse_ban_message() -> str:
    return current_app.config.get(
        "METHOD_NOT_ALLOWED_BAN_MESSAGE",
        (
            "Access temporarily blocked because this IP sent repeated invalid "
            "POST/PATCH requests to routes that do not allow those methods. "
            "Try again later."
        ),
    )


def is_method_not_allowed_ban_enabled() -> bool:
    return bool(current_app.config.get("METHOD_NOT_ALLOWED_BAN_ENABLED", True))


def is_tracked_method(method: str | None) -> bool:
    if not method:
        return False
    return method.upper() in _tracked_methods()


def get_temporary_ban(ip_address: str | None) -> dict[str, Any] | None:
    normalized_ip = _normalize_ip(ip_address)
    if not normalized_ip or not is_method_not_allowed_ban_enabled():
        return None

    payload = cache.get(_ban_key(normalized_ip))
    if not payload:
        return None

    now = int(time.time())
    expires_at = int(payload.get("expires_at", 0))
    if expires_at <= now:
        cache.delete(_ban_key(normalized_ip))
        return None

    remaining_seconds = max(expires_at - now, 1)
    return {
        "ip_address": normalized_ip,
        "remaining_seconds": remaining_seconds,
        "trigger_count": int(payload.get("trigger_count", 0)),
        "last_method": payload.get("last_method"),
        "last_path": payload.get("last_path"),
        "banned_at": int(payload.get("banned_at", now)),
        "expires_at": expires_at,
    }


def is_ip_temporarily_banned(ip_address: str | None) -> bool:
    return get_temporary_ban(ip_address) is not None


def record_method_not_allowed_abuse(
    ip_address: str | None,
    *,
    method: str | None,
    path: str,
) -> dict[str, Any]:
    normalized_ip = _normalize_ip(ip_address)
    normalized_method = (method or "").upper()
    if (
        not normalized_ip
        or not is_method_not_allowed_ban_enabled()
        or normalized_method not in _tracked_methods()
    ):
        return {"tracked": False, "banned": False}

    now = int(time.time())
    window_seconds = int(
        current_app.config.get("METHOD_NOT_ALLOWED_BAN_WINDOW_SECONDS", 600)
    )
    threshold = int(current_app.config.get("METHOD_NOT_ALLOWED_BAN_THRESHOLD", 10))
    ban_seconds = int(current_app.config.get("METHOD_NOT_ALLOWED_BAN_SECONDS", 3600))

    counter_payload = cache.get(_counter_key(normalized_ip)) or {
        "count": 0,
        "first_seen_at": now,
    }
    count = int(counter_payload.get("count", 0)) + 1
    updated_counter = {
        "count": count,
        "first_seen_at": int(counter_payload.get("first_seen_at", now)),
        "last_seen_at": now,
        "last_method": normalized_method,
        "last_path": path,
    }
    cache.set(_counter_key(normalized_ip), updated_counter, timeout=window_seconds)

    if count < threshold:
        return {
            "tracked": True,
            "banned": False,
            "count": count,
            "threshold": threshold,
        }

    ban_payload = {
        "banned_at": now,
        "expires_at": now + ban_seconds,
        "trigger_count": count,
        "last_method": normalized_method,
        "last_path": path,
    }
    cache.set(_ban_key(normalized_ip), ban_payload, timeout=ban_seconds)
    cache.delete(_counter_key(normalized_ip))

    current_app.logger.warning(
        "method_not_allowed_ip_banned ip=%s method=%s path=%s count=%s window_seconds=%s ban_seconds=%s",
        normalized_ip,
        normalized_method,
        path,
        count,
        window_seconds,
        ban_seconds,
    )

    return {
        "tracked": True,
        "banned": True,
        "count": count,
        "threshold": threshold,
        "ban_seconds": ban_seconds,
        "expires_at": ban_payload["expires_at"],
    }
