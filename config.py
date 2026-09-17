import os
import re
import tempfile
from datetime import timedelta
from urllib.parse import urlparse

import redis
from dotenv import load_dotenv

load_dotenv()

basedir = os.path.abspath(os.path.dirname(__file__))


# --- Attachment object store -------------------------------------------------
# DigitVA keeps its own permanent copy of every attachment. ``ATTACHMENT_STORE``
# selects the backend: local files under APP_DATA (development, tests, and the
# pre-cutover state) or a private DigitVA-owned S3 bucket.
# Baseline: docs/policy/attachment-storage.md.

ATTACHMENT_STORE_LOCAL = "local"
ATTACHMENT_STORE_S3 = "s3"
ATTACHMENT_STORES = (ATTACHMENT_STORE_LOCAL, ATTACHMENT_STORE_S3)

# Names only — values are secrets and are never logged or echoed.
REQUIRED_S3_CONFIG_KEYS = (
    "S3_SERVER",
    "S3_BUCKET",
    "S3_REGION",
    "S3_ACCESS_KEY_ID",
    "S3_SECRET_ACCESS_KEY",
)

_AWS_S3_HOST_RE = re.compile(r"^s3[.-]([a-z0-9-]+)\.amazonaws\.com$", re.IGNORECASE)


def _region_from_s3_server(server: str) -> str:
    """Derive the region from an AWS endpoint host, else "".

    ``https://s3.ap-south-1.amazonaws.com`` -> ``ap-south-1``. A non-AWS or
    unrecognised endpoint returns "" so that S3_REGION becomes required.
    """
    if not server:
        return ""
    host = urlparse(server if "//" in server else f"https://{server}").hostname or ""
    match = _AWS_S3_HOST_RE.match(host)
    return match.group(1).lower() if match else ""


def validate_attachment_store_config(config) -> None:
    """Fail closed at startup when the selected attachment store is unusable.

    Called from ``create_app``. With ``ATTACHMENT_STORE=s3`` every required key
    must be present: a missing key is a hard startup error, never a silent
    fallback to local disk, because that would scatter PHI across app servers
    that are expected to hold nothing. Only key *names* appear in the message.
    """
    store = (config.get("ATTACHMENT_STORE") or "").strip().lower()
    if store not in ATTACHMENT_STORES:
        raise RuntimeError(
            f"ATTACHMENT_STORE must be one of {', '.join(ATTACHMENT_STORES)}; got '{store}'."
        )

    expiry = config.get("ATTACHMENT_PRESIGN_EXPIRY_SECONDS")
    if not isinstance(expiry, int) or not (1 <= expiry <= 604800):
        raise RuntimeError(
            "ATTACHMENT_PRESIGN_EXPIRY_SECONDS must be an integer between 1 and 604800."
        )

    if store != ATTACHMENT_STORE_S3:
        return

    missing = [key for key in REQUIRED_S3_CONFIG_KEYS if not config.get(key)]
    if missing:
        raise RuntimeError(
            "ATTACHMENT_STORE=s3 requires these environment variables: "
            + ", ".join(missing)
            + ". Set them or switch ATTACHMENT_STORE back to 'local'; "
            "DigitVA never falls back to local disk silently."
        )


def _require_env(key: str) -> str:
    value = os.environ.get(key)
    if not value:
        raise RuntimeError(
            f"Required environment variable '{key}' is not set. "
            f"Add it to your .env file or container environment."
        )
    return value


