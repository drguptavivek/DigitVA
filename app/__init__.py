import gc
import importlib
import logging
import os
import weakref
import pytz
import warnings

# Suppress deprecation warnings from libraries until they update to modern datetime APIs
warnings.filterwarnings("ignore", category=DeprecationWarning)

from flask import Flask, request, redirect, jsonify, flash
from flask_migrate import Migrate
from flask_login import LoginManager, current_user
from flask_login.utils import login_url
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import MetaData
from flask_wtf.csrf import CSRFProtect
from flask_session import Session
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_talisman import Talisman
from flask_caching import Cache
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.middleware.proxy_fix import ProxyFix
from cryptography.fernet import Fernet
from config import (
    Config,
    DevelopmentConfig,
    TestConfig,
    trusted_hosts_for,
    validate_attachment_store_config,
)
from celery import Celery, Task

# Deterministic names for constraints the models leave unnamed, so model metadata
# and the live schema can be compared (see tests/migrations/test_schema_drift.py).
#
# Alembic also applies this convention to tables built by `op.create_table`, which
# means it retroactively renames constraints in existing migrations. "uq" therefore
# reproduces PostgreSQL's own default (`<table>_<column>_key`) instead of the
# Alembic-standard `uq_...`: every unnamed unique constraint in this database
# already carries the PostgreSQL name, and the standard form would rewrite them.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "%(table_name)s_%(column_0_name)s_key",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

db = SQLAlchemy(metadata=MetaData(naming_convention=NAMING_CONVENTION))
migrate = Migrate()
login = LoginManager()
csrf = CSRFProtect()
sess_manager = Session()

# A forked child (a gunicorn --preload worker, the Celery prefork child) must
# never reuse a pooled connection it inherited: two processes on one socket
# corrupt the protocol, and pool_pre_ping does not catch it. dispose(close=False)
# is SQLAlchemy's child-side reset: the child drops the inherited pool. When
# psycopg2 frees those connections the server ends them, so the parent's idle
# pooled connection is reconnected by pool_pre_ping on its next checkout (the
# gunicorn master and the Celery main process do no DB work after fork).
# redis-py and kombu reset their own pools on a pid change. gc.freeze before
# fork keeps the collector from touching (and so copying) the parent's objects
# in the child: with gunicorn --preload it is what makes the workers share the
# master's memory.
_engines_to_reset_after_fork = weakref.WeakSet()


def _freeze_before_fork():
    # Collect first: whatever is frozen is never collected again, and the
    # Celery main process forks a new child each time one is replaced.
    gc.collect()
    gc.freeze()


def _reset_engines_after_fork():
    for engine in list(_engines_to_reset_after_fork):
        engine.dispose(close=False)


os.register_at_fork(before=_freeze_before_fork, after_in_child=_reset_engines_after_fork)


def _rate_limit_key():
    """Per-user bucket for authenticated sessions; per-IP for anonymous."""
    if current_user and current_user.is_authenticated:
        return f"user:{current_user.get_id()}"
    return get_remote_address()


# Authenticated users get a generous per-user bucket (they use the dashboard
# frequently).  Anonymous / unauthenticated requests are capped tightly by IP.
limiter = Limiter(
    key_func=_rate_limit_key,
    default_limits=["12000 per day", "900 per hour"],
)


class _HideRateLimitKey(logging.Filter):
    """Flask-Limiter logs each breach with its limit key, and per-identifier
    limits key on an email or mobile number, which must never reach a log
    (digitva-4koe). Keep the line, drop the key: the app logs 429s itself
    with method, path and IP."""

    def filter(self, record):
        if isinstance(record.msg, str) and record.msg.startswith("ratelimit ") and len(record.args or ()) == 3:
            record.args = (record.args[0], "key hidden", record.args[2])
        return True


logging.getLogger("flask-limiter").addFilter(_HideRateLimitKey())
# Bound now: importing the app.logging package later rebinds the name ``logging`` here.
_startup_log = logging.getLogger(__name__)
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

