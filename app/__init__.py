import uuid
import os
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



def _factor_enrollment_banner_context():
    """docs/policy/authentication-factors.md section 6: before
    ``AUTH_FACTOR_ENFORCE_FROM``, a privileged user with no passkey and no
    confirmed TOTP sees a banner naming the deadline on every page. Unset
    deadline means the rollout has not been announced -- no banner at all.
    Once the deadline has passed the redirect guard (``enforce_factor_setup``)
    takes over instead, so this stops firing then too.
    """
    if not (current_user and current_user.is_authenticated):
        return None
    from app.services import totp_service

    deadline = totp_service.enforcement_date()
    if deadline is None:
        return None
    if datetime.now(pytz.UTC).date() >= deadline:
        return None
    if not (current_user.is_admin() or current_user.is_data_manager()):
        return None
    if totp_service.has_any_factor(current_user.user_id):
        return None
    return {"deadline": deadline.strftime("%B %d, %Y")}


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


def create_app(config_class=None):
    if config_class is None:
        config_class = _default_config_class()
    app = Flask(__name__)
    app.config.from_object(config_class)
    if not (app.debug or app.testing):
        app.config["TRUSTED_HOSTS"] = trusted_hosts_for(app.config["MAIL_BASE_URL"])
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
            return jsonify({"error": f"The upload exceeds the {limit_mb} MB limit."}), 413
        return None

    # Fail closed before anything can serve an attachment: an S3 store with a
    # missing key must stop the app, never quietly fall back to local disk.
    validate_attachment_store_config(app.config)

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
    app.config.setdefault("WTF_CSRF_HEADERS", ["X-CSRFToken"])
    
    # Initialize Celery
    celery_init_app(app)

    from app.routes import register_blueprints  
    register_blueprints(app)
    from app.routes.expo_client import expo_client
    app.register_blueprint(expo_client)
    from app.routes.va_errors import register_error_handlers
    register_error_handlers(app)
    from app.logging import va_logging
    va_logging(app)
    
    from app import models #noqa
    from app import services #noqa
    from app import utils #noqa
    from app.tasks import kpi_tasks #noqa

    from app.commands.odk_sync import init_app as init_odk_sync_commands
    init_odk_sync_commands(app)

    from app.commands.form_types import init_app as init_form_types_commands
    init_form_types_commands(app)

    from app.commands.seed import init_app as init_seed_commands
    init_seed_commands(app)

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
    from app.utils.who_va_bundle import who_va_bundle_version

    app.add_template_global(who_va_bundle_version, "who_va_bundle_version")
    # The Organization panel's reference card, standalone or inside Project Setup.
    from app.services.organization_service import district_reference_model

    app.add_template_global(district_reference_model, "district_reference_model")

    @app.context_processor
    def inject_template_globals():
        from app.services.site_maintenance_service import get_site_maintenance_banner_context

        is_authenticated = bool(current_user and current_user.is_authenticated)
        is_admin = bool(
            current_user and current_user.is_authenticated and current_user.is_admin()
        )
        return {
            "current_year": datetime.now(pytz.UTC).astimezone(
                _current_user_timezone()
            ).year,
            "site_maintenance_banner": get_site_maintenance_banner_context(
                is_authenticated=is_authenticated,
                is_admin=is_admin,
            ),
            "site_maintenance_watcher_enabled": is_authenticated,
            "site_maintenance_user_is_admin": is_admin,
            "factor_enrollment_banner": _factor_enrollment_banner_context(),
        }

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
                response = jsonify({"error": message})
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

        from app.models import VaUsers

        fresh_user = db.session.get(VaUsers, current_user_id)
        if fresh_user is None or not fresh_user.is_active:
            return

        from app.services.site_maintenance_service import should_block_non_admin_after_cutoff
        from flask_login import logout_user

        if not fresh_user.is_admin() and should_block_non_admin_after_cutoff():
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
                        "error": "Site is under maintenance. Only admin login is allowed right now."
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
        }
        if fresh_user.pw_reset_t_and_c is False and request.endpoint not in allowed_endpoints:
            if request.endpoint == "api_v1.client_api.bootstrap":
                response = jsonify({
                    "code": "password_change_required",
                    "redirect_url": url_for('profile.force_password_change'),
                })
                response.status_code = 403
                response.headers["Cache-Control"] = "no-store"
                return response
            return redirect(url_for('profile.force_password_change'))

    # docs/policy/authentication-factors.md section 6: once
    # AUTH_FACTOR_ENFORCE_FROM has passed, a privileged user (admin or
    # data_manager) with no passkey and no confirmed TOTP is redirected to
    # the Profile factor-setup section from every other page -- no lock-out,
    # they can still sign in with their password. A break-glass reset
    # (va_login_factor_reset) forces the same redirect regardless of the
    # date via session["factor_setup_forced"], until they enrol.
    #
    # Uses current_user (not a raw session lookup) so it honours
    # auth_session_version the way force_password_update's fresh_user does
    # not: Flask-Login's user_loader already rejects a session whose version
    # is stale, and current_user is cached on `g` once resolved, so this
    # costs nothing extra when something upstream already touched it.
    # profile.force_password_change must stay reachable: force_password_update
    # (above) sends there first, and holding it here too looped a privileged
    # user with pw_reset_t_and_c=False (e.g. after a forgot-password reset)
    # between the two pages forever.
    _FACTOR_SETUP_EXEMPT_ENDPOINTS = {
        "static", "health.health_check", "profile.view", "profile.force_password_change",
    }

    @app.before_request
    def enforce_factor_setup():
        if request.path.startswith("/static") or request.path == "/health":
            return None
        # The device API is bearer-only and must never write a session
        # (cookie); its sign-in already asked for any factor the user holds.
        if request.path.startswith("/api/v1/device/"):
            return None
        if not current_user.is_authenticated:
            return None

        from app.services import totp_service

        # Cheap checks first: until the deadline (or a break-glass reset)
        # nobody is held, so skip the grant queries entirely.
        forced = session.get("factor_setup_forced")
        if not (forced or totp_service.enforcement_active()):
            return None

        # ponytail: privileged status isn't cached, so a grant added mid-
        # session takes effect immediately; two grant queries per request
        # while enforcement is on. Cache in the session if that ever shows.
        privileged = current_user.is_admin() or current_user.is_data_manager()
        if not privileged:
            return None

        needed = session.get("factor_setup_needed")
        if needed is None:
            needed = not totp_service.has_any_factor(current_user.user_id)
            session["factor_setup_needed"] = needed
        if not needed:
            session.pop("factor_setup_forced", None)
            return None

        endpoint = request.endpoint or ""
        if (
            endpoint in _FACTOR_SETUP_EXEMPT_ENDPOINTS
            or endpoint.startswith("va_auth.")
            or endpoint.startswith("api_v1.profile_api.")
        ):
            return None

        from app.decorators.role_required import API_PATH_PREFIXES

        if request.path.startswith(API_PATH_PREFIXES):
            if request.endpoint == "api_v1.client_api.bootstrap":
                return jsonify({
                    "error": "factor_setup_required",
                    "code": "factor_setup_required",
                    "redirect_url": url_for("profile.view") + "#passkeys-card",
                }), 403
            return jsonify({"error": "factor_setup_required"}), 403
        return redirect(url_for("profile.view") + "#passkeys-card")

    @app.after_request
    def apply_static_cache_headers(response):
        # Browser intake carries identifiers and questionnaire answers. This
        # applies to errors and redirects as well as successful JSON responses.
        if request.path.startswith(("/intake/api/", "/api/v1/client/")):
            response.headers["Cache-Control"] = "no-store"
        if request.path.startswith("/static/") and response.status_code == 200:
            response.cache_control.public = True
            response.cache_control.max_age = app.config["STATIC_ASSET_CACHE_MAX_AGE"]
        started_at = getattr(g, "_request_started_at", None)
        if started_at is not None:
            duration_ms = (perf_counter() - started_at) * 1000
            response.headers["Server-Timing"] = f"app;dur={duration_ms:.1f}"
            response.headers["X-Response-Time"] = f"{duration_ms:.1f}ms"
            if duration_ms >= 300:
                app.logger.info(
                    "slow_request method=%s path=%s status=%s duration_ms=%.1f",
                    request.method,
                    request.path,
                    response.status_code,
                    duration_ms,
                )
        return response

    return app