class Config:
    # SECURITY: SECRET_KEY must be set via environment variable in production.
    # The fallback is only for development convenience and should never be used in production.
    # Docker Compose will fail to start if .env is missing required variables.
    SECRET_KEY = _require_env("SECRET_KEY")
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=30)
    REMEMBER_COOKIE_DURATION = timedelta(days=30)
    STATIC_ASSET_CACHE_MAX_AGE = int(
        os.environ.get("STATIC_ASSET_CACHE_MAX_AGE", str(60 * 60 * 24 * 30))
    )
    STATIC_ASSET_VERSION = os.environ.get("STATIC_ASSET_VERSION", "1")
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = os.environ.get("SESSION_COOKIE_SAMESITE", "Lax")
    SESSION_COOKIE_SECURE = True
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = os.environ.get("REMEMBER_COOKIE_SAMESITE", "Lax")
    REMEMBER_COOKIE_SECURE = True
    WTF_CSRF_SSL_STRICT = True
    
    # Session Configuration
    SESSION_TYPE = "sqlalchemy"
    SESSION_PERMANENT = True
    SESSION_USE_SIGNER = True
    SESSION_SQLALCHEMY_TABLE = "va_sessions"
    
    SQLALCHEMY_DATABASE_URI = _require_env("DATABASE_URL")
    # Database connection pool settings - prevents connection leaks and pool exhaustion
    # 3 services × (pool_size=3 + max_overflow=5) = 24 max connections → fits within max_connections=40
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,      # Detect stale connections before use
        "pool_size": 3,             # Reduced from 5 — sufficient for low-concurrency Flask/Celery
        "max_overflow": 5,          # Burst up to 8 total per process when needed
        "pool_recycle": 300,        # Recycle connections after 5 minutes
        "pool_use_lifo": True,      # Reuse most-recently-used connections; lets cold ones expire naturally
        "pool_timeout": 20,         # Fail fast if pool exhausted (default is 30s)
    }
    APP_BASEDIR = basedir
    APP_RESOURCE = os.path.join(basedir, "resource")
    APP_DATA = os.path.join(basedir, "data")
    APP_SMARTVA_RUNS = os.environ.get(
        "APP_SMARTVA_RUNS",
        os.path.join(basedir, "smartva_runs"),
    )
    APP_LOG = os.path.join(basedir, "logs")

    # Validated at runtime when first used — see app/utils/credential_crypto.py
    ODK_CREDENTIAL_PEPPER: str = os.environ.get("ODK_CREDENTIAL_PEPPER", "")
    ODK_CONNECTION_FAILURE_THRESHOLD = int(
        os.environ.get("ODK_CONNECTION_FAILURE_THRESHOLD", "3")
    )
    ODK_CONNECTION_FAILURE_COOLDOWN_SECONDS = int(
        os.environ.get("ODK_CONNECTION_FAILURE_COOLDOWN_SECONDS", "300")
    )
    ODK_CONNECTION_MIN_REQUEST_INTERVAL_SECONDS = float(
        os.environ.get("ODK_CONNECTION_MIN_REQUEST_INTERVAL_SECONDS", "0.5")
    )
    HIBP_PASSWORD_BREACH_CHECK_ENABLED = os.environ.get(
        "HIBP_PASSWORD_BREACH_CHECK_ENABLED", "true"
    ).lower() in ("true", "1", "yes")
    HIBP_PASSWORD_BREACH_CHECK_TIMEOUT_SECONDS = float(
        os.environ.get("HIBP_PASSWORD_BREACH_CHECK_TIMEOUT_SECONDS", "5")
    )
    ODK_CONNECTION_TEST_TIMEOUT_SECONDS = int(
        os.environ.get("ODK_CONNECTION_TEST_TIMEOUT_SECONDS", "10")
    )
    ODK_CONNECT_TIMEOUT_SECONDS = float(
        os.environ.get("ODK_CONNECT_TIMEOUT_SECONDS", "10")
    )
    ODK_READ_TIMEOUT_SECONDS = float(
        os.environ.get("ODK_READ_TIMEOUT_SECONDS", "60")
    )
    # Request-path attachment fetches from ODK Central (Phase 4a of
    # docs/planning/s3-attachment-plan.md). Deliberately tighter than the sync
    # timeouts above: these run inside a coder's HTTP request, so a stalled
    # Central must fail fast instead of occupying a web worker.
    ATTACHMENT_FETCH_CONNECT_TIMEOUT_SECONDS = float(
        os.environ.get("ATTACHMENT_FETCH_CONNECT_TIMEOUT_SECONDS", "5")
    )
    ATTACHMENT_FETCH_READ_TIMEOUT_SECONDS = float(
        os.environ.get("ATTACHMENT_FETCH_READ_TIMEOUT_SECONDS", "30")
    )
    # How long a request-path fetch will queue behind the shared ODK pacing
    # interval before giving up (see OdkRequestSlotBusyError). 0 = never wait.
    ATTACHMENT_FETCH_MAX_SLOT_WAIT_SECONDS = float(
        os.environ.get("ATTACHMENT_FETCH_MAX_SLOT_WAIT_SECONDS", "1")
    )

    # --- Attachment object store ---------------------------------------
    # 'local' keeps the historical files under APP_DATA/<form_id>/media/.
    # 's3' puts every original and MP3 derivative in a private DigitVA-owned
    # bucket and delivers each one as a short-lived presigned redirect.
    # Validated by validate_attachment_store_config() at app startup.
    ATTACHMENT_STORE = os.environ.get("ATTACHMENT_STORE", ATTACHMENT_STORE_LOCAL).strip().lower()
    # Endpoint URL, e.g. https://s3.ap-south-1.amazonaws.com
    S3_SERVER = os.environ.get("S3_SERVER", "").strip()
    S3_BUCKET = os.environ.get("S3_BUCKET", "").strip()
    # Derived from the endpoint host when it is an AWS one; otherwise required.
    S3_REGION = (
        os.environ.get("S3_REGION", "").strip() or _region_from_s3_server(S3_SERVER)
    )
    # Secrets: read from the environment, never logged and never sent to a client.
    S3_ACCESS_KEY_ID = os.environ.get("S3_ACCESS_KEY_ID", "")
    S3_SECRET_ACCESS_KEY = os.environ.get("S3_SECRET_ACCESS_KEY", "")
    # Optional key prefix inside the bucket, e.g. "digitva/" (empty by default).
    S3_PREFIX = os.environ.get("S3_PREFIX", "")
    # Lifetime of a delivery presigned URL. Short by design: the URL is a
    # bearer capability for PHI bytes and is never stored, cached or logged.
    ATTACHMENT_PRESIGN_EXPIRY_SECONDS = int(
        os.environ.get("ATTACHMENT_PRESIGN_EXPIRY_SECONDS", "300")
    )
    # How often the Celery sweep copies any attachment blob still held only on
    # the VM into the bucket (``run_attachment_s3_upload``). The sweep is an
    # instant no-op when the store is local or the backlog is empty, so it is
    # left scheduled permanently: it is both the cutover mechanism and the
    # self-heal for any row that later ends up with store_state='local'.
    ATTACHMENT_S3_UPLOAD_SWEEP_MINUTES = int(
        os.environ.get("ATTACHMENT_S3_UPLOAD_SWEEP_MINUTES", "10")
    )

    # --- SmartVA run archive -------------------------------------------
    # A SmartVA run directory is a local working area the CLI needs while it
    # runs; once its likelihood rows are in va_smartva_run_outputs nothing in
    # the app reads it again. With ATTACHMENT_STORE=s3 the whole directory is
    # archived under the smartva_runs/ prefix of the same private bucket and
    # the local copy is removed once this many days have passed since the run
    # completed. 0 = remove immediately after a verified archive. Raise it only
    # to keep a debugging window on the VM; the objects are never presigned and
    # never served. Ignored entirely on the local store.
    # Baseline: docs/policy/smartva-generation-policy.md.
    SMARTVA_RUNS_KEEP_LOCAL_DAYS = int(
        os.environ.get("SMARTVA_RUNS_KEEP_LOCAL_DAYS", "0")
    )

    # --- Database backups ----------------------------------------------
    # The nightly ``pg_dump -Fc`` of the application database. With
    # ATTACHMENT_STORE=s3 the dump goes straight to the DigitVA bucket under
    # the db-backups/ prefix and the VM keeps no dump history at all; on the
    # local store it lands in DB_BACKUP_LOCAL_DIR so development still has a
    # useful command. Retention is a count of dumps, applied to whichever of
    # the two the deployment uses.
    # Baseline: docs/current-state/backup.md.
    DB_BACKUP_DAILY_TIME = os.environ.get("DB_BACKUP_DAILY_TIME", "01:30").strip()
    DB_BACKUP_KEEP_DAILY = int(os.environ.get("DB_BACKUP_KEEP_DAILY", "30"))
    # Where a dump is written on the local store. Inside the container this is
    # a directory of the project, not $HOME, so it survives neither more nor
    # less than the rest of the bind mount.
    DB_BACKUP_LOCAL_DIR = os.environ.get(
        "DB_BACKUP_LOCAL_DIR", os.path.join(basedir, "dailybackups")
    )
    # Scratch space for the dump on its way to the bucket. One file at a time,
    # removed in a finally: the VM never accumulates dumps.
    DB_BACKUP_TMP_DIR = os.environ.get("DB_BACKUP_TMP_DIR", tempfile.gettempdir())
    # Hard stop for one pg_dump. Well above the ~30 MB / few-seconds dump this
    # database produces today; a run that hits it is a hung connection.
    DB_BACKUP_TIMEOUT_SECONDS = int(
        os.environ.get("DB_BACKUP_TIMEOUT_SECONDS", "1800")
    )

    # --- Data-manager CSV exports --------------------------------------
    # An export is derived data: a data manager can always ask for it again.
    # With ATTACHMENT_STORE=s3 it is written to the exports/ prefix of the same
    # private bucket and delivered as a short-lived presigned download, so the
    # app server keeps no export file; on the local store it lands under
    # APP_DATA/exports/. Either way it is deleted once this many hours old.
    # Baseline: docs/current-state/data-manager-dashboard.md.
    EXPORT_RETENTION_HOURS = int(os.environ.get("EXPORT_RETENTION_HOURS", "24"))

    # Email (SMTP)
    MAIL_SERVER = os.environ.get("MAIL_SERVER", "localhost")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", "587"))
    MAIL_USE_TLS = os.environ.get("MAIL_USE_TLS", "true").lower() in ("true", "1", "yes")
    MAIL_USE_SSL = os.environ.get("MAIL_USE_SSL", "false").lower() in ("true", "1", "yes")
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME", "")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD", "")
    MAIL_DEFAULT_SENDER = os.environ.get("MAIL_DEFAULT_SENDER", "noreply@digitva.org")
    # Base URL used for building links in emails (e.g. https://digitva.example.com)
    MAIL_BASE_URL = os.environ.get("MAIL_BASE_URL", "")
    MAIL_SUPPRESS_SEND = os.environ.get("MAIL_SUPPRESS_SEND", "false").lower() in (
        "true",
        "1",
        "yes",
    )
    EMAIL_DELIVERY_ENABLED = os.environ.get(
        "EMAIL_DELIVERY_ENABLED", "true"
    ).lower() in ("true", "1", "yes")
    EMAIL_SUPPRESSION_TTL_SECONDS = int(
        os.environ.get("EMAIL_SUPPRESSION_TTL_SECONDS", str(60 * 60 * 24 * 14))
    )
    EMAIL_SUPPRESSION_CACHE_PREFIX = os.environ.get(
        "EMAIL_SUPPRESSION_CACHE_PREFIX", "digitva_email_suppressed:"
    )
    METHOD_NOT_ALLOWED_BAN_ENABLED = os.environ.get(
        "METHOD_NOT_ALLOWED_BAN_ENABLED", "true"
    ).lower() in ("true", "1", "yes")
    METHOD_NOT_ALLOWED_BAN_METHODS = tuple(
        method.strip().upper()
        for method in os.environ.get(
            "METHOD_NOT_ALLOWED_BAN_METHODS",
            "POST,PATCH",
        ).split(",")
        if method.strip()
    )
    METHOD_NOT_ALLOWED_BAN_THRESHOLD = int(
        os.environ.get("METHOD_NOT_ALLOWED_BAN_THRESHOLD", "10")
    )
    METHOD_NOT_ALLOWED_BAN_WINDOW_SECONDS = int(
        os.environ.get("METHOD_NOT_ALLOWED_BAN_WINDOW_SECONDS", "600")
    )
    METHOD_NOT_ALLOWED_BAN_SECONDS = int(
        os.environ.get("METHOD_NOT_ALLOWED_BAN_SECONDS", "3600")
    )
    METHOD_NOT_ALLOWED_BAN_COUNTER_PREFIX = os.environ.get(
        "METHOD_NOT_ALLOWED_BAN_COUNTER_PREFIX",
        "digitva_method_not_allowed:count:",
    )
    METHOD_NOT_ALLOWED_BAN_PREFIX = os.environ.get(
        "METHOD_NOT_ALLOWED_BAN_PREFIX",
        "digitva_method_not_allowed:ban:",
    )
    METHOD_NOT_ALLOWED_BAN_MESSAGE = os.environ.get(
        "METHOD_NOT_ALLOWED_BAN_MESSAGE",
        (
            "Access temporarily blocked because this IP sent repeated invalid "
            "POST/PATCH requests to routes that do not allow those methods. "
            "Try again later."
        ),
    )

    REDIS_URL = os.environ.get("REDIS_URL") or "redis://localhost:6379/0"
    ICD_SEARCH_CACHE_TIMEOUT = int(
        os.environ.get("ICD_SEARCH_CACHE_TIMEOUT", str(60 * 60 * 24 * 7))
    )
    
    CELERY = {
        "broker_url": os.environ.get("CELERY_BROKER_URL") or REDIS_URL,
        "result_backend": os.environ.get("CELERY_RESULT_BACKEND") or REDIS_URL,
        "task_ignore_result": True,
        "beat_dburi": SQLALCHEMY_DATABASE_URI,
        "timezone": "UTC",
        "enable_utc": True,
        "worker_prefetch_multiplier": 1,    # Fetch one task at a time — prevents memory hoarding
        "worker_max_tasks_per_child": 100,  # Recycle worker after 100 tasks to prevent memory drift
    }


