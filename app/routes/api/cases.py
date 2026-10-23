"""The shared case list API: ``/api/v1/cases`` (docs/policy/case-list-views.md).

Read-only GETs for the Deaths, VA Interview, VA Code and Supervision presets,
either credential. Gated by ``login_required`` on purpose: any grant reaches
some cases, and a caller with none gets an empty list (200), not a 403. Scope
and field visibility are decided per row in the service
(``app.services.case_list_service``); nothing here changes state, so there is
no CSRF surface. The supervision preset is empty under device credentials.
"""
from functools import wraps

from flask import Blueprint, Response, jsonify, request, stream_with_context
from flask_login import current_user, login_required

from app import cache, db, limiter
from app.decorators import role_required
from app.routes.api.request_helpers import browser_session_only, identifier_rate_limit, intake_error
from app.services import case_export_service as case_export
from app.services import case_list_service as case_list
from app.services import training_scope
from app.services.export_store_service import EXPORT_CONTENT_TYPE, UTF8_BOM
from app.services.web_intake_service import WebIntakeError

bp = Blueprint("cases_api", __name__)
EXPORT_LOCK_SECONDS = 1800


@bp.before_request
def _without_training():
    """The cases list, its filters and its CSV never hold the training project
    (docs/policy/training-demo-project.md, "Separation from real work")."""
    training_scope.use(training_scope.EXCLUDE)


@bp.after_request
def _no_store(response):
    # Case rows carry identifiers, errors included.
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.errorhandler(WebIntakeError)
def _bad_query(exc):
    db.session.rollback()
    return intake_error(exc)


@bp.get("")
@login_required
@limiter.limit("120 per minute")
@identifier_rate_limit(lambda: bool(request.args.get("identifier_number")), search=True)
def list_cases():
    """``{cases, counts, [tiles,] next_cursor}``; ``counts`` and ``tiles`` only
    without a ``cursor``. Query: ``preset``
    (``deaths`` default, ``interview``, ``coding``, ``supervision``),
    ``project_id``, ``site_id``, ``org_unit_id``, ``status`` (repeatable),
    ``state``, ``dod_from``, ``dod_to``, ``reported_from``, ``reported_to``,
    ``sex``, ``age_min``, ``age_max``, ``attention``, ``visit_note``, ``sort``, ``cursor``,
    ``limit``; registration numbers: ``identifier`` (``has`` or ``missing``, an
    active type of the case's project) with optional ``identifier_type`` (a type
    code), and ``identifier_number`` (an exact number, found only where the
    caller sees values; counted against the per-user
    ``IDENTIFIER_SEARCH_RATE_LIMIT`` budget, 429 past it)."""
    return jsonify(case_list.case_list_page(current_user._get_current_object(), request.args))


@bp.get("/filter-options")
@login_required
@limiter.limit("120 per minute")
def filter_options():
    """Projects, sites, units the caller's cases span."""
    return jsonify(case_list.filter_options(current_user._get_current_object()))


def _cookie_session_only(view):
    """Refuse a device bearer token (403 ``cookie_session_required``) before
    the role gate: an export is a browser action."""
    @wraps(view)
    def guarded(*args, **kwargs):
        return browser_session_only() or view(*args, **kwargs)
    return guarded


@bp.get("/export.csv")
@_cookie_session_only
@role_required("data_manager", "admin")  # authz: project_pi and site_pi hold the data_manager gate
@limiter.limit("10 per minute")
@identifier_rate_limit(lambda: bool(request.args.get("identifier_number")), search=True)
def export_cases_csv():
    """The list as a CSV download, same query and scope as ``GET /cases``
    (``cursor`` and ``limit`` are ignored; the stream pages by itself).
    Gate: ``data_manager`` or ``admin`` (``effective_roles``, so a project PI
    and an In-charge, who hold the data manager gate, export too, as for the
    data management CSVs). Registration-number columns only for the projects where the exporter sees
    values (admin, or a data_manager, project_pi or site_pi grant there), audited before the first byte (``case_export_service``);
    ``X-Identifier-Columns``: ``full`` (every row's project qualifies),
    ``partial`` (other rows leave those cells empty) or absent (no columns).
    413 ``export_too_large`` over ``EXPORT_MAX_ROWS``; 429 ``export_in_progress``
    while this user's previous export still streams; 500 ``export_unreadable``
    when an identifier cell cannot be decrypted (checked before the first
    byte, so no file and no audit row)."""
    user = current_user._get_current_object()
    # One running export per user; the TTL frees the slot if a worker dies.
    lock_key = f"cases-export:{user.user_id}"
    if not cache.add(lock_key, 1, timeout=EXPORT_LOCK_SECONDS):
        raise WebIntakeError("An export is already running; wait for it to finish.", 429, "export_in_progress")
    try:
        plan, _ = case_export.prepare(user, request.args)
    except Exception:
        cache.delete(lock_key)
        raise
    # X-Accel-Buffering: nginx must not buffer or spool the plaintext to disk
    # (deploy/ingress-routes.conf sets the same for this path).
    headers = {"Content-Disposition": 'attachment; filename="cases.csv"', "X-Accel-Buffering": "no"}
    if plan.identifier_columns:
        headers["X-Identifier-Columns"] = plan.identifier_columns

    def body():
        try:
            yield UTF8_BOM.encode("utf-8")
            yield from case_export.stream(user, plan)
        finally:
            cache.delete(lock_key)

    return Response(stream_with_context(body()), content_type=EXPORT_CONTENT_TYPE, headers=headers)
