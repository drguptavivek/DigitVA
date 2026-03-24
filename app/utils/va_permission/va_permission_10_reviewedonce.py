import sqlalchemy as sa
from app import db
from app.models import VaStatuses, VaSubmissionWorkflow
from app.utils.va_permission.va_permission_01_abortwithflash import va_permission_abortwithflash


def va_permission_reviewedonce(sid):
    # A re-review may only be requested after at least one full reviewer cycle
    # has completed. The canonical signal is the workflow state:
    # reviewer_finalized means a reviewer final COD was submitted.
    # NQA and Social Autopsy are supporting artifacts — submitting them alone
    # does not satisfy the re-review precondition.
    workflow_state = db.session.scalar(
        sa.select(VaSubmissionWorkflow.workflow_state).where(
            VaSubmissionWorkflow.va_sid == sid
        )
    )
    if workflow_state != "reviewer_finalized":
        va_permission_abortwithflash(
            "This VA form must be reviewed at least once before requesting a re-review.",
            403,
        )
