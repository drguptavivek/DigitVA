"""Gunicorn entry point for the isolated public DORIS training service."""

from app.public_doris import create_public_doris_app

app = create_public_doris_app()
