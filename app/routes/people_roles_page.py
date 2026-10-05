"""People & roles page: a shell the panel's JS fills from
/api/v1/projects/<project_id>/people-roles.

``login_required``, not a role list: any grant opens the page, and the API
decides per project what the caller may see (docs/policy/people-and-roles-page.md).
"""

from flask import Blueprint, render_template
from flask_login import login_required

people_roles_page = Blueprint("people_roles_page", __name__)


@people_roles_page.get("/people-roles")
@login_required
def page():
    return render_template("va_frontpages/va_people_roles.html")
