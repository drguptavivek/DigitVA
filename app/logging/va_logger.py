import logging
import sys
import time
from logging.handlers import TimedRotatingFileHandler
import os
import uuid
from flask import jsonify, render_template, request, session
from flask_login import current_user
from sqlalchemy import event
from sqlalchemy.engine import Engine
from werkzeug.exceptions import HTTPException
from app.logging.va_queryfilter import SQLWriteFilter

# Log any write query (INSERT/UPDATE/DELETE) that takes longer than this
SLOW_QUERY_THRESHOLD_S = 0.5

SENSITIVE_FIELDS = ['password', 'token', 'csrf_token', "new_password", "va_current_password", "va_new_password", "va_confirm_password", "confirm_password"]

# Create logs directory
va_log = "logs"
os.makedirs(va_log, exist_ok=True)

# Formatters
va_detailed_formatter = logging.Formatter(
    '%(asctime)s - %(levelname)s - %(name)s - %(message)s [in %(pathname)s:%(lineno)d]'
)

# Setup logger
def va_setup_logger(name, log_file, level=logging.INFO, formatter=None, stderr=False):
    logger = logging.getLogger(name)
    logger.setLevel(level)
    fmt = formatter or va_detailed_formatter
    file_handler = TimedRotatingFileHandler(
        filename=log_file,
        when='W0',
        interval=1,
        backupCount=0,
        encoding='utf-8'
    )
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)
    if stderr:
        stream_handler = logging.StreamHandler(sys.stderr)
        stream_handler.setFormatter(fmt)
        logger.addHandler(stream_handler)
    return logger

# Formatters
grant_audit_formatter = logging.Formatter('%(asctime)s %(message)s')

# Initialize loggers
request_logger = va_setup_logger('REQUEST_LOG', f'{va_log}/requests.log', logging.INFO, va_detailed_formatter)
error_logger = va_setup_logger('ERROR_LOG', f'{va_log}/errors.log', logging.ERROR, va_detailed_formatter, stderr=True)
sql_logger = va_setup_logger('SQL_LOG', f'{va_log}/sql.log', logging.INFO, va_detailed_formatter)
grant_audit_logger = va_setup_logger('GRANT_AUDIT', f'{va_log}/grants.log', logging.INFO, grant_audit_formatter)


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


def _safe_current_user_email():
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

# Middleware for logging
def va_logging(app):
    @app.before_request
    def log_request_info():
        if request.path.startswith('/static'):
            return
        user_info = _safe_current_user_email()
        # Safely handle request data  
        request_data = None
        if request.content_type == 'application/json':
            raw = request.get_json(silent=True)
            # Copy before masking — get_json() returns Flask's cached dict and
            # mutating it in-place would corrupt the data seen by route handlers.
            request_data = dict(raw) if raw else None
        elif request.form:
            request_data = request.form.to_dict()
        if request_data:
            for field in SENSITIVE_FIELDS:
                if field in request_data:
                    request_data[field] = '***'
        request_logger.info(
            f"User: {user_info} - Request from {request.remote_addr} - {request.method} {request.url} - Data: {request_data}"
        )
    @app.after_request
    def log_response_info(response):
        if request.path.startswith('/static'):
            return response
        user_info = _safe_current_user_email()
        content_type = response.headers.get('Content-Type', '')
        if content_type.startswith(('text/', 'application/json')):
            try:
                response_data = response.get_data(as_text=True)
                trimmed_data = "\n".join(response_data.splitlines()[:3])
            except Exception as e:
                trimmed_data = f"[Error reading response data: {e}]"
        else:
            trimmed_data = f"[Skipped logging for content type: {content_type}]"

        request_logger.info(
            f"User: {user_info} - Response to {request.remote_addr} - Status: {response.status_code} - Data: {trimmed_data}"
        )
        return response
    @app.errorhandler(Exception)
    def handle_exception(e):
        error_logger.error(f"Error: {str(e)}", exc_info=True)
        if isinstance(e, HTTPException):
            return e
        from app import db
        db.session.rollback()
        if request.path.startswith("/api/") or request.path.startswith("/admin/api/"):
            return jsonify({"error": "Internal server error."}), 500
        return render_template("va_errors/va_500.html"), 500

    # Slow-query logging via SQLAlchemy engine events.
    # Only write statements (INSERT/UPDATE/DELETE) that exceed SLOW_QUERY_THRESHOLD_S
    # are logged — avoids flooding sql.log with fast session heartbeats while still
    # catching genuinely slow writes on any table.
    sql_handler = TimedRotatingFileHandler(
        filename='logs/sql.log',
        when='W0',
        interval=1,
        backupCount=0,
        encoding='utf-8'
    )
    sql_handler.setFormatter(va_detailed_formatter)
    slow_query_logger = logging.getLogger('slow_sql')
    slow_query_logger.setLevel(logging.WARNING)
    slow_query_logger.addHandler(sql_handler)

    @event.listens_for(Engine, "before_cursor_execute")
    def _before_execute(conn, cursor, statement, parameters, context, executemany):
        conn.info["query_start"] = time.monotonic()

    @event.listens_for(Engine, "after_cursor_execute")
    def _after_execute(conn, cursor, statement, parameters, context, executemany):
        elapsed = time.monotonic() - conn.info.pop("query_start", time.monotonic())
        if elapsed >= SLOW_QUERY_THRESHOLD_S and any(
            statement.lstrip().upper().startswith(kw) for kw in ("INSERT", "UPDATE", "DELETE")
        ):
            slow_query_logger.warning(
                "SLOW QUERY (%.3fs): %s",
                elapsed,
                statement.split("\n")[0][:200],
            )
