"""Coding dashboard route."""

from datetime import datetime

import sqlalchemy as sa
from flask import render_template
from flask_login import current_user

from app import db
from app.authz.access import action_authorized
from app.authz.scope import user_has_role
from app.models import (
    VaAllocation,
    VaAllocations,
    VaForms,
    VaStatuses,
    VaSubmissionWorkflow,
    VaSubmissions,
)
from app.models.va_project_sites import VaProjectSites
from app.services.coding.coder.dashboard import (
    get_coder_completed_count,
    get_coder_completed_history,
    get_coder_recodeable_sids,
)
from app.services.coding.coder.workflow import (
    _narration_language_filter,
    _tr01_cutoff_filter,
    get_active_coding_allocation,
    get_pick_available_forms,
)
from app.services.coding.demo import get_demo_training_project_ids
from app.services.workflow.definition import CODER_READY_POOL_STATES
from app.services.coding.coder.intake_policy import split_form_ids_by_coding_intake_mode

from .common import coding


@coding.get("/")
@action_authorized("coding_dashboard_view")
def dashboard():
    va_form_access = current_user.get_coder_va_forms() | current_user.get_coding_tester_va_forms()
    if va_form_access:
        narration_language_filter = _narration_language_filter(current_user)
        random_form_ids, pick_form_ids = split_form_ids_by_coding_intake_mode(va_form_access)
        total_filters = [
            VaSubmissions.va_form_id.in_(va_form_access),
            VaSubmissionWorkflow.workflow_state.in_(CODER_READY_POOL_STATES),
        ]
        if narration_language_filter is not None:
            total_filters.append(narration_language_filter)
        tr01_cutoff_filter = _tr01_cutoff_filter(current_user)
        if tr01_cutoff_filter is not None:
            total_filters.append(tr01_cutoff_filter)
        va_total_forms = db.session.scalar(
            sa.select(sa.func.count())
            .select_from(VaSubmissions)
            .join(VaSubmissionWorkflow, VaSubmissionWorkflow.va_sid == VaSubmissions.va_sid)
            .where(sa.and_(*total_filters))
        )
        va_random_ready_forms = 0
        if random_form_ids:
            random_filters = [
                VaSubmissions.va_form_id.in_(random_form_ids),
                VaSubmissionWorkflow.workflow_state.in_(CODER_READY_POOL_STATES),
            ]
            if narration_language_filter is not None:
                random_filters.append(narration_language_filter)
            if tr01_cutoff_filter is not None:
                random_filters.append(tr01_cutoff_filter)
            va_random_ready_forms = db.session.scalar(
                sa.select(sa.func.count())
                .select_from(VaSubmissions)
                .join(VaSubmissionWorkflow, VaSubmissionWorkflow.va_sid == VaSubmissions.va_sid)
                .where(sa.and_(*random_filters))
            )
        pick_ready_rows = get_pick_available_forms(current_user, pick_form_ids)
        va_forms_completed = get_coder_completed_count(current_user.user_id, va_form_access)
        va_forms = get_coder_completed_history(current_user.user_id, va_form_access)
        va_pick_ready_forms_count = len(pick_ready_rows)
        has_random_mode = bool(random_form_ids)
        has_pick_mode = bool(pick_form_ids)
        from app.models import VaResearchProjects, VaSites  # noqa: PLC0415

        today = datetime.utcnow().date()
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        _tc_rows = db.session.execute(
            sa.select(VaForms.site_id, sa.func.count().label("cnt"))
            .select_from(VaAllocations)
            .join(VaSubmissions, VaSubmissions.va_sid == VaAllocations.va_sid)
            .join(VaForms, VaForms.form_id == VaSubmissions.va_form_id)
            .where(
                VaAllocations.va_allocated_to == current_user.user_id,
                VaAllocations.va_allocation_for == VaAllocation.coding,
                VaAllocations.va_allocation_createdat >= today_start,
                VaForms.form_id.in_(va_form_access),
            )
            .group_by(VaForms.site_id)
        ).all()
        site_today_counts = {r.site_id: r.cnt for r in _tc_rows}
        eligibility_rows = db.session.execute(
            sa.select(
                VaResearchProjects.project_id,
                VaResearchProjects.project_nickname,
                VaSites.site_name,
                VaSites.site_abbr,
                VaForms.form_id,
                VaForms.site_id,
                VaProjectSites.coding_enabled,
                VaProjectSites.coding_start_date,
                VaProjectSites.coding_end_date,
                VaProjectSites.daily_coder_limit,
            )
            .join(VaSites, VaSites.site_id == VaForms.site_id)
            .join(VaResearchProjects, VaResearchProjects.project_id == VaForms.project_id)
            .join(
                VaProjectSites,
                sa.and_(
                    VaProjectSites.project_id == VaForms.project_id,
                    VaProjectSites.site_id == VaForms.site_id,
                    VaProjectSites.project_site_status == VaStatuses.active,
                ),
            )
            .where(VaForms.form_id.in_(va_form_access))
            .order_by(VaResearchProjects.project_id, VaSites.site_id)
        ).all()

        pi_project_ids = set(current_user.get_project_pi_projects())
        pi_site_ids = set(current_user.get_site_pi_sites())
        tester_projects = set(current_user.get_coding_tester_projects())
        tester_pairs = current_user.get_coding_tester_project_site_pairs()

        def _coding_status(row):
            is_pi = row.project_id in pi_project_ids or row.site_id in pi_site_ids
            is_tester = row.project_id in tester_projects or (
                row.project_id,
                row.site_id,
            ) in tester_pairs
            if not is_pi and not is_tester:
                if row.coding_enabled is False:
                    return "disabled"
                if row.coding_start_date and row.coding_start_date > today:
                    return "not_started"
            if not is_pi:
                if row.coding_end_date and row.coding_end_date < today:
                    return "ended"
            return "open"

        coder_eligibility = [
            {
                "project_id": row.project_id,
                "project": row.project_nickname,
                "site": row.site_name,
                "site_abbr": row.site_abbr,
                "form_id": row.form_id,
                "site_id": row.site_id,
                "coding_status": _coding_status(row),
                "coding_start_date": row.coding_start_date,
                "coding_end_date": row.coding_end_date,
                "daily_coder_limit": row.daily_coder_limit
                if row.daily_coder_limit is not None
                else 100,
                "today_count": site_today_counts.get(row.site_id, 0),
            }
            for row in eligibility_rows
        ]
        coder_languages = sorted(current_user.vacode_language or [])
    else:
        va_total_forms = 0
        va_random_ready_forms = 0
        va_forms_completed = 0
        va_forms = []
        pick_ready_rows = []
        va_pick_ready_forms_count = 0
        has_random_mode = False
        has_pick_mode = False
        coder_eligibility = []
        coder_languages = []

    va_has_allocation = get_active_coding_allocation(current_user.user_id)
    demo_projects = []
    if va_form_access:
        demo_projects = get_demo_training_project_ids(va_form_access)

    return render_template(
        "va_frontpages/va_code.html",
        va_total_forms=va_total_forms,
        va_random_ready_forms=va_random_ready_forms,
        va_pick_ready_forms_count=va_pick_ready_forms_count,
        va_forms_completed=va_forms_completed,
        va_forms=va_forms,
        pick_ready_forms=pick_ready_rows,
        has_random_mode=has_random_mode,
        has_pick_mode=has_pick_mode,
        va_has_allocation=va_has_allocation,
        va_recodeable=get_coder_recodeable_sids(current_user.user_id, va_form_access),
        is_admin=user_has_role(current_user, "admin"),
        demo_projects=demo_projects,
        coder_eligibility=coder_eligibility,
        coder_languages=coder_languages,
    )
