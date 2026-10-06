"""Questionnaire translations page: a shell the page's JS fills from
/api/v1/translations/ (digitva-5op).

``login_required``, not a role list: any grant opens the page, and the API
decides per project what the caller may read, suggest or review.
"""

from flask import Blueprint, render_template
from flask_login import login_required

translation_suggestions_page = Blueprint("translation_suggestions_page", __name__)


@translation_suggestions_page.get("/questionnaire-translations")
@login_required
def page():
    return render_template("va_frontpages/va_translation_suggestions.html")
