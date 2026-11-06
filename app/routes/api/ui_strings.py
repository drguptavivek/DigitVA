"""UI language packs for the Expo app — /api/v1/ui-strings/ (digitva-s028)

``GET /`` lists the published UI languages; ``GET /<locale>`` returns one
published language's full pack: ``strings`` (the app's text, bundled with the
accepted corrections over it) and ``form`` (the WHO form's own labels). An
older client that laid ``strings`` over its bundle as corrections gets the same
result, since the full pack over the bundle equals the corrections over it.

Public by design: the sign-in screen is translated too, so a signed-out phone
must read it. The body is reference text with no personal data. Policy:
docs/policy/ui-strings.md.
"""

import hashlib
import json
import logging

from flask import Blueprint, Response, jsonify, request
from werkzeug.http import is_resource_modified

from app import limiter
from app.services.ui_string_service import (
    UiLanguageNotPublished,
    UiStringError,
    pack,
    published_languages,
)

bp = Blueprint("ui_strings_api", __name__)
log = logging.getLogger(__name__)

#: Seconds a shared cache may reuse a response before it asks again. The ETag
#: is the version, so a correction is seen at the next revalidation either way.
_PUBLIC_MAX_AGE = 60


def _conditional(payload: dict, etag: str):
    # An unchanged body answers 304 with no body, decided before the pack is
    # serialised (the check make_conditional itself uses).
    if request.method in ("GET", "HEAD") and not is_resource_modified(request.environ, etag=etag):
        response = Response(status=304)
    else:
        response = jsonify(payload)
    response.set_etag(etag)
    response.cache_control.public = True
    response.cache_control.max_age = _PUBLIC_MAX_AGE
    return response.make_conditional(request)


def _unavailable(exc: UiStringError):
    # The export is missing or unreadable (mid-deploy). A 503, never a short
    # list: the app keeps its stored list and packs on any non-200.
    log.warning("ui strings unavailable | %s", exc)
    return jsonify({"error": "UI strings are unavailable.", "code": "unavailable"}), 503


@bp.get("", strict_slashes=False)
@limiter.limit("120 per minute")
def ui_languages():
    """``{version, languages: [{locale, native_name, bcp47_tag, direction, version, reviewed}]}``."""
    try:
        languages = published_languages()
    except UiStringError as exc:
        return _unavailable(exc)
    version = hashlib.sha256(
        json.dumps(languages, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return _conditional({"version": version, "languages": languages}, version)


@bp.get("/<locale>")
@limiter.limit("120 per minute")
def ui_string_pack(locale: str):
    """One published language's pack; 404 for ``en`` and any unpublished locale, 503 on an export fault."""
    try:
        payload = pack((locale or "").strip())
    except UiLanguageNotPublished:
        return jsonify({"error": "Translation not found.", "code": "not_found"}), 404
    except UiStringError as exc:
        return _unavailable(exc)
    return _conditional(payload, payload["version"])
