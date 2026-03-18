"""Versioned API package — all JSON endpoints live under /api/v1/."""

from flask import Blueprint

api_v1 = Blueprint("api_v1", __name__)

from app.routes.api import analytics, data_management  # noqa: E402, F401

api_v1.register_blueprint(analytics.bp, url_prefix="/analytics")
api_v1.register_blueprint(data_management.bp, url_prefix="/data-management")
