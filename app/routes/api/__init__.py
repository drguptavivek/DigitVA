"""Versioned API package — all JSON endpoints live under /api/v1/."""

from flask import Blueprint

api_v1 = Blueprint("api_v1", __name__)

from app.routes.api import (  # noqa: E402, F401
    analytics,
    app_release,
    area,
    attachments,
    auth,
    bundles,
    cases,
    cod_buckets,
    coding,
    coding_search_demo,
    consent_settings,
    data_management,
    doris_clinical,
    help_contextual,
    icd10,
    icd11,
    identifier_types,
    instruments,
    intake,
    intake_consent,
    me,
    nqa,
    organization,
    people_roles,
    profile,
    reviewing,
    so,
    station_config,
    training,
    translation_suggestions,
    ui_strings,
    users,
    va_case,
    va_definitions,
    workflow,
)

# DM KPI analytics sub-blueprints
from app.routes.api.dm_kpi import (  # noqa: E402, F401
    dm_kpi_burndown,
    dm_kpi_coders,
    dm_kpi_critical_path,
    dm_kpi_exclusions,
    dm_kpi_grid,
    dm_kpi_language,
    dm_kpi_outcomes,
    dm_kpi_pipeline,
    dm_kpi_sync,
    dm_kpi_workflow,
)
from app.routes.api.dm_kpi.dm_kpi_scope import bp as dm_kpi_cache_bp  # noqa: E402, F401

api_v1.register_blueprint(analytics.bp, url_prefix="/analytics")
api_v1.register_blueprint(app_release.bp, url_prefix="/app")
api_v1.register_blueprint(area.bp, url_prefix="/area")
api_v1.register_blueprint(attachments.bp, url_prefix="/attachments")
api_v1.register_blueprint(auth.bp, url_prefix="/auth")
api_v1.register_blueprint(cases.bp, url_prefix="/cases")
api_v1.register_blueprint(cod_buckets.bp, url_prefix="/cod-buckets")
api_v1.register_blueprint(coding.bp, url_prefix="/coding")
api_v1.register_blueprint(coding_search_demo.bp, url_prefix="/coding-search-demo")
api_v1.register_blueprint(data_management.bp, url_prefix="/data-management")
api_v1.register_blueprint(doris_clinical.bp, url_prefix="/doris-clinical")
api_v1.register_blueprint(help_contextual.bp, url_prefix="/help")
api_v1.register_blueprint(icd10.bp, url_prefix="/icd10")
api_v1.register_blueprint(icd11.bp, url_prefix="/icd11")
api_v1.register_blueprint(instruments.bp, url_prefix="/instruments")
api_v1.register_blueprint(intake.bp, url_prefix="/intake")
api_v1.register_blueprint(intake_consent.bp, url_prefix="/intake")
api_v1.register_blueprint(me.bp, url_prefix="/me")
api_v1.register_blueprint(nqa.bp, url_prefix="/va")
api_v1.register_blueprint(organization.bp, url_prefix="/organization")
api_v1.register_blueprint(identifier_types.bp, url_prefix="/projects")
api_v1.register_blueprint(consent_settings.bp, url_prefix="/projects")
api_v1.register_blueprint(people_roles.bp, url_prefix="/projects")
api_v1.register_blueprint(profile.bp, url_prefix="/profile")
api_v1.register_blueprint(reviewing.bp, url_prefix="/reviewing")
api_v1.register_blueprint(so.bp, url_prefix="/va")
api_v1.register_blueprint(station_config.bp)
api_v1.register_blueprint(bundles.bp)
api_v1.register_blueprint(training.bp, url_prefix="/training")
api_v1.register_blueprint(translation_suggestions.bp, url_prefix="/translations")
api_v1.register_blueprint(ui_strings.bp, url_prefix="/ui-strings")
api_v1.register_blueprint(users.bp, url_prefix="/users")
api_v1.register_blueprint(va_case.bp, url_prefix="/va")
api_v1.register_blueprint(va_definitions.bp, url_prefix="/va-definitions")
api_v1.register_blueprint(workflow.bp, url_prefix="/workflow")

# DM KPI dashboard endpoints
api_v1.register_blueprint(dm_kpi_grid.bp, url_prefix="/analytics/dm-kpi/grid")
api_v1.register_blueprint(dm_kpi_sync.bp, url_prefix="/analytics/dm-kpi/sync")
api_v1.register_blueprint(dm_kpi_language.bp, url_prefix="/analytics/dm-kpi/language")
api_v1.register_blueprint(dm_kpi_exclusions.bp, url_prefix="/analytics/dm-kpi/exclusions")
api_v1.register_blueprint(dm_kpi_coders.bp, url_prefix="/analytics/dm-kpi/coders")
api_v1.register_blueprint(dm_kpi_pipeline.bp, url_prefix="/analytics/dm-kpi/pipeline")
api_v1.register_blueprint(dm_kpi_burndown.bp, url_prefix="/analytics/dm-kpi/burndown")
api_v1.register_blueprint(dm_kpi_workflow.bp, url_prefix="/analytics/dm-kpi/workflow")
api_v1.register_blueprint(dm_kpi_outcomes.bp, url_prefix="/analytics/dm-kpi/outcomes")
api_v1.register_blueprint(dm_kpi_critical_path.bp, url_prefix="/analytics/dm-kpi/critical-path")
api_v1.register_blueprint(dm_kpi_cache_bp, url_prefix="/analytics/dm-kpi")
