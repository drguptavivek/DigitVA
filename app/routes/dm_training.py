"""Trainer report of the Training & demo project (TRN01), under /data-management/training.

Extends the ``data_management`` blueprint in place (like admin_training.py does
for ``admin``). Read-only GET pages and two CSV exports. The report holds the
answer key, so every route resolves the session through
``training_report_service.authorized_session``: an admin, or the session's own
active reviewer_data_manager, nobody else. Policy:
docs/policy/training-demo-project.md.
"""
from flask import Response, render_template
from flask_login import current_user

from app.decorators import role_required
from app.routes.data_management import data_management
from app.services import training_report_service as report_service
from app.services.training_demo_service import TrainingDemoError
from app.utils.va_permission.va_permission_01_abortwithflash import va_permission_abortwithflash


def _report(ref):
    try:
        return report_service.training_session_report(ref, current_user._get_current_object())
    except TrainingDemoError as exc:
        va_permission_abortwithflash(exc.message, 403 if exc.code == "report_forbidden" else 404)


def _csv(body: str, name: str) -> Response:
    return Response(body, mimetype="text/csv", headers={
        "Content-Disposition": f'attachment; filename="{name}"',
        "Cache-Control": "no-store",
    })


@data_management.get("/training")
@role_required("data_manager", "admin")
def training_sessions():
    """The training sessions the viewer may report on."""
    return render_template(
        "va_frontpages/va_training_sessions.html",
        sessions=report_service.sessions_for_viewer(current_user._get_current_object()),
    )


@data_management.get("/training/<ref>")
@role_required("data_manager", "admin")
def training_report(ref):
    return render_template("va_frontpages/va_training_report.html", report=_report(ref))


@data_management.get("/training/<ref>/coders.csv")
@role_required("data_manager", "admin")
def training_coders_csv(ref):
    report = _report(ref)
    return _csv(report_service.coders_csv(report), f"training_{report['session']['session_code']}_coders.csv")


@data_management.get("/training/<ref>/cases.csv")
@role_required("data_manager", "admin")
def training_cases_csv(ref):
    report = _report(ref)
    return _csv(report_service.cases_csv(report), f"training_{report['session']['session_code']}_cases.csv")
