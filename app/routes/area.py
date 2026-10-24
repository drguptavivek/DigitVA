"""Area dashboard page: a shell the JS fills from /api/v1/area/*.

``login_required``, not a role list: any grant of any role opens an area, and
a user with no grant sees an empty page, not an error
(docs/policy/area-dashboard.md).
"""

from urllib.parse import urlencode

from flask import Blueprint, redirect, render_template, request
from flask_login import login_required

area = Blueprint("area", __name__)


#: Query names shared with /api/v1/area/* and the Expo Statistics route.
_CARRIED = ("project", "unit", "site", "period")
_MAX_CARRIED_LENGTH = 64


@area.get("/")
@login_required
def dashboard():
    """With the Expo export deployed the dashboard is the app's Statistics
    screen: redirect there, carrying the selection. The values are only
    re-encoded into an internal URL (the app validates them); the page below
    is the fallback for a server-only deployment."""
    from app.routes.expo_client import export_ready

    if export_ready():
        carried = {
            name: request.args[name]
            for name in _CARRIED
            if request.args.get(name) and len(request.args[name]) <= _MAX_CARRIED_LENGTH
        }
        query = f"?{urlencode(carried)}" if carried else ""
        return redirect(f"/app/statistics{query}")
    return render_template("va_frontpages/va_area_dashboard.html")
