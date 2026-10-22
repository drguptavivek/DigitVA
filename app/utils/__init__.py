"""Lazy barrel for the helpers in app.utils.

Importing a helper submodule (e.g. app.utils.pii_crypto) must not pull in
every helper's heavy dependencies (pandas, pyodk) at process startup, so the
re-exported names below resolve on first access (PEP 562) instead of eagerly.
"""

import importlib

_EXPORTS = {
    "va_odk_clientsetup": "app.utils.va_odk.va_odk_01_clientsetup",
    "va_odk_submissionupdatedate": "app.utils.va_odk.va_odk_03_submissionupdatedate",
    "va_odk_delta_count": "app.utils.va_odk.va_odk_05_deltacheck",
    "va_odk_fetch_instance_ids": "app.utils.va_odk.va_odk_06_fetchsubmissions",
    "va_odk_fetch_submissions": "app.utils.va_odk.va_odk_06_fetchsubmissions",
    "va_odk_fetch_submissions_by_ids": "app.utils.va_odk.va_odk_06_fetchsubmissions",
    "va_odk_sync_form_attachments": "app.utils.va_odk.va_odk_07_syncattachments",
    "va_odk_sync_submission_attachments": "app.utils.va_odk.va_odk_07_syncattachments",
    "va_preprocess_prepdata": "app.utils.va_preprocess.va_preprocess_01_prepdata",
    "va_preprocess_summcatenotification": "app.utils.va_preprocess.va_preprocess_02_summcatenotification",
    "va_preprocess_categoriestodisplay": "app.utils.va_preprocess.va_preprocess_03_categoriestodisplay",
    "VA_SMARTVA_ICDS": "app.utils.va_smartva.va_smartva_01_icdcodes",
    "va_smartva_prepdata": "app.utils.va_smartva.va_smartva_02_prepdata",
    "va_smartva_runsmartva": "app.utils.va_smartva.va_smartva_03_runsmartva",
    "va_smartva_formatsmartvaresult": "app.utils.va_smartva.va_smartva_04_formatsmartvaresult",
    "validate_form_id": "app.utils.va_form.va_form_01_variablevalidators",
    "validate_project_id": "app.utils.va_form.va_form_01_variablevalidators",
    "validate_site_id": "app.utils.va_form.va_form_01_variablevalidators",
    "validate_boolean_string": "app.utils.va_form.va_form_01_variablevalidators",
    "validate_odk_form": "app.utils.va_form.va_form_01_variablevalidators",
    "va_get_form_type_code_for_form": "app.utils.va_form.va_form_02_formtyperesolution",
    "smartva_allowed_countries": "app.utils.va_smartva.va_smartva_06_smartvacountries",
    "validate_smartva_country": "app.utils.va_form.va_form_01_variablevalidators",
    "validate_project_code": "app.utils.va_researchproject.va_researchproject_01_variablevalidators",
    "va_permission_abortwithflash": "app.utils.va_permission.va_permission_01_abortwithflash",
    "va_permission_ensureallocation": "app.utils.va_permission.va_permission_02_ensureallocation",
    "va_permission_ensureanyallocation": "app.utils.va_permission.va_permission_03_ensureanyallocation",
    "va_permission_ensurenoactiveallocation": "app.utils.va_permission.va_permission_04_ensurenoactiveallocation",
    "va_permission_validaterecodelimits": "app.utils.va_permission.va_permission_05_validaterecodelimits",
    "va_permission_ensureviewable": "app.utils.va_permission.va_permission_06_ensureviewable",
    "va_permission_ensurenotreviewed": "app.utils.va_permission.va_permission_07_ensurenotreviewed",
    "va_permission_ensurereviewed": "app.utils.va_permission.va_permission_08_ensurereviewed",
    "va_render_categoryneighbours": "app.utils.va_render.va_render_01_categoryneighbours",
    "va_mapping_fieldsitepi": "app.utils.va_mapping.va_mapping_01_fieldsitepi",
    "va_mapping_fieldcoder": "app.utils.va_mapping.va_mapping_02_fieldcoder",
    "va_mapping_choice": "app.utils.va_mapping.va_mapping_03_choice",
    "va_mapping_summary": "app.utils.va_mapping.va_mapping_04_summary",
    "va_mapping_summaryflip": "app.utils.va_mapping.va_mapping_05_summaryflip",
    "va_mapping_info": "app.utils.va_mapping.va_mapping_06_info",
    "va_mapping_flip": "app.utils.va_mapping.va_mapping_07_flip",
    "va_render_processcategorydata": "app.utils.va_render.va_render_06_processcategorydata",
    "va_render_serialisedates": "app.utils.va_render.va_render_07_serialisedates",
    "va_local_date": "app.utils.va_render.va_render_07_serialisedates",
    "va_user_timezone_name": "app.utils.va_render.va_render_07_serialisedates",
}

__all__ = [
    "va_odk_clientsetup",
    "va_odk_submissionupdatedate",
    "va_odk_delta_count",
    "va_odk_fetch_instance_ids",
    "va_odk_fetch_submissions",
    "va_odk_fetch_submissions_by_ids",
    "va_odk_sync_form_attachments",
    "va_odk_sync_submission_attachments",
    "va_preprocess_prepdata",
    "va_preprocess_summcatenotification",
    "va_preprocess_categoriestodisplay",
    "VA_SMARTVA_ICDS",
    "va_smartva_prepdata",
    "va_smartva_runsmartva",
    "va_smartva_formatsmartvaresult",
    "validate_form_id",
    "validate_project_id",
    "validate_site_id",
    "validate_boolean_string",
    "validate_odk_form",
    "va_get_form_type_code_for_form",
    "smartva_allowed_countries",
    "validate_smartva_country",
    "validate_project_code",
    "va_permission_abortwithflash",
    "va_permission_ensureallocation",
    "va_permission_ensureanyallocation",
    "va_permission_ensurenoactiveallocation",
    "va_permission_validaterecodelimits",
    "va_permission_ensureviewable",
    "va_permission_ensurenotreviewed",
    "va_permission_ensurereviewed",
    "va_render_categoryneighbours",
    "va_mapping_fieldsitepi",
    "va_mapping_fieldcoder",
    "va_mapping_choice",
    "va_mapping_summary",
    "va_mapping_summaryflip",
    "va_mapping_info",
    "va_mapping_flip",
    "va_render_processcategorydata",
    "va_render_serialisedates",
    "va_local_date",
    "va_user_timezone_name",
]


def __getattr__(name):
    module_path = _EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(module_path), name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(__all__ + list(globals()))
