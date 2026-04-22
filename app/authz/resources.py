from __future__ import annotations

import sqlalchemy as sa

from app import db
from app.authz.access import ResourceContext, ResourceResolutionError
from app.models import VaForms, VaProjectSites, VaSubmissions, VaUserAccessGrants
from app.models.va_submission_attachments import VaSubmissionAttachments


def submission_from_kwarg(param_name: str):
    def resolver(*_args, **kwargs):
        va_sid = kwargs.get(param_name)
        submission = db.session.get(VaSubmissions, va_sid)
        if submission is None:
            raise ResourceResolutionError("Submission not found.", status_code=404)
        row = db.session.execute(
            sa.select(VaForms.project_id, VaForms.site_id).where(
                VaForms.form_id == submission.va_form_id
            )
        ).first()
        if row is None:
            raise ResourceResolutionError("Submission scope could not be resolved.", status_code=404)
        return ResourceContext(
            resource_type="submission",
            resource_id=str(va_sid),
            project_id=row.project_id,
            site_id=row.site_id,
            form_id=submission.va_form_id,
            obj=submission,
        )

    return resolver


def form_from_kwarg(param_name: str):
    def resolver(*_args, **kwargs):
        form_id = kwargs.get(param_name)
        row = db.session.execute(
            sa.select(VaForms.form_id, VaForms.project_id, VaForms.site_id).where(
                VaForms.form_id == form_id
            )
        ).first()
        if row is None:
            raise ResourceResolutionError("Form not found.", status_code=404)
        return ResourceContext(
            resource_type="form",
            resource_id=row.form_id,
            project_id=row.project_id,
            site_id=row.site_id,
            form_id=row.form_id,
        )

    return resolver


def attachment_form_from_storage_name(param_name: str):
    def resolver(*_args, **kwargs):
        storage_name = kwargs.get(param_name)
        row = db.session.execute(
            sa.select(VaForms.form_id, VaForms.project_id, VaForms.site_id)
            .select_from(VaSubmissionAttachments)
            .join(VaSubmissions, VaSubmissions.va_sid == VaSubmissionAttachments.va_sid)
            .join(VaForms, VaForms.form_id == VaSubmissions.va_form_id)
            .where(VaSubmissionAttachments.storage_name == storage_name)
            .where(VaSubmissionAttachments.exists_on_odk == True)  # noqa: E712
        ).first()
        if row is None:
            raise ResourceResolutionError("Attachment not found.", status_code=404)
        return ResourceContext(
            resource_type="form",
            resource_id=row.form_id,
            project_id=row.project_id,
            site_id=row.site_id,
            form_id=row.form_id,
        )

    return resolver


def grant_from_kwarg(param_name: str):
    def resolver(*_args, **kwargs):
        grant_id = kwargs.get(param_name)
        grant = db.session.get(VaUserAccessGrants, grant_id)
        if grant is None:
            raise ResourceResolutionError("Grant not found.", status_code=404)
        project_id = grant.project_id
        site_id = None
        if grant.project_site_id is not None:
            ps = db.session.get(VaProjectSites, grant.project_site_id)
            if ps is not None:
                project_id = ps.project_id
                site_id = ps.site_id
        return ResourceContext(
            resource_type="grant",
            resource_id=str(grant_id),
            project_id=project_id,
            site_id=site_id,
            obj=grant,
        )

    return resolver


def user_from_kwarg(param_name: str):
    def resolver(*_args, **kwargs):
        user_id = kwargs.get(param_name)
        return ResourceContext(
            resource_type="user",
            resource_id=str(user_id),
        )

    return resolver
