"""Public privacy policy, contact us, and consent and data requests pages.

Policy: docs/policy/public-privacy-and-data-requests.md. GET only, no sign-in, no
form, so no CSRF surface. Organisation details come from config; unset values
render neutral wording, never a placeholder.
"""

from flask import Blueprint, current_app, render_template

public_pages = Blueprint("public_pages", __name__)

_DEFAULT_ORG = "the DigitVA programme team"


def _org():
    cfg = current_app.config
    return {
        "name": cfg.get("PUBLIC_ORG_NAME") or _DEFAULT_ORG,
        "email": cfg.get("PUBLIC_CONTACT_EMAIL") or "",
        "grievance_officer": cfg.get("PUBLIC_GRIEVANCE_OFFICER") or "",
        "address": cfg.get("PUBLIC_POSTAL_ADDRESS") or "",
    }


def _page(template):
    response = current_app.make_response(render_template(template, org=_org()))
    response.headers["Cache-Control"] = "public, max-age=300"
    return response


@public_pages.get("/privacy")
def privacy():
    return _page("va_frontpages/va_public_privacy.html")


@public_pages.get("/contact")
def contact():
    return _page("va_frontpages/va_public_contact.html")


@public_pages.get("/data-requests")
def data_requests():
    return _page("va_frontpages/va_public_data_requests.html")
