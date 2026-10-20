"""Personal activity counts for the signed-in user's Home / Dashboard (digitva-dsj2).

Computes overall and per-project counts of forms filled (submitted interviews),
in-progress drafts, deaths reported, forms coded (and not-codeable), and forms
reviewed by the caller in a fixed number of grouped SQL queries, and the
Home page's per-role blocks (``get_home_blocks``).
"""

from __future__ import annotations

import sqlalchemy as sa

from app import db
from app.models import (
    VaCoderReview,
    VaDeathRegister,
    VaFinalAssessments,
    VaForms,
    VaProjectMaster,
    VaReviewerFinalAssessments,
    VaStatuses,
    VaSubmissions,
    VaWebIntakeDraft,
)
from app.services.authz import role_flags
from app.services.authz.consulted import mark_consulted
from app.services.authz.grants import resolve_grants
from app.services.duplicate_exclusion import not_confirmed_duplicate_condition
from app.services.workflow.definition import (
    WORKFLOW_NOT_CODEABLE_BY_CODER,
    WORKFLOW_NOT_CODEABLE_BY_DATA_MANAGER,
    WORKFLOW_READY_FOR_CODING,
    WORKFLOW_SCREENING_PENDING,
)


def _empty_counts() -> dict[str, int]:
    return {
        "deaths_reported": 0,
        "interviews_submitted": 0,
        "drafts_in_progress": 0,
        "coded": 0,
        "not_codeable": 0,
        "reviewed": 0,
    }


def get_user_activity_summary(user) -> dict:
    """Return ``{"totals": ..., "by_project": {<project_id>: ...}}`` for *user*."""
    mark_consulted()
    if user is None or not getattr(user, "is_authenticated", True):
        return {"totals": _empty_counts(), "by_project": {}}
    user_id = getattr(user, "user_id", None)
    if user_id is None:
        return {"totals": _empty_counts(), "by_project": {}}

    resolved = resolve_grants(user)
    granted_projects = sorted(
        {
            g.project_id
            for g in resolved.grants
            if g.role != "admin" and g.project_id and g.source != "demo_training"
        }
    )
    by_project: dict[str, dict[str, int]] = {
        pid: _empty_counts() for pid in granted_projects
    }

    def _bucket(project_id: str | None) -> dict[str, int] | None:
        if not project_id:
            return None
        if project_id not in by_project:
            by_project[project_id] = _empty_counts()
        return by_project[project_id]

    not_demo_project = sa.or_(
        VaProjectMaster.demo_training_enabled.is_(False),
        VaProjectMaster.demo_training_enabled.is_(None),
    )

    # 1. Deaths reported by this user (excluding duplicate and cancelled cases).
    # Register entries only: a direct start is an interview (counted below as
    # a draft), and "My registered deaths" lists only register entries.
    death_sel = sa.select(
        VaDeathRegister.project_id.label("project_id"),
        sa.literal("deaths_reported").label("metric"),
        sa.cast(VaDeathRegister.death_id, sa.Text).label("entity_id"),
    ).where(
        VaDeathRegister.registered_by == user_id,
        VaDeathRegister.source == "register",
        VaDeathRegister.status.notin_(("duplicate", "cancelled")),
    )

    # 2. Web/device intake drafts submitted or in progress ("draft") by this user.
    # Aliased so not_confirmed_duplicate_condition's own VaDeathRegister subquery
    # is not auto-correlated to this outer join.
    draft_case = sa.orm.aliased(VaDeathRegister, name="draft_case")
    draft_metric = sa.case(
        (VaWebIntakeDraft.status == "submitted", sa.literal("interviews_submitted")),
        (VaWebIntakeDraft.status == "draft", sa.literal("drafts_in_progress")),
    ).label("metric")
    draft_sel = (
        sa.select(
            VaWebIntakeDraft.project_id.label("project_id"),
            draft_metric,
            sa.cast(VaWebIntakeDraft.draft_id, sa.Text).label("entity_id"),
        )
        .outerjoin(
            draft_case,
            draft_case.death_id == VaWebIntakeDraft.death_id,
        )
        .where(
            VaWebIntakeDraft.user_id == user_id,
            VaWebIntakeDraft.status.in_(("submitted", "draft")),
            sa.or_(
                VaWebIntakeDraft.death_id.is_(None),
                draft_case.status.notin_(("duplicate", "cancelled")),
            ),
            sa.or_(
                VaWebIntakeDraft.va_sid.is_(None),
                not_confirmed_duplicate_condition(VaWebIntakeDraft.va_sid),
            ),
        )
    )

    # 3. Submissions coded (active final assessments) by this user, excluding demo.
    coded_sel = (
        sa.select(
            VaForms.project_id.label("project_id"),
            sa.literal("coded").label("metric"),
            sa.cast(VaFinalAssessments.va_sid, sa.Text).label("entity_id"),
        )
        .join(VaSubmissions, VaSubmissions.va_sid == VaFinalAssessments.va_sid)
        .join(VaForms, VaForms.form_id == VaSubmissions.va_form_id)
        .outerjoin(VaProjectMaster, VaProjectMaster.project_id == VaForms.project_id)
        .where(
            VaFinalAssessments.va_finassess_by == user_id,
            VaFinalAssessments.va_finassess_status == VaStatuses.active,
            VaFinalAssessments.is_tester.is_(False),
            not_demo_project,
            not_confirmed_duplicate_condition(VaSubmissions.va_sid),
        )
    )

    # 4. Submissions marked not-codeable by this user, excluding demo.
    nc_sel = (
        sa.select(
            VaForms.project_id.label("project_id"),
            sa.literal("not_codeable").label("metric"),
            sa.cast(VaCoderReview.va_sid, sa.Text).label("entity_id"),
        )
        .join(VaSubmissions, VaSubmissions.va_sid == VaCoderReview.va_sid)
        .join(VaForms, VaForms.form_id == VaSubmissions.va_form_id)
        .outerjoin(VaProjectMaster, VaProjectMaster.project_id == VaForms.project_id)
        .where(
            VaCoderReview.va_creview_by == user_id,
            VaCoderReview.va_creview_status == VaStatuses.active,
            VaCoderReview.is_tester.is_(False),
            not_demo_project,
            not_confirmed_duplicate_condition(VaSubmissions.va_sid),
        )
    )

    # 5. Submissions reviewed (active reviewer finals) by this user, excluding demo.
    reviewed_sel = (
        sa.select(
            VaForms.project_id.label("project_id"),
            sa.literal("reviewed").label("metric"),
            sa.cast(VaReviewerFinalAssessments.va_sid, sa.Text).label("entity_id"),
        )
        .join(VaSubmissions, VaSubmissions.va_sid == VaReviewerFinalAssessments.va_sid)
        .join(VaForms, VaForms.form_id == VaSubmissions.va_form_id)
        .outerjoin(VaProjectMaster, VaProjectMaster.project_id == VaForms.project_id)
        .where(
            VaReviewerFinalAssessments.va_rfinassess_by == user_id,
            VaReviewerFinalAssessments.va_rfinassess_status == VaStatuses.active,
            not_demo_project,
            not_confirmed_duplicate_condition(VaSubmissions.va_sid),
        )
    )

    all_unioned = sa.union_all(death_sel, draft_sel, coded_sel, nc_sel, reviewed_sel).subquery("user_activity")
    activity_rows = db.session.execute(
        sa.select(
            all_unioned.c.project_id,
            all_unioned.c.metric,
            sa.func.count(sa.distinct(all_unioned.c.entity_id)),
        )
        .group_by(all_unioned.c.project_id, all_unioned.c.metric)
    ).all()

    for project_id, metric, count in activity_rows:
        bucket = _bucket(project_id)
        if bucket is not None and metric in bucket:
            bucket[metric] = int(count or 0)

    totals = _empty_counts()
    for counts in by_project.values():
        for key in totals:
            totals[key] += counts[key]

    return {
        "totals": totals,
        "by_project": dict(sorted(by_project.items())),
    }


