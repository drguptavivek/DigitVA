"""Versioned API package — all JSON endpoints live under /api/v1/."""

from flask import Blueprint

api_v1 = Blueprint("api_v1", __name__)

from app.routes.api import analytics, coding, data_management, icd10, nqa, so  # noqa: E402, F401

api_v1.register_blueprint(analytics.bp, url_prefix="/analytics")
api_v1.register_blueprint(coding.bp, url_prefix="/coding")
api_v1.register_blueprint(data_management.bp, url_prefix="/data-management")
api_v1.register_blueprint(icd10.bp, url_prefix="/icd10")
api_v1.register_blueprint(nqa.bp, url_prefix="/va")
api_v1.register_blueprint(so.bp, url_prefix="/va")
