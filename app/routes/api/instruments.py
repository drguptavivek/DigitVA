"""Instrument translation delivery — /api/v1/instruments/

The one delivery contract for every frontend: the browser VA form today, the
native app later. A client caches a locale by its ``version``, revalidates with
``If-None-Match`` (or against ``translation_versions`` in the project's
form-options payload) whenever it loads a form, and re-fetches only when the
version moved — so an administrator's edit reaches interviewers on their next
form without a rebuild or a redeploy.

Read-only and signed-in only. A locale is served when it is active or
``in_review`` (the form shows an ``in_review`` locale only with its English
beside it, decided 2026-09-21); a ``draft`` locale is not served. Activating
one is an explicit administrative action and is not gated on how much of it
is translated. A half-translated locale is safe to serve because an
untranslated string is absent from this payload rather than empty, so the form
falls back to English for that string alone.
Policy: docs/policy/va-web-form-options.md.

The same blueprint serves the composed form itself: ``/<code>/definition``
(one project's definition, ETag'd by its SHA-256) and ``/<code>/versions``
(every form version this server has served, newest first). Policy:
docs/policy/field-data-collection.md ("Form version", "Form definition from
the server").
"""

import logging

from flask import Blueprint, Response, jsonify, request
from flask_login import current_user, login_required

from app import db, limiter
from app.models import VaProjectMaster, VaStatuses
from app.services import served_form_service
from app.services.authz import reachable_unit_ids
from app.services.instrument_translation_service import (
    BASE_LOCALE,
    InstrumentTranslationError,
    export_translations,
    get_locale,
)
from app.services.org_grant_service import ROLES_ALLOWING_ORG_UNIT
from app.services.web_form_instruments import is_servable

bp = Blueprint("instruments_api", __name__)
log = logging.getLogger(__name__)

#: Bumped whenever export_translations' render-time rules change, so a cached
#: body (keyed on this ETag) is refetched even though the locale's own
#: ``version`` did not move.
_RENDER_RULES = "r1"


@bp.get("/<instrument_code>/translations/<locale>")
@login_required
@limiter.limit("120 per minute")
def instrument_translations(instrument_code: str, locale: str):
    """One locale's strings for one standard instrument.

    Served for an active or ``in_review`` locale. 404 for an unknown
    instrument, an unknown locale and a ``draft`` one alike: whether a
    language exists but is still a draft is not something this endpoint's
    callers need to tell apart.

    Optional ``?project_id=``: narrows to what that project serves (its
    default form type's instrument and its ``available_locales``), and needs
    a grant reaching the project, as ``/organization/<project>/form-options``
    does. Anything else is 404, a project the caller cannot reach 403. The
    offline app passes it; the browser form need not.
    """
    code = (instrument_code or "").strip().upper()
    locale = (locale or "").strip()
    project_id = (request.args.get("project_id") or "").strip().upper()
    if project_id:
        from app.routes.api.organization import served_instrument_locales

        reachable = reachable_unit_ids(current_user, project_id, ROLES_ALLOWING_ORG_UNIT)
        project = db.session.get(VaProjectMaster, project_id)
        if project is None or project.project_status != VaStatuses.active:
            return jsonify({"error": "Project not found.", "code": "not_found"}), 404
        if reachable is not None and not reachable:
            return jsonify({"error": "You do not have access to that project.", "code": "forbidden"}), 403
        served_code, served_locales = served_instrument_locales(project)
        if code != served_code or locale not in served_locales:
            return jsonify({"error": "Translation not found.", "code": "not_found"}), 404
    return translations_response(code, locale)


def translations_response(code: str, locale: str):
    """One locale's strings as a response with its weak ETag (304 when the
    client's copy is current); 404 when not servable. The caller decides
    access."""
    if locale != BASE_LOCALE:
        row = get_locale(code, locale)
        if row is None or not is_servable(row):
            return jsonify({"error": "Translation not found.", "code": "not_found"}), 404

    try:
        payload = export_translations(code, locale)
    except InstrumentTranslationError:
        return jsonify({"error": "Translation not found.", "code": "not_found"}), 404

    # Weak ETag: the body is regenerated per request, so byte equality is not
    # promised — semantic equality at this version is.
    etag = f"{code}-{locale}-{payload['version']}-{_RENDER_RULES}"
    if request.if_none_match.contains_weak(etag):
        response = jsonify({})
        response.status_code = 304
    else:
        response = jsonify(payload)
    response.set_etag(etag, weak=True)
    # Signed-in response, but the body is reference data with no personal
    # content: let a browser revalidate rather than re-download an unchanged
    # locale.
    response.cache_control.private = True
    response.cache_control.max_age = 0
    response.cache_control.must_revalidate = True
    return response


