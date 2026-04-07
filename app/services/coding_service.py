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


def _count_attachments_per_category(form_type_code: str, payload_data: dict, va_sid: str) -> dict[str, int]:
    """Count non-empty attachment fields per category for media_gallery subcategories.

    Returns {category_code: count} for categories whose render_mode is 'attachments',
    counting only fields that belong to subcategories with render_mode 'media_gallery'.

    Result is cached in Redis for 30 min (payload rarely changes).
    Reuses the cached field mapping service — no extra DB queries on cache hit.
    """
    from app import cache as flask_cache

    cache_key = f"attachment_counts:{va_sid}"
    cached = flask_cache.get(cache_key)
    if cached is not None:
        return cached

    from app.services.field_mapping_service import get_mapping_service

    _mapping_svc = get_mapping_service()
    fieldsitepi = _mapping_svc.get_fieldsitepi(form_type_code)

    # Build {category_code: [field_ids]} for media_gallery subcategories
    counts: dict[str, int] = {}
    for cat_code, subcats in fieldsitepi.items():
        render_modes = _mapping_svc.get_subcategory_render_modes(form_type_code, cat_code)
        attachment_fields = [
            field_id
            for sub_code, mode in render_modes.items()
            if mode == "media_gallery"
            for field_id in subcats.get(sub_code, {})
        ]
        if attachment_fields:
            count = sum(1 for f in attachment_fields if payload_data.get(f))
            if count >= 1:
                counts[cat_code] = count

    flask_cache.set(cache_key, counts, timeout=1800)
    return counts


def render_va_coding_page(submission, va_action: str, va_actiontype: str, back_dashboard_role: str):
    """Render va_coding.html for a VA form session entry point."""
    from flask import render_template, url_for
    from app.utils import va_get_form_type_code_for_form
    from app.services.category_rendering_service import get_category_rendering_service, get_visible_category_codes
    from app.services.coder_workflow_service import is_upstream_recode
    from app.services.submission_payload_version_service import get_active_payload_version
    from app.services.workflow.upstream_changes import get_latest_pending_upstream_change

    form_type_code = va_get_form_type_code_for_form(submission.va_form_id)
    category_service = get_category_rendering_service()
    active_version = get_active_payload_version(submission.va_sid)
    payload_data = active_version.payload_data if active_version else {}
    visible_codes = get_visible_category_codes(payload_data, submission.va_form_id)
    category_nav = category_service.get_category_nav(form_type_code, va_action, visible_codes)
    default_category_code = category_service.get_default_category_code(form_type_code, va_action, visible_codes)
    attachment_counts = _count_attachments_per_category(form_type_code, payload_data, submission.va_sid)
    has_pending_upstream_change = (
        back_dashboard_role == "data_manager"
        and get_latest_pending_upstream_change(submission.va_sid) is not None
    )
    return render_template(
        "va_frontpages/va_coding.html",
        va_sid=submission.va_sid,
        va_action=va_action,
        va_actiontype=va_actiontype,
        catlist=visible_codes,
        category_nav=category_nav,
        default_category_code=default_category_code,
        catcount=submission.va_catcount,
        attachment_counts=attachment_counts,
        form_type_code=form_type_code,
        va_uniqueid=submission.va_uniqueid_masked,
        va_age=submission.va_deceased_age,
        va_gender=submission.va_deceased_gender,
        back_dashboard_role=back_dashboard_role,
        is_upstream_recode=is_upstream_recode(submission.va_sid),
        has_pending_upstream_change=has_pending_upstream_change,
        upstream_change_details_url=(
            url_for(
                "api_v1.data_management_api.upstream_change_details",
                va_sid=submission.va_sid,
            )
            if has_pending_upstream_change
            else None
        ),
    )
