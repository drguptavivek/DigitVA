import logging
from app import create_app

flask_app = create_app()

# Silence noisy SQLAlchemy INFO logging in Celery worker/beat output
logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)

celery_app = flask_app.extensions["celery"]