#: Case states still waiting for an interview: registered but not yet
#: submitted, refused, closed as a duplicate or cancelled.
OPEN_CASE_STATES = ("registered", "scheduled", "in_progress", "paused", "not_reachable")
#: Roles whose Home block is project progress only, no work queue of their own.
PROGRESS_ROLES = ("project_pi", "site_pi", "collaborator", "collaborator_pii")
_DM_STATES = (
    WORKFLOW_SCREENING_PENDING,
    WORKFLOW_READY_FOR_CODING,
    WORKFLOW_NOT_CODEABLE_BY_CODER,
    WORKFLOW_NOT_CODEABLE_BY_DATA_MANAGER,
)


def _death_reporter_block(user) -> dict:
    """Deaths *user* registered (the "My registered deaths" definition, not the
    scope-wide dashboard count) and how many of them still await an interview."""
    registered, awaiting = db.session.execute(
        sa.select(
            sa.func.count(),
            sa.func.count().filter(VaDeathRegister.status.in_(OPEN_CASE_STATES)),
        ).where(
            VaDeathRegister.registered_by == user.user_id,
            VaDeathRegister.source == "register",
            VaDeathRegister.status.notin_(("duplicate", "cancelled")),
        )
    ).one()
    return {"registered": registered, "awaiting_interview": awaiting}


def _interviewer_block(user, drafts_in_progress: int) -> dict:
    """Own open drafts, and open cases in the interviewer's reach that *user*
    registered, started or worked on (the worklist's "Mine" filter)."""
    # Private helpers of web_intake_service: the worklist's own scope and
    # "mine" rule, so this count never drifts from the list it summarises.
    from app.services.web_intake_service import _mine_condition, _worklist_scope

    scope = _worklist_scope(user)
    needing_visit = 0
    if scope is not None:
        needing_visit = db.session.scalar(
            sa.select(sa.func.count()).where(
                scope,
                _mine_condition(user),
                VaDeathRegister.status.in_(OPEN_CASE_STATES),
            )
        ) or 0
    return {"drafts_in_progress": drafts_in_progress, "needing_visit": needing_visit}


