"""Cookie and CSRF settings for the admin System health panel (api-v1.md rule 5).

Each row shows a setting's value and what it should be, never a secret: these
settings are booleans and SameSite names only. Read-only; nothing is changed.
"""

SAME_SITE_OK = ("lax", "strict")


def _row(key, value, expected, ok, detail=""):
    return {"key": key, "value": str(value), "expected": expected,
            "status": "ok" if ok else "warning", "detail": detail}


def security_settings_report(config, *, dev: bool) -> list[dict]:
    """One row per setting. *dev* is a debug or test app, where cookies are
    sent over plain HTTP on purpose, so Secure off is no warning there."""
    rows = []
    for key in ("SESSION_COOKIE_SAMESITE", "REMEMBER_COOKIE_SAMESITE"):
        value = config.get(key)
        rows.append(_row(key, value, "Lax or Strict", str(value).strip().lower() in SAME_SITE_OK))
    for key in ("SESSION_COOKIE_SECURE", "REMEMBER_COOKIE_SECURE"):
        value = bool(config.get(key))
        rows.append(_row(key, value, "True", value or dev,
                         "off on a dev or test app" if not value and dev else ""))
    httponly = bool(config.get("SESSION_COOKIE_HTTPONLY"))
    rows.append(_row("SESSION_COOKIE_HTTPONLY", httponly, "True", httponly))
    csrf_on = bool(config.get("WTF_CSRF_ENABLED", True))
    rows.append(_row("WTF_CSRF_ENABLED", csrf_on, "True", csrf_on))
    return rows
