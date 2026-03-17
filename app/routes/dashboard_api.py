"""Dashboard API blueprint — dashboard-specific actions for logged-in users.

Routes:
  POST /vadashboard/api/data-manager/refresh-mv  — trigger on-demand MV refresh
                                                    then reload the dashboard

For analytics data (KPI, submissions, demographics, workflow, COD) use the
dedicated analytics blueprint at /api/analytics/*.
"""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify
from flask_login import login_required, current_user

from app.services.submission_analytics_mv import refresh_submission_analytics_mv

dashboard_api = Blueprint("dashboard_api", __name__)
log = logging.getLogger(__name__)


@dashboard_api.post("/api/data-manager/refresh-mv")
@login_required
def data_manager_refresh_mv():
    """Refresh the submission analytics materialized view on demand."""
    if not current_user.is_data_manager():
        return jsonify({"error": "Data-manager access is required."}), 403

    try:
        refresh_submission_analytics_mv(concurrently=False)
    except Exception as exc:
        log.exception("On-demand MV refresh failed: %s", exc)
        return jsonify({"error": "Dashboard refresh failed. Check server logs."}), 500

    return jsonify({"message": "Dashboard data refreshed successfully."}), 200
