"""Coding workflow action routes."""

import sys

from flask import redirect, request, url_for
from flask_login import current_user

from app import db
from app.authz.access import action_authorized
from app.authz.resources import submission_from_kwarg
from app.authz.scope import user_has_coding_form_access, user_has_role
from app.models import VaSubmissions
from app.services.coder_workflow_service import (
    AllocationError,
    allocate_pick_form,
    allocate_random_form,
    get_active_coding_allocation,
    start_demo_allocation,
    start_recode_allocation,
)
from app.services.demo_project_service import should_use_demo_actiontype_for_submission
from app.utils import va_permission_abortwithflash

from .common import coding, handle_allocation_error


def _render_va_coding_page(*args, **kwargs):
    route_module = sys.modules.get("app.routes.coding") or sys.modules[
        "app.routes.workflow.coding"
    ]
    return route_module.render_va_coding_page(*args, **kwargs)


@coding.post("/start")
@action_authorized("coding_start")
def start():
    project_id = (request.args.get("project_id") or "").strip().upper() or None
    try:
        result = allocate_random_form(current_user, project_id=project_id)
    except AllocationError as error:
        handle_allocation_error(error)
    if result.actiontype == "varesumecoding":
        return redirect(url_for("coding.resume"))
    form = db.session.get(VaSubmissions, result.va_sid)
    return _render_va_coding_page(form, "vacode", result.actiontype, "coder")


@coding.get("/resume")
@action_authorized("coding_resume")
def resume():
    va_sid = get_active_coding_allocation(current_user.user_id)
    if not va_sid:
        va_permission_abortwithflash("No active coding allocation found.", 404)
    form = db.session.get(VaSubmissions, va_sid)
    if not form:
        va_permission_abortwithflash("Submission not found.", 404)
    if not user_has_role(current_user, "admin") and not user_has_coding_form_access(
        current_user, form.va_form_id
    ):
        va_permission_abortwithflash(
            "You do not have coder access to resume this submission.",
            403,
        )
    actiontype = (
        "vademo_start_coding"
        if should_use_demo_actiontype_for_submission(va_sid)
        else "varesumecoding"
    )
    return _render_va_coding_page(form, "vacode", actiontype, "coder")


@coding.post("/pick/<va_sid>")
@action_authorized("coding_pick", resource_resolver=submission_from_kwarg("va_sid"))
def pick(va_sid):
    try:
        result = allocate_pick_form(current_user, va_sid)
    except AllocationError as error:
        handle_allocation_error(error)
    form = db.session.get(VaSubmissions, result.va_sid)
    return _render_va_coding_page(form, "vacode", result.actiontype, "coder")


@coding.post("/recode/<va_sid>")
@action_authorized("coding_recode_start", resource_resolver=submission_from_kwarg("va_sid"))
def recode(va_sid):
    try:
        start_recode_allocation(current_user, va_sid)
    except AllocationError as error:
        handle_allocation_error(error)
    return redirect(url_for("coding.resume"))


@coding.post("/demo")
@action_authorized("coding_demo_start")
def demo():
    project_id = (request.args.get("project_id") or "").strip().upper() or None
    try:
        result = start_demo_allocation(current_user, project_id)
    except AllocationError as error:
        handle_allocation_error(error)
    form = db.session.get(VaSubmissions, result.va_sid)
    return _render_va_coding_page(form, "vacode", result.actiontype, "coder")


@coding.get("/view/<va_sid>")
@action_authorized("coding_submission_view", resource_resolver=submission_from_kwarg("va_sid"))
def view_submission(va_sid):
    form = db.session.get(VaSubmissions, va_sid)
    if not form:
        va_permission_abortwithflash("Submission not found.", 404)
    if not user_has_coding_form_access(current_user, form.va_form_id):
        va_permission_abortwithflash("You do not have coder access to view this submission.", 403)
    return _render_va_coding_page(form, "vacode", "vaview", "coder")
