import uuid
from datetime import datetime
import pytz
import warnings

# Suppress deprecation warnings from libraries until they update to modern datetime APIs
warnings.filterwarnings("ignore", category=DeprecationWarning)

from flask import Flask, request, redirect, session, url_for
from flask_migrate import Migrate
from flask_login import LoginManager, current_user
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from flask_session import Session
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_talisman import Talisman
from flask_caching import Cache
from werkzeug.middleware.proxy_fix import ProxyFix
from config import Config
from celery import Celery, Task

db = SQLAlchemy()
migrate = Migrate()
login = LoginManager()
csrf = CSRFProtect()
sess_manager = Session()
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"],
)
talisman = Talisman()
cache = Cache()

def celery_init_app(app: Flask) -> Celery:
    class FlaskTask(Task):
        def __call__(self, *args: object, **kwargs: object) -> object:
            with app.app_context():
                return self.run(*args, **kwargs)

    celery_app = Celery(app.name, task_cls=FlaskTask)
    celery_app.config_from_object(app.config.get("CELERY", {}))
    celery_app.set_default()
    app.extensions["celery"] = celery_app
    return celery_app

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    migrate.init_app(app, db)
    login.init_app(app)
    csrf.init_app(app)
    
    app.config['SESSION_SQLALCHEMY'] = db
    sess_manager.init_app(app)

    # Initialize rate limiter with Redis storage
    app.config.setdefault("RATELIMIT_STORAGE_URI", app.config.get("REDIS_URL", "redis://localhost:6379/0"))
    limiter.init_app(app)

    # Initialize cache (Redis backend, 5-minute default TTL)
    app.config.setdefault("CACHE_TYPE", "RedisCache")
    app.config.setdefault("CACHE_REDIS_URL", app.config.get("REDIS_URL", "redis://localhost:6379/0"))
    app.config.setdefault("CACHE_DEFAULT_TIMEOUT", 300)  # 5 minutes
    app.config.setdefault("CACHE_KEY_PREFIX", "digitva_cache:")
    cache.init_app(app)

    # Initialize security headers with Flask-Talisman
    # In development/testing, disable HTTPS enforcement
    force_https = not (app.debug or app.testing)
    talisman.init_app(
        app,
        force_https=force_https,
        strict_transport_security=True,
        strict_transport_security_max_age=31536000,
        content_security_policy={
            'default-src': "'self'",
            'script-src': "'self' 'unsafe-inline'",  # unsafe-inline needed for HTMX
            'style-src': "'self' 'unsafe-inline'",
            'img-src': "'self' data:",
            'font-src': "'self'",
            'connect-src': "'self'",
        },
        frame_options='DENY',
        x_content_type_options=True,
        x_xss_protection=True,
        referrer_policy='strict-origin-when-cross-origin',
    )

    # Handle reverse proxy headers (X-Forwarded-For, X-Forwarded-Proto, etc.)
    # Set x_for=1 if behind a single reverse proxy (nginx, traefik, etc.)
    # Increase count if behind multiple proxies
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    login.login_view = 'va_auth.va_login'
    login.login_message = 'Please log in to access this page.'
    app.config.setdefault("WTF_CSRF_HEADERS", ["X-CSRFToken"])
    
    # Initialize Celery
    celery_init_app(app)

    from app.routes import register_blueprints  
    register_blueprints(app)
    from app.routes.va_errors import register_error_handlers
    register_error_handlers(app)
    from app.logging import va_logging
    va_logging(app)
    
    from app import models #noqa
    from app import services #noqa
    from app import utils #noqa

    from app.commands.odk_sync import init_app as init_odk_sync_commands
    init_odk_sync_commands(app)

    from app.commands.form_types import init_app as init_form_types_commands
    init_form_types_commands(app)

    from app.commands.seed import init_app as init_seed_commands
    init_seed_commands(app)

    from app.commands.analytics import init_app as init_analytics_commands
    init_analytics_commands(app)
    
    @app.template_filter('user_timezone')
    def user_timezone_filter(dt, format='%Y-%m-%d %H:%M:%S'):
        if not dt:
            return ""
        if isinstance(dt, str):
            try:
                dt = datetime.fromisoformat(dt.replace('Z', '+00:00'))
            except ValueError:
                return dt
                
        # If naive, assume UTC
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=pytz.UTC)
            
        tz_name = getattr(current_user, 'timezone', 'Asia/Kolkata')
        try:
            tz = pytz.timezone(tz_name)
        except pytz.UnknownTimeZoneError:
            tz = pytz.timezone('Asia/Kolkata')
            
        local_dt = dt.astimezone(tz)
        return local_dt.strftime(format)
    
    @app.before_request
    def force_password_update():
        current_user_id = session.get("_user_id")
        if not current_user_id:
            return
        try:
            current_user_id = uuid.UUID(current_user_id)
        except (TypeError, ValueError):
            return

        from app.models import VaUsers

        fresh_user = db.session.get(VaUsers, current_user_id)
        if fresh_user is None:
            return

        allowed_endpoints = {
            'static',
            'va_main.force_password_change',
            'va_auth.va_logout',
            'va_auth.va_login',
        }
        if fresh_user.pw_reset_t_and_c is False and request.endpoint not in allowed_endpoints:
            return redirect(url_for('va_main.force_password_change'))

    return app
