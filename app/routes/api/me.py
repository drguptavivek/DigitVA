"""The signed-in user's own access (docs/policy/api-v1.md), either credential."""
import logging
import uuid

from flask import Blueprint, g, jsonify, request, session
from flask_login import current_user, login_required, logout_user
from flask_wtf.csrf import generate_csrf
from sqlalchemy.exc import IntegrityError

from app import db, limiter
from app.routes.api import profile
from app.routes.api.request_helpers import error, optional_object_body
from app.services import (
    account_deletion_service,
    area_dashboard_service,
    device_auth_service,
    mentor_institute_service,
    notification_service,
    public_demo_purge_service,
    training_scope,
    user_home_service,
)
from app.services.access_summary_service import build_access_summary
from app.services.authz import effective_roles

log = logging.getLogger(__name__)
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


def _own_account_key():
    """Per-account limiter key: the signed-in caller, never a body field."""
    return f"own-account:{current_user.get_id() if current_user.is_authenticated else ''}"


@bp.get("/devices")
@login_required
@limiter.limit("60 per minute", key_func=_own_account_key)
def list_my_devices():
    """List this account's live native-device pairs (web or bearer)."""
    effective_roles(current_user._get_current_object())
    device_session = g.get("device_session")
    current_device_id = device_session.device_id if device_session is not None else None
    response = jsonify({
        "devices": device_auth_service.list_account_devices(current_user.user_id, current_device_id),
    })
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.delete("/devices/<uuid:device_id>")
@login_required
@limiter.limit("10 per minute", key_func=_own_account_key)
def decommission_my_device(device_id: uuid.UUID):
    """End this account's sessions on one device pair, retaining the pair and data."""
    effective_roles(current_user._get_current_object())
    ended = device_auth_service.decommission_account_device(
        current_user.user_id,
        device_id,
        current_user._get_current_object(),
    )
    db.session.commit()
    device_session = g.get("device_session")
    return jsonify({
        "decommissioned": True,
        "sessions_ended": ended,
        "current": bool(device_session is not None and device_session.device_id == device_id),
    })


# ---------------------------------------------------------------------------
# Delete my account (docs/policy/public-privacy-and-data-requests.md section 8)
# ---------------------------------------------------------------------------

#: The guard refusals a self-delete shows, by ``PurgeRefused.reason``.
SELF_DELETE_REFUSALS = {
    "shared_case": "Another account shares one of your cases, so this account cannot be deleted here.",
    "grant_outside_demo": "This account has access outside the demo, so it cannot be deleted here.",
    "not_demo_project": "This account has data outside the demo, so it cannot be deleted here.",
    "main_database": "The demo is not available right now. Please try again later.",
    "not_enabled": "The demo is not available right now. Please try again later.",
}


@bp.post("/account/delete")
@login_required
@limiter.limit("5 per minute", key_func=_own_account_key)
@limiter.limit("20 per hour", key_func=_own_account_key)
def delete_own_account():
    """A public-demo account deletes itself at once, after its password is
    checked again (docs/policy/public-demo.md section 9a). Body
    ``{"password"}``; the password is never logged or stored. Either
    credential; a cookie request carries ``X-CSRFToken`` (the app-level
    hook) and is signed out afterwards. 200 ``{"deleted": true}``; 403
    ``not_demo_account`` (staff use ``/deletion-request``), 400
    ``wrong_password``, 409 ``deletion_refused`` with ``reason`` when a guard
    refuses (nothing is deleted)."""
    user = current_user._get_current_object()
    effective_roles(user)  # records the authz decision: the caller's own account only
    if not user.is_public_demo:
        return error("Ask for deletion instead: this account is deleted by the programme team.",
                     "not_demo_account", 403)
    body = optional_object_body()
    password = body.get("password") if isinstance(body, dict) else None
    if not isinstance(password, str) or not password or not user.check_password(password):
        # 400, not 401 or 403: the phone reads 401 as "sign in again" and 403 as changed access.
        return error("Incorrect password.", "wrong_password", 400)
    user_id = user.user_id  # the row is gone after the delete; never read it again
    try:
        public_demo_purge_service.delete_own_account(user_id)
    except public_demo_purge_service.PurgeRefused as exc:
        db.session.rollback()
        message = SELF_DELETE_REFUSALS.get(exc.reason, "This account cannot be deleted here.")
        return error(message, "deletion_refused", 409, reason=exc.reason)
    except IntegrityError:
        # A row the deletion plan does not cover still points at the account: the savepoint
        # rolled back, so nothing was deleted.
        db.session.rollback()
        return error("This account cannot be deleted here.", "deletion_refused", 409, reason="not_eligible")
    db.session.commit()
    if not g.get("bearer_auth"):
        logout_user()
        session.clear()
    return jsonify({"deleted": True})


@bp.post("/deletion-request")
@login_required
@limiter.limit("10 per hour", key_func=_own_account_key)
def request_account_deletion():
    """A staff account asks to be deleted; an admin reviews it and deletion
    stays manual. Identified by the session alone (no body). Either
    credential; a cookie request carries ``X-CSRFToken``. 201
    ``{"status": "pending", "created": true}`` when filed; 200 with
    ``created`` false while one is already pending (nothing changes). 403
    ``demo_account``: a demo account deletes itself (``/account/delete``)."""
    user = current_user._get_current_object()
    effective_roles(user)  # records the authz decision: the caller's own account only
    if user.is_public_demo:
        return error("Delete this demo account from Delete my account.", "demo_account", 403)
    _row, created = account_deletion_service.request_deletion(
        user, via="web" if not g.get("bearer_auth") else "app")
    db.session.commit()
    if created:
        # The request is filed and shown to admins; a mail outage must not report it as failed.
        try:
            account_deletion_service.notify(user)
        except Exception:
            log.warning("account deletion request notice not sent", exc_info=True)
    return jsonify({"status": "pending", "created": created}), 201 if created else 200
