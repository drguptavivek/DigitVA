import sqlalchemy as sa
from app import db
from flask_login import current_user
from app.models import VaAllocations, VaStatuses, VaAllocation
from app.utils.va_permission.va_permission_01_abortwithflash import va_permission_abortwithflash
from flask import request, make_response, url_for, flash, abort


def va_permission_ensureanyallocation(role):
    alloc = db.session.scalar(
        sa.select(VaAllocations.va_sid).where(
            (VaAllocations.va_allocated_to == current_user.user_id)
            & (VaAllocations.va_allocation_for == getattr(VaAllocation, role))
            & (VaAllocations.va_allocation_status == VaStatuses.active)
        )
    )
    if not alloc:
        if request.headers.get("HX-Request"):
            response = make_response("", 403)
            response.headers["HX-Redirect"] = url_for("va_main.va_dashboard", va_role="coder")
            flash("Timeout: The VA form you are trying to access is no longer allocated to you. Coder may only hold / reserve a particular VA form for 1 hour only. Please start coding a new form.", "danger")
            abort(response)
        va_permission_abortwithflash("You have no active VA form allocation.", 403)
