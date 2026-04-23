"""Legacy data-management endpoints that proxy to the API blueprint."""

from app.authz.access import action_authorized
from app.authz.resources import form_from_kwarg, submission_from_kwarg
from app.routes.api.data_management.analytics import run_project_site_submissions
from app.routes.api.data_management.sync import (
    run_sync_form,
    run_sync_preview,
    run_sync_submission,
)

from .base import data_management


@data_management.post("/api/sync/preview")
@action_authorized("dm_sync_preview")
def legacy_sync_preview():
    return run_sync_preview()


@data_management.get("/api/project-site-submissions")
@action_authorized("dm_project_site_submissions_view")
def legacy_project_site_submissions():
    return run_project_site_submissions()


@data_management.post("/api/forms/<form_id>/sync")
@action_authorized("dm_form_sync", resource_resolver=form_from_kwarg("form_id"))
def legacy_sync_form(form_id):
    return run_sync_form(form_id=form_id)


@data_management.post("/api/submissions/<va_sid>/sync")
@action_authorized("dm_submission_sync", resource_resolver=submission_from_kwarg("va_sid"))
def legacy_sync_submission(va_sid):
    return run_sync_submission(va_sid=va_sid)
