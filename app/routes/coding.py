import dataclasses

import sqlalchemy as sa
from app import db
from app.models import VaSubmissions, VaSubmissionWorkflow, VaAllocations, VaAllocation, VaStatuses, VaForms, VaAccessRoles
from flask_login import current_user
from flask import Blueprint, render_template, url_for, redirect, request
from app.decorators import role_required
from app.utils import va_permission_abortwithflash, va_render_serialisedates
from app.services.coder_dashboard_service import (
    get_coder_completed_count,
    get_coder_completed_history,
    get_coder_recodeable_sids,
)
from app.services.authz import (
    Action,
    AuthzError,
    coding_gate_waivers,
    require,
    resolve_grants,
    scope_filter,
)
from app.services.duplicate_exclusion import not_confirmed_duplicate_condition
from app.services.workflow.intake_modes import split_form_ids_by_coding_intake_mode
from app.services.coding_service import render_va_coding_page
from app.services.coder_workflow_service import (
    AllocationError,
    AllocationResult,
    _available_submission_filters,
    allocate_random_form,
    allocate_pick_form,
    start_recode_allocation,
    start_demo_allocation,
    get_active_coding_allocation,
    get_pick_available_forms,
)
from app.services.demo_project_service import should_use_demo_actiontype_for_submission
from app.services.demo_project_service import get_demo_training_project_ids
from app.services.demo_project_service import get_demo_project_retention_minutes
from app.models.va_project_master import VaProjectMaster
from app.models.va_project_sites import VaProjectSites
from datetime import datetime


coding = Blueprint("coding", __name__)


def _handle_allocation_error(e: AllocationError):
    va_permission_abortwithflash(e.message, e.status_code)


def _require_or_abort(action: Action, va_sid: str) -> None:
    """``authz.require``, refusing with a flash the way allocation errors do."""
    try:
        require(current_user, action, va_sid)
    except AuthzError as e:
        va_permission_abortwithflash(e.message, e.status_code)


@coding.get("/")
@role_required("coder", "coding_tester", "admin")
def dashboard():
    va_form_access = current_user.get_coder_va_forms() | current_user.get_coding_tester_va_forms()
    if va_form_access:
        random_form_ids, pick_form_ids = split_form_ids_by_coding_intake_mode(va_form_access)

        # The pool's own filters (state, ODK, duplicates, language, coding
        # scope, TR01), so the counts match what the pool and pick list offer.
        def _count_ready(form_ids):
            return db.session.scalar(
                sa.select(sa.func.count())
                .select_from(VaSubmissions)
                .join(VaSubmissionWorkflow, VaSubmissionWorkflow.va_sid == VaSubmissions.va_sid)
                .where(sa.and_(*_available_submission_filters(form_ids, user=current_user)))
            )

        va_total_forms = _count_ready(va_form_access)
        va_random_ready_forms = _count_ready(random_form_ids) if random_form_ids else 0
        pick_ready_rows = get_pick_available_forms(current_user, pick_form_ids)
        va_forms_completed = get_coder_completed_count(current_user.user_id, va_form_access)
        va_forms = get_coder_completed_history(current_user.user_id, va_form_access)
        va_pick_ready_forms_count = len(pick_ready_rows)
        has_random_mode = bool(random_form_ids)
        has_pick_mode = bool(pick_form_ids)
        from app.models import VaSites, VaResearchProjects  # noqa: PLC0415
        today = datetime.utcnow().date()
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        _tc_rows = db.session.execute(
            sa.select(VaForms.project_id, VaForms.site_id, sa.func.count().label("cnt"))
            .select_from(VaAllocations)
            .join(VaSubmissions, VaSubmissions.va_sid == VaAllocations.va_sid)
            .join(VaForms, VaForms.form_id == VaSubmissions.va_form_id)
            .where(
                VaAllocations.va_allocated_to == current_user.user_id,
                VaAllocations.va_allocation_for == VaAllocation.coding,
                VaAllocations.va_allocation_createdat >= today_start,
                VaForms.form_id.in_(va_form_access),
            )
            .group_by(VaForms.project_id, VaForms.site_id)
        ).all()
        # Keyed on the pair: a site_id is shared across projects (digitva-d5s).
        site_today_counts = {(r.project_id, r.site_id): r.cnt for r in _tc_rows}
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
            .join(VaProjectSites, sa.and_(
                VaProjectSites.project_id == VaForms.project_id,
                VaProjectSites.site_id == VaForms.site_id,
                VaProjectSites.project_site_status == VaStatuses.active,
            ))
            .where(VaForms.form_id.in_(va_form_access))
            .order_by(VaResearchProjects.project_id, VaSites.site_id)
        ).all()

        waivers = coding_gate_waivers(current_user)

        def _coding_status(r):
            # Site-level status: a unit tester's waiver is per submission and
            # does not reopen the whole site, so it is not applied here.
            is_pi = waivers.is_pi(r.project_id, r.site_id)
            is_tester = waivers.is_tester(r.project_id, r.site_id)
            if not is_pi and not is_tester:
                if r.coding_enabled is False:
                    return "disabled"
                if r.coding_start_date and r.coding_start_date > today:
                    return "not_started"
            if not is_pi:
                if r.coding_end_date and r.coding_end_date < today:
                    return "ended"
            return "open"

        coder_eligibility = [
            {
                "project_id": r.project_id,
                "project": r.project_nickname,
                "site": r.site_name,
                "site_abbr": r.site_abbr,
                "form_id": r.form_id,
                "site_id": r.site_id,
                "coding_status": _coding_status(r),
                "coding_start_date": r.coding_start_date,
                "coding_end_date": r.coding_end_date,
                "daily_coder_limit": r.daily_coder_limit if r.daily_coder_limit is not None else 100,
                "today_count": site_today_counts.get((r.project_id, r.site_id), 0),
            }
            for r in eligibility_rows
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
    # The banner states each demo project's own retention, not a fixed 10.
    demo_retention_minutes = {
        project_id: get_demo_project_retention_minutes(db.session.get(VaProjectMaster, project_id))
        for project_id in demo_projects
    }

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
        is_admin=current_user.is_admin(),
        demo_projects=demo_projects,
        demo_retention_minutes=demo_retention_minutes,
        coder_eligibility=coder_eligibility,
        coder_languages=coder_languages,
        has_org_unit_area=_has_org_unit_area(),
    )


