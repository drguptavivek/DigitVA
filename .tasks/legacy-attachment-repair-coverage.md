Status: pending
Priority: medium
Created: 2026-04-18
Goal: Treat legacy media attachment rows with `storage_name IS NULL` as attachment-incomplete in admin repair coverage and repair flows.
Context: The admin backfill coverage query currently counts attachment completeness by row count only. Legacy non-`audit.csv` media rows can therefore look complete even when they are not renderable until a `storage_name` is populated.
References:
- app/tasks/sync_tasks.py
- app/routes/admin.py
- app/utils/va_odk/va_odk_07_syncattachments.py
- app/utils/va_render/va_render_06_processcategorydata.py
Expected Scope: Adjust completeness checks and attachment repair logic so legacy media rows are surfaced and self-healed without relying on a one-time migration.
