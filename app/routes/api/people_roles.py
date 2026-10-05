"""People and roles JSON and CSV — /api/v1/projects/<project_id>/people-roles.

Read-only GETs (no CSRF surface). Any user with a live grant in the project
may open it; what they get is narrowed by ``people_roles_service`` (audience,
identity tier, audit columns). A project the caller has no grant in, or a
closed one, is a 404 whether it exists or not. Policy:
docs/policy/people-and-roles-page.md.
"""

import csv
import io
import logging

from flask import Blueprint, Response, jsonify, request
from flask_login import current_user, login_required

from app import limiter
from app.routes.api.request_helpers import error as api_error
from app.services import people_roles_service as service

bp = Blueprint("people_roles_api", __name__)
log = logging.getLogger(__name__)


@bp.get("/<project_id>/people-roles")
@login_required
@limiter.limit("120 per minute")
def people_roles(project_id: str):
    """Query: ``level``, ``unit``, ``cadre``, ``capability``, ``status``
    (active | deactivated | all), ``q``, ``mode`` (granted_here |
    can_act_here), ``limit`` (clamped to 500), ``offset``."""
    try:
        result = service.people_roles(current_user, project_id, request.args)
    except service.PeopleRolesError as exc:
        return api_error(str(exc), status_code=exc.status)
    response = jsonify(result)
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.get("/<project_id>/people-roles.csv")
@login_required
@limiter.limit("20 per minute")
def people_roles_csv(project_id: str):
    """The same filters, service and redaction as the JSON, unpaged. Computed
    in the view body (authz decides before the first byte); only the
    serialisation streams."""
    try:
        result = service.people_roles(current_user, project_id, request.args, paged=False)
    except service.PeopleRolesError as exc:
        return api_error(str(exc), status_code=exc.status)
    log.info("people-roles csv project=%s rows=%d", result["project_id"], result["total"])

    def stream():
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        for line in service.csv_table(result):
            writer.writerow(line)
            yield buffer.getvalue()
            buffer.seek(0)
            buffer.truncate(0)

    headers = {
        "Content-Disposition": f'attachment; filename="people-roles-{result["project_id"]}.csv"',
        "Cache-Control": "no-store",
    }
    if result["truncated"]:
        # The grant read hit its cap: the file is incomplete, say so.
        headers["X-Truncated"] = "true"
    return Response(stream(), mimetype="text/csv", headers=headers)
