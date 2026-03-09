import os

basedir = os.path.abspath(os.path.dirname(__file__))

class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY") or "5Ag92#2g]oLIHEk"
    SQLALCHEMY_DATABASE_URI = (
        os.environ.get("DATABASE_URL")
        or "postgresql://minerva:minerva@localhost:5432/minerva"
    )
    APP_BASEDIR = basedir
    APP_RESOURCE = os.path.join(basedir, "resource")
    APP_DATA = os.path.join(basedir, "data")
    APP_BACKUP = os.path.join(basedir, "backup")
    APP_LOG = os.path.join(basedir, "logs")


class TestConfig(Config):
    TESTING = True
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