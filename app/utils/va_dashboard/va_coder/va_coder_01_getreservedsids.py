import sqlalchemy as sa
from app import db
from app.models import (
    VaInitialAssessments,
    VaFinalAssessments,
    VaCoderReview,
    VaAllocations,
    VaStatuses,
    VaAllocation,
)


def va_coder_getreservedsids():
    va_inicoded_forms = db.session.scalars(
        sa.select(VaInitialAssessments.va_sid).where(
            (VaInitialAssessments.va_iniassess_status == VaStatuses.active)
        )
    ).all()
    va_fincoded_forms = db.session.scalars(
        sa.select(VaFinalAssessments.va_sid).where(
            (VaFinalAssessments.va_finassess_status == VaStatuses.active)
        )
    ).all()
    va_coderreview_forms = db.session.scalars(
        sa.select(VaCoderReview.va_sid).where(
            (VaCoderReview.va_creview_status == VaStatuses.active)
        )
    ).all()
    va_allocated_forms = db.session.scalars(
        sa.select(VaAllocations.va_sid).where(
            (VaAllocations.va_allocation_status == VaStatuses.active)
            & (VaAllocations.va_allocation_for == VaAllocation.coding)
        )
    )
    return (
        va_inicoded_forms
        + va_fincoded_forms
        + va_coderreview_forms
        + va_allocated_forms
    )
