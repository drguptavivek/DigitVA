import sqlalchemy as sa
from app import db
from app.models import VaSubmissions, VaSubmissionWorkflow, VaAllocations, VaAllocation, VaStatuses, VaForms
from flask_login import current_user
from flask import Blueprint, render_template, url_for, redirect, request
from app.decorators import role_required
from app.utils import va_permission_abortwithflash, va_render_serialisedates
from app.services.coder_dashboard_service import (
    get_coder_completed_count,
    get_coder_completed_history,
    get_coder_recodeable_sids,
)
from app.services.odk_retirement_service import submission_is_in_odk
from app.services.workflow.definition import CODER_READY_POOL_STATES
from app.services.workflow.intake_modes import split_form_ids_by_coding_intake_mode
from app.services.coding_service import render_va_coding_page
from app.services.coder_workflow_service import (
    AllocationError,
    AllocationResult,
    _narration_language_filter,
    _tr01_cutoff_filter,
    allocate_random_form,
    allocate_pick_form,
    start_recode_allocation,
    start_demo_allocation,
    get_active_coding_allocation,
    get_pick_available_forms,
    _org_unit_scope_filter,
)
from app.services.demo_project_service import should_use_demo_actiontype_for_submission
from app.services.demo_project_service import get_demo_training_project_ids
from app.models.va_project_sites import VaProjectSites
from datetime import datetime


coding = Blueprint("coding", __name__)


def _handle_allocation_error(e: AllocationError):
    va_permission_abortwithflash(e.message, e.status_code)


@coding.get("/")
@role_required("coder", "coding_tester", "admin")
def dashboard():
    va_form_access = current_user.get_coder_va_forms() | current_user.get_coding_tester_va_forms()
    if va_form_access:
        narration_language_filter = _narration_language_filter(current_user)
        random_form_ids, pick_form_ids = split_form_ids_by_coding_intake_mode(va_form_access)
        total_filters = [
            VaSubmissions.va_form_id.in_(va_form_access),
            VaSubmissionWorkflow.workflow_state.in_(CODER_READY_POOL_STATES),
            submission_is_in_odk(),
        ]
        if narration_language_filter is not None:
            total_filters.append(narration_language_filter)
        # Organization-tree projects are limited to the coder's own units, so
        # the dashboard counts match what the pick list actually offers.
        org_unit_filter = _org_unit_scope_filter(current_user)
        if org_unit_filter is not None:
            total_filters.append(org_unit_filter)
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
                submission_is_in_odk(),
            ]
            if narration_language_filter is not None:
                random_filters.append(narration_language_filter)
            if org_unit_filter is not None:
                random_filters.append(org_unit_filter)
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
        from app.models import VaSites, VaResearchProjects  # noqa: PLC0415
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
            .join(VaProjectSites, sa.and_(
                VaProjectSites.project_id == VaForms.project_id,
                VaProjectSites.site_id == VaForms.site_id,
                VaProjectSites.project_site_status == VaStatuses.active,
            ))
            .where(VaForms.form_id.in_(va_form_access))
            .order_by(VaResearchProjects.project_id, VaSites.site_id)
        ).all()

        pi_project_ids = set(current_user.get_project_pi_projects())
        pi_site_ids = set(current_user.get_site_pi_sites())
        tester_projects = set(current_user.get_coding_tester_projects())
        tester_pairs = current_user.get_coding_tester_project_site_pairs()

        def _coding_status(r):
            is_pi = r.project_id in pi_project_ids or r.site_id in pi_site_ids
            is_tester = r.project_id in tester_projects or (r.project_id, r.site_id) in tester_pairs
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
                "today_count": site_today_counts.get(r.site_id, 0),
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
        coder_eligibility=coder_eligibility,
        coder_languages=coder_languages,
        has_org_unit_area=_has_org_unit_area(),
    )