def _supervisor_block(user) -> dict:
    """Cases in the supervisor's scope: flagged ones awaiting a decision, open
    ones and submitted ones, in one grouped query."""
    from app.services.authz.supervision import supervised_case_condition

    rows = db.session.execute(
        sa.select(
            VaDeathRegister.status,
            sa.func.count(),
            sa.func.count().filter(VaDeathRegister.pending_flag.is_not(None)),
        )
        .where(supervised_case_condition(user))
        .group_by(VaDeathRegister.status)
    ).all()
    return {
        "flagged": sum(flagged for _, _, flagged in rows),
        "open": sum(count for status, count, _ in rows if status in OPEN_CASE_STATES),
        "submitted": sum(count for status, count, _ in rows if status == "submitted"),
    }


def _coder_block(user, practice: bool) -> dict:
    """Ready pool, own completed codings, and own codings still recodeable
    (the same rule ``recode_limit_error`` applies). *practice*: a coding
    tester without a coder grant; the client labels the block as practice."""
    from app.services.coder_dashboard_service import (
        get_coder_output_summary,
        get_coder_recodeable_sids,
    )
    from app.services.coder_workflow_service import get_coder_ready_stats

    ready = get_coder_ready_stats(user)
    block = {"ready": ready["random_ready"] + ready["pick_ready"], "practice": practice}
    if practice:
        return block
    block["completed"] = get_coder_output_summary(user.user_id)["completed"]
    block["recodeable"] = len(
        get_coder_recodeable_sids(user, list(user.get_coder_va_forms() or []))
    )
    return block


def _reviewer_block(user) -> dict:
    from app.services import reviewer_dashboard_service as reviewing

    return {
        "available": reviewing.count_available(user),
        "completed": reviewing.count_completed(user),
    }


def _data_manager_block(user) -> dict:
    """Workflow counts over the data manager's grants (the dashboard's scope),
    one grouped query on the analytics snapshot."""
    from app.services.data_management_service import dm_grant_scope
    from app.services.submission_analytics_mv import CORE_MV_NAME, _mv_scope_filter

    core = sa.table(
        CORE_MV_NAME,
        sa.column("va_sid"),
        sa.column("project_id"),
        sa.column("site_id"),
        sa.column("org_unit_id"),
        sa.column("workflow_state"),
        sa.column("odk_missing"),
    )
    scope = dm_grant_scope(user)
    counts = dict(
        db.session.execute(
            sa.select(core.c.workflow_state, sa.func.count())
            .where(
                _mv_scope_filter(
                    core,
                    sorted(scope.project_ids),
                    scope.pairs,
                    scope_unit_ids=scope.unit_subtree(),
                ),
                core.c.workflow_state.in_(_DM_STATES),
            )
            .group_by(core.c.workflow_state)
        ).all()
    )
    return {
        "screening_pending": counts.get(WORKFLOW_SCREENING_PENDING, 0),
        "ready_for_coding": counts.get(WORKFLOW_READY_FOR_CODING, 0),
        "not_codeable": counts.get(WORKFLOW_NOT_CODEABLE_BY_CODER, 0)
        + counts.get(WORKFLOW_NOT_CODEABLE_BY_DATA_MANAGER, 0),
    }


def get_home_blocks(user) -> dict:
    """The Home page's one block per role *user* holds (docs/current-state/api-v1.md,
    ``GET /api/v1/me/home``): ``{"roles": [...], "blocks": {<role>: {counts}}}``.

    ``roles`` are the access summary's (explicit grants, no demo-training
    virtual roles). Each count is computed only for a role held, inside that
    role's own scope, by the service its screen already uses. Progress roles
    (``PROGRESS_ROLES``) get ``blocks["progress"] = {"roles": [...]}`` and no
    counts here: the client loads ``/me/kpis`` only when that block is opened.
    """
    mark_consulted()
    roles = role_flags(user, virtual=False)
    blocks: dict[str, dict] = {}
    if "death_reporter" in roles:
        blocks["death_reporter"] = _death_reporter_block(user)
    if "interviewer" in roles:
        drafts = get_user_activity_summary(user)["totals"]["drafts_in_progress"]
        blocks["interviewer"] = _interviewer_block(user, drafts)
    if "interview_supervisor" in roles:
        blocks["interview_supervisor"] = _supervisor_block(user)
    if "coder" in roles or "coding_tester" in roles:
        blocks["coder"] = _coder_block(user, practice="coder" not in roles)
    if "reviewer" in roles:
        blocks["reviewer"] = _reviewer_block(user)
    if "data_manager" in roles:
        blocks["data_manager"] = _data_manager_block(user)
    progress = [role for role in PROGRESS_ROLES if role in roles]
    if progress:
        blocks["progress"] = {"roles": progress}
    return {"roles": sorted(roles), "blocks": blocks}
