import logging
import os
import sys
import time
import uuid
from contextvars import ContextVar
from logging.handlers import TimedRotatingFileHandler
from typing import Any

from flask import g, has_request_context, jsonify, render_template, request, session
from flask_limiter.errors import RateLimitExceeded
from flask_login import current_user
from sqlalchemy import event
from sqlalchemy.engine import Engine
from werkzeug.exceptions import HTTPException

# Rotate high-volume logs every 6 hours and keep two weeks of history.
LOG_ROTATION_HOURS = 6
LOG_BACKUP_COUNT = 56
SLOW_QUERY_THRESHOLD_S = 0.5

SENSITIVE_FIELDS = [
    "password",
    "token",
    "csrf_token",
    "new_password",
    "va_current_password",
    "va_new_password",
    "va_confirm_password",
    "confirm_password",
]

# Create logs directory
va_log = "logs"
os.makedirs(va_log, exist_ok=True)


_request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")


def set_request_id(request_id: str | None) -> None:
    if request_id:
        _request_id_ctx.set(str(request_id))


def clear_request_id() -> None:
    _request_id_ctx.set("-")


def _extract_celery_context() -> tuple[str, str]:
    try:
        from celery import current_task

        task = current_task
    except Exception:
        task = None

    if task is None or getattr(task, "request", None) is None:
        return "-", "-"

    task_name = getattr(task, "name", "-") or "-"
    task_request = task.request
    task_id = getattr(task_request, "id", "-") or "-"
    root_id = getattr(task_request, "root_id", None)
    if root_id:
        set_request_id(root_id)
    return task_name, str(task_id)


class LogContextFilter(logging.Filter):
    """Attach request/task correlation fields required by log formatters."""

    def filter(self, record: logging.LogRecord) -> bool:
        request_id = _request_id_ctx.get()
        if has_request_context():
            request_id = getattr(g, "request_id", request_id)
        task_name, task_id = _extract_celery_context()

        record.request_id = getattr(record, "request_id", request_id)
        record.task_name = getattr(record, "task_name", task_name)
        record.task_id = getattr(record, "task_id", task_id)
        return True


# Formatters
va_detailed_formatter = logging.Formatter(
    "%(asctime)s - %(levelname)s - %(name)s - "
    "[request_id=%(request_id)s task=%(task_name)s/%(task_id)s] "
    "%(message)s [in %(pathname)s:%(lineno)d]"
)

grant_audit_formatter = logging.Formatter(
    "%(asctime)s [request_id=%(request_id)s] %(message)s"
)


def _build_rotating_handler(log_file: str, formatter: logging.Formatter) -> TimedRotatingFileHandler:
    handler = TimedRotatingFileHandler(
        filename=log_file,
        when="h",
        interval=LOG_ROTATION_HOURS,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
        utc=True,
    )
    handler.setFormatter(formatter)
    handler.addFilter(LogContextFilter())
    return handler


# Setup logger
def va_setup_logger(
    name: str,
    log_file: str,
    level: int = logging.INFO,
    formatter: logging.Formatter | None = None,
    stderr: bool = False,
) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = False
    fmt = formatter or va_detailed_formatter
    abs_log_file = os.path.abspath(log_file)

    has_file_handler = any(
        isinstance(handler, TimedRotatingFileHandler)
        and getattr(handler, "baseFilename", "") == abs_log_file
        for handler in logger.handlers
    )
    if not has_file_handler:
        logger.addHandler(_build_rotating_handler(abs_log_file, fmt))

    if stderr:
        has_stderr = any(
            isinstance(handler, logging.StreamHandler)
            and getattr(handler, "stream", None) is sys.stderr
            for handler in logger.handlers
        )
        if not has_stderr:
            stream_handler = logging.StreamHandler(sys.stderr)
            stream_handler.setFormatter(fmt)
            stream_handler.addFilter(LogContextFilter())
            logger.addHandler(stream_handler)

    return logger


# Initialize loggers
request_logger = va_setup_logger(
    "REQUEST_LOG",
    f"{va_log}/requests.log",
    logging.INFO,
    va_detailed_formatter,
)
response_logger = va_setup_logger(
    "RESPONSE_LOG",
    f"{va_log}/responses.log",
    logging.INFO,
    va_detailed_formatter,
)
error_logger = va_setup_logger(
    "ERROR_LOG",
    f"{va_log}/errors.log",
    logging.ERROR,
    va_detailed_formatter,
    stderr=True,
)
sql_logger = va_setup_logger(
    "SQL_LOG",
    f"{va_log}/sql.log",
    logging.INFO,
    va_detailed_formatter,
)
grant_audit_logger = va_setup_logger(
    "GRANT_AUDIT",
    f"{va_log}/grants.log",
    logging.INFO,
    grant_audit_formatter,
)


def log_grant_action(
    *,
    action: str,
    actor_user_id,
    actor_role: str,
    target_user_id,
    grant_id,
    role: str,
    scope_type: str,
    project_id=None,
    project_site_id=None,
    request_ip: str | None = None,
):
    """Write a structured line to grants.log for every grant mutation.

    Fields (pipe-separated for easy grep / awk):
      action | actor | actor_role | target | grant_id | role | scope | project | site | ip
    """
    grant_audit_logger.info(
        "action=%s actor=%s actor_role=%s target=%s grant_id=%s role=%s scope=%s project=%s site=%s ip=%s",
        action,
        actor_user_id,
        actor_role,
        target_user_id,
        grant_id,
        role,
        scope_type,
        project_id or "-",
        project_site_id or "-",
        request_ip or "-",
    )


