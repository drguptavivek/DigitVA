"""The project's ODK XLSForm download (digitva-aek).

Thin HTTP layer over ``app.services.xlsform_service``; every rule lives there.
Extends the ``admin`` blueprint like ``app/routes/admin_organization.py``.
Policy: docs/policy/va-form-project-configuration.md, "The ODK form is a
project output".
"""
import io
import logging

from flask import jsonify, request, send_file
from flask_login import current_user

from app import db
from app.decorators import role_required
from app.models import VaProjectMaster
from app.routes.admin import _current_user_can_manage_project, _json_error, admin
from app.services import xlsform_service

log = logging.getLogger(__name__)

XLSX_MIMETYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@admin.get("/api/projects/<project_id>/odk-xlsform.xlsx")
@role_required("admin", "project_pi")
def admin_project_odk_xlsform(project_id):
    """Download the project's ODK form: WHO VA 2022 with exactly the project's
    enabled extensions and approved, active languages.

    Admins and the PI of this project only. ``?form_id=`` chooses among the
    project's mapped ODK forms when it has several (one per site); the
    ``form_id`` itself is never taken from the request, only matched against
    the mappings. ``version`` is a fresh UTC stamp on every download.
    """
    if not _current_user_can_manage_project(project_id):
        return _json_error("You do not have access to that project.", 403)
    project = db.session.get(VaProjectMaster, project_id)
    if project is None:
        return _json_error("Project not found.", 404)
    try:
        form, data = xlsform_service.build_project_xlsform(
            project, form_id=request.args.get("form_id")
        )
    except xlsform_service.XlsFormError as exc:
        body = {"error": str(exc)}
        if exc.forms:
            body["forms"] = exc.forms
        return jsonify(body), exc.status_code
    log.info(
        "odk xlsform download | project=%s | by=%s | form_id=%s | version=%s | extensions=%s",
        project_id, getattr(current_user, "user_id", None), form.form_id, form.version,
        ",".join(form.extensions),
    )
    response = send_file(
        io.BytesIO(data), mimetype=XLSX_MIMETYPE, as_attachment=True, download_name=form.filename
    )
    response.headers["Cache-Control"] = "no-store"
    return response
