"""Public demo pages and downloads (digitva-77v5.3 and .4).

Policy: docs/policy/public-demo.md sections 5 to 7. One blueprint, no URL
prefix, so the pages and the JSON share it:

* ``GET /public-demo/cases``: the signed-in demo user's submissions.
* ``GET /public-demo/cases/<va_sid>/report``: one report, its submitter only.
* ``GET /api/v1/public-demo/my-responses.csv`` and ``.json``: the user's own
  responses; rate-limited, one at a time, audited (counts only).
* ``GET /public-demo/dashboard`` and ``GET /api/v1/public-demo/dashboard.json``:
  aggregates, no sign-in.

Everything answers 404 unless ``PUBLIC_DEMO_ENABLED``; the personal routes
also 404 for any account that is not a public-demo account (admins use the
normal views) and for a case that is not the caller's, whether or not it
exists. All routes are GET, so there is no CSRF surface. The blueprint is
registered always and gates in the view, so the flag can be switched per test
and per deployment without changing the URL map.
"""

from flask import Blueprint, Response, abort, jsonify, render_template, request
from flask_login import current_user, login_required

from app import cache, db, limiter
from app.services import public_demo_dashboard_service as dashboard_service
from app.services import public_demo_report_service as reports
from app.services import public_demo_service as demo
from app.services.authz import Action, can
from app.services.export_store_service import EXPORT_CONTENT_TYPE, UTF8_BOM
from app.services.security_event_service import record_security_event

public_demo = Blueprint("public_demo", __name__)

EXPORT_LOCK_SECONDS = 300
EXPORT_EVENT = "public_demo_download"
_PUBLIC_CACHE = "public, max-age=60"
_PRIVATE_CACHE = "private, no-store"


@public_demo.after_request
def _cache_headers(response):
    """A person's reports and downloads are never stored by a browser or
    proxy; the aggregate dashboard may be, briefly, for anonymous viewers."""
    if request.endpoint in ("public_demo.dashboard_page", "public_demo.dashboard_json"):
        if response.status_code == 200:
            # The page's navbar is personal for a signed-in viewer: never shared.
            personal = request.endpoint == "public_demo.dashboard_page" and current_user.is_authenticated
            response.headers["Cache-Control"] = _PRIVATE_CACHE if personal else _PUBLIC_CACHE
    else:
        response.headers["Cache-Control"] = "no-store"
    return response


def _user():
    return current_user._get_current_object()


@public_demo.get("/public-demo/cases")
@login_required
def my_submissions():
    """The caller's submitted cases, newest first, each with its pipeline
    state and a link to its report."""
    try:
        cases = reports.own_reports(_user())
    except reports.NotAvailable:
        abort(404)
    return render_template("public_demo/my_submissions.html", cases=cases)


@public_demo.get("/public-demo/cases/<va_sid>/report")
@login_required
def case_report(va_sid):
    """One case's cause-of-death report, for its submitter only."""
    user = _user()
    # authz first (it decides the request), then every refusal is one 404.
    allowed = bool(can(user, Action.VIEW, va_sid))
    if not allowed or not (demo.enabled() and user.is_public_demo):
        abort(404)
    try:
        found = reports.own_reports(user, va_sid=va_sid)
    except reports.NotAvailable:
        abort(404)
    if not found:
        abort(404)
    return render_template("public_demo/report.html", report=found[0], notice=reports.NOT_A_CERTIFICATE)


def _download(fmt: str):
    user = _user()
    lock_key = f"public-demo-export:{user.user_id}"
    # One running download per user; the TTL frees the slot if a worker dies.
    if not cache.add(lock_key, 1, timeout=EXPORT_LOCK_SECONDS):
        return jsonify({"error": "A download is already running; wait for it to finish.",
                        "code": "export_in_progress"}), 429
    try:
        try:
            own = reports.own_reports(user, with_answers=True)
        except reports.NotAvailable:
            abort(404)
        record_security_event(
            user_id=user.user_id, event_type=EXPORT_EVENT, detail={"format": fmt, "cases": len(own)},
        )
        db.session.commit()
        if fmt == "csv":
            body = UTF8_BOM + reports.csv_text(own)
            return Response(body, content_type=EXPORT_CONTENT_TYPE, headers={
                "Content-Disposition": 'attachment; filename="my-responses.csv"'})
        response = jsonify(reports.json_document(own))
        response.headers["Content-Disposition"] = 'attachment; filename="my-responses.json"'
        return response
    finally:
        cache.delete(lock_key)


@public_demo.get("/api/v1/public-demo/my-responses.csv")
@login_required
@limiter.shared_limit(reports.download_rate_limit, scope="public_demo_download")
def download_csv():
    """The caller's own submissions and report fields as CSV."""
    return _download("csv")


@public_demo.get("/api/v1/public-demo/my-responses.json")
@login_required
@limiter.shared_limit(reports.download_rate_limit, scope="public_demo_download")
def download_json():
    """The caller's own submissions and report fields as JSON."""
    return _download("json")


@public_demo.get("/public-demo/dashboard")
@limiter.limit("60 per minute")
def dashboard_page():
    """Public aggregate dashboard (no sign-in)."""
    if not demo.enabled():
        abort(404)
    return render_template("public_demo/dashboard.html", data=dashboard_service.dashboard())


@public_demo.get("/api/v1/public-demo/dashboard.json")
@limiter.limit("60 per minute")
def dashboard_json():
    """The dashboard figures as JSON (no sign-in)."""
    if not demo.enabled():
        abort(404)
    return jsonify(dashboard_service.dashboard())