def _safe_current_user_email() -> str:
    user_id = session.get("_user_id")
    if user_id:
        try:
            from app import db
            from app.models import VaUsers

            user = db.session.get(VaUsers, uuid.UUID(user_id))
            if user is not None:
                return user.email
        except Exception:
            return "anonymous"
    try:
        if current_user.is_authenticated:
            return current_user.email
    except Exception:
        return "anonymous"
    return "anonymous"


def _masked_request_payload() -> dict[str, Any] | None:
    request_data: dict[str, Any] | None = None
    if request.content_type == "application/json":
        raw = request.get_json(silent=True)
        request_data = dict(raw) if isinstance(raw, dict) else None
    elif request.form:
        request_data = request.form.to_dict()

    if request_data:
        for field in SENSITIVE_FIELDS:
            if field in request_data:
                request_data[field] = "***"
    return request_data


def _payload_summary(payload: dict[str, Any] | None) -> str:
    if not payload:
        return "-"
    keys = sorted(payload.keys())
    preview_keys = keys[:20]
    suffix = "" if len(keys) <= 20 else f"+{len(keys) - 20}"
    return f"keys={preview_keys}{suffix}"


_slow_query_registered = set()  # guard against double-registration per logger name


def setup_slow_query_logging(
    log_file: str,
    threshold_s: float = 0.5,
    logger_name: str = "slow_sql",
    all_statements: bool = False,
    stderr: bool = False,
) -> None:
    """Register SQLAlchemy engine event listeners for slow-query logging."""
    if logger_name in _slow_query_registered:
        return  # already wired up — avoid duplicate listeners on hot-reload
    _slow_query_registered.add(logger_name)

    os.makedirs(os.path.dirname(os.path.abspath(log_file)), exist_ok=True)
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.WARNING)
    logger.propagate = False
    logger.addHandler(_build_rotating_handler(log_file, va_detailed_formatter))
    if stderr:
        stream_handler = logging.StreamHandler(sys.stderr)
        stream_handler.setFormatter(va_detailed_formatter)
        stream_handler.addFilter(LogContextFilter())
        logger.addHandler(stream_handler)

    info_key = f"_sq_start_{logger_name}"

    @event.listens_for(Engine, "before_cursor_execute")
    def _before(conn, cursor, statement, parameters, context, executemany):
        conn.info[info_key] = time.monotonic()

    @event.listens_for(Engine, "after_cursor_execute")
    def _after(conn, cursor, statement, parameters, context, executemany):
        elapsed = time.monotonic() - conn.info.pop(info_key, time.monotonic())
        if elapsed < threshold_s:
            return
        stmt_upper = statement.lstrip().upper()
        if not all_statements and not any(
            stmt_upper.startswith(kw) for kw in ("INSERT", "UPDATE", "DELETE")
        ):
            return
        logger.warning(
            "slow_query elapsed_s=%.3f stmt=%s",
            elapsed,
            statement.split("\n")[0][:300],
        )


# Middleware for logging
def va_logging(app):
    @app.before_request
    def log_request_info():
        if request.path.startswith("/static"):
            return

        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        g.request_id = request_id
        set_request_id(request_id)

        user_info = _safe_current_user_email()
        payload = _masked_request_payload()
        request_logger.info(
            "event=request user=%s ip=%s method=%s path=%s query=%s payload=%s",
            user_info,
            request.remote_addr,
            request.method,
            request.path,
            request.query_string.decode("utf-8", errors="replace"),
            _payload_summary(payload),
        )

    @app.after_request
    def log_response_info(response):
        if request.path.startswith("/static"):
            return response

        request_id = getattr(g, "request_id", _request_id_ctx.get())
        response.headers["X-Request-ID"] = request_id
        set_request_id(request_id)

        user_info = _safe_current_user_email()
        response_logger.info(
            "event=response user=%s ip=%s method=%s path=%s status=%s bytes=%s content_type=%s",
            user_info,
            request.remote_addr,
            request.method,
            request.path,
            response.status_code,
            response.calculate_content_length(),
            response.headers.get("Content-Type", ""),
        )
        clear_request_id()
        return response

    @app.errorhandler(Exception)
    def handle_exception(e):
        if isinstance(e, RateLimitExceeded):
            error_logger.error(
                "rate_limited method=%s path=%s ip=%s",
                request.method,
                request.path,
                request.remote_addr,
            )
            return e

        error_logger.error(
            "unhandled_exception method=%s path=%s ip=%s user=%s",
            request.method,
            request.path,
            request.remote_addr,
            _safe_current_user_email(),
            exc_info=True,
        )

        if isinstance(e, HTTPException):
            return e

        from app import db

        db.session.rollback()
        if request.path.startswith("/api/") or request.path.startswith("/admin/api/"):
            return jsonify({"error": "Internal server error."}), 500
        return render_template("va_errors/va_500.html"), 500

    setup_slow_query_logging(
        log_file="logs/sql.log",
        threshold_s=SLOW_QUERY_THRESHOLD_S,
        logger_name="slow_sql",
        all_statements=True,  # capture slow SELECTs as well as writes
        stderr=False,
    )
