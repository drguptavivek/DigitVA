"""Reviewer workflow action routes."""

from flask_login import current_user

from app import db
from app.authz.access import action_authorized
from app.authz.resources import submission_from_kwarg
from app.authz.scope import user_has_form_access
from app.models import VaSubmissions
from app.services.reviewer_coding_service import (
    ReviewerCodingError,
    get_active_reviewing_allocation,
    start_reviewer_coding,
)
from app.utils import va_permission_abortwithflash

from .common import render_va_coding_page_for_route, reviewing


@reviewing.get("/start/<va_sid>")
@action_authorized("reviewing_start", resource_resolver=submission_from_kwarg("va_sid"))
def start(va_sid):
    try:
        result = start_reviewer_coding(current_user, va_sid)
    except ReviewerCodingError as exc:
        va_permission_abortwithflash(exc.message, exc.status_code)

    form = db.session.get(VaSubmissions, result.va_sid)
    return render_va_coding_page_for_route(
        form,
        "vareview",
        result.actiontype,
        "reviewer",
    )


@reviewing.get("/resume")
@action_authorized("reviewing_resume")
def resume():
    va_sid = get_active_reviewing_allocation(current_user.user_id)
    if not va_sid:
        va_permission_abortwithflash("You have no active VA form allocation.", 403)
    form = db.session.get(VaSubmissions, va_sid)
    if not form:
        va_permission_abortwithflash("Submission not found.", 404)
    if not user_has_form_access(current_user, form.va_form_id, "reviewer"):
        va_permission_abortwithflash(
            "Reviewer access is required to resume this submission.",
            403,
        )
    if form.va_narration_language not in current_user.vacode_language:
        va_permission_abortwithflash(
            "Your profile does not support reviewing forms in "
            f"{form.va_narration_language}.",
            403,
        )
    return render_va_coding_page_for_route(
        form,
        "vareview",
        "varesumereviewing",
        "reviewer",
    )


@reviewing.get("/view/<va_sid>")
@action_authorized(
    "reviewing_submission_view",
    resource_resolver=submission_from_kwarg("va_sid"),
)
def view_submission(va_sid):
    form = db.session.get(VaSubmissions, va_sid)
    return render_va_coding_page_for_route(form, "vareview", "vaview", "reviewer")
