import os
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
    SECRET_KEY = os.environ.get("SECRET_KEY") or "5Ag92#2g]oLIHEk"
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=30)
    REMEMBER_COOKIE_DURATION = timedelta(minutes=30)
    
    # Session Configuration
    SESSION_TYPE = "sqlalchemy"
    SESSION_PERMANENT = True
    SESSION_USE_SIGNER = True
    SESSION_SQLALCHEMY_TABLE = "va_sessions"
    
    SQLALCHEMY_DATABASE_URI = (
        os.environ.get("DATABASE_URL")
        or "postgresql://minerva:minerva@localhost:5432/minerva"
    )
    APP_BASEDIR = basedir
    APP_RESOURCE = os.path.join(basedir, "resource")
    APP_DATA = os.path.join(basedir, "data")
    APP_BACKUP = os.path.join(basedir, "backup")
    APP_LOG = os.path.join(basedir, "logs")

    # Validated at runtime when first used — see app/utils/credential_crypto.py
    ODK_CREDENTIAL_PEPPER: str = os.environ.get("ODK_CREDENTIAL_PEPPER", "")

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
    ODK_CREDENTIAL_PEPPER = "test-pepper-do-not-use-in-production"
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
    
    CELERY = Config.CELERY.copy()
    CELERY["beat_dburi"] = SQLALCHEMY_DATABASE_URI