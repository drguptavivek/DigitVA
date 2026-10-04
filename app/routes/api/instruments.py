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
"""

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from app import db, limiter
from app.models import VaProjectMaster, VaStatuses
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
