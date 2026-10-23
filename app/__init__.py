import gc
import uuid
import os
import weakref
from datetime import datetime
from time import perf_counter
import pytz
import warnings

# Suppress deprecation warnings from libraries until they update to modern datetime APIs
warnings.filterwarnings("ignore", category=DeprecationWarning)

from flask import Flask, g, request, redirect, session, url_for, jsonify, flash
from flask_migrate import Migrate
from flask_login import LoginManager, current_user
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import MetaData
from flask_wtf.csrf import CSRFProtect
from flask_session import Session
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_talisman import Talisman
from flask_caching import Cache
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
#: API paths whose responses are never stored by a browser or proxy.
_NO_STORE_API_PREFIXES = ("/api/v1/me/", "/api/v1/intake/", "/api/v1/cases",
                         "/api/v1/coding/")


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


def create_app(config_class=None, register_routes=True):
    """Celery beat passes register_routes=False: it only sends tasks by name."""
    if config_class is None:
        config_class = _default_config_class()
    app = Flask(__name__)
    app.config.from_object(config_class)
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

    # /api/v1/ takes a session cookie or a device bearer token. Runs before
    # every other hook (the logger, the limiter's key functions and the
    # gates below all read the user): a bearer is authenticated alone, so the
    # cookie on the same request is ignored, and a bad one is refused rather
    # than falling back to the cookie.
    @app.before_request
    def authenticate_bearer():
        from app.models.va_users import load_user_from_device_token
        from app.services.device_auth_service import (
            UNAUTHENTICATED_ENDPOINTS,
            request_bearer_token,
        )

        g.bearer_auth = False
        g.pop("device_session", None)
        if request_bearer_token(request) is None:
            return None
        # Sign-in endpoints take no token: a client may still send its stale one.
        if request.endpoint in UNAUTHENTICATED_ENDPOINTS:
            return None
        user = load_user_from_device_token(request)
        if user is None:
            g._login_user = login.anonymous_user()  # no second lookup from the response logger
            return jsonify({"error": "Authentication required.", "code": "unauthorized"}), 401
        g._login_user = user  # Flask-Login's per-request cache: skips the cookie loaders
        g.bearer_auth = True
        return None

    # Every request runs in the training "exclude" scope (app/services/
    # training_scope.py); the trainer tools opt out here.
    from app.services.training_scope import open_trainer_tools

    app.before_request(open_trainer_tools)

    # CSRFProtect reads multipart form data in its before_request hook. Bound
    # organization imports before that hook can parse and spool an upload.
    @app.before_request
    def _limit_organization_import_upload():
        if request.method != "POST":
            return None
        parts = request.path.split("/")
        if parts[:4] != ["", "admin", "api", "organization"]:
            return None
        if len(parts) == 7 and parts[5:] == ["project-users", "import"]:
            limit_mb = 1
        elif len(parts) == 6 and parts[5] == "import":
            limit_mb = 5
        else:
            return None
        limit = limit_mb * 1024 * 1024 + 64 * 1024
        request.max_content_length = limit
        if request.content_length is not None and request.content_length > limit:
            return jsonify({"error": f"The upload exceeds the {limit_mb} MB limit.", "code": "payload_too_large"}), 413
        return None

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

    @app.before_request
    def csrf_protect_cookie_requests():
        from app.services.device_auth_service import request_bearer_token

        # Mirrors flask_wtf.csrf.CSRFProtect's hook minus the bearer case.
        if (
            not app.config["WTF_CSRF_ENABLED"]
            or request.method not in app.config["WTF_CSRF_METHODS"]
            or not request.endpoint
            or request_bearer_token(request) is not None
            or app.blueprints.get(request.blueprint) in csrf._exempt_blueprints
        ):
            return None
        view = app.view_functions.get(request.endpoint)
        if f"{view.__module__}.{view.__name__}" in csrf._exempt_views:
            return None
        csrf.protect()
        return None
    
    app.config['SESSION_SQLALCHEMY'] = db
    sess_manager.init_app(app)
    from app.utils.bearer_session import BearerBlindSessionInterface

    app.session_interface = BearerBlindSessionInterface(app.session_interface)

    # Initialize rate limiter with Redis storage
    app.config.setdefault("RATELIMIT_STORAGE_URI", app.config.get("REDIS_URL", "redis://localhost:6379/0"))
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

    from flask_login import user_loaded_from_cookie
    from app.services.public_demo_service import stamp_remembered_sign_in

    # Remember-me returns of public-demo accounts keep their idle clock moving.
    user_loaded_from_cookie.connect(stamp_remembered_sign_in, weak=False)

    login.login_view = 'va_auth.va_login'
    login.login_message = 'Please log in to access this page.'

    @login.unauthorized_handler
    def _login_required_unauthorized():
        """``login_required`` on a JSON path answers 401 like role_required;
        a page keeps Flask-Login's flash and redirect to the login page."""
        from flask_login.utils import login_url

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
    from app.logging.va_logger import slow_request_logger
    va_logging(app)
    
    from app import models #noqa
    from app import services #noqa
    from app import utils #noqa
    from app.tasks import kpi_tasks #noqa
    from app.tasks import ui_string_tasks #noqa

    from app.commands.odk_sync import init_app as init_odk_sync_commands
    init_odk_sync_commands(app)

    from app.commands.form_types import init_app as init_form_types_commands
    init_form_types_commands(app)

    from app.commands.seed import init_app as init_seed_commands
    init_seed_commands(app)

    from app.commands.organization_demo import init_app as init_organization_demo_commands
    init_organization_demo_commands(app)

    from app.commands.training_demo import init_app as init_training_demo_commands
    init_training_demo_commands(app)
    from app.commands.public_demo import init_app as init_public_demo_commands
    init_public_demo_commands(app)

    from app.commands.analytics import init_app as init_analytics_commands
    init_analytics_commands(app)

    from app.commands.users import init_app as init_users_commands
    init_users_commands(app)

    from app.commands.auth import init_app as init_auth_commands
    init_auth_commands(app)

    from app.commands.payload_backfill import init_app as init_payload_backfill_commands
    init_payload_backfill_commands(app)

    from app.commands.kpi import init_app as init_kpi_commands
    init_kpi_commands(app)

    from app.commands.cod_buckets import init_app as init_cod_bucket_commands
    init_cod_bucket_commands(app)

    from app.commands.icd10 import init_app as init_icd10_commands
    init_icd10_commands(app)
    from app.commands.icd11 import init_app as init_icd11_commands
    init_icd11_commands(app)
    from app.commands.va_definitions import init_app as init_va_definition_commands
    init_va_definition_commands(app)
    from app.commands.organization import init_app as init_org_commands
    init_org_commands(app)
    from app.commands.mentor_institute import init_app as init_mentor_commands
    init_mentor_commands(app)

    from app.commands.instrument_translations import (
        init_app as init_instrument_translation_commands,
    )
    init_instrument_translation_commands(app)

    from app.commands.ui_strings import init_app as init_ui_string_commands
    init_ui_string_commands(app)

    from app.commands.repair import init_app as init_repair_commands
    init_repair_commands(app)

    from app.commands.odk_mappings import init_app as init_odk_mapping_commands
    init_odk_mapping_commands(app)

    from app.commands.attachments import init_app as init_attachment_commands
    init_attachment_commands(app)

    from app.commands.smartva import init_app as init_smartva_commands
    init_smartva_commands(app)

    from app.commands.backups import init_app as init_backup_commands
    init_backup_commands(app)

    from app.commands.web_intake import init_app as init_web_intake_commands
    init_web_intake_commands(app)

    from app.commands.devices import init_app as init_device_commands
    init_device_commands(app)

    from app.commands.schema_drift import init_app as init_schema_drift_commands
    init_schema_drift_commands(app)

    from app.commands.xlsform import init_app as init_xlsform_commands
    init_xlsform_commands(app)

    from app.commands.pii import init_app as init_pii_commands
    init_pii_commands(app)

    # The coding screens' ICD classification switch
    # (va_form_partials/_icd_classification_switch.html).
    from app.services.icd_coding_value import (
        classification_of_value,
        get_icd_classification_for_submission,
    )

    app.add_template_global(get_icd_classification_for_submission, "icd_classification_for")
    app.add_template_global(classification_of_value, "icd_classification_of")
    from app.services.smartva_icd11 import smartva_icd11_mapping

    app.add_template_global(smartva_icd11_mapping, "smartva_icd11_mapping")
    from app.services.icd11_titles import icd11_alternatives_label, stored_cod_label

    app.add_template_global(icd11_alternatives_label, "icd11_alternatives_label")
    app.add_template_global(stored_cod_label, "stored_cod_label")
    from app.services.smartva_service import smartva_panel

    app.add_template_global(smartva_panel, "smartva_panel")
    from app.utils.who_va_bundle import who_va_bundle_version

    app.add_template_global(who_va_bundle_version, "who_va_bundle_version")
    # The Organization panel's reference card, standalone or inside Project Setup.
    from app.services.organization_service import district_reference_model

    app.add_template_global(district_reference_model, "district_reference_model")

    # The admin Access grants panel's role labels, shared with the API.
    from app.models.va_selectives import ROLE_LABELS

    app.add_template_global(ROLE_LABELS, "role_labels")

    def training_page_url():
        """Where "my training checklist" opens: the Expo page while its export is present, else the Flask fallback."""
        from app.routes.expo_client import export_ready

        return "/app/training" if export_ready() else url_for("training_demo.welcome")

    app.add_template_global(training_page_url, "training_page_url")

    @app.context_processor
    def inject_template_globals():
        from app.services.icd11_licence import DIGITVA_ADDITION_LABEL, ICD11_CITATION
        from app.services.site_maintenance_service import get_site_maintenance_banner_context

        is_authenticated = bool(current_user and current_user.is_authenticated)
        is_admin = bool(
            current_user and current_user.is_authenticated and current_user.is_admin()
        )
        return {
            "current_year": datetime.now(pytz.UTC).astimezone(
                _current_user_timezone()
            ).year,
            # Today in the user's zone, for date inputs' max (never the UTC date).
            "current_user_today": datetime.now(pytz.UTC).astimezone(
                _current_user_timezone()
            ).date().isoformat(),
            "site_maintenance_banner": get_site_maintenance_banner_context(
                is_authenticated=is_authenticated,
                is_admin=is_admin,
            ),
            "icd11_citation": ICD11_CITATION,
            "digitva_addition_label": DIGITVA_ADDITION_LABEL,
            "site_maintenance_watcher_enabled": is_authenticated,
            "site_maintenance_user_is_admin": is_admin,
        }

    # Imported here, not at module level: app.utils pulls in ODK modules that need `db` from this package.
    from app.utils.number_format import whole_number

    app.add_template_filter(whole_number)

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

        local_dt = dt.astimezone(_current_user_timezone())
        return local_dt.strftime(format)
    
    timed_prefixes = (
        "/data-management",
        "/api/v1/data-management",
        "/api/v1/analytics",
    )

    @app.before_request
    def force_password_update():
        if request.path.startswith("/static") or request.path == "/health":
            return
        if request.path.startswith(timed_prefixes):
            g._request_started_at = perf_counter()
        g._slow_started_at = perf_counter()
        # g outlives the request when an app context is already pushed (tests).
        g._sql_count, g._sql_ms = 0, 0.0

        from app.services.request_abuse_service import (
            abuse_ban_message,
            get_temporary_ban,
        )

        temporary_ban = get_temporary_ban(request.remote_addr)
        if temporary_ban is not None:
            app.logger.warning(
                "blocked_temporarily_banned_ip ip=%s method=%s path=%s remaining_seconds=%s",
                request.remote_addr,
                request.method,
                request.path,
                temporary_ban["remaining_seconds"],
            )
            message = abuse_ban_message()
            if request.path.startswith("/api/") or request.path.startswith("/admin/api/"):
                response = jsonify({"error": message, "code": "temporarily_blocked"})
            else:
                response = app.response_class(
                    f"{message}\n",
                    status=403,
                    mimetype="text/plain",
                )
            response.status_code = 403
            response.headers["Retry-After"] = str(
                temporary_ban["remaining_seconds"]
            )
            return response

        from app.models import VaUsers
        from app.services.device_auth_service import request_bearer_token

        # A bearer request has no session: its user is the one
        # authenticate_bearer pinned. The gates below answer it in JSON.
        is_bearer = request_bearer_token(request) is not None
        if is_bearer:
            if not g.get("bearer_auth"):
                return
            fresh_user = current_user._get_current_object()
        else:
            current_user_id = session.get("_user_id")
            if not current_user_id:
                return
            # Flask-Login's session value is VaUsers.get_id(), "<uuid>" or
            # "<uuid>:<version>" once a session version is set — see
            # VaUsers.get_id / load_user.
            raw_uid, _sep, _version = current_user_id.rpartition(":")
            try:
                current_user_id = uuid.UUID(raw_uid or current_user_id)
            except (TypeError, ValueError):
                return

            fresh_user = db.session.get(VaUsers, current_user_id)
            if fresh_user is None or not fresh_user.is_active:
                return

        from app.services.site_maintenance_service import should_block_non_admin_after_cutoff
        from flask_login import logout_user

        if not fresh_user.is_admin() and should_block_non_admin_after_cutoff():
            if is_bearer:
                return jsonify({"error": "Site is under maintenance.", "code": "maintenance"}), 403
            logout_user()
            flash(
                "Site is under maintenance. Only admin login is allowed right now.",
                "warning",
            )
            if (
                request.path.startswith("/api/")
                or request.path.startswith("/admin/api/")
                or request.path.startswith("/api/v1/")
            ):
                return jsonify(
                    {
                        "error": "Site is under maintenance. Only admin login is allowed right now.",
                        "code": "maintenance",
                    }
                ), 401
            return redirect(url_for("va_auth.va_login"))

        allowed_endpoints = {
            'static',
            'profile.force_password_change',
            'va_auth.va_logout',
            'va_auth.va_login',
            'va_auth.forgot_password',
            'va_auth.reset_password',
            'va_auth.verify_email',
            'va_auth.resend_verification',
            'api_v1.profile_api.accept_terms',
            'api_v1.me_api.accept_terms',
            # Sign-out must work while the terms are pending (onboarding
            # policy 5.4); accepting is me_api.accept_terms above.
            'api_v1.auth_api.end_session',
        }
        if fresh_user.pw_reset_t_and_c is False and request.endpoint not in allowed_endpoints:
            if is_bearer:
                return jsonify({
                    "error": "Accept the terms of use to continue.",
                    "code": "terms_required",
                }), 403
            from app.decorators.role_required import API_PATH_PREFIXES

            # Every JSON path gets terms_required (onboarding policy 5.4).
            if request.path.startswith(API_PATH_PREFIXES):
                code = "terms_required"
            else:
                return redirect(url_for('profile.force_password_change'))
            response = jsonify({
                "error": "Accept the terms of use to continue.",
                "code": code,
                "redirect_url": url_for('profile.force_password_change'),
            })
            response.status_code = 403
            response.headers["Cache-Control"] = "no-store"
            # A browser client with pending terms cannot reach me/access for
            # its CSRF token, so the refusal carries one for POST me/terms.
            from flask_wtf.csrf import generate_csrf

            response.headers["X-CSRFToken"] = generate_csrf()
            return response

    @app.before_request
    def training_demo_onboarding():
        """Send a trainee with a pending training session to its training page, once.

        The page is the Expo ``/app/training`` while the export is present,
        else the Flask welcome page. Browser page loads only: never the API,
        htmx fragments, static files, auth pages, the welcome flow itself or
        the Expo shell under ``/app/`` (``/app/`` is never redirected to a
        Flask page; the Expo home sends a pending trainee itself). Cheap:
        nothing runs unless the feature is configured, and the answer is cached
        in the login session. docs/policy/training-demo-project.md.
        """
        if not app.config.get("DIGITVA_TRAINING_PROJECT_ID"):
            return None
        if (
            request.method != "GET"
            or request.headers.get("HX-Request")
            or request.is_json
            or request.path.startswith(
                ("/static", "/api/", "/admin/api/", "/app/", "/demo", "/vaauth", "/profile", "/health", "/help")
            )
            or not request.endpoint
            # The Expo shell is a role home (login lands there); its assets are not pages.
            or request.endpoint == "expo_client.expo_asset"
        ):
            return None
        user_id = session.get("_user_id")
        if not user_id or g.get("bearer_auth"):
            return None
        from app.services import training_demo_service

        raw_uid = user_id.rpartition(":")[0] or user_id
        try:
            uid = uuid.UUID(raw_uid)
        except (TypeError, ValueError):
            return None
        if training_demo_service.should_redirect_to_welcome(uid):
            from app.routes.expo_client import export_ready

            return redirect("/app/training" if export_ready() else url_for("training_demo.welcome"))
        return None

    @app.after_request
    def apply_static_cache_headers(response):
        # Browser intake carries identifiers and questionnaire answers, and the
        # case list and intake replies carry registration numbers. This
        # applies to errors and redirects as well as successful JSON responses
        # (also set by those blueprints; this covers a request refused before
        # it reaches one, such as a CSRF or terms refusal).
        if request.path.startswith(_NO_STORE_API_PREFIXES):
            response.headers["Cache-Control"] = "no-store"
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

    return app
