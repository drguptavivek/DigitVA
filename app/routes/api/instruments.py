"""Instrument translation delivery — /api/v1/instruments/

The one delivery contract for every frontend: the browser VA form today, the
native app later. A client caches a locale by its ``version``, revalidates with
``If-None-Match`` (or against ``translation_versions`` in the project's
form-options payload) whenever it loads a form, and re-fetches only when the
version moved — so an administrator's edit reaches interviewers on their next
form without a rebuild or a redeploy.

Read-only and signed-in only. A locale that is not active is not served: an
administrator activates a language when its coverage passes the threshold, and
until then the form must not be switched into a half-translated questionnaire.
Policy: docs/policy/va-web-form-options.md.
"""

from flask import Blueprint, jsonify, request
from flask_login import login_required

from app import limiter
from app.services.instrument_translation_service import (
    BASE_LOCALE,
    InstrumentTranslationError,
    export_translations,
    get_locale,
)

bp = Blueprint("instruments_api", __name__)


@bp.get("/<instrument_code>/translations/<locale>")
@login_required
@limiter.limit("120 per minute")
def instrument_translations(instrument_code: str, locale: str):
    """One locale's strings for one standard instrument.

    404 for an unknown instrument, an unknown locale and an inactive one
    alike: whether a language exists but is being worked on is not something
    this endpoint's callers need to tell apart.
    """
    code = (instrument_code or "").strip().upper()
    locale = (locale or "").strip()

    if locale != BASE_LOCALE:
        row = get_locale(code, locale)
        if row is None or not row.is_active:
            return jsonify({"error": "Translation not found."}), 404

    try:
        payload = export_translations(code, locale)
    except InstrumentTranslationError:
        return jsonify({"error": "Translation not found."}), 404

    # Weak ETag: the body is regenerated per request, so byte equality is not
    # promised — semantic equality at this version is.
    etag = f"{code}-{locale}-{payload['version']}"
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
