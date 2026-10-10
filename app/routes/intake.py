"""Web intake pages: death register, worklist and WHO VA 2022 questionnaire.

Thin layer over ``app.services.web_intake_service``. Pages render Jinja
templates that load the vendored questionnaire bundle; their scripts call the
JSON API at ``/api/v1/intake`` (app/routes/api/intake.py), sending
``X-CSRFToken`` from the page's ``csrf_token()``.
Policy: docs/policy/web-intake.md
"""
from flask import Blueprint, current_app, render_template
from flask_login import current_user

from app import _content_security_policy, talisman
from app.decorators import role_required
from app.services import web_intake_service as intake_svc

intake = Blueprint("intake", __name__)


class _FormPageContentSecurityPolicy:
    """Build the global policy per request, allowing blob-backed audio."""

    def items(self):
        policy = _content_security_policy(current_app)
        policy["media-src"] += " blob:"
        return policy.items()


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------


@intake.get("/")
@role_required("interviewer")
def dashboard():
    # The worklist script's scope picker; rendered here, not fetched.
    return render_template(
        "va_frontpages/va_intake.html", context=intake_svc.interviewer_context(current_user)
    )


@intake.get("/deaths/new")
@role_required("interviewer")
def new_death_page():
    return render_template("va_frontpages/va_intake_death.html")


@intake.get("/supervision")
@role_required("interview_supervisor", "data_manager")
def supervision_page():
    """The supervisor list over ``/api/v1/intake/supervision/cases`` (digitva-vzk.8)."""
    return render_template("va_frontpages/va_intake_supervision.html")


@intake.get("/form/<draft_id>")
@talisman(content_security_policy=_FormPageContentSecurityPolicy())
@role_required("interviewer")
def form_page(draft_id):
    try:
        draft = intake_svc.get_draft(current_user, draft_id)
    except intake_svc.WebIntakeError as exc:
        return render_template("va_errors/va_404.html"), exc.status_code
    return render_template(
        "va_frontpages/va_intake_form.html",
        draft=intake_svc.serialize_draft(draft),
        prefill=draft.prefill or {},
        names=intake_svc.resolve_draft_display_names(draft),
    )
