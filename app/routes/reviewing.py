from flask import Blueprint, redirect, render_template, url_for
from flask_login import current_user

from app import db
from app.decorators import role_required
from app.models import VaSubmissions
from app.routes.coding import _has_org_unit_area, _require_or_abort
from app.services import reviewer_dashboard_service
from app.services.authz import Action
from app.services.coding_service import render_va_coding_page
from app.services.reviewer_coding_service import (
    ReviewerCodingError,
    get_active_reviewing_allocation,
    start_reviewer_coding,
)
from app.utils import va_permission_abortwithflash, va_permission_ensureanyallocation

reviewing = Blueprint("reviewing", __name__)


@reviewing.get("/")
@role_required("reviewer")
def dashboard():
    return render_template(
        "va_frontpages/va_reviewer.html",
        va_total_forms=reviewer_dashboard_service.count_in_scope(current_user),
        va_forms_completed=reviewer_dashboard_service.count_completed(current_user),
        va_forms=reviewer_dashboard_service.list_dashboard_forms(current_user),
        va_has_allocation=reviewer_dashboard_service.get_scoped_allocation(current_user),
        has_org_unit_area=_has_org_unit_area("reviewer"),
    )


@reviewing.post("/start/<va_sid>")
@role_required("reviewer")
def start(va_sid):
    # POST (CSRF-checked) because it allocates and moves the workflow; the
    # redirect keeps a browser refresh from re-firing it.
    try:
        start_reviewer_coding(current_user, va_sid)
    except ReviewerCodingError as exc:
        va_permission_abortwithflash(exc.message, exc.status_code)
    return redirect(url_for("reviewing.resume"))


@reviewing.get("/resume")
@role_required("reviewer")
def resume():
    va_permission_ensureanyallocation("reviewing")
    va_sid = get_active_reviewing_allocation(current_user.user_id)
    # The allocation is ownership, not scope: a revoked grant or a reroute
    # out of the reviewer's unit leaves it behind, so REVIEW is asked again.
    _require_or_abort(Action.REVIEW, va_sid)
    form = db.session.get(VaSubmissions, va_sid)
    return render_va_coding_page(form, "vareview", "varesumereviewing", "reviewer")


@reviewing.get("/view/<va_sid>")
@role_required("reviewer")
def view_submission(va_sid):
    # VIEW, not REVIEW: viewing is the wider right, so a reviewer above the
    # coding scope level still opens their subtree read-only (F7). The
    # ``vaview`` partials ask the same VIEW (va_validate_permissions).
    _require_or_abort(Action.VIEW, va_sid)
    form = db.session.get(VaSubmissions, va_sid)
    return render_va_coding_page(form, "vareview", "vaview", "reviewer")
