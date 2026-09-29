"""Area dashboard page: a shell the JS fills from /api/v1/area/*.

``login_required``, not a role list: any grant of any role opens an area, and
a user with no grant sees an empty page, not an error
(docs/policy/area-dashboard.md).
"""

from flask import Blueprint, render_template
from flask_login import login_required

area = Blueprint("area", __name__)


@area.get("/")
@login_required
def dashboard():
    return render_template("va_frontpages/va_area_dashboard.html")
