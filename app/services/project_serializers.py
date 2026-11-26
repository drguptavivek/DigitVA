"""Projects and project-site mappings as the admin and data-manager APIs
serve them.

Moved out of ``app.routes.admin`` so ``app.routes.data_management`` shares
them without importing the admin module's privates (digitva-r8nh.13).
"""

import sqlalchemy as sa

from app import db
from app.services import collection_gate


def _form_type_codes_by_id(form_type_ids):
    """``{form_type_id: form_type_code}`` for the ids given, in one query.

    Batched so serializing a list of projects costs one lookup rather than one
    per project.
    """
    from app.models import MasFormTypes

    wanted = {ft_id for ft_id in form_type_ids if ft_id is not None}
    if not wanted:
        return {}
    rows = db.session.execute(
        sa.select(MasFormTypes.form_type_id, MasFormTypes.form_type_code).where(
            MasFormTypes.form_type_id.in_(wanted)
        )
    ).all()
    return {row.form_type_id: row.form_type_code for row in rows}


def _serialize_projects(projects):
    """Serialize a list of projects, resolving every web form type code once."""
    projects = list(projects)
    codes = _form_type_codes_by_id(
        [project.web_intake_form_type_id for project in projects]
    )
    return [_serialize_project(project, form_type_codes=codes) for project in projects]


def _serialize_project(project, form_type_codes=None):
    """One project as the admin API serves it.

    ``form_type_codes`` is the prefetched ``{form_type_id: code}`` map
    ``_serialize_projects`` builds; a single-project caller may omit it and
    pay one lookup.
    """
    if form_type_codes is None:
        form_type_codes = _form_type_codes_by_id([project.web_intake_form_type_id])
    return {
        "project_id": project.project_id,
        "project_code": project.project_code,
        "project_name": project.project_name,
        "project_nickname": project.project_nickname,
        "status": project.project_status.value,
        "narrative_qa_enabled": project.narrative_qa_enabled,
        "social_autopsy_collect_enabled": project.social_autopsy_collect_enabled,
        "social_autopsy_enabled": project.social_autopsy_enabled,
        "reviewer_social_autopsy_enabled": project.reviewer_social_autopsy_enabled,
        "coding_intake_mode": project.coding_intake_mode,
        "icd_classification": project.icd_classification,
        "masked_cod_required": project.masked_cod_required,
        "cod_entry_mode": project.cod_entry_mode,
        "project_structure_mode": project.project_structure_mode,
        "coding_scope_level_id": str(project.coding_scope_level_id)
        if project.coding_scope_level_id
        else None,
        "above_scope_coding_mode": project.above_scope_coding_mode,
        "demo_training_enabled": project.demo_training_enabled,
        "demo_retention_minutes": project.demo_retention_minutes,
        "home_kpis_included": project.home_kpis_included,
        "recode_window_minutes": project.recode_window_minutes,
        "timezone": project.timezone,
        "project_target_completion_date": project.project_target_completion_date.isoformat()
        if project.project_target_completion_date
        else None,
        "project_country_iso3": project.project_country_iso3,
        "attachment_central_fetch_enabled": project.attachment_central_fetch_enabled,
        "web_intake_mode": project.web_intake_mode,
        "self_coding_enabled": project.self_coding_enabled,
        # Tier-2 web form options — docs/policy/va-web-form-options.md.
        "web_intake_default_locale": project.web_intake_default_locale,
        "web_intake_available_locales": project.web_intake_available_locales,
        "web_intake_narration_languages": project.web_intake_narration_languages,
        "web_intake_show_guidance": project.web_intake_show_guidance,
        # The web questionnaire and its two extension settings — WP1 of
        # docs/planning/web-capture-project-configuration-plan.md.
        "web_intake_form_type_id": str(project.web_intake_form_type_id)
        if project.web_intake_form_type_id
        else None,
        "web_intake_form_type_code": form_type_codes.get(
            project.web_intake_form_type_id
        ),
        "web_intake_intake_note": project.web_intake_intake_note,
        "web_intake_death_summary_enabled": project.web_intake_death_summary_enabled,
        "web_intake_medical_records_enabled": project.web_intake_medical_records_enabled,
        "web_intake_equity_enabled": project.web_intake_equity_enabled,
    }


def _serialize_project_site(row):
    return {
        "project_site_id": str(row.project_site_id),
        "project_id": row.project_id,
        "site_id": row.site_id,
        "project_name": row.project_name,
        "site_name": row.site_name,
        "status": row.project_site_status.value,
        "coding_enabled": row.coding_enabled,
        "coding_start_date": row.coding_start_date.isoformat() if row.coding_start_date else None,
        "coding_end_date": row.coding_end_date.isoformat() if row.coding_end_date else None,
        "daily_coder_limit": row.daily_coder_limit,
        **collection_gate.serialize_settings(row),
    }
