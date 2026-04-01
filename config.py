import os
import tempfile
import redis
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()

basedir = os.path.abspath(os.path.dirname(__file__))


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
    SECRET_KEY = os.environ.get("SECRET_KEY") or "5Ag92#2g]oLIHEk"
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=30)
    REMEMBER_COOKIE_DURATION = timedelta(minutes=30)
    STATIC_ASSET_CACHE_MAX_AGE = int(
        os.environ.get("STATIC_ASSET_CACHE_MAX_AGE", str(60 * 60 * 24 * 30))
    )
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = os.environ.get("SESSION_COOKIE_SAMESITE", "Lax")
    SESSION_COOKIE_SECURE = True
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = os.environ.get("REMEMBER_COOKIE_SAMESITE", "Lax")
    REMEMBER_COOKIE_SECURE = True
    
    # Session Configuration
    SESSION_TYPE = "sqlalchemy"
    SESSION_PERMANENT = True
    SESSION_USE_SIGNER = True
    SESSION_SQLALCHEMY_TABLE = "va_sessions"
    
    SQLALCHEMY_DATABASE_URI = (
        os.environ.get("DATABASE_URL")
        or "postgresql://minerva:minerva@localhost:5432/minerva"
    )
    # Database connection pool settings - prevents connection leaks and pool exhaustion
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,  # Detect stale connections before use
        "pool_size": 5,         # 5 connections per pool (default)
        "max_overflow": 10,     # Allow 10 extra connections when pool is full
        "pool_recycle": 300,    # Recycle connections after 5 minutes (good for Celery + cloud DBs)
    }
    APP_BASEDIR = basedir
    APP_RESOURCE = os.path.join(basedir, "resource")
    APP_DATA = os.path.join(basedir, "data")
    APP_BACKUP = os.path.join(basedir, "backup")
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
    ODK_CONNECTION_TEST_TIMEOUT_SECONDS = int(
        os.environ.get("ODK_CONNECTION_TEST_TIMEOUT_SECONDS", "10")
    )
    ODK_CONNECT_TIMEOUT_SECONDS = float(
        os.environ.get("ODK_CONNECT_TIMEOUT_SECONDS", "10")
    )
    ODK_READ_TIMEOUT_SECONDS = float(
        os.environ.get("ODK_READ_TIMEOUT_SECONDS", "60")
    )

    REDIS_URL = os.environ.get("REDIS_URL") or "redis://localhost:6379/0"
    
    CELERY = {
        "broker_url": os.environ.get("CELERY_BROKER_URL") or REDIS_URL,
        "result_backend": os.environ.get("CELERY_RESULT_BACKEND") or REDIS_URL,
        "task_ignore_result": True,
        "beat_dburi": SQLALCHEMY_DATABASE_URI,
        "timezone": "UTC",
        "enable_utc": True,
    }


class TestConfig(Config):
    TESTING = True
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_SECURE = False
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
    ODK_CONNECTION_MIN_REQUEST_INTERVAL_SECONDS = 0.0
    ODK_CONNECTION_FAILURE_COOLDOWN_SECONDS = 60
    ODK_CONNECT_TIMEOUT_SECONDS = 1.0
    ODK_READ_TIMEOUT_SECONDS = 5.0

    CELERY = Config.CELERY.copy()
    CELERY["beat_dburi"] = SQLALCHEMY_DATABASE_URI
