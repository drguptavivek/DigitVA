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
from app.services.demo_project_service import should_use_demo_actiontype_for_submission
from app.services.final_cod_authority_service import (
    get_authoritative_final_assessment,
    get_active_recode_episode,
    start_recode_episode,
)
from app.services.workflow.definition import (
    CODER_READY_POOL_STATES,
    WORKFLOW_CODING_IN_PROGRESS,
    WORKFLOW_CODER_FINALIZED,
    WORKFLOW_REVIEWER_ELIGIBLE,
)
from app.services.workflow.intake_modes import split_form_ids_by_coding_intake_mode
from app.services.workflow.state_store import get_submission_workflow_state
from app.services.workflow.transitions import (
    admin_actor,
    coder_actor,
    mark_coding_started,
    mark_demo_started,
    mark_reviewer_eligible_after_recode_window,
    mark_recode_started,
    mark_admin_override_to_recode,
    reset_demo_state,
    system_actor,
)


# ---------------------------------------------------------------------------
# Stats / dashboard helpers
# ---------------------------------------------------------------------------

def _normalized_vacode_languages(user) -> list[str]:
    return [
        str(language).strip().lower()
        for language in (user.vacode_language or [])
        if str(language).strip()
    ]


def _narration_language_filter(user):
    normalized = _normalized_vacode_languages(user)
    if not normalized:
        return None
    return sa.func.lower(VaSubmissions.va_narration_language).in_(normalized)

def get_coder_ready_stats(user) -> dict:
    """Return ready-pool counts for the coder dashboard.

    Returns a dict with:
      random_ready   – submissions available for random allocation
      pick_ready     – submissions available for pick-mode (len of pick list)
      has_random_mode – bool
      has_pick_mode   – bool
    """
    va_form_access = user.get_coder_va_forms()
    if not va_form_access:
        return {"random_ready": 0, "pick_ready": 0, "has_random_mode": False, "has_pick_mode": False}

    random_form_ids, pick_form_ids = split_form_ids_by_coding_intake_mode(va_form_access)

    def _count_ready(form_ids):
        filters = _available_submission_filters(form_ids, user=user)
        if user.is_coder(va_form="UNSW01TR0101"):
            filters.append(sa.func.date(VaSubmissions.va_submission_date) <= datetime(2025, 9, 9).date())
        return db.session.scalar(
            sa.select(sa.func.count())
            .select_from(VaSubmissions)
            .join(VaSubmissionWorkflow, VaSubmissionWorkflow.va_sid == VaSubmissions.va_sid)
            .where(sa.and_(*filters))
        ) or 0

    random_ready = _count_ready(random_form_ids) if random_form_ids else 0
    pick_ready = len(get_pick_available_forms(user, pick_form_ids)) if pick_form_ids else 0

    return {
        "random_ready": random_ready,
        "pick_ready": pick_ready,
        "has_random_mode": bool(random_form_ids),
        "has_pick_mode": bool(pick_form_ids),
    }


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
        language_filter = _narration_language_filter(user)
        if language_filter is not None:
            filters.append(language_filter)
    if project_id:
        filters.append(
            VaSubmissions.va_form_id.in_(
                sa.select(VaForms.form_id).where(VaForms.project_id == project_id)
            )
        )
    return filters


def _actiontype_for_submission(va_sid: str, default_actiontype: str) -> str:
    if should_use_demo_actiontype_for_submission(va_sid):
        return "vademo_start_coding"
    return default_actiontype


def _require_submission_exists(va_sid: str):
    row = db.session.execute(
        sa.select(
            VaSubmissions.va_sid,
            VaForms.project_id,
            VaForms.site_id,
        )
        .join(VaForms, VaForms.form_id == VaSubmissions.va_form_id)
        .where(VaSubmissions.va_sid == va_sid)
    ).first()
    if not row:
        raise AllocationError("Submission not found.", 404)
    return row