def _json_error(message: str, status: int, code: str):
    return jsonify({"error": message, "code": code}), status


@bp.get("/<instrument_code>/definition")
@login_required
@limiter.limit("120 per minute")
def instrument_definition(instrument_code: str):
    """One project's composed form definition (JSON).

    ``?project_id=`` is required and gated exactly as
    ``/organization/<project>/form-options`` is (404 unknown or inactive
    project, 403 no grant reaching it). 404 for an instrument without a
    composed definition or one the project does not use. The body is the
    composed definition minus the layers the project has not enabled, with
    top-level ``version`` and ``engineVersion``; its SHA-256 is the ETag
    (``"<sha256>"``) and the ``X-Definition-SHA256`` header, never part of the
    body. ``If-None-Match`` with that ETag gets a bodiless 304. ``Cache-Control:
    private, no-cache``: a client may keep the body but must revalidate.

    The body's top-level ``extensions`` lists the conditional extensions the
    slice contains: (``version``, ``extensions``) with the SHA-256 identifies
    it. To fetch an exact earlier slice (a draft filled on it, cache lost) pass
    both ``?version=<recorded version>&extensions=a,b`` (empty = none): 404
    ``version_unknown`` for a version this server never recorded, 422
    ``invalid_extensions`` for names outside that version's tags, 400 when only
    one of the two is given. The project check above is the only authorization;
    the project need not enable those extensions today. Same body shape,
    headers, gzip and 304 handling.
    """
    from app.routes.api.organization import form_options_project, project_instrument_and_extensions

    code = (instrument_code or "").strip().upper()
    project_id = (request.args.get("project_id") or "").strip().upper()
    if not project_id:
        return _json_error("project_id is required.", 400, "invalid_request")
    project, refusal = form_options_project(project_id)
    if refusal is not None:
        return refusal
    served_code, extensions = project_instrument_and_extensions(project)
    if code != served_form_service.INSTRUMENT_CODE or code != served_code:
        return _json_error("Definition not found.", 404, "not_found")
    version = (request.args.get("version") or "").strip()
    if bool(version) != ("extensions" in request.args):
        return _json_error("version and extensions are given together.", 400, "invalid_request")
    try:
        if version:
            requested = {name.strip() for name in request.args["extensions"].split(",") if name.strip()}
            served = served_form_service.historical_definition(version, requested)
        else:
            served = served_form_service.served_definition(extensions)
    except served_form_service.UnknownVersion:
        return _json_error("Form version not found.", 404, "version_unknown")
    except served_form_service.InvalidExtensions:
        return _json_error("Unknown extensions for that form version.", 422, "invalid_extensions")
    except served_form_service.ServedFormUnavailable:
        log.exception("instrument_definition: composed definition unavailable")
        return _json_error("The form definition is unavailable.", 503, "unavailable")
    served_form_service.record_served_version()

    # A strong ETag names one representation, so the gzipped body has its own
    # (``<sha256>.gz``); either one revalidates. The SHA-256 the app verifies
    # is always over the uncompressed JSON (X-Definition-SHA256).
    gzipped = "gzip" in request.accept_encodings
    etag = f"{served.sha256}.gz" if gzipped else served.sha256
    if request.if_none_match.contains(served.sha256) or request.if_none_match.contains(f"{served.sha256}.gz"):
        response = Response(status=304)
    else:
        response = Response(served.gzip_body if gzipped else served.body, mimetype="application/json")
        if gzipped:
            response.headers["Content-Encoding"] = "gzip"
    response.vary.add("Accept-Encoding")
    response.set_etag(etag)
    response.headers["X-Definition-SHA256"] = served.sha256
    response.cache_control.private = True
    response.cache_control.no_cache = True
    return response


@bp.get("/<instrument_code>/versions")
@login_required
@limiter.limit("120 per minute")
def instrument_versions(instrument_code: str):
    """Every composed form version this server has served, newest first:
    ``{"instrument_code", "current", "versions": [{"version", "activated_at"}]}``.
    ``current`` is the version the running code serves now (always in
    ``versions``: serving it records it)."""
    code = (instrument_code or "").strip().upper()
    if code != served_form_service.INSTRUMENT_CODE:
        return _json_error("Instrument not found.", 404, "not_found")
    try:
        current = served_form_service.composed_version()
    except served_form_service.ServedFormUnavailable:
        log.exception("instrument_versions: composed definition unavailable")
        return _json_error("The form definition is unavailable.", 503, "unavailable")
    served_form_service.record_served_version()
    return jsonify(
        {"instrument_code": code, "current": current, "versions": served_form_service.list_versions()}
    )
