"""UI string corrections for the Expo app — /api/v1/ui-strings/

``GET /<locale>`` returns one locale's corrections as ``{version, strings}``.
The client keeps the bundled text and lays these over it; a locale with no
corrections returns an empty ``strings``.

Public by design: the sign-in screen is translated too, so a signed-out phone
must read it. The body is reference text with no personal data. Policy:
docs/policy/ui-strings.md.
"""

import logging

from flask import Blueprint, jsonify, request

from app import limiter
from app.services.ui_string_service import UiStringError, overrides

bp = Blueprint("ui_strings_api", __name__)
log = logging.getLogger(__name__)

#: Seconds a shared cache may reuse a locale before it asks again. The ETag is
#: the version, so a correction is seen at the next revalidation either way.
_PUBLIC_MAX_AGE = 60


@bp.get("/<locale>")
@limiter.limit("120 per minute")
def ui_string_overrides(locale: str):
    """One locale's corrections; 404 for ``en``, an unknown or unshipped locale."""
    try:
        payload = overrides((locale or "").strip())
    except UiStringError:
        return jsonify({"error": "Translation not found.", "code": "not_found"}), 404

    response = jsonify(payload)
    # The version is the ETag: an unchanged locale answers 304 with no body.
    response.set_etag(payload["version"])
    response.cache_control.public = True
    response.cache_control.max_age = _PUBLIC_MAX_AGE
    return response.make_conditional(request)
