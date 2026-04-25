from __future__ import annotations

import logging

from flask import current_app, jsonify
from flask_login import current_user

from app import db, limiter
from app.authz.access import action_authorized
from app.authz.resources import submission_from_kwarg
from app.services.analytics.data_management import (
    dm_accept_upstream_change,
    dm_reject_upstream_change,
    dm_upstream_change_details,
)
from app.services.analytics.submission_mv import refresh_submission_analytics_mv

from . import bp
from .helpers import refresh_dm_dashboard_analytics

log = logging.getLogger(__name__)


@bp.get("/submissions/<path:va_sid>/upstream-change-details")
@action_authorized(
    "dm_upstream_change_details_view",
    resource_resolver=submission_from_kwarg("va_sid"),
)
@limiter.limit("120 per minute")
def upstream_change_details(va_sid: str):
    try:
        return jsonify(dm_upstream_change_details(current_user, va_sid))
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 403
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404


@bp.post("/submissions/<va_sid>/accept-upstream-change")
@action_authorized(
    "dm_submission_upstream_accept",
    resource_resolver=submission_from_kwarg("va_sid"),
)
def accept_upstream_change(va_sid: str):
    try:
        dm_accept_upstream_change(current_user, va_sid)
        db.session.commit()
        refresh_dm_dashboard_analytics(refresh_submission_analytics_mv)
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 403
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception:
        db.session.rollback()
        log.error("accept_upstream_change failed for %s", va_sid, exc_info=True)
        return jsonify({"error": "Operation failed. Check server logs."}), 500

    task_id = None
    try:
        from app.tasks.sync_tasks import run_smartva_for_submission

        if current_app.extensions.get("celery"):
            task = run_smartva_for_submission.delay(
                va_sid=va_sid,
                triggered_by="data-manager-accept",
            )
            task_id = task.id
    except Exception:
        log.warning(
            "accept_upstream_change: could not enqueue SmartVA for %s",
            va_sid,
            exc_info=True,
        )

    return jsonify(
        {
            "message": "Upstream change accepted for recoding. Submission moved to SmartVA pending.",
            "smartva_task_id": task_id,
        }
    )


@bp.post("/submissions/<va_sid>/reject-upstream-change")
@action_authorized(
    "dm_submission_upstream_keep_current_icd",
    resource_resolver=submission_from_kwarg("va_sid"),
)
def reject_upstream_change(va_sid: str):
    try:
        dm_reject_upstream_change(current_user, va_sid)
        db.session.commit()
        refresh_dm_dashboard_analytics(refresh_submission_analytics_mv)
        return jsonify(
            {
                "message": (
                    "Latest upstream ODK data adopted. Current finalized ICD decision kept."
                )
            }
        )
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 403
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception:
        db.session.rollback()
        log.error("reject_upstream_change failed for %s", va_sid, exc_info=True)
        return jsonify({"error": "Operation failed. Check server logs."}), 500
