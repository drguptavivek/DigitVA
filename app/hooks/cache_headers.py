from time import perf_counter

from flask import g, request
from werkzeug.http import http_date

from app.logging.va_logger import slow_request_logger

#: API paths whose responses are never stored by a browser or proxy.
_NO_STORE_API_PREFIXES = ("/api/v1/me/", "/api/v1/intake/", "/api/v1/cases",
                         "/api/v1/coding/")


def register_cache_headers(app):
    """Cache-Control, Date and request-timing headers on every response, and
    the slow-request log line (timers started by force_password_update)."""
    @app.after_request
    def apply_static_cache_headers(response):
        # Browser intake carries identifiers and questionnaire answers, and the
        # case list and intake replies carry registration numbers. This
        # applies to errors and redirects as well as successful JSON responses
        # (including a request refused before it reaches a blueprint, such as
        # a CSRF or terms refusal; the cases, intake and bundles blueprints
        # rely on this hook alone, digitva-r8nh.5).
        if request.path.startswith(_NO_STORE_API_PREFIXES):
            response.headers["Cache-Control"] = "no-store"
        # The phone measures its clock offset from this header on every
        # response (docs/policy/field-data-collection.md "Phone clock").
        response.headers.setdefault("Date", http_date())
        if request.path.startswith("/static/") and response.status_code == 200:
            response.cache_control.public = True
            response.cache_control.max_age = app.config["STATIC_ASSET_CACHE_MAX_AGE"]
        started_at = getattr(g, "_request_started_at", None)
        if started_at is not None:
            duration_ms = (perf_counter() - started_at) * 1000
            response.headers["Server-Timing"] = f"app;dur={duration_ms:.1f}"
            response.headers["X-Response-Time"] = f"{duration_ms:.1f}ms"
        slow_started_at = getattr(g, "_slow_started_at", None)
        if slow_started_at is not None:
            slow_ms = (perf_counter() - slow_started_at) * 1000
            if slow_ms >= app.config["SLOW_REQUEST_LOG_MS"]:
                # Route pattern, never request.path: paths carry case ids.
                slow_request_logger.info(
                    "event=slow_request method=%s endpoint=%s rule=%s status=%s "
                    "duration_ms=%.1f sql_count=%d sql_ms=%.1f",
                    request.method,
                    request.endpoint or "-",
                    request.url_rule.rule if request.url_rule else "-",
                    response.status_code,
                    slow_ms,
                    getattr(g, "_sql_count", 0),
                    getattr(g, "_sql_ms", 0.0),
                )
        return response