def _default_config_class():
    flask_env = os.environ.get("FLASK_ENV", "").lower().strip()
    if flask_env == "development":
        return DevelopmentConfig
    if flask_env == "testing":
        return TestConfig
    return Config


def _current_user_timezone():
    tz_name = getattr(current_user, "timezone", "Asia/Kolkata") or "Asia/Kolkata"
    try:
        return pytz.timezone(tz_name)
    except pytz.UnknownTimeZoneError:
        return pytz.timezone("Asia/Kolkata")



def _content_security_policy(app):
    """Content security policy, widened only for the attachment bucket.

    Attachment delivery is a 302 from a DigitVA URL to a presigned bucket URL,
    and the browser applies ``img-src``/``media-src`` to the *final* URL of a
    redirect. With the S3 store the bucket's origins therefore have to be named
    here or every image and audio player fails silently. With the local store
    nothing is added and the policy is unchanged.
    """
    from app.services.attachment_store import s3_public_origins

    media_origins = ""
    if (app.config.get("ATTACHMENT_STORE") or "").strip().lower() == "s3":
        origins = s3_public_origins(app.config)
        media_origins = ("" .join(f" {origin}" for origin in origins))
    return {
        'default-src': "'self'",
        'script-src': "'self' 'unsafe-inline'",  # unsafe-inline needed for HTMX
        'style-src': "'self' 'unsafe-inline'",
        'img-src': f"'self' data:{media_origins}",
        'media-src': f"'self'{media_origins}",
        'font-src': "'self' data:",
        'connect-src': "'self'",
    }


def _namespace_public_demo(app: Flask) -> None:
    """Give a ``PUBLIC_DEMO_ENABLED`` deployment its own Redis namespace and
    Celery queue (docs/policy/public-demo.md section 8a), so a demo pointed at
    the main Redis by mistake can neither read nor consume the main
    deployment's cache, rate-limit, grant, notification or lock keys, or its
    Celery tasks. Runs before any extension reads its configuration; the
    flag off leaves every setting as it is."""
    app.config.update(
        CACHE_KEY_PREFIX="digitva_demo:",
        RATELIMIT_KEY_PREFIX="demo",
        AUTHZ_GRANT_CACHE_PREFIX="digitva_demo_authz:",
        NOTIFICATION_CACHE_PREFIX="digitva_demo_msg:last:",
        SWEEP_LOCK_KEY_PREFIX="demo:",
    )
    celery_conf = dict(app.config.get("CELERY", {}))
    keyprefix = {"global_keyprefix": "demo:"}
    celery_conf["task_default_queue"] = "demo"
    for option in ("broker_transport_options", "result_backend_transport_options"):
        celery_conf[option] = {**celery_conf.get(option, {}), **keyprefix}
    app.config["CELERY"] = celery_conf


def _require_same_site_cookies(config):
    """Keep the sign-in cookies same-site whatever the environment says.

    The CSRF-exempt views (the ICD-11 proxy among them) rely on the browser
    withholding the session from another site's POST, which only ``Lax`` and
    ``Strict`` do. Both settings read an environment variable; any other value
    is logged as an error and replaced with ``Lax`` rather than refusing to
    start, so a stray env value never stops a deploy (owner 2026-11-25;
    policy: api-v1.md rule 5)."""
    for key in ("SESSION_COOKIE_SAMESITE", "REMEMBER_COOKIE_SAMESITE"):
        value = config.get(key)
        if str(value).strip().lower() not in ("lax", "strict"):
            _startup_log.error(
                "%s=%r is not same-site; using Lax instead (api-v1.md rule 5).", key, value)
            config[key] = "Lax"


