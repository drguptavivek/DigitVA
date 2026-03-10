---
title: ODK Sync And Attachments
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-03-10
---

# ODK Sync And Attachments

## Summary

ODK sync is a batch process that:

1. loads active app forms from the database
2. uses each form's `odk_project_id` and `odk_form_id`
3. downloads `submissions.csv.zip` from ODK Central
4. extracts CSV and attachments to local disk
5. preprocesses submission rows
6. writes or updates `va_submissions`
7. refreshes SmartVA outputs

## Connection Model

**Connection Model (current)**:

- ODK connection details are stored in `mas_odk_connections` (DB) with encrypted credentials
- Each project is linked to a connection via `map_project_odk`
- `va_odk_clientsetup(project_id)` resolves the connection from DB first, falls back to legacy `odk_config.toml` if no DB mapping exists
- pyODK `Client` is built using an explicit `Session` (base_url, username, password) passed at construction; a shared stub config file (`odk_stub_config.toml`) satisfies the file-read requirement without storing credentials
- Each connection uses its own cache file (`odk_cache_<connection_id>.toml`) so concurrent calls to different ODK servers do not share or overwrite auth tokens
- The legacy `odk_config.toml` fallback remains for projects not yet migrated to DB-managed connections

## Sync Entry Point

Main service:

- [`va_data_sync_odkcentral()`](../../app/services/va_data_sync/va_data_sync_01_odkcentral.py)

Current behavior:

- loads all active `va_forms`
- loops over each form
- downloads and preprocesses data for each form

## How Downloads Work

For each active form, the app calls the ODK endpoint:

- `projects/{odk_project_id}/forms/{odk_form_id}/submissions.csv.zip`

This is done in:

- [`va_odk_downloadformdata()`](../../app/utils/va_odk/va_odk_02_downloadformdata.py)

The response zip is stored temporarily and extracted under:

- `data/<form_id>/`

Typical extracted contents:

- `<odk_form_id>.csv`
- `media/` attachment directory when attachments exist

## Attachment Handling

Attachments are not pulled one by one. They arrive as part of the exported zip.

Current local storage pattern:

- `data/<form_id>/media/<filename>`

Audio post-processing:

- `.amr` files in the media directory are converted to `.mp3`
- original `.amr` files are deleted after successful conversion

Media serving:

- media is served later through the Flask route in [`va_api.py`](../../app/routes/va_api.py)
- access is checked against the current user's form access

## Submission Preprocessing

The extracted CSV is processed in:

- [`va_preprocess_prepdata()`](../../app/utils/va_preprocess/va_preprocess_01_prepdata.py)

Current normalization steps include:

- replace pandas null-like values with Python `None`
- add `form_def = <app form_id>` if missing
- add `sid = <ODK KEY>-<form_id.lower()>` if missing
- add `updatedAt` using an additional ODK API call
- derive `unique_id2` when possible

This means `va_submissions` is not a raw mirror of ODK rows. It is a managed application table populated from normalized ODK data.

## Update Detection

The app fetches `__system/updatedAt` from ODK using:

- [`va_odk_submissionupdatedate()`](../../app/utils/va_odk/va_odk_03_submissionupdatedate.py)

During sync:

- if a `va_sid` already exists and `updatedAt` changed, the submission row is updated
- if a `va_sid` does not exist and consent is `yes`, a new row is inserted

## Derived Data Added During Sync

After basic preprocessing, the app computes:

- `va_summary`
- `va_catcount`
- `va_category_list`

These values are derived from mapping-driven preprocessing and are used later in UI rendering and workflow logic.

## SmartVA During Sync

The same sync run also:

- prepares SmartVA input
- runs SmartVA
- formats SmartVA output
- stores SmartVA results tied to the submission

## Important Current-State Behavior

If an ODK submission changes and sync updates the corresponding `va_submissions` row, the app deactivates related local workflow artifacts such as:

- active allocations
- coder review records
- initial assessments
- final assessments
- reviewer reviews
- user notes

This means ODK is treated as the source of truth for the submission content.

## Mapping Spreadsheets

Current mapping spreadsheets under `resource/mapping`:

- `mapping_labels.xlsx`
- `mapping_choices.xlsx`
- `icdcodes.xlsx`

Current usage:

- `mapping_labels.xlsx` and `mapping_choices.xlsx` feed mapping generation used by preprocessing and rendering
- `icdcodes.xlsx` is used to populate ICD lookup data, not to perform the ODK sync itself