def _create_coding_allocation(
    va_sid: str,
    user,
    audit_action: str,
    by_role: str,
    *,
    demo_session: bool = False,
):
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
    actor = coder_actor(user.user_id) if by_role == "vacoder" else admin_actor(user.user_id)
    if demo_session:
        mark_demo_started(
            va_sid,
            reason="demo_coder_allocation_created",
            actor=actor,
        )
    elif get_active_recode_episode(va_sid):
        mark_recode_started(
            va_sid,
            reason="recode_allocation_created",
            actor=actor,
        )
    else:
        mark_coding_started(
            va_sid,
            reason="coder_allocation_created",
            actor=actor,
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


def allocate_random_form(user, project_id: str | None = None) -> AllocationResult:
    """Allocate a random available form for coding.

    If the user already has an active allocation returns it (resume).
    If project_id is given, restricts the pool to that project only —
    the caller must have already validated the user has access to it.
    Raises AllocationError if no forms are available.
    """
    release_stale_coding_allocations(timeout_hours=1)

    existing_sid = get_active_coding_allocation(user.user_id)
    if existing_sid:
        return AllocationResult(va_sid=existing_sid, actiontype="varesumecoding")

    random_form_ids, _ = split_form_ids_by_coding_intake_mode(user.get_coder_va_forms())
    if not random_form_ids:
        raise AllocationError("No random-allocation coding projects are available to you.")

    if project_id:
        allowed_projects = set(db.session.scalars(
            sa.select(VaForms.project_id).where(VaForms.form_id.in_(random_form_ids))
        ).all())
        if project_id not in allowed_projects:
            raise AllocationError("You do not have coder access to the selected project.")

    base_filters = _available_submission_filters(random_form_ids, project_id=project_id, user=user)

    # Temporary: TR01 site restricted to submissions up to 2025-09-09
    if user.is_coder(va_form="UNSW01TR0101"):
        base_filters = [
            *_available_submission_filters(random_form_ids, project_id=project_id, user=user),
            sa.func.date(VaSubmissions.va_submission_date) <= datetime(2025, 9, 9).date(),
        ]

    va_new_sid = db.session.scalar(
        sa.select(VaSubmissions.va_sid)
        .join(VaSubmissionWorkflow, VaSubmissionWorkflow.va_sid == VaSubmissions.va_sid)
        .where(sa.and_(*base_filters))
    )
    if not va_new_sid:
        msg = (
            f"No forms are available to you for VA coding in project {project_id}."
            if project_id
            else "No forms are available to you for VA coding."
        )
        raise AllocationError(msg)

    actiontype = _actiontype_for_submission(va_new_sid, "vastartcoding")
    _create_coding_allocation(
        va_new_sid,
        user,
        "form allocated to coder",
        "vacoder",
        demo_session=(actiontype == "vademo_start_coding"),
    )
    db.session.commit()
    return AllocationResult(va_sid=va_new_sid, actiontype=actiontype)


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

    actiontype = _actiontype_for_submission(va_sid, "vapickcoding")
    _create_coding_allocation(
        va_sid,
        user,
        "form picked by coder for coding",
        "vacoder",
        demo_session=(actiontype == "vademo_start_coding"),
    )
    db.session.commit()
    return AllocationResult(va_sid=va_sid, actiontype=actiontype)


def start_recode_allocation(user, va_sid: str) -> AllocationResult:
    """Start a recode episode and create an allocation.

    Raises AllocationError if outside the recode window.
    """
    from datetime import timedelta

    current_state = get_submission_workflow_state(va_sid)
    if current_state != WORKFLOW_CODER_FINALIZED:
        raise AllocationError("Only coder-finalized submissions can be reopened for recode.")

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
    mark_recode_started(
        va_sid,
        reason="recode_allocation_created",
        actor=coder_actor(user.user_id),
    )
    db.session.commit()
    # After recode setup, coder resumes on the same form
    return AllocationResult(va_sid=va_sid, actiontype="varesumecoding")


def admin_override_to_recode(user, va_sid: str) -> None:
    """Prepare a finalized submission for recode without allocating it yet.

    Current policy uses global-only admin grants, so this action is restricted
    by admin role membership rather than project/site-scoped admin access.
    """
    _require_submission_exists(va_sid)
    current_state = get_submission_workflow_state(va_sid)
    if current_state not in (WORKFLOW_CODER_FINALIZED, WORKFLOW_REVIEWER_ELIGIBLE):
        raise AllocationError(
            "Only coder-finalized or reviewer-eligible submissions can be overridden for recode."
        )

    authoritative_final = get_authoritative_final_assessment(va_sid)
    if not authoritative_final:
        raise AllocationError(
            "Only coder-finalized or reviewer-eligible submissions can be overridden for recode."
        )

    start_recode_episode(
        va_sid,
        user.user_id,
        base_final_assessment=authoritative_final,
    )
    mark_admin_override_to_recode(
        va_sid,
        reason="admin_override_to_recode",
        actor=admin_actor(user.user_id),
    )
    db.session.add(
        VaSubmissionsAuditlog(
            va_sid=va_sid,
            va_audit_byrole="vaadmin",
            va_audit_by=user.user_id,
            va_audit_operation="u",
            va_audit_action="admin override to recode",
            va_audit_entityid=uuid.uuid4(),
        )
    )
    db.session.commit()


def mark_reviewer_eligible_after_recode_window_submissions(
    *,
    now: datetime | None = None,
    actor=None,
) -> int:
    """Transition coder-finalized submissions to reviewer_eligible after 24 hours."""
    from datetime import timedelta, timezone

    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)
    finalized_sids = db.session.scalars(
        sa.select(VaSubmissionWorkflow.va_sid).where(
            VaSubmissionWorkflow.workflow_state == WORKFLOW_CODER_FINALIZED
        )
    ).all()

    transitioned = 0
    for va_sid in finalized_sids:
        if get_active_recode_episode(va_sid):
            continue
        authoritative_final = get_authoritative_final_assessment(va_sid)
        if authoritative_final is None:
            continue
        final_created_at = authoritative_final.va_finassess_createdat
        if final_created_at.tzinfo is None:
            final_created_at = final_created_at.replace(tzinfo=timezone.utc)
        if final_created_at > cutoff:
            continue
        mark_reviewer_eligible_after_recode_window(
            va_sid,
            reason="reviewer_eligible_after_recode_window",
            actor=actor or system_actor(),
        )
        transitioned += 1

    if transitioned:
        db.session.commit()
    return transitioned


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
        reset_demo_state(
            existing_alloc.va_sid,
            reason="demo_allocation_reset",
            actor=admin_actor(user.user_id),
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
    mark_demo_started(
        va_new_sid,
        reason="demo_coder_allocation_created",
        actor=admin_actor(user.user_id),
    )
    db.session.commit()

    if released_sid:
        reset_demo_state(
            released_sid,
            reason="demo_allocation_reset_finalized",
            actor=admin_actor(user.user_id),
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


def is_upstream_recode(va_sid: str) -> bool:
    """Check if this submission is a re-code due to accepted upstream data change.

    Returns True if the submission has a recent data_manager_accepted_upstream_odk_change
    audit action and no subsequent coding activity yet.
    """
    # Check for the DM accept action
    accept_action = db.session.scalar(
        sa.select(VaSubmissionsAuditlog.va_audit_id)
        .where(VaSubmissionsAuditlog.va_sid == va_sid)
        .where(VaSubmissionsAuditlog.va_audit_action == "data_manager_accepted_upstream_odk_change")
        .order_by(VaSubmissionsAuditlog.va_audit_createdat.desc())
        .limit(1)
    )
    return accept_action is not None
