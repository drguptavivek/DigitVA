"""Data management API package — /api/v1/data-management/."""

from flask import Blueprint

from app.services.data_management.dashboard import (
    dm_smartva_input_export_csv,
    dm_smartva_likelihoods_export_csv,
    dm_smartva_results_export_csv,
)
from app.services.analytics.submission_mv import get_dm_kpi_from_mv

bp = Blueprint("data_management_api", __name__)

from . import analytics, exports, screening, submissions, sync, upstream_changes  # noqa: E402,F401
from .analytics import coder_daily_stats, filter_options, kpi, project_site_submissions  # noqa: E402,F401
from .exports import (  # noqa: E402,F401
    submissions_export_csv,
    submissions_export_smartva_input_csv,
    submissions_export_smartva_likelihoods_csv,
    submissions_export_smartva_results_csv,
)
from .screening import screening_pass, screening_reject  # noqa: E402,F401
from .submissions import submissions  # noqa: E402,F401
from .sync import sync_form, sync_preview, sync_runs, sync_submission  # noqa: E402,F401
from .upstream_changes import accept_upstream_change, reject_upstream_change, upstream_change_details  # noqa: E402,F401

__all__ = [
    "bp",
    "accept_upstream_change",
    "coder_daily_stats",
    "dm_smartva_input_export_csv",
    "dm_smartva_likelihoods_export_csv",
    "dm_smartva_results_export_csv",
    "filter_options",
    "get_dm_kpi_from_mv",
    "kpi",
    "project_site_submissions",
    "reject_upstream_change",
    "screening_pass",
    "screening_reject",
    "submissions",
    "submissions_export_csv",
    "submissions_export_smartva_input_csv",
    "submissions_export_smartva_likelihoods_csv",
    "submissions_export_smartva_results_csv",
    "sync_form",
    "sync_preview",
    "sync_runs",
    "sync_submission",
    "upstream_change_details",
]
