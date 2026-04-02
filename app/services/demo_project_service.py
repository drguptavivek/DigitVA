"""Helpers for project-level demo/training coding behavior."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sqlalchemy as sa

from app import db
from app.models import (
    VaAllocations,
    VaAllocation,
    VaForms,
    VaProjectMaster,
    VaStatuses,
    VaSubmissionWorkflowEvent,
    VaSubmissions,
)
from app.services.workflow.definition import TRANSITION_DEMO_RESET, TRANSITION_DEMO_STARTED


ADMIN_DEMO_RETENTION_HOURS = 6
DEFAULT_DEMO_PROJECT_RETENTION_MINUTES = 10
DEMO_CODING_ALLOCATION_TIMEOUT_MINUTES = 15


def demo_project_schema_ready() -> bool:
    """Return whether demo/training project columns are present in the DB."""
    inspector = sa.inspect(db.engine)
    try:
        column_names = {
            column["name"] for column in inspector.get_columns("va_project_master")
        }
    except Exception:
        return False
    return {
        "demo_training_enabled",
        "demo_retention_minutes",
    }.issubset(column_names)


def is_demo_training_project(project: VaProjectMaster | None) -> bool:
    if not demo_project_schema_ready():
        return False
    return bool(project and project.demo_training_enabled)


def get_demo_project_retention_minutes(project: VaProjectMaster | None) -> int:
    if not project or not project.demo_retention_minutes:
        return DEFAULT_DEMO_PROJECT_RETENTION_MINUTES
    return max(int(project.demo_retention_minutes), 1)


def get_project_for_form(form_id: str | None) -> VaProjectMaster | None:
    if not form_id or not demo_project_schema_ready():
        return None
    project_id = db.session.scalar(
        sa.select(VaForms.project_id).where(VaForms.form_id == form_id)
    )
    if not project_id:
        return None
    return db.session.get(VaProjectMaster, project_id)


def get_project_for_submission(va_sid: str | None) -> VaProjectMaster | None:
    if not va_sid or not demo_project_schema_ready():
        return None
    form_id = db.session.scalar(
        sa.select(VaSubmissions.va_form_id).where(VaSubmissions.va_sid == va_sid)
    )
    return get_project_for_form(form_id)


def get_demo_expiry_for_submission(
    va_sid: str,
    va_actiontype: str | None,
) -> datetime | None:
    if va_actiontype != "vademo_start_coding":
        return None

    project = get_project_for_submission(va_sid)
    now = datetime.now(timezone.utc)
    if is_demo_training_project(project):
        return now + timedelta(minutes=get_demo_project_retention_minutes(project))
    return now + timedelta(hours=ADMIN_DEMO_RETENTION_HOURS)


def get_demo_coding_allocation_timeout_minutes(va_sid: str) -> int:
    """Return the coding-allocation timeout for demo/training sessions."""
    return DEMO_CODING_ALLOCATION_TIMEOUT_MINUTES


def get_coder_demo_project_form_ids(*, only_active: bool = True) -> set[str]:
    if not demo_project_schema_ready():
        return set()

    stmt = (
        sa.select(VaForms.form_id)
        .join(VaProjectMaster, VaProjectMaster.project_id == VaForms.project_id)
        .where(VaProjectMaster.demo_training_enabled.is_(True))
    )
    if only_active:
        stmt = stmt.where(
            VaForms.form_status == VaStatuses.active,
            VaProjectMaster.project_status == VaStatuses.active,
        )
    return set(db.session.scalars(stmt).all())


def get_demo_training_project_ids(
    accessible_form_ids: set[str] | list[str] | tuple[str, ...] | None = None,
) -> list[str]:
    """Return distinct active demo/training project IDs, optionally scoped to forms."""
    if not demo_project_schema_ready():
        return []

    stmt = (
        sa.select(VaForms.project_id)
        .join(VaProjectMaster, VaProjectMaster.project_id == VaForms.project_id)
        .where(
            VaProjectMaster.demo_training_enabled.is_(True),
            VaProjectMaster.project_status == VaStatuses.active,
            VaForms.form_status == VaStatuses.active,
        )
    )
    if accessible_form_ids:
        stmt = stmt.where(VaForms.form_id.in_(accessible_form_ids))

    return db.session.execute(
        stmt.distinct().order_by(VaForms.project_id)
    ).scalars().all()


def is_demo_training_submission(va_sid: str) -> bool:
    return is_demo_training_project(get_project_for_submission(va_sid))


def should_use_demo_actiontype_for_submission(va_sid: str) -> bool:
    if is_demo_training_submission(va_sid):
        return True

    latest_demo_event = db.session.scalar(
        sa.select(VaSubmissionWorkflowEvent.event_created_at)
        .where(
            VaSubmissionWorkflowEvent.va_sid == va_sid,
            VaSubmissionWorkflowEvent.transition_id == TRANSITION_DEMO_STARTED,
        )
        .order_by(VaSubmissionWorkflowEvent.event_created_at.desc())
        .limit(1)
    )
    if latest_demo_event is None:
        return False

    latest_demo_reset = db.session.scalar(
        sa.select(VaSubmissionWorkflowEvent.event_created_at)
        .where(
            VaSubmissionWorkflowEvent.va_sid == va_sid,
            VaSubmissionWorkflowEvent.transition_id == TRANSITION_DEMO_RESET,
        )
        .order_by(VaSubmissionWorkflowEvent.event_created_at.desc())
        .limit(1)
    )
    if latest_demo_reset is not None and latest_demo_reset >= latest_demo_event:
        return False

    active_allocation_exists = db.session.scalar(
        sa.select(sa.literal(True))
        .select_from(VaAllocations)
        .where(
            VaAllocations.va_sid == va_sid,
            VaAllocations.va_allocation_for == VaAllocation.coding,
            VaAllocations.va_allocation_status == VaStatuses.active,
        )
        .limit(1)
    )
    return bool(active_allocation_exists)
