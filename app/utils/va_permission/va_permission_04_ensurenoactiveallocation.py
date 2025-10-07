import sqlalchemy as sa
from app import db
from flask_login import current_user
from app.models import VaAllocations, VaStatuses, VaAllocation
from app.utils.va_permission.va_permission_01_abortwithflash import va_permission_abortwithflash


def va_permission_ensurenoactiveallocation(role):
    alloc = db.session.scalar(
        sa.select(VaAllocations.va_sid).where(
            (VaAllocations.va_allocated_to == current_user.user_id)
            & (VaAllocations.va_allocation_for == getattr(VaAllocation, role))
            & (VaAllocations.va_allocation_status == VaStatuses.active)
        )
    )
    if alloc:
        va_permission_abortwithflash(
            "You already have a VA form allocated. Please finish it before starting / recoding another.",
            403,
        )
