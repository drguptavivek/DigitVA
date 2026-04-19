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
from app.services.demo_project_service import (
    is_demo_training_submission,
    should_use_demo_actiontype_for_submission,
)
from app.services.final_cod_authority_service import (
    get_authoritative_final_assessment,
    get_active_recode_episode,
    start_recode_episode,
)
from app.services.workflow.definition import (
    CODER_READY_POOL_STATES,
    WORKFLOW_CODING_IN_PROGRESS,
    WORKFLOW_CODER_FINALIZED,
    WORKFLOW_READY_FOR_CODING,
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


def _tr01_cutoff_filter(user):
    """Limit TR01 site submissions by date without restricting other forms."""
    if not user or not user.is_coder(va_form="UNSW01TR0101"):
        return None
    return sa.or_(
        VaSubmissions.va_form_id != "UNSW01TR0101",
        sa.func.date(VaSubmissions.va_submission_date) <= datetime(2025, 9, 9).date(),
    )

def get_coder_ready_stats(user, project_id: str | None = None) -> dict:
    """Return ready-pool counts for the coder dashboard.

    Returns a dict with:
      random_ready   – submissions available for random allocation
      pick_ready     – submissions available for pick-mode (len of pick list)
      has_random_mode – bool
      has_pick_mode   – bool
    """
    va_form_access = user.get_coder_va_forms() | user.get_coding_tester_va_forms()
    if not va_form_access:
        return {"random_ready": 0, "pick_ready": 0, "has_random_mode": False, "has_pick_mode": False}

    if project_id:
        from app.models import VaForms
        va_form_access = db.session.scalars(
            sa.select(VaForms.form_id).where(
                VaForms.form_id.in_(va_form_access),
                VaForms.project_id == project_id,
            )
        ).all() or []
        if not va_form_access:
            return {"random_ready": 0, "pick_ready": 0, "has_random_mode": False, "has_pick_mode": False}

    random_form_ids, pick_form_ids = split_form_ids_by_coding_intake_mode(va_form_access)

    def _count_ready(form_ids):
        filters = _available_submission_filters(form_ids, user=user)
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


def _demo_recode_reset_message() -> str:
    return (
        "This demo form can no longer be recoded because its demo coding "
        "session was reset. Start a fresh demo coding session instead."
    )


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
    tr01_filter = _tr01_cutoff_filter(user)
    if tr01_filter is not None:
        filters.append(tr01_filter)
    return filters


def _get_excluded_sites_for_coding(form_ids: list, user) -> set:
    """Return site_ids that are ineligible for new coding allocations.

    A site is excluded when any of the following are true:
      - coding_enabled is False
      - today is before coding_start_date
      - today is after coding_end_date
      - the user has already met the daily_coder_limit for that site today

    coding_tester waiver: users who hold coding_tester access for the project
    or project/site pair are exempt from all four gates above.

    PI waiver: users who hold a project_pi grant for the project OR a site_pi
    grant for the site are exempt from enabled/date restrictions and
    daily_coder_limit restrictions.

    Sites with no VaProjectSites row are not restricted.
    """
    from app.models.va_project_sites import VaProjectSites

    if not form_ids:
        return set()

    today = datetime.utcnow().date()
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    user_id = user.user_id

    pi_project_ids = set(user.get_project_pi_projects())
    pi_site_ids = set(user.get_site_pi_sites())
    tester_projects = set(user.get_coding_tester_projects())
    tester_pairs = user.get_coding_tester_project_site_pairs()

    pairs = db.session.execute(
        sa.select(VaForms.project_id, VaForms.site_id).distinct()
        .where(VaForms.form_id.in_(form_ids))
    ).all()
    if not pairs:
        return set()

    ps_rows = db.session.scalars(
        sa.select(VaProjectSites).where(
            VaProjectSites.project_site_status == VaStatuses.active,
            sa.or_(*[
                sa.and_(VaProjectSites.project_id == p.project_id, VaProjectSites.site_id == p.site_id)
                for p in pairs
            ])
        )
    ).all()
    ps_by_pair = {(ps.project_id, ps.site_id): ps for ps in ps_rows}

    site_ids = list({p.site_id for p in pairs})
    today_counts = {
        r.site_id: r.cnt
        for r in db.session.execute(
            sa.select(VaForms.site_id, sa.func.count().label("cnt"))
            .select_from(VaAllocations)
            .join(VaSubmissions, VaSubmissions.va_sid == VaAllocations.va_sid)
            .join(VaForms, VaForms.form_id == VaSubmissions.va_form_id)
            .where(
                VaAllocations.va_allocated_to == user_id,
                VaAllocations.va_allocation_for == VaAllocation.coding,
                VaAllocations.va_allocation_createdat >= today_start,
                VaForms.site_id.in_(site_ids),
            )
            .group_by(VaForms.site_id)
        ).all()
    }

    excluded = set()
    for p in pairs:
        ps = ps_by_pair.get((p.project_id, p.site_id))
        if not ps:
            continue
        is_pi = p.project_id in pi_project_ids or p.site_id in pi_site_ids
        is_tester = p.project_id in tester_projects or (p.project_id, p.site_id) in tester_pairs
        # coding_enabled + date-window + daily limit checks are waived for PI
        # and coding_tester users.
        if not is_pi and not is_tester:
            if not ps.coding_enabled:
                excluded.add(p.site_id)
                continue
            if ps.coding_start_date and ps.coding_start_date > today:
                excluded.add(p.site_id)
                continue
        if not is_pi and not is_tester:
            if ps.coding_end_date and ps.coding_end_date < today:
                excluded.add(p.site_id)
                continue
        if not is_pi and not is_tester and today_counts.get(p.site_id, 0) >= ps.daily_coder_limit:
            excluded.add(p.site_id)
    return excluded


def _get_site_coding_error(project_id: str, site_id: str, user) -> str:
    """Return a human-readable reason why a specific site is blocked.

    PI and coding_tester waivers apply to all coding gates.
    """
    from app.models.va_project_sites import VaProjectSites

    today = datetime.utcnow().date()
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    user_id = user.user_id

    pi_project_ids = set(user.get_project_pi_projects())
    pi_site_ids = set(user.get_site_pi_sites())
    tester_projects = set(user.get_coding_tester_projects())
    tester_pairs = user.get_coding_tester_project_site_pairs()
    is_pi = project_id in pi_project_ids or site_id in pi_site_ids
    is_tester = project_id in tester_projects or (project_id, site_id) in tester_pairs

    ps = db.session.scalar(
        sa.select(VaProjectSites).where(
            VaProjectSites.project_id == project_id,
            VaProjectSites.site_id == site_id,
            VaProjectSites.project_site_status == VaStatuses.active,
        )
    )
    if not ps:
        return "Coding is not configured for this site."
    if not is_pi and not is_tester:
        if not ps.coding_enabled:
            return "Coding is currently disabled for this site."
        if ps.coding_start_date and ps.coding_start_date > today:
            return f"Coding for this site opens on {ps.coding_start_date.strftime('%B %-d, %Y')}."
    if not is_pi and not is_tester:
        if ps.coding_end_date and ps.coding_end_date < today:
            return f"Coding for this site ended on {ps.coding_end_date.strftime('%B %-d, %Y')}."
    count = db.session.scalar(
        sa.select(sa.func.count())
        .select_from(VaAllocations)
        .join(VaSubmissions, VaSubmissions.va_sid == VaAllocations.va_sid)
        .join(VaForms, VaForms.form_id == VaSubmissions.va_form_id)
        .where(
            VaAllocations.va_allocated_to == user_id,
            VaAllocations.va_allocation_for == VaAllocation.coding,
            VaAllocations.va_allocation_createdat >= today_start,
            VaForms.site_id == site_id,
        )
    ) or 0
    if not is_pi and not is_tester and count >= ps.daily_coder_limit:
        return (
            f"You have reached today's coding limit of {ps.daily_coder_limit} "
            f"form{'s' if ps.daily_coder_limit != 1 else ''} for this site."
        )
    return "Coding is not available for this site."


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

    all_form_ids = user.get_coder_va_forms() | user.get_coding_tester_va_forms()
    random_form_ids, _ = split_form_ids_by_coding_intake_mode(all_form_ids)
    if not random_form_ids:
        raise AllocationError("No random-allocation coding projects are available to you.")

    if project_id:
        allowed_projects = set(db.session.scalars(
            sa.select(VaForms.project_id).where(VaForms.form_id.in_(random_form_ids))
        ).all())
        if project_id not in allowed_projects:
            raise AllocationError("You do not have coder access to the selected project.")

    excluded_sites = _get_excluded_sites_for_coding(random_form_ids, user)
    base_filters = _available_submission_filters(random_form_ids, project_id=project_id, user=user)
    if excluded_sites:
        base_filters.append(
            VaSubmissions.va_form_id.not_in(
                sa.select(VaForms.form_id).where(VaForms.site_id.in_(excluded_sites))
            )
        )

    va_new_sid = db.session.scalar(
        sa.select(VaSubmissions.va_sid)
        .join(VaSubmissionWorkflow, VaSubmissionWorkflow.va_sid == VaSubmissions.va_sid)
        .where(sa.and_(*base_filters))
        .order_by(sa.func.random())
        .limit(1)
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
    if not (user.has_va_form_access(form.va_form_id, "coder") or user.is_coding_tester(form.va_form_id)):
        raise AllocationError("You do not have coder access for this VA form.")

    sub_row = _require_submission_exists(va_sid)
    excluded = _get_excluded_sites_for_coding([form.va_form_id], user)
    if sub_row.site_id in excluded:
        raise AllocationError(_get_site_coding_error(sub_row.project_id, sub_row.site_id, user))

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

    existing_sid = get_active_coding_allocation(user.user_id)
    active_recode_episode = get_active_recode_episode(va_sid)
    if existing_sid:
        if existing_sid == va_sid and active_recode_episode:
            current_state = get_submission_workflow_state(va_sid)
            if current_state in (
                WORKFLOW_CODER_FINALIZED,
                WORKFLOW_READY_FOR_CODING,
            ):
                mark_recode_started(
                    va_sid,
                    reason="recode_allocation_resumed",
                    actor=coder_actor(user.user_id),
                )
                db.session.commit()
            return AllocationResult(va_sid=va_sid, actiontype="varesumecoding")
        raise AllocationError("You already have an active coding allocation.")

    current_state = get_submission_workflow_state(va_sid)
    if current_state != WORKFLOW_CODER_FINALIZED:
        if (
            current_state == WORKFLOW_READY_FOR_CODING
            and is_demo_training_submission(va_sid)
        ):
            raise AllocationError(_demo_recode_reset_message(), 409)
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
    """Start a demo coding session, releasing any existing allocation first.

    Accessible to admins, coding_testers, and data_managers in addition to
    regular coders.  All three role types automatically include demo project
    forms via get_coder_demo_project_form_ids() in _get_granted_va_forms.

    Raises AllocationError if no forms are available.
    """
    coder_form_ids = (
        user.get_coder_va_forms()
        | user.get_coding_tester_va_forms()
        | user.get_data_manager_va_forms()
    )
    if not coder_form_ids:
        raise AllocationError("You do not have access to any VA forms for demo coding.")

    if project_id:
        allowed = set(db.session.scalars(
            sa.select(VaForms.project_id).where(VaForms.form_id.in_(coder_form_ids))
        ).all())
        if project_id not in allowed:
            raise AllocationError("You do not have access to the selected project for demo coding.")

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
    # The pool only contains ready_for_coding forms, but guard here in case
    # the demo cleanup task hasn't run yet and the form is in a stale state.
    from app.services.workflow.definition import WORKFLOW_READY_FOR_CODING
    wf_state = db.session.scalar(
        sa.select(VaSubmissionWorkflow.workflow_state)
        .where(VaSubmissionWorkflow.va_sid == va_new_sid)
    )
    if wf_state and wf_state != WORKFLOW_READY_FOR_CODING:
        reset_demo_state(
            va_new_sid,
            reason="demo_allocation_stale_state_reset",
            actor=admin_actor(user.user_id),
        )
    mark_demo_started(
        va_new_sid,
        reason="demo_coder_allocation_created",
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