def _has_org_unit_area():
    """Whether this user oversees any organization units, in either role."""
    from app.models import VaAccessRoles
    from app.services.org_grant_service import viewable_unit_ids

    return bool(
        viewable_unit_ids(current_user.user_id, VaAccessRoles.coder)
        or viewable_unit_ids(current_user.user_id, VaAccessRoles.reviewer)
    )


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
    form = db.session.get(VaSubmissions, va_sid)
    if not form:
        va_permission_abortwithflash("Submission not found.", 404)
    if not (
        current_user.has_va_form_access(form.va_form_id, "coder")
        or current_user.is_coding_tester(form.va_form_id)
    ):
        va_permission_abortwithflash("You do not have coder access to view this submission.", 403)
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
    """Submissions in the units this user's grants cover, read-only."""
    from app.models import MasOrgUnit, VaAccessRoles, VaFinalAssessments
    from app.services.org_grant_service import codeable_unit_ids, viewable_unit_ids

    role = VaAccessRoles.reviewer if _prefers_reviewer_area() else VaAccessRoles.coder
    viewable = viewable_unit_ids(current_user.user_id, role)
    if not viewable:
        return render_template(
            "va_frontpages/va_area_overview.html",
            rows=[],
            role=role.value,
            codeable_count=0,
            viewable_count=0,
            truncated=False,
        )

    codeable = codeable_unit_ids(current_user.user_id, role)

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
        )
        .select_from(VaSubmissions)
        .join(VaSubmissionWorkflow, VaSubmissionWorkflow.va_sid == VaSubmissions.va_sid)
        .join(MasOrgUnit, MasOrgUnit.org_unit_id == VaSubmissions.org_unit_id)
        .outerjoin(authoritative, authoritative.c.va_sid == VaSubmissions.va_sid)
        .where(VaSubmissions.org_unit_id.in_(sorted(viewable)))
        .order_by(MasOrgUnit.path, VaSubmissions.va_submission_date.desc())
        .limit(AREA_OVERVIEW_MAX_ROWS + 1)
    )
    records = db.session.execute(stmt).mappings().all()
    truncated = len(records) > AREA_OVERVIEW_MAX_ROWS

    rows = []
    for record in records[:AREA_OVERVIEW_MAX_ROWS]:
        row = dict(record)
        # "Codeable here" is what separates oversight from work: a viewer sees
        # every row, and may open the ones inside their coding scope.
        row["is_codeable"] = record["org_unit_id"] in codeable
        rows.append(va_render_serialisedates(row, ["va_submission_date"]))

    return render_template(
        "va_frontpages/va_area_overview.html",
        rows=rows,
        role=role.value,
        codeable_count=len(codeable),
        viewable_count=len(viewable),
        truncated=truncated,
    )


def _prefers_reviewer_area() -> bool:
    """Show the reviewer's area to someone who only holds reviewer grants."""
    from app.models import VaAccessRoles
    from app.services.org_grant_service import viewable_unit_ids

    requested = (request.args.get("role") or "").strip().lower()
    if requested in {"coder", "reviewer"}:
        return requested == "reviewer"
    if viewable_unit_ids(current_user.user_id, VaAccessRoles.coder):
        return False
    return bool(viewable_unit_ids(current_user.user_id, VaAccessRoles.reviewer))


@coding.get("/area/<va_sid>")
@role_required("coder", "coding_tester", "reviewer", "admin")
def area_view_submission(va_sid):
    """Read-only view of one submission inside the user's area."""
    from app.models import VaAccessRoles
    from app.services.org_grant_service import submission_within_org_view_scope

    submission = db.session.get(VaSubmissions, va_sid)
    if not submission:
        va_permission_abortwithflash("Submission not found.", 404)

    role = VaAccessRoles.reviewer if _prefers_reviewer_area() else VaAccessRoles.coder
    if not submission_within_org_view_scope(current_user, va_sid, role):
        va_permission_abortwithflash(
            "This submission belongs to a unit outside your area.", 403
        )
    # vadata is the read-only rendering the data manager already uses; the
    # coder back-link keeps the viewer inside their own dashboard.
    return render_va_coding_page(submission, "vadata", "vaview", "coder")
