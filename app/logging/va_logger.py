import logging
from logging.handlers import TimedRotatingFileHandler
import os
from flask import request
from flask_login import current_user
from app.logging.va_queryfilter import SQLWriteFilter

SENSITIVE_FIELDS = ['password', 'token', 'csrf_token', "new_password", "va_current_password", "va_new_password", "va_confirm_password", "confirm_password"]

# Create logs directory
va_log = "logs"
os.makedirs(va_log, exist_ok=True)

# Formatters
va_detailed_formatter = logging.Formatter(
    '%(asctime)s - %(levelname)s - %(name)s - %(message)s [in %(pathname)s:%(lineno)d]'
)

# Setup logger
def va_setup_logger(name, log_file, level=logging.INFO, formatter=None):
    logger = logging.getLogger(name)
    logger.setLevel(level)
    handler = TimedRotatingFileHandler(
        filename=log_file,
        when='W0',
        interval=1,
        backupCount=0,
        encoding='utf-8'
    )
    handler.setFormatter(formatter or va_detailed_formatter)
    logger.addHandler(handler)
    return logger

# Initialize loggers
request_logger = va_setup_logger('REQUEST_LOG', f'{va_log}/requests.log', logging.INFO, va_detailed_formatter)  
error_logger = va_setup_logger('ERROR_LOG', f'{va_log}/errors.log', logging.ERROR, va_detailed_formatter)  
sql_logger = va_setup_logger('SQL_LOG', f'{va_log}/sql.log', logging.INFO, va_detailed_formatter)

# Middleware for logging
def va_logging(app):
    @app.before_request
    def log_request_info():
        if request.path.startswith('/static'):
            return
        user_info = "anonymous"
        if current_user.is_authenticated:
            user_info = current_user.email
        # Safely handle request data  
        request_data = None  
        if request.content_type == 'application/json':  
            request_data = request.get_json()  
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
        user_info = "anonymous"
        if current_user.is_authenticated:
            user_info = current_user.email
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
        return e

    # Enable SQL query logging
    logging.getLogger('sqlalchemy.engine').setLevel(logging.INFO)
    sql_handler = TimedRotatingFileHandler(
        filename='logs/sql.log',
        when='W0',
        interval=1,
        backupCount=0,
        encoding='utf-8'
    )
    sql_handler.setFormatter(va_detailed_formatter)
    sql_handler.addFilter(SQLWriteFilter())
    logging.getLogger('sqlalchemy.engine').addHandler(sql_handler)