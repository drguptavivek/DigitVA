"""Public explainer and first-sign-in welcome for the Training & demo project.

``GET /demo`` needs no sign-in and lists no users. ``/demo/welcome`` (signed in)
shows the role checklist of the user's own training participations; its Start
button records ``onboarded_at`` and opens the role landing page. Policy:
docs/policy/training-demo-project.md.
"""
from flask import Blueprint, redirect, render_template, url_for
from flask_login import current_user, login_required

from app.services import training_demo_service as service
from app.services.authz import effective_roles

training_demo = Blueprint("training_demo", __name__)

# role -> (title, what the trainee can try, [(link label, endpoint)], landing endpoint).
# Links go into the real app; the trainee's grants scope them to TRN01.
ROLE_GUIDE = {
    "death_reporter": (
        "Death reporter",
        "Register a death in the community, as a field worker would.",
        [("Report a death", "intake.new_death_page")],
        "intake.new_death_page",
    ),
    "interviewer": (
        "Interviewer",
        "Start and complete a verbal autopsy interview for a registered death.",
        [("Open your worklist", "intake.dashboard"), ("Report a death", "intake.new_death_page")],
        "intake.dashboard",
    ),
    "interview_supervisor": (
        "Interview supervisor",
        "Review the deaths and interviews of your unit and follow them up.",
        [("Open the supervision list", "intake.supervision_page")],
        "intake.supervision_page",
    ),
    "coder": (
        "Coder",
        "Pick one of your 10 training cases, read it and assign the cause of death.",
        [("Open your coding list", "coding.dashboard")],
        "coding.dashboard",
    ),
    "reviewer_data_manager": (
        "Reviewer and data manager",
        "Review coders' work on the whole session, and see its data, progress and exports.",
        [
            ("Open the reviewer list", "reviewing.dashboard"),
            ("Open the data manager dashboard", "data_management.dashboard"),
            ("Read the training report (progress and agreement)", "data_management.training_sessions"),
        ],
        "reviewing.dashboard",
    ),
}


def _guide() -> list[dict]:
    return [
        {"role": role, "title": title, "what": what}
        for role, (title, what, _links, _landing) in ROLE_GUIDE.items()
    ]


@training_demo.get("/demo")
def public_page():
    """What the training project is; no sign-in, no user data."""
    return render_template(
        "va_frontpages/va_training_demo.html",
        guide=_guide(),
        sign_in_url=url_for("va_auth.va_login", next=url_for("training_demo.welcome")),
    )


@training_demo.get("/demo/welcome")
@login_required
def welcome():
    effective_roles(current_user)  # records the authz decision for this request
    parts = service.participations(current_user.user_id)
    cards = [
        {
            **part,
            "title": ROLE_GUIDE[part["role"]][0],
            "what": ROLE_GUIDE[part["role"]][1],
            "links": [(label, url_for(endpoint)) for label, endpoint in ROLE_GUIDE[part["role"]][2]],
        }
        for part in parts
    ]
    return render_template(
        "va_frontpages/va_training_welcome.html",
        cards=cards,
        pending=any(part["onboarded_at"] is None for part in parts),
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
    return redirect(url_for(ROLE_GUIDE[parts[0]["role"]][3]))
