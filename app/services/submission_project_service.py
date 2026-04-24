"""Shared project lookups for forms and submissions."""

import sqlalchemy as sa

from app import db
from app.models import VaSubmissions
from app.models.va_forms import VaForms
from app.models.va_project_master import VaProjectMaster


def get_project_for_form(form_id: str | None) -> VaProjectMaster | None:
    if not form_id:
        return None
    project_id = db.session.scalar(
        sa.select(VaForms.project_id).where(VaForms.form_id == form_id)
    )
    if not project_id:
        return None
    return db.session.get(VaProjectMaster, project_id)


def get_project_for_submission(va_sid: str | None) -> VaProjectMaster | None:
    if not va_sid:
        return None
    form_id = db.session.scalar(
        sa.select(VaSubmissions.va_form_id).where(VaSubmissions.va_sid == va_sid)
    )
    return get_project_for_form(form_id)