# The coding-track roles whose grants make up a user's area, per track.
_AREA_ROLES = {
    "coder": frozenset({VaAccessRoles.coder, VaAccessRoles.coding_tester}),
    "reviewer": frozenset({VaAccessRoles.reviewer}),
}


def _area_grants(track: str | None = None):
    """The user's grants that make up their area, as a ``ResolvedGrants``.

    Real coder / coding_tester / reviewer grants (one track, or both) on
    organization-tree projects, at any scope: a project or pair grant is the
    top of the tree (F2). Not admin's bypass and not the demo-training
    virtual grants: neither is an area someone oversees.
    """
    g = resolve_grants(current_user)
    roles = _AREA_ROLES[track] if track else _AREA_ROLES["coder"] | _AREA_ROLES["reviewer"]
    return dataclasses.replace(g, is_admin=False, grants=tuple(
        x for x in g.of(roles, virtual=False) if g.has_tree(x.project_id)
    ))


def _has_org_unit_area():
    """Whether this user oversees any part of an organization tree, in either track."""
    return bool(_area_grants().grants)


@coding.post("/start")
@role_required("coder", "coding_tester", "admin")
def start():
    project_id = (request.args.get("project_id") or "").strip().upper() or None
    try:
        result = allocate_random_form(current_user, project_id=project_id)
    except AllocationError as e:
        _handle_allocation_error(e)
    if result.actiontype == "varesumecoding":
        return redirect(url_for("coding.resume"))
    form = db.session.get(VaSubmissions, result.va_sid)
    return render_va_coding_page(form, "vacode", result.actiontype, "coder")


@coding.get("/resume")
@role_required("coder", "coding_tester", "admin")
def resume():
    va_sid = get_active_coding_allocation(current_user.user_id)
    if not va_sid:
        va_permission_abortwithflash("No active coding allocation found.", 404)
    form = db.session.get(VaSubmissions, va_sid)
    actiontype = (
        "vademo_start_coding"
        if should_use_demo_actiontype_for_submission(va_sid)
        else "varesumecoding"
    )
    return render_va_coding_page(form, "vacode", actiontype, "coder")


@coding.post("/pick/<va_sid>")
@role_required("coder", "coding_tester")
def pick(va_sid):
    try:
        result = allocate_pick_form(current_user, va_sid)
    except AllocationError as e:
        _handle_allocation_error(e)
    form = db.session.get(VaSubmissions, result.va_sid)
    return render_va_coding_page(form, "vacode", result.actiontype, "coder")


@coding.post("/recode/<va_sid>")
@role_required("coder", "coding_tester")
def recode(va_sid):
    try:
        start_recode_allocation(current_user, va_sid)
    except AllocationError as e:
        _handle_allocation_error(e)
    return redirect(url_for("coding.resume"))


@coding.post("/demo")
@role_required("admin")
def demo():
    project_id = (request.args.get("project_id") or "").strip().upper() or None
    try:
        result = start_demo_allocation(current_user, project_id)
    except AllocationError as e:
        _handle_allocation_error(e)
    form = db.session.get(VaSubmissions, result.va_sid)
    return render_va_coding_page(form, "vacode", result.actiontype, "coder")


