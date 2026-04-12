"""Shared coding-allocation access check for API routes.

Used by the NQA and Social Autopsy APIs — both require an active coding
allocation for the target submission.  Admin users performing demo-mode
sessions are allowed through when va_actiontype == "vademo_start_coding".
"""

import sqlalchemy as sa
from flask import jsonify, request
from flask_login import current_user

from app import db
from app.models import VaAllocations, VaAllocation, VaStatuses
from app.services.demo_project_service import is_demo_training_submission


def require_coding_access(va_sid: str):
    """Return a JSON 403 response if the user lacks an active coding allocation.

    Returns None if access is granted, or a (response, status_code) tuple to
    return immediately from the route if access is denied.
    """
    data = request.get_json(silent=True) or {}
    if data.get("va_actiontype") == "vademo_start_coding":
        if current_user.is_admin():
            return None
        if not (current_user.is_coder() or current_user.is_coding_tester()) or not is_demo_training_submission(va_sid):
            return jsonify({"error": "Only demo/training projects allow coder demo sessions."}), 403

    alloc = db.session.scalar(
        sa.select(VaAllocations.va_sid).where(
            VaAllocations.va_allocated_to == current_user.user_id,
            VaAllocations.va_allocation_for == VaAllocation.coding,
            VaAllocations.va_allocation_status == VaStatuses.active,
            VaAllocations.va_sid == va_sid,
        )
    )
    if not alloc:
        return jsonify({"error": "Active coding allocation required."}), 403
    return None
