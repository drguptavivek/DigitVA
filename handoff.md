# Handoff

## Status

`main` already includes the recent sync/dashboard/data-manager work pushed in commit `bdb3d81`:

- `Sync` / `Force-resync` / `Backfill` separation
- targeted batch backfill for metadata, attachments, and SmartVA
- improved sync progress logging
- local-only backfill coverage card
- corrected pending-coding KPI and workflow donut behavior
- coded grid `Coded On` / `Coded By`
- new ODK Central edit URL shape in Data Manager

Current local work in progress adds a project-level toggle for the app-owned Social Autopsy analysis form:

- new `va_project_master.social_autopsy_enabled` flag
- admin project create/edit support for that flag
- coding UI renders the Social Autopsy analysis form only when the project flag is enabled
- Social Autopsy completion gating is skipped when the project flag is disabled
- Social Autopsy save API rejects writes when the project flag is disabled

This change preserves the existing mapped `social_autopsy` category fields. The toggle only controls the app-owned analysis form and its workflow requirements.

## Migration

The migration for the new project flag is now applied:

- migration revision: `aa12bb34cc56`
- `docker compose exec minerva_app_service uv run flask db current`
  - `aa12bb34cc56 (head)`

Note:

- the first attempt used a duplicate Alembic revision id and was corrected
- the live migration file is:
  - `migrations/versions/a1b2c3d4e5f6_add_social_autopsy_enabled_to_projects.py`
  - internal Alembic `revision` value is `aa12bb34cc56`

## Files Changed Locally

- `app/models/va_project_master.py`
- `app/routes/admin.py`
- `app/routes/va_form.py`
- `app/routes/api/so.py`
- `app/templates/admin/panels/projects.html`
- `app/templates/va_formcategory_partials/category_table_sections.html`
- `migrations/versions/a1b2c3d4e5f6_add_social_autopsy_enabled_to_projects.py`
- `tests/test_admin_api.py`
- `tests/test_category_table_sections_template.py`
- `tests/routes/test_social_autopsy_analysis.py`
- `docs/policy/social-autopsy-analysis.md`
- `docs/current-state/admin-and-setup.md`

## Verified

- `docker compose exec minerva_app_service uv run flask db heads`
  - `aa12bb34cc56 (head)`
- `docker compose exec minerva_app_service uv run flask db upgrade`
  - passed
- `docker compose exec minerva_app_service uv run flask db current`
  - `aa12bb34cc56 (head)`

## Still To Do

1. finish docs updates for the Social Autopsy toggle:
   - `docs/current-state/category-rendering-and-visibility.md`
   - likely `docs/current-state/data-model.md`
2. run focused verification for the new toggle:
   - admin project create/edit test
   - Social Autopsy API rejection test
   - category template gating test
3. commit and push the Social Autopsy project-level toggle work

## Implementation Notes

- Backward compatibility is preserved by defaulting `social_autopsy_enabled` to `true`.
- Runtime helper logic treats missing project rows as enabled to avoid surprising breakage on older data paths.
- The intent is:
  - mapped category presence still comes from form/category definitions
  - app-owned Social Autopsy analysis visibility comes from the project-level flag
