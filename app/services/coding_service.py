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


from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from app.models import VaSubmissions


def render_va_coding_page(submission, va_action: str, va_actiontype: str, back_dashboard_role: str):
    """Render va_coding.html for a VA form session entry point."""
    from flask import render_template
    from app.utils import va_get_form_type_code_for_form
    from app.services.category_rendering_service import get_category_rendering_service, get_visible_category_codes
    from app.services.coder_workflow_service import is_upstream_recode

    form_type_code = va_get_form_type_code_for_form(submission.va_form_id)
    category_service = get_category_rendering_service()
    visible_codes = get_visible_category_codes(submission.va_data, submission.va_form_id)
    category_nav = category_service.get_category_nav(form_type_code, va_action, visible_codes)
    default_category_code = category_service.get_default_category_code(form_type_code, va_action, visible_codes)
    return render_template(
        "va_frontpages/va_coding.html",
        va_sid=submission.va_sid,
        va_action=va_action,
        va_actiontype=va_actiontype,
        catlist=visible_codes,
        category_nav=category_nav,
        default_category_code=default_category_code,
        catcount=submission.va_catcount,
        form_type_code=form_type_code,
        va_uniqueid=submission.va_uniqueid_masked,
        va_age=submission.va_deceased_age,
        va_gender=submission.va_deceased_gender,
        back_dashboard_role=back_dashboard_role,
        is_upstream_recode=is_upstream_recode(submission.va_sid),
    )
