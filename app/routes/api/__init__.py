"""Versioned API package — all JSON endpoints live under /api/v1/."""

from flask import Blueprint

api_v1 = Blueprint("api_v1", __name__)

from app.routes.api import analytics, coding, data_management, icd10, nqa, profile, reviewing, so, workflow  # noqa: E402, F401

# DM KPI analytics sub-blueprints
from app.routes.api.dm_kpi import (  # noqa: E402, F401
    dm_kpi_grid,
    dm_kpi_sync,
    dm_kpi_language,
    dm_kpi_exclusions,
    dm_kpi_coders,
    dm_kpi_pipeline,
    dm_kpi_burndown,
)

api_v1.register_blueprint(analytics.bp, url_prefix="/analytics")
api_v1.register_blueprint(coding.bp, url_prefix="/coding")
api_v1.register_blueprint(data_management.bp, url_prefix="/data-management")
api_v1.register_blueprint(icd10.bp, url_prefix="/icd10")
api_v1.register_blueprint(nqa.bp, url_prefix="/va")
api_v1.register_blueprint(profile.bp, url_prefix="/profile")
api_v1.register_blueprint(reviewing.bp, url_prefix="/reviewing")
api_v1.register_blueprint(so.bp, url_prefix="/va")
api_v1.register_blueprint(workflow.bp, url_prefix="/workflow")

# DM KPI dashboard endpoints
api_v1.register_blueprint(dm_kpi_grid.bp, url_prefix="/analytics/dm-kpi/grid")
api_v1.register_blueprint(dm_kpi_sync.bp, url_prefix="/analytics/dm-kpi/sync")
api_v1.register_blueprint(dm_kpi_language.bp, url_prefix="/analytics/dm-kpi/language")
api_v1.register_blueprint(dm_kpi_exclusions.bp, url_prefix="/analytics/dm-kpi/exclusions")
api_v1.register_blueprint(dm_kpi_coders.bp, url_prefix="/analytics/dm-kpi/coders")
api_v1.register_blueprint(dm_kpi_pipeline.bp, url_prefix="/analytics/dm-kpi/pipeline")
api_v1.register_blueprint(dm_kpi_burndown.bp, url_prefix="/analytics/dm-kpi/burndown")