@coding.get("/view/<va_sid>")
@role_required("coder", "coding_tester", "admin")
def view_submission(va_sid):
    # The same VIEW the ``vaview`` partial validator requires (F4); the
    # partials add the coder's own-outcome check (design 2.4).
    _require_or_abort(Action.VIEW, va_sid)
    form = db.session.get(VaSubmissions, va_sid)
    return render_va_coding_page(form, "vacode", "vaview", "coder")


# ---------------------------------------------------------------------------
# Area overview — oversight of the units a grant covers but may not code
#
# A coder granted above the project's coding scope level codes nothing, but
# still oversees their subtree: they see the cause of death and the submission
# data, read-only. The list and the view below are that right. They are
# deliberately built on the *viewable* unit set, never the codeable one.
# Policy: docs/policy/organization-model.md#coding-scope
# ---------------------------------------------------------------------------

AREA_OVERVIEW_MAX_ROWS = 200


@coding.get("/area")
@role_required("coder", "coding_tester", "reviewer", "admin")
def area_overview():
    """Submissions this user's coding-track grants let them view, read-only."""
    from app.models import MasOrgUnit, VaFinalAssessments

    track = "reviewer" if _prefers_reviewer_area() else "coder"
    area = _area_grants(track)
    if not area.grants:
        return render_template(
            "va_frontpages/va_area_overview.html",
            rows=[],
            role=track,
            codeable_count=0,
            has_area=False,
            truncated=False,
        )

    # Rows: VIEW over the area grants (routed or not, F2). "Codeable" is the
    # track's own work action over all of the user's grants.
    viewable = scope_filter(current_user, Action.VIEW, _grants=area)
    codeable = scope_filter(
        current_user, Action.REVIEW if track == "reviewer" else Action.CODE
    )
    authoritative = (
        sa.select(
            VaFinalAssessments.va_sid.label("va_sid"),
            sa.func.max(VaFinalAssessments.va_finassess_createdat).label("coded_at"),
        )
        .where(VaFinalAssessments.va_finassess_status == VaStatuses.active)
        .group_by(VaFinalAssessments.va_sid)
        .subquery()
    )
    stmt = (
        sa.select(
            VaSubmissions.va_sid,
            VaSubmissions.va_uniqueid_masked,
            VaSubmissions.va_submission_date,
            VaSubmissions.va_deceased_age,
            VaSubmissions.va_deceased_gender,
            VaSubmissions.org_unit_id,
            MasOrgUnit.unit_code,
            MasOrgUnit.unit_name,
            VaSubmissionWorkflow.workflow_state,
            authoritative.c.coded_at,
            sa.case((codeable, True), else_=False).label("is_codeable"),
        )
        .select_from(VaSubmissions)
        .join(VaSubmissionWorkflow, VaSubmissionWorkflow.va_sid == VaSubmissions.va_sid)
        .outerjoin(MasOrgUnit, MasOrgUnit.org_unit_id == VaSubmissions.org_unit_id)
        .outerjoin(authoritative, authoritative.c.va_sid == VaSubmissions.va_sid)
        .where(viewable, not_confirmed_duplicate_condition(VaSubmissions.va_sid))
        .order_by(MasOrgUnit.path.asc().nulls_last(), VaSubmissions.va_submission_date.desc())
        .limit(AREA_OVERVIEW_MAX_ROWS + 1)
    )
    records = db.session.execute(stmt).mappings().all()
    truncated = len(records) > AREA_OVERVIEW_MAX_ROWS
    rows = [
        va_render_serialisedates(dict(record), ["va_submission_date"])
        for record in records[:AREA_OVERVIEW_MAX_ROWS]
    ]
    return render_template(
        "va_frontpages/va_area_overview.html",
        rows=rows,
        role=track,
        codeable_count=sum(1 for row in rows if row["is_codeable"]),
        has_area=True,
        truncated=truncated,
    )


def _prefers_reviewer_area() -> bool:
    """Show the reviewer's area to someone who only holds reviewer grants."""
    requested = (request.args.get("role") or "").strip().lower()
    if requested in _AREA_ROLES:
        return requested == "reviewer"
    if _area_grants("coder").grants:
        return False
    return bool(_area_grants("reviewer").grants)


@coding.get("/area/<va_sid>")
@role_required("coder", "coding_tester", "reviewer", "admin")
def area_view_submission(va_sid):
    """Read-only view of one submission the user may view.

    VIEW alone, whichever track listed it, so every overview row opens
    (F17); the ``role`` the link carries does not narrow it.
    """
    _require_or_abort(Action.VIEW, va_sid)
    submission = db.session.get(VaSubmissions, va_sid)
    # vadata is the read-only rendering the data manager already uses; the
    # coder back-link keeps the viewer inside their own dashboard.
    return render_va_coding_page(submission, "vadata", "vaview", "coder")
