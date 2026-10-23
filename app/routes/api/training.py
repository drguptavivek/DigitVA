"""The signed-in user's own training participations (the Expo Training menu).

``GET /api/v1/training/me`` and ``POST /api/v1/training/me/start``. Policy:
docs/policy/training-demo-project.md, "Onboarding and the public page". Both
read only the caller's own rows; the browser write carries ``X-CSRFToken`` like
every cookie-session write.
"""
from flask import Blueprint, jsonify
from flask_login import current_user, login_required

from app import limiter
from app.services import training_demo_service as service
from app.services.authz import effective_roles

bp = Blueprint("training_api", __name__)


@bp.get("/me")
@login_required
@limiter.limit("120 per minute")
def me():
    """``{project_id, areas, pending, participations}``: ``areas`` are the
    Training sub-menus to show (``interview``, ``coding``, ``review``), empty
    without an active participation; ``pending`` is true until Start."""
    effective_roles(current_user._get_current_object())  # records the authz decision
    return jsonify(service.me_summary(current_user.user_id))


@bp.post("/me/start")
@login_required
@limiter.limit("30 per minute")
def start():
    """Record that the caller started the training (sets ``onboarded_at`` on
    their pending participations); idempotent. Replies as ``GET /me``."""
    effective_roles(current_user._get_current_object())
    service.complete_onboarding(current_user.user_id)
    service.remember_onboarding_checked(current_user.user_id)
    return jsonify(service.me_summary(current_user.user_id))
