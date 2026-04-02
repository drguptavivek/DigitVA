# Handoff

## Status

This checkpoint includes local work for:

- sync pipeline refactor to `thin upsert -> enrich -> attachments -> SmartVA`
- per-form sync progress logging
- `attachment_sync_pending` workflow gating and sync-run attachment progress tracking
- admin project-form UI for SmartVA settings
- SmartVA HIV/malaria runtime override from ODK payload values
- admin-managed user coding languages
- enrich/category-generation fix for the Celery `ResourceClosedError`

It does **not** yet include the new admin sync-dashboard backfill status card/API requested last.

## Verified

- `docker compose exec minerva_app_service uv run python -m pytest tests/test_admin_api.py -k 'admin_can_manage_users or odk_site_mappings or attachment_cache_backfill or sync_status' -q`
  - `5 passed, 18 deselected`
- `docker compose exec minerva_app_service uv run python -m py_compile app/routes/admin.py app/tasks/sync_tasks.py app/services/va_data_sync/va_data_sync_01_odkcentral.py app/services/smartva_service.py app/utils/va_smartva/va_smartva_02_prepdata.py app/utils/va_smartva/va_smartva_03_runsmartva.py app/utils/va_preprocess/va_preprocess_03_categoriestodisplay.py app/utils/va_form/va_form_02_formtyperesolution.py`
  - passed

## Known Test Gap

- `docker compose exec minerva_app_service uv run python -m pytest tests/services/test_submission_workflow_service.py -k 'attachment_sync_pending or mark_attachment_sync_completed' -q`
  - fails in `tests/base.py` setup with the known Postgres enum/type bootstrap problem:
    - `type "status_enum" does not exist`
  - this is a test harness issue, not a new assertion failure in the workflow change itself

## Next Recommended Step

Implement the requested admin sync-dashboard backfill card/API:

1. add a project/site/form-wise status API for:
   - local data rows
   - metadata-enriched rows
   - attachment-complete rows
2. add a dashboard card/table in `app/templates/admin/panels/sync_dashboard.html`
3. add a scoped backfill trigger that:
   - enriches thin rows from ODK
   - downloads missing attachments from ODK
   - advances `attachment_sync_pending` rows into the normal SmartVA path

## Notes

- For the new dashboard backfill feature, attachment backfill should come from **ODK**, not just from the existing local attachment-cache rebuild tool.
- The existing `Backfill Attachment Cache` card should stay separate; it repairs cache rows from already-downloaded local files.
