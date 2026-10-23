"""Public explainer and first-sign-in welcome for the Training & demo project.

``GET /demo`` needs no sign-in and lists no users. ``/demo/welcome`` (signed in)
shows the role checklist of the user's own training participations; its Start
button records ``onboarded_at`` and opens the Training menu of the DigitVA app
(training is Expo-only, never a Flask work page). Policy:
docs/policy/training-demo-project.md.
"""
from flask import Blueprint, redirect, render_template, url_for
from flask_login import current_user, login_required

from app.routes.expo_client import export_ready
from app.services import training_demo_service as service
from app.services.authz import effective_roles

training_demo = Blueprint("training_demo", __name__)

# role -> (title, what the trainee can try). Training is done in the DigitVA
# app (/app/training), never in the Flask work pages.
ROLE_GUIDE = {
    "death_reporter": ("Death reporter", "Register a death in the community, as a field worker would."),
    "interviewer": (
        "Interviewer",
        "Start and complete a verbal autopsy interview for a registered death.",
    ),
    "interview_supervisor": (
        "Interview supervisor",
        "Review the deaths and interviews of your unit and follow them up.",
    ),
    "coder": (
        "Coder",
        "Pick one of your 10 training cases, read it and assign the cause of death.",
    ),
    "reviewer_data_manager": (
        "Reviewer and data manager",
        "Review coders' work on the whole session, and see its data, progress and exports.",
    ),
}
TRAINING_APP_URL = "/app/training"


def _guide() -> list[dict]:
    return [
        {"role": role, "title": title, "what": what}
        for role, (title, what) in ROLE_GUIDE.items()
    ]


def _report_links(role: str) -> list[tuple[str, str]]:
    """The one Flask page a trainee is sent to: the trainer report a session
    manager reads (everything else is in the DigitVA app)."""
    if role != "reviewer_data_manager":
        return []
    return [("Read the training report (progress and agreement)", url_for("data_management.training_sessions"))]


@training_demo.get("/demo")
def public_page():
    """What the training project is; no sign-in, no user data."""
    return render_template(
        "va_frontpages/va_training_demo.html",
        guide=_guide(),
        sign_in_url=url_for(
            "va_auth.va_login",
            next=TRAINING_APP_URL if export_ready() else url_for("training_demo.welcome"),
        ),
    )


@training_demo.get("/demo/welcome")
@login_required
def welcome():
    effective_roles(current_user)  # records the authz decision for this request
    # Training lives in the Expo app while its export is present; this page is the fallback.
    if export_ready():
        return redirect(TRAINING_APP_URL)
    parts = service.participations(current_user.user_id)
    cards = [
        {
            **part,
            "title": ROLE_GUIDE[part["role"]][0],
            "what": ROLE_GUIDE[part["role"]][1],
            "links": _report_links(part["role"]),
        }
        for part in parts
    ]
    return render_template(
        "va_frontpages/va_training_welcome.html",
        cards=cards,
        pending=any(part["onboarded_at"] is None for part in parts),
        training_app_url=TRAINING_APP_URL,
    )


@training_demo.post("/demo/welcome/start")
@login_required
def start():
    effective_roles(current_user)
    parts = service.participations(current_user.user_id)
    service.complete_onboarding(current_user.user_id)
    service.remember_onboarding_checked(current_user.user_id)
    if not parts:
        return redirect(url_for("training_demo.welcome"))
    return redirect(TRAINING_APP_URL)
