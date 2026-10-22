"""Shared coding-allocation access check for API routes.

Used by the NQA, Social Autopsy and ICD-10 APIs: coding scope (Action.CODE)
and an active coding allocation for the target submission.  Admin demo
sessions (va_actiontype == "vademo_start_coding") pass on a demo/training
submission; on any other submission they need the admin's own active coding
allocation, as admin holds no CODE scope.
"""

import sqlalchemy as sa
from flask import jsonify, request
from flask_login import current_user

from app import db
from app.models import VaAllocations, VaAllocation, VaStatuses
from app.services.authz import Action, can
from app.services.demo_project_service import is_demo_training_submission


def require_coding_access(va_sid: str):
    """Return a JSON 403 response if the user lacks an active coding allocation.

    The body is ``{"error", "code"}``: ``forbidden`` (outside the coding
    scope, or a coder demo session off a demo/training project) or
    ``no_allocation``.

    Returns None if access is granted, or a (response, status_code) tuple to
    return immediately from the route if access is denied.
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}
    is_admin = current_user.is_admin()
    if data.get("va_actiontype") == "vademo_start_coding":
        demo_submission = is_demo_training_submission(va_sid)
        if is_admin and demo_submission:
            return None
        if not is_admin and (
            not (current_user.is_coder() or current_user.is_coding_tester())
            or not demo_submission
        ):
            return jsonify({
                "error": "Only demo/training projects allow coder demo sessions.",
                "code": "forbidden",
            }), 403

    # CODE scope as well as the allocation: an allocation that outlived a
    # re-routing or a narrowed grant does not carry the save. Admin holds no
    # CODE scope; its only coding is the demo session on its own allocation
    # (start_demo_allocation), so admin is held to the allocation alone.
    if not is_admin and not can(current_user, Action.CODE, va_sid):
        return jsonify({
            "error": "This submission is outside your coding scope.",
            "code": "forbidden",
        }), 403

    alloc = db.session.scalar(
        sa.select(VaAllocations.va_sid).where(
            VaAllocations.va_allocated_to == current_user.user_id,
            VaAllocations.va_allocation_for == VaAllocation.coding,
            VaAllocations.va_allocation_status == VaStatuses.active,
            VaAllocations.va_sid == va_sid,
        )
    )
    if not alloc:
        return jsonify({
            "error": "Active coding allocation required.",
            "code": "no_allocation",
        }), 403
    return None
