from __future__ import annotations

import logging

from flask import jsonify
from flask_login import current_user

from app import db
from app.authz.access import action_authorized
from app.authz.resources import submission_from_kwarg
from app.services.data_management.dashboard import dm_screening_pass, dm_screening_reject

from . import bp

log = logging.getLogger(__name__)


@bp.post("/submissions/<va_sid>/screening-pass")
@action_authorized(
    "dm_submission_screening_pass",
    resource_resolver=submission_from_kwarg("va_sid"),
)
def screening_pass(va_sid: str):
    try:
        dm_screening_pass(current_user, va_sid)
        db.session.commit()
        return jsonify({"message": "Screening passed. Submission moved to SmartVA pending."})
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 403
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception:
        db.session.rollback()
        log.error("screening_pass failed for %s", va_sid, exc_info=True)
        return jsonify({"error": "Operation failed. Check server logs."}), 500


@bp.post("/submissions/<va_sid>/screening-reject")
@action_authorized(
    "dm_submission_screening_reject",
    resource_resolver=submission_from_kwarg("va_sid"),
)
def screening_reject(va_sid: str):
    try:
        dm_screening_reject(current_user, va_sid)
        db.session.commit()
        return jsonify({"message": "Screening rejected. Submission marked not codeable."})
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 403
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception:
        db.session.rollback()
        log.error("screening_reject failed for %s", va_sid, exc_info=True)
        return jsonify({"error": "Operation failed. Check server logs."}), 500
