"""Coding service — shared helpers for VA coding routes.

Used by:
  app/routes/coding.py          (HTMX rendering routes)
  app/routes/api/va.py          (JSON API routes)
"""

import sqlalchemy as sa
from app import db
from app.models import VaSubmissions
from app.models.va_forms import VaForms
from app.models.va_project_master import VaProjectMaster


def get_project_for_submission(va_sid: str):
    """Return the VaProjectMaster for a submission, or None."""
    form_id = db.session.scalar(
        sa.select(VaSubmissions.va_form_id).where(VaSubmissions.va_sid == va_sid)
    )
    if not form_id:
        return None
    project_id = db.session.scalar(
        sa.select(VaForms.project_id).where(VaForms.form_id == form_id)
    )
    if not project_id:
        return None
    return db.session.get(VaProjectMaster, project_id)
