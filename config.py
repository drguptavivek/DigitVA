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