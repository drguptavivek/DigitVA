"""The signed-in user's own access (docs/policy/api-v1.md), either credential."""
from flask import Blueprint, g, jsonify, request
from flask_login import current_user, login_required
from flask_wtf.csrf import generate_csrf

from app import limiter
from app.routes.api import profile
from app.routes.api.request_helpers import error
from app.services import (
    area_dashboard_service,
    mentor_institute_service,
    notification_service,
    training_scope,
    user_home_service,
)
from app.services.access_summary_service import build_access_summary
from app.services.authz import effective_roles

bp = Blueprint("me_api", __name__)


@bp.get("/access")
@login_required
@limiter.limit("120 per minute")
def access():
    """Everything about the caller's access in one body
    (docs/current-state/api-v1.md). JSON 401 when signed out. A cookie
    request gets full account access and a CSRF token in ``X-CSRFToken``.
    A bearer request gets native worker grants only and no CSRF token,
    since generating one writes the session."""
    response = jsonify(build_access_summary(current_user._get_current_object()))
    if not g.get("bearer_auth"):
        response.headers["X-CSRFToken"] = generate_csrf()
    return response


@bp.get("/activity")
@login_required
@limiter.limit("120 per minute")
def activity():
    """Personal activity counts (overall and per project) for the caller's
    Home / Dashboard (docs/current-state/api-v1.md, digitva-dsj2). The
    training project is left out (docs/policy/training-demo-project.md)."""
    training_scope.use(training_scope.EXCLUDE)
    return jsonify(user_home_service.get_user_activity_summary(current_user._get_current_object()))


@bp.get("/home")
@login_required
@limiter.limit("120 per minute")
def home():
    """The Home page's one block per role the caller holds, counts only, each
    within that role's own scope (docs/current-state/api-v1.md). JSON 401
    when signed out. ``android_apk_url``: the Android app download link, or
    null when ``DIGITVA_ANDROID_APK_URL`` is unset or not a clean https URL."""
    from app.services.worker_enrolment_service import valid_android_apk_url

    training_scope.use(training_scope.EXCLUDE)
    body = user_home_service.get_home_blocks(current_user._get_current_object())
    return jsonify({**body, "android_apk_url": valid_android_apk_url()})


@bp.get("/kpis")
@login_required
@limiter.limit("120 per minute")
def kpis():
    """Home KPI strip: one row per project in the caller's area, names and
    counts only (docs/policy/area-dashboard.md, "Home KPIs"). Cached per user
    for a minute. JSON 401 when signed out."""
    return jsonify({"projects": area_dashboard_service.home_kpis(current_user)})


@bp.get("/notifications")
@login_required
@limiter.limit("120 per minute")
def notifications():
    """The caller's own notifications after the cursor ``after`` (default 0),
    oldest first, at most 100: ``{notifications, next_cursor}``
    (docs/current-state/api-v1.md). A nudge to sync, never the truth; zero
    database queries when Redis says nothing is newer. 400 ``invalid_request``
    for an ``after`` that is not a non-negative integer."""
    raw = request.args.get("after", "0")
    if not raw.isascii() or not raw.isdigit() or int(raw) > notification_service.BIGINT_MAX:
        return error("after must be a non-negative integer.", "invalid_request", 400)
    training_scope.use(training_scope.EXCLUDE)
    return jsonify(notification_service.poll(current_user.user_id, int(raw)))


@bp.get("/mentoring")
@login_required
@limiter.limit("120 per minute")
def mentoring():
    """The caller's own mentoring-institute memberships and supported districts."""
    effective_roles(current_user._get_current_object())
    return jsonify(mentor_institute_service.user_mentoring_summary(current_user._get_current_object()))


# The terms screen's call, same view as POST /api/v1/profile/terms: one
# acceptance rule, one audit event, whichever URL a client uses.
bp.add_url_rule("/terms", view_func=profile.accept_terms, methods=["POST"])