class TestConfig(Config):
    TESTING = True
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_SECURE = False
    WTF_CSRF_SSL_STRICT = False
    ODK_CREDENTIAL_PEPPER = "test-pepper-do-not-use-in-production"
    # Use in-memory storage for the rate limiter during tests.
    RATELIMIT_STORAGE_URI = "memory://"
    # Keep test sessions out of SQLAlchemy metadata/schema lifecycle.
    # This avoids Flask-Session redefining the va_sessions table every time
    # create_app() is called across multiple test classes.
    SESSION_TYPE = "filesystem"
    SESSION_FILE_DIR = os.path.join(
        tempfile.gettempdir(), "digitva_test_flask_session"
    )
    # Derive test DB URL from DATABASE_URL (swap db name to minerva_test) so
    # this works both inside Docker (minerva_db_service:5432) and locally
    # (localhost:8450).  TEST_DATABASE_URL overrides everything.
    _base_url = (
        os.environ.get("DATABASE_URL")
        or "postgresql://minerva:minerva@localhost:8450/minerva"
    )
    SQLALCHEMY_DATABASE_URI = (
        os.environ.get("TEST_DATABASE_URL")
        or _base_url.rsplit("/", 1)[0] + "/minerva_test"
    )
    # Use a fixed secret key so CSRF tokens are reproducible within a test session
    SECRET_KEY = "test-secret-key-not-for-production"
    WTF_CSRF_SECRET_KEY = "test-csrf-secret-key-not-for-production"
    METHOD_NOT_ALLOWED_BAN_COUNTER_PREFIX = "digitva_test_method_not_allowed:count:"
    METHOD_NOT_ALLOWED_BAN_PREFIX = "digitva_test_method_not_allowed:ban:"
    ODK_CONNECTION_MIN_REQUEST_INTERVAL_SECONDS = 0.0
    ODK_CONNECTION_FAILURE_COOLDOWN_SECONDS = 60
    ODK_CONNECT_TIMEOUT_SECONDS = 1.0
    ODK_READ_TIMEOUT_SECONDS = 5.0
    ATTACHMENT_FETCH_CONNECT_TIMEOUT_SECONDS = 1.0
    ATTACHMENT_FETCH_READ_TIMEOUT_SECONDS = 5.0
    ATTACHMENT_FETCH_MAX_SLOT_WAIT_SECONDS = 0.0
    # The suite runs against the local store by default so the existing
    # attachment tests keep their disk semantics. The S3 test classes flip
    # ATTACHMENT_STORE themselves and run entirely inside moto, which
    # intercepts botocore before any socket is opened. The endpoint has to be
    # AWS-shaped for moto to recognise the service; the bucket does not exist
    # and the credentials below are obvious fakes, so a test that forgot to
    # start the mock fails to authenticate rather than touching real data.
    ATTACHMENT_STORE = ATTACHMENT_STORE_LOCAL
    S3_SERVER = "https://s3.ap-south-1.amazonaws.com"
    S3_BUCKET = "digitva-test-attachments"
    S3_REGION = "ap-south-1"
    S3_ACCESS_KEY_ID = "testing-access-key"
    S3_SECRET_ACCESS_KEY = "testing-secret-key"
    S3_PREFIX = ""
    ATTACHMENT_PRESIGN_EXPIRY_SECONDS = 300
    SMARTVA_RUNS_KEEP_LOCAL_DAYS = 0
    # Each backup test points DB_BACKUP_LOCAL_DIR / DB_BACKUP_TMP_DIR at its own
    # temporary directory; the timeout is short so a hung pg_dump fails the test
    # rather than the session.
    DB_BACKUP_TIMEOUT_SECONDS = 120
    DB_BACKUP_KEEP_DAILY = 3
    HIBP_PASSWORD_BREACH_CHECK_ENABLED = False
    HIBP_PASSWORD_BREACH_CHECK_TIMEOUT_SECONDS = 1.0
    MAIL_SUPPRESS_SEND = True

    CELERY = Config.CELERY.copy()
    CELERY["beat_dburi"] = SQLALCHEMY_DATABASE_URI


class DevelopmentConfig(Config):
    DEBUG = True
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_SECURE = False
    WTF_CSRF_SSL_STRICT = False
