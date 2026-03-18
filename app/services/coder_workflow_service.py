"""Coder workflow service — allocation operations with no Flask dependency.

Pure domain logic consumed by both:
  app/routes/coding.py          (HTMX page routes)
  app/routes/api/coding.py      (JSON API routes)
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

import sqlalchemy as sa

from app import db
from app.models import (
    VaAllocation,
    VaAllocations,
    VaForms,
    VaStatuses,
    VaSubmissionWorkflow,
    VaSubmissions,
    VaSubmissionsAuditlog,
)
from app.services.coding_allocation_service import release_stale_coding_allocations
from app.services.final_cod_authority_service import (
    get_authoritative_final_assessment,
    start_recode_episode,
)
from app.services.project_workflow_service import split_form_ids_by_coding_intake_mode
from app.services.submission_workflow_service import (
    CODER_READY_POOL_STATES,
    WORKFLOW_CODING_IN_PROGRESS,
    infer_workflow_state_after_coding_release,
    set_submission_workflow_state,
)


# ---------------------------------------------------------------------------
# Result / error types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AllocationResult:
    va_sid: str
    actiontype: str  # vastartcoding | vapickcoding | vademo_start_coding | varesumecoding


class AllocationError(Exception):
    """Raised when an allocation cannot be completed."""

    def __init__(self, message: str, status_code: int = 403):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


# ---------------------------------------------------------------------------
# Internal helpers (no current_user — caller passes user explicitly)
# ---------------------------------------------------------------------------

def _available_submission_filters(form_ids, project_id=None, user=None):
    filters = [
        VaSubmissions.va_form_id.in_(form_ids),
        VaSubmissionWorkflow.workflow_state.in_(CODER_READY_POOL_STATES),
    ]
    if user is not None:
        filters.append(VaSubmissions.va_narration_language.in_(user.vacode_language))
    if project_id:
        filters.append(
            VaSubmissions.va_form_id.in_(
                sa.select(VaForms.form_id).where(VaForms.project_id == project_id)
            )
        )
    return filters


def _create_coding_allocation(va_sid: str, user, audit_action: str, by_role: str):
    """Create allocation row, bump formcount, write audit, advance workflow state."""
    gen_uuid = uuid.uuid4()
    db.session.add(VaAllocations(
        va_allocation_id=gen_uuid,
        va_sid=va_sid,
        va_allocated_to=user.user_id,
        va_allocation_for=VaAllocation.coding,
    ))
    user.vacode_formcount += 1
    db.session.add(VaSubmissionsAuditlog(
        va_sid=va_sid,
        va_audit_byrole=by_role,
        va_audit_by=user.user_id,
        va_audit_operation="c",
        va_audit_action=audit_action,
        va_audit_entityid=gen_uuid,
    ))
    set_submission_workflow_state(
        va_sid,
        WORKFLOW_CODING_IN_PROGRESS,
        reason="coder_allocation_created",
        by_user_id=user.user_id,
        by_role=by_role,
    )


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------

def get_active_coding_allocation(user_id: str) -> str | None:
    """Return the va_sid of the current active coding allocation, or None."""
    return db.session.scalar(
        sa.select(VaAllocations.va_sid).where(
            VaAllocations.va_allocated_to == user_id,
            VaAllocations.va_allocation_for == VaAllocation.coding,
            VaAllocations.va_allocation_status == VaStatuses.active,
        )
    )


def allocate_random_form(user) -> AllocationResult:
    """Allocate a random available form for coding.

    If the user already has an active allocation returns it (resume).
    Raises AllocationError if no forms are available.
    """
    release_stale_coding_allocations(timeout_hours=1)

    existing_sid = get_active_coding_allocation(user.user_id)
    if existing_sid:
        return AllocationResult(va_sid=existing_sid, actiontype="varesumecoding")

    random_form_ids, _ = split_form_ids_by_coding_intake_mode(user.get_coder_va_forms())
    if not random_form_ids:
        raise AllocationError("No random-allocation coding projects are available to you.")

    base_filters = _available_submission_filters(random_form_ids, user=user)

    # Temporary: TR01 site restricted to submissions up to 2025-09-09
    if user.is_coder(va_form="UNSW01TR0101"):
        base_filters = [
            *_available_submission_filters(random_form_ids, user=user),
            sa.func.date(VaSubmissions.va_submission_date) <= datetime(2025, 9, 9).date(),
        ]

    va_new_sid = db.session.scalar(
        sa.select(VaSubmissions.va_sid)
        .join(VaSubmissionWorkflow, VaSubmissionWorkflow.va_sid == VaSubmissions.va_sid)
        .where(sa.and_(*base_filters))
    )
    if not va_new_sid:
        raise AllocationError("No forms are available to you for VA coding.")

    _create_coding_allocation(va_new_sid, user, "form allocated to coder", "vacoder")
    db.session.commit()
    return AllocationResult(va_sid=va_new_sid, actiontype="vastartcoding")


def allocate_pick_form(user, va_sid: str) -> AllocationResult:
    """Allocate a specific form for coding (pick-mode projects).

    Raises AllocationError if the form is ineligible.
    """
    if user.vacode_formcount >= 200:
        raise AllocationError("You have reached your yearly limit of 200 coded VA forms.")

    form = db.session.get(VaSubmissions, va_sid)
    if not form:
        raise AllocationError("Submission not found.", 404)
    if not user.has_va_form_access(form.va_form_id, "coder"):
        raise AllocationError("You do not have coder access for this VA form.")

    _create_coding_allocation(va_sid, user, "form picked by coder for coding", "vacoder")
    db.session.commit()
    return AllocationResult(va_sid=va_sid, actiontype="vapickcoding")


def start_recode_allocation(user, va_sid: str) -> AllocationResult:
    """Start a recode episode and create an allocation.

    Raises AllocationError if outside the recode window.
    """
    from datetime import timedelta

    authoritative_final = get_authoritative_final_assessment(va_sid)
    if not authoritative_final:
        raise AllocationError("Only coder-finalized submissions can be reopened for recode.")
    cutoff = (
        datetime.now(authoritative_final.va_finassess_createdat.tzinfo)
        - timedelta(hours=24)
    )
    if authoritative_final.va_finassess_createdat <= cutoff:
        raise AllocationError("This submission is outside the recode window.")

    episode = start_recode_episode(
        va_sid, user.user_id, base_final_assessment=authoritative_final
    )
    gen_uuid = uuid.uuid4()
    db.session.add(VaAllocations(
        va_allocation_id=gen_uuid,
        va_sid=va_sid,
        va_allocated_to=user.user_id,
        va_allocation_for=VaAllocation.coding,
    ))
    db.session.add(VaSubmissionsAuditlog(
        va_sid=va_sid,
        va_audit_byrole="vacoder",
        va_audit_by=user.user_id,
        va_audit_operation="c",
        va_audit_action="form allocated to coder for recoding",
        va_audit_entityid=gen_uuid,
    ))
    db.session.add(VaSubmissionsAuditlog(
        va_sid=va_sid,
        va_audit_byrole="vacoder",
        va_audit_by=user.user_id,
        va_audit_operation="c",
        va_audit_action="recode episode started",
        va_audit_entityid=episode.episode_id,
    ))
    set_submission_workflow_state(
        va_sid, WORKFLOW_CODING_IN_PROGRESS,
        reason="recode_allocation_created",
        by_user_id=user.user_id,
        by_role="vacoder",
    )
    db.session.commit()
    # After recode setup, coder resumes on the same form
    return AllocationResult(va_sid=va_sid, actiontype="varesumecoding")


def start_demo_allocation(user, project_id: str | None = None) -> AllocationResult:
    """Start an admin demo coding session, releasing any existing allocation first.

    Raises AllocationError if no forms are available.
    """
    coder_form_ids = user.get_coder_va_forms()
    if not coder_form_ids:
        raise AllocationError("You do not have coder access to any VA forms for demo coding.")

    if project_id:
        allowed = set(db.session.scalars(
            sa.select(VaForms.project_id).where(VaForms.form_id.in_(coder_form_ids))
        ).all())
        if project_id not in allowed:
            raise AllocationError("You do not have coder access to the selected project.")

    existing_alloc = db.session.scalar(
        sa.select(VaAllocations).where(
            VaAllocations.va_allocated_to == user.user_id,
            VaAllocations.va_allocation_for == VaAllocation.coding,
            VaAllocations.va_allocation_status == VaStatuses.active,
        )
    )
    released_sid = None
    if existing_alloc:
        released_sid = existing_alloc.va_sid
        existing_alloc.va_allocation_status = VaStatuses.deactive
        db.session.flush()
        set_submission_workflow_state(
            existing_alloc.va_sid,
            infer_workflow_state_after_coding_release(existing_alloc.va_sid),
            reason="demo_allocation_reset",
            by_user_id=user.user_id,
            by_role="vaadmin",
        )
        db.session.add(VaSubmissionsAuditlog(
            va_sid=existing_alloc.va_sid,
            va_audit_entityid=existing_alloc.va_allocation_id,
            va_audit_byrole="vaadmin",
            va_audit_by=user.user_id,
            va_audit_operation="d",
            va_audit_action="va_allocation_released_by_admin_for_demo",
        ))

    va_new_sid = db.session.scalar(
        sa.select(VaSubmissions.va_sid)
        .join(VaSubmissionWorkflow, VaSubmissionWorkflow.va_sid == VaSubmissions.va_sid)
        .where(sa.and_(*_available_submission_filters(coder_form_ids, project_id=project_id, user=user)))
        .order_by(sa.func.random())
    )
    if not va_new_sid:
        raise AllocationError("No forms are currently available for demo coding.")

    gen_uuid = uuid.uuid4()
    db.session.add(VaAllocations(
        va_allocation_id=gen_uuid,
        va_sid=va_new_sid,
        va_allocated_to=user.user_id,
        va_allocation_for=VaAllocation.coding,
    ))
    db.session.add(VaSubmissionsAuditlog(
        va_sid=va_new_sid,
        va_audit_byrole="vaadmin",
        va_audit_by=user.user_id,
        va_audit_operation="c",
        va_audit_action="form allocated to admin for demo coding",
        va_audit_entityid=gen_uuid,
    ))
    set_submission_workflow_state(
        va_new_sid, WORKFLOW_CODING_IN_PROGRESS,
        reason="demo_coder_allocation_created",
        by_user_id=user.user_id,
        by_role="vaadmin",
    )
    db.session.commit()

    if released_sid:
        set_submission_workflow_state(
            released_sid,
            infer_workflow_state_after_coding_release(released_sid),
            reason="demo_allocation_reset_finalized",
            by_user_id=user.user_id,
            by_role="vaadmin",
        )
        db.session.commit()

    return AllocationResult(va_sid=va_new_sid, actiontype="vademo_start_coding")


def get_pick_available_forms(user, pick_form_ids: list[str]) -> list[dict]:
    """Return submissions available for pick-mode coding, ordered for display."""
    if not pick_form_ids:
        return []

    stmt = (
        sa.select(
            VaSubmissions.va_sid,
            VaSubmissions.va_uniqueid_masked,
            VaSubmissions.va_form_id,
            VaForms.project_id,
            VaForms.site_id,
            sa.func.date(VaSubmissions.va_submission_date).label("va_submission_date"),
            VaSubmissions.va_data_collector,
            VaSubmissions.va_deceased_age,
            VaSubmissions.va_deceased_gender,
        )
        .select_from(VaSubmissions)
        .join(VaForms, VaForms.form_id == VaSubmissions.va_form_id)
        .join(VaSubmissionWorkflow, VaSubmissionWorkflow.va_sid == VaSubmissions.va_sid)
        .where(sa.and_(*_available_submission_filters(pick_form_ids, user=user)))
        .order_by(
            VaForms.project_id,
            VaForms.site_id,
            VaSubmissions.va_submission_date,
            VaSubmissions.va_uniqueid_masked,
        )
    )
    if user.is_coder(va_form="UNSW01TR0101"):
        stmt = stmt.where(
            sa.func.date(VaSubmissions.va_submission_date) <= datetime(2025, 9, 9).date()
        )

    from app.utils import va_render_serialisedates
    return [
        va_render_serialisedates(row, ["va_submission_date"])
        for row in db.session.execute(stmt).mappings().all()
    ]