def create_app(config_class=None, register_routes=True):
    """Celery beat passes register_routes=False: it only sends tasks by name."""
    if config_class is None:
        config_class = _default_config_class()
    app = Flask(__name__)
    app.config.from_object(config_class)
    _require_same_site_cookies(app.config)
    if app.config.get("PUBLIC_DEMO_ENABLED"):
        _namespace_public_demo(app)
    if not (app.debug or app.testing):
        app.config["TRUSTED_HOSTS"] = trusted_hosts_for(app.config["PUBLIC_BASE_URL"])
        if not app.config.get("CAPTCHA_HMAC_KEY"):
            raise RuntimeError(
                "CAPTCHA_HMAC_KEY must be set in production. Add it to your "
                ".env file or container environment."
            )
        auth_factor_key = app.config.get("AUTH_FACTOR_ENCRYPTION_KEY")
        if not auth_factor_key:
            raise RuntimeError(
                "AUTH_FACTOR_ENCRYPTION_KEY must be set in production. Add it "
                "to your .env file or container environment."
            )
        try:
            # Format check only: a valid Fernet key is exactly a 44-character
            # urlsafe-base64 encoding of 32 random bytes, which is also what
            # the AES-256-GCM key derivation (totp_service._aes_key) needs.
            Fernet(auth_factor_key.encode("utf-8"))
        except Exception as exc:
            raise RuntimeError(
                "AUTH_FACTOR_ENCRYPTION_KEY must be a 44-character "
                "urlsafe-base64 string encoding 32 random bytes, e.g. from "
                "`openssl rand -base64 32 | tr '+/' '-_'`."
            ) from exc

    # Registration identifier keys: production refuses to start without them
    # (docs/policy/death-registration-identifiers.md, "Keys and configuration");
    # development and test fall back to throwaway keys.
    from app.utils import pii_crypto
    pii_crypto.init_app(app)

    from app.hooks.auth import register_authenticate_bearer

    register_authenticate_bearer(app)

    # Idle sign-out and the retired remember cookie (app/utils/idle_session.py).
    from app.utils.idle_session import enforce_idle_timeout

    app.before_request(enforce_idle_timeout)

    # Every request runs in the training "exclude" scope (app/services/
    # training_scope.py); the trainer tools opt out here.
    from app.services.training_scope import open_trainer_tools

    app.before_request(open_trainer_tools)

    from app.hooks.upload_limits import register_upload_limits

    register_upload_limits(app)

    @app.errorhandler(RequestEntityTooLarge)
    def _body_too_large(exc):
        if request.path.startswith(("/api/", "/admin/api/")):
            limit_mb = (request.max_content_length or 0) // (1024 * 1024)
            message = f"The upload exceeds the {limit_mb} MB limit." if limit_mb else "The request body is too large."
            return jsonify({"error": message, "code": "payload_too_large"}), 413
        return exc

    # Fail closed before anything can serve an attachment: an S3 store with a
    # missing key must stop the app, never quietly fall back to local disk.
    validate_attachment_store_config(app.config)

    db.init_app(app)
    with app.app_context():
        _engines_to_reset_after_fork.update(db.engines.values())
    migrate.init_app(app, db)
    login.init_app(app)
    # CSRFProtect's own hook is switched off so the one below can skip bearer
    # requests (no ambient credential, nothing to forge); every other request
    # is checked exactly as before. Same slot in the hook order.
    app.config["WTF_CSRF_CHECK_DEFAULT"] = False
    csrf.init_app(app)

    from app.hooks.csrf import register_csrf_protect_cookie_requests

    register_csrf_protect_cookie_requests(app)

    app.config['SESSION_SQLALCHEMY'] = db
    sess_manager.init_app(app)
    from app.utils.bearer_session import BearerBlindSessionInterface

    app.session_interface = BearerBlindSessionInterface(app.session_interface)

    # Initialize rate limiter with Redis storage
    app.config.setdefault("RATELIMIT_STORAGE_URI", app.config.get("REDIS_URL", "redis://localhost:6379/0"))
    # Fail open (owner 2026-11-27, digitva-248z): without this the limiter raises
    # on every request when Redis is down and the whole app returns 500.
    app.config.setdefault("RATELIMIT_SWALLOW_ERRORS", True)
    limiter.init_app(app)

    # Initialize cache (Redis backend, 5-minute default TTL)
    app.config.setdefault("CACHE_TYPE", "RedisCache")
    app.config.setdefault("CACHE_REDIS_URL", app.config.get("REDIS_URL", "redis://localhost:6379/0"))
    app.config.setdefault("CACHE_DEFAULT_TIMEOUT", 300)  # 5 minutes
    app.config.setdefault("CACHE_KEY_PREFIX", "digitva_cache:")
    cache.init_app(app)

    # Initialize email (Flask-Mail)
    from app.services.email_service import init_mail
    init_mail(app)

    # Initialize security headers with Flask-Talisman
    # In development/testing, disable HTTPS enforcement
    force_https = not (app.debug or app.testing)
    talisman.init_app(
        app,
        force_https=force_https,
        strict_transport_security=True,
        strict_transport_security_max_age=31536000,
        content_security_policy=_content_security_policy(app),
        frame_options='SAMEORIGIN',
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

    @login.unauthorized_handler
    def _login_required_unauthorized():
        """``login_required`` on a JSON path answers 401 like role_required;
        a page keeps Flask-Login's flash and redirect to the login page."""
        # Local: app.decorators imports app.models, which needs this module's db.
        from app.decorators.role_required import API_PATH_PREFIXES

        if request.path.startswith(API_PATH_PREFIXES):
            return jsonify({"error": "Authentication required.", "code": "unauthorized"}), 401
        if request.headers.get("HX-Request") == "true":
            # Same as role_required: base.js shows Session Expired, not a
            # login page swapped into an htmx target.
            return "Authentication required.", 401
        flash(login.login_message, login.login_message_category)
        return redirect(login_url(login.login_view, next_url=request.url))
    app.config.setdefault("WTF_CSRF_HEADERS", ["X-CSRFToken"])
    
    # Initialize Celery
    celery_init_app(app)

    if register_routes:
        from app.routes import register_blueprints
        register_blueprints(app)
        from app.routes.expo_client import expo_client
        app.register_blueprint(expo_client)
        # Always registered, gated by PUBLIC_DEMO_ENABLED in each view (404 off).
        from app.routes.public_demo import public_demo
        app.register_blueprint(public_demo)
        # After every blueprint: wrap each non-exempt view so a request authz
        # never decided is logged, and refused where AUTHZ_ENFORCE_CONSULTED.
        from app.services.authz import consulted as authz_consulted
        authz_consulted.install(app)
        from app.routes.va_errors import register_error_handlers
        register_error_handlers(app)
    from app.logging import va_logging
    va_logging(app)
    
    from app import models #noqa
    from app import services #noqa
    from app import utils #noqa
    from app.tasks import ui_string_tasks #noqa
    from app.tasks import instrument_translation_tasks #noqa

    # CLI command groups (app/commands/<module>.init_app), in registration order.
    for command_module in (
        "odk_sync",
        "form_types",
        "seed",
        "organization_demo",
        "training_demo",
        "public_demo",
        "analytics",
        "users",
        "auth",
        "payload_backfill",
        "cod_buckets",
        "icd10",
        "icd11",
        "va_definitions",
        "ai_search",
        "ai_catalog",
        "organization",
        "mentor_institute",
        "instrument_translations",
        "ui_strings",
        "translations",
        "repair",
        "odk_mappings",
        "attachments",
        "smartva",
        "backups",
        "web_intake",
        "devices",
        "schema_drift",
        "xlsform",
        "pii",
    ):
        importlib.import_module(f"app.commands.{command_module}").init_app(app)

    from app.template_helpers import register_template_helpers

    register_template_helpers(app)

    from app.hooks.terms_gate import register_force_password_update

    register_force_password_update(app)

    from app.hooks.onboarding import register_training_demo_onboarding

    register_training_demo_onboarding(app)

    from app.hooks.cache_headers import register_cache_headers

    register_cache_headers(app)

    return app
