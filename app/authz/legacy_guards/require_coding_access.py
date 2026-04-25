"""Shared work-session access check for coding/reviewing artifact APIs.

Used by the NQA and Social Autopsy APIs. These routes require an active
coding or reviewing allocation for the target submission depending on the
submitted actiontype. Admin users performing demo-mode sessions are allowed
through when va_actiontype == "vademo_start_coding".
"""

import sqlalchemy as sa
from flask import jsonify, request
from flask_login import current_user

from app import db
from app.authz.scope import user_has_role
from app.models import VaAllocations, VaAllocation, VaStatuses
from app.services.coding.demo import is_demo_training_submission


def require_coding_access(va_sid: str):
    """Return a JSON 403 response if the user lacks a valid work-session allocation.

    Returns None if access is granted, or a (response, status_code) tuple to
    return immediately from the route if access is denied.
    """
    data = request.get_json(silent=True) or {}
    actiontype = data.get("va_actiontype")
    if actiontype == "vademo_start_coding":
        if user_has_role(current_user, "admin"):
            return None
        if not (
            user_has_role(current_user, "coder")
            or user_has_role(current_user, "coding_tester")
        ) or not is_demo_training_submission(va_sid):
            return jsonify({"error": "Only demo/training projects allow coder demo sessions."}), 403

    allocation_for = VaAllocation.coding
    allocation_label = "coding"
    if actiontype in {"vastartreviewing", "varesumereviewing"}:
        allocation_for = VaAllocation.reviewing
        allocation_label = "reviewing"

    alloc = db.session.scalar(
        sa.select(VaAllocations.va_sid).where(
            VaAllocations.va_allocated_to == current_user.user_id,
            VaAllocations.va_allocation_for == allocation_for,
            VaAllocations.va_allocation_status == VaStatuses.active,
            VaAllocations.va_sid == va_sid,
        )
    )
    if not alloc:
        return jsonify({"error": f"Active {allocation_label} allocation required."}), 403
    return None
