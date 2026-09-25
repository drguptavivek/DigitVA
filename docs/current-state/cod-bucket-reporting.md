---
title: COD Bucket Reporting
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-09-25
---

# COD Bucket Reporting

DigitVA now supports versioned ICD-to-bucket reporting schemes for aggregating
coded submissions without mutating the submission's final ICD record.

Routes:

- page: `/data-management/cod-buckets`
- API:
  - `/api/v1/cod-buckets/schemes`
  - `/api/v1/cod-buckets/aggregates`
- admin editor:
  - `/admin/panels/cod-buckets`

## ICD-10 and ICD-11 deaths

Every death is bucketed through the rows of its own classification, decided
by the final COD's code shape (the ICD-10 and ICD-11 shapes do not overlap).
There is no crosswalk.

- ICD-10 deaths use the scheme's `icd10` rows, with the legacy reporting
  aliases, as before.
- ICD-11 deaths use the scheme's `icd11` rows: the exact code, else its
  nearest ancestor on the `mas_icd11_mms` parent chain that has a row. A
  post-coordinated value (`1G40&XN...`, `1G40/...`) is bucketed by its first
  stem. The ancestor is chosen ignoring age scope.
- `va_submission_cod_detail_mv` carries `final_icd` (ICD-10 code) and, since
  migration `e7b2c9d4a1f3`, `final_icd11` (ICD-11 stem). At most one is set.
  The admin unmapped-ICD grid still reads `final_icd` only, so ICD-11 codes
  never appear there as unmapped ICD-10.
- An ICD-11 death with no bucket is shown in the "View dropped CoDs" modal
  under "ICD-11 codes not included in <scheme>", never among the ICD-10
  sections. In a scheme with no ICD-11 rows (`WHO_2022_VA`, `SRS_INDIA`,
  `CMEA10`) every ICD-11 death is unmapped, under "ICD-11 codes: <scheme> has
  no ICD-11 mappings, so every ICD-11 death is unmapped".
- The report CSV's "Final authoritative COD" is the ICD-10 code or the ICD-11
  stem.

Since migration `d1a6e3b7c2f4`, `va_submission_cod_snapshot_mv` (and the coded
COD snapshot export it backs) does the same in `WHO_2022_VA_2026`, and records
each bucket's provenance (`icd10`, `icd11_native`, `unmapped`). See
[Submission Analytics](submission-analytics.md#cod-snapshot-mv).

On the dev dataset (7,879 final CODs, all ICD-10), moving the snapshot from
`WHO_2022_VA` to `WHO_2022_VA_2026` changed 15 authoritative buckets:
`R10` Other GI to Acute abdomen (4), `R95` Cause of death unknown to Other
perinatal (6), and `R19`/`R51`/`R55` from no bucket to Cause of death unknown
(5).

## Reporting UI

The data-management report page at `/data-management/cod-buckets` now:

- defaults to the `WHO_2022_VA_2026` scheme when available (owner,
  2026-09-24); the scheme filter still offers `WHO_2022_VA`. The
  `/aggregates` and `/export.csv` API routes resolve an omitted
  `scheme_code` through the same one resolver
  (`default_reporting_scheme_code()`: `WHO_2022_VA_2026` when active, else
  the first active scheme, else a 400 explaining that no scheme is
  configured) — they no longer fall back silently to the ICD-10-only
  `WHO_2022_VA`, which left every ICD-11 death unmatched
- exposes filters for scheme, project, site, form, submission date, and gender
- scopes all page bootstrap data and aggregate API results to the caller's
  data-manager project/site grants
- shows key indicators first for `Total coded`, `Scheme used`, and the current
  filter scope
- shows a top-10 causes section with a ranked table and horizontal bar chart
- shows a first-level cause-group section with counts and percentages
- shows demographic summaries as:
  - an age-sex table
  - an age pyramid
  - a sex pie chart
- uses SRS scheme age bands for SRS demographic summaries
- uses these custom age bands for WHO 2022 VA and CMEA10 demographic summaries:
  - `0-<28 days`
  - `28 days-<365 days`
  - `365 days-<12 years`
  - `12 years-<50 years`
  - `>=50 years`
- keeps `All Ages` first in the bottom detailed COD hierarchy section and, for
  WHO 2022 VA and CMEA10, adds additional detailed tables for each reporting
  age band after the all-ages table
- shows a top-10 cause heatmap that can pivot across country, year, sex, and age
- shows an all-causes treemap for the same filtered matched population
- shows the bottom COD hierarchy tables with `Male n (%)`, `Female n (%)`,
  `Unknown n (%)`, and `Total n (%)` columns for each scheme row
- supports CSV export of the current scoped page data, including SID, age, age
  group, sex, final authoritative COD, scheme hierarchy levels, project, site,
  form code, and year
- keeps the bottom COD hierarchy tables ordered by the scheme-defined sort
  order fields rather than applying separate label-based sorting
- keeps the detailed age-scope tables and dropped-COD drilldown modal below the
  chart
- is styled for printing without internal table/card scroll regions

## Public mapping list

`/help/va-code-mappings` (and `/help/va-code-mappings.csv`) publishes, without
login, every active ICD-10 and ICD-11 row of `WHO_2022_VA_2026`: code, code
title, VA cause, the row's note, and an origin (`who`, `who_resolved`,
`digitva`) derived at read time against WHO's 2026 annex. Policy:
`docs/policy/icd10-to-icd11-transition.md` section 7.

- Service: `app/services/va_code_mapping_public_service.py`; routes in
  `app/routes/help.py` (GET only, 60 per minute, 100 rows per page, search and
  filters validated against fixed sets).
- The annex and footnotes are read from `resource/` copies, because `docs/`
  is not in the image; a test keeps them equal to the `docs/` copies.
- The derived table is cached per process and rebuilt when the scheme's
  version, row count, latest row or node edit, or an annex file changes. ICD-11
  ranges are expanded with the native generator's functions against the
  `2026-01` catalogue.
- Footnote f: land transport codes it lists (V01-V89) and `Y85.0` are road
  traffic (`VAs-12.01`); its tail `V90-V99; Y85.9` and every unlisted V/Y85
  code are other transport (`VAs-12.02`).
- Sub-pages (`digitva-xud`):
  - `/help/va-code-mappings/compare?va_code=` shows the ICD-10 and ICD-11
    codes of one VA cause side by side, as chapter/block trees.
  - `/help/va-code-mappings/unmapped` (and `.csv`) lists every in-scope
    ICD-11 category with its VA cause or "Unmapped", selectability and policy
    review status. It is filtered by selectable and search, and paged.
  - The ICD-11 hierarchy and policy come from `get_icd11_catalogue()`. It
    makes one pass over `mas_icd11_mms` for the release and is cached per
    process. The cache key is the release's row count and latest
    `updated_at`, so an admin policy edit shows on the next load. ICD-10
    chapter and block come from `mas_icd10_2019_2`, joined in the same query
    that builds the mapping rows.
  - The `/unmapped.csv` download without a search is served from a file
    cache under `APP_DATA/public_csv/`, one file per selectable variant
    (all / yes / no). The file name carries a digest of the mapping and
    ICD-11 cache keys, so an edit writes a new file and removes the old one.
    Files are written to a temp file and moved into place with `os.replace`,
    so every gunicorn worker sees a whole file. Only public data is written.
    A search always streams live and never creates a file. If the directory
    cannot be written, the download streams live.
  - The mapping cache key also covers the ICD-10 catalogue (row count and
    latest `updated_at`), so chapter and block title edits reach the compare
    view, and the ICD-11 catalogue of the release (row count and latest
    `updated_at`), so an ICD-11 title edit alone refreshes the mapping rows
    too.
  - Both pages render with the shared Wunderbaum tree-table:
    `app/templates/components/tree_table.html`, `app/static/js/tree_table.js`
    and `app/static/css/tree_table.css`. It takes a flat node list and sets
    every value as text.

## Storage model

The reporting layer uses four tables:

- `mas_cod_bucket_schemes`
  - one row per reporting taxonomy, for example `SRS India`, `CMEA10`, or
    `WHO 2022 VA`
- `mas_cod_bucket_scheme_age_bands`
  - one row per scheme age band
  - stores label, display order, explicit lower and upper bounds, and level count
- `mas_cod_bucket_nodes`
  - hierarchy nodes within a scheme
  - supports variable depth and optional age scope
- `map_icd_cod_buckets`
  - maps an ICD code and optional age scope to a leaf node

## Scheme shape

### `SRS India`

Imported from:

- [`docs/icd-causegrp-mappings/migration-artifacts/srs-india-cod-2026-04-27/icd-10-CODES_SRS_India.xlsx`](../icd-causegrp-mappings/migration-artifacts/srs-india-cod-2026-04-27/icd-10-CODES_SRS_India.xlsx)

Characteristics:

- age-scoped mapping
- currently uses:
  - `adult_over5y`
  - `child_1_59m`
  - `neonate`
- hierarchy depth:
  - category
  - optional subcategory
  - field

### `CMEA10`

Imported from:

- [`docs/icd-causegrp-mappings/migration-artifacts/cmea10-cod-2026-04-27/icd-10-CODES_CMEA10_mapped.xlsx`](../icd-causegrp-mappings/migration-artifacts/cmea10-cod-2026-04-27/icd-10-CODES_CMEA10_mapped.xlsx)

Characteristics:

- flat mapping
- no age scope
- hierarchy depth:
  - field only

### `WHO 2022 VA`

Imported from:

- [`docs/icd-causegrp-mappings/migration-artifacts/who-2022-va-icd-cod-2026-04-27/WHO_2022_VA_Bucket_Mapping_document_derived.xlsx`](../icd-causegrp-mappings/migration-artifacts/who-2022-va-icd-cod-2026-04-27/WHO_2022_VA_Bucket_Mapping_document_derived.xlsx)

Characteristics:

- generated from the WHO 2022 VA crosswalk and ICD-10 2019 hierarchy
- splits `VAs-12.01 Road traffic accident` and `VAs-12.02 Other transport
  accident` from the reviewed RTA/non-RTA transport workbook
- flat all-ages age scope
- hierarchy depth:
  - WHO VA section
  - WHO VA cause bucket
- includes WHO-valid three-character ICD rows and dotted detailed ICD rows
- remains document-derived and is not narrowed by the later WHO assignability
  disable review; disabled codes simply stop being assignable during coding
- ambiguous ICD matches are resolved in the workbook before import; the import
  uses the primary bucket in `ICD_Mapped`

## Migration Artifacts

The source workbooks under `docs/icd-causegrp-mappings/ICD-to-VA-Buckets/` are
working inputs. Alembic migrations use fixed copies under
`docs/icd-causegrp-mappings/migration-artifacts/` so master-data rebuilds are
repeatable.

For the built-in schemes (`SRS India`, `CMEA10`, and `WHO 2022 VA`), those
same migration-artifact workbook copies are also the source of truth for
`Reset Default` in the admin COD bucket editor.

The 2026-04-27 rebuild migration imports:

- ICD-10 2019 base hierarchy from
  `migration-artifacts/icd10-2019-base-2026-04-27/icd10_2019_hierarchy.csv`
- reviewed WHO 2022 assignability policy from
  `migration-artifacts/who-2022-va-icd-cod-2026-04-27/who_2022_icd10_2019_2_policy_reviewed.json`
- SRS India COD buckets from
  `migration-artifacts/srs-india-cod-2026-04-27/icd-10-CODES_SRS_India.xlsx`
- CMEA10 COD buckets from
  `migration-artifacts/cmea10-cod-2026-04-27/icd-10-CODES_CMEA10_mapped.xlsx`
- WHO 2022 VA COD buckets from
  `migration-artifacts/who-2022-va-icd-cod-2026-04-27/WHO_2022_VA_Bucket_Mapping_document_derived.xlsx`
- reviewed VAs-12.01/VAs-12.02 transport decisions from the archived support
  workbook
  `archive/migration-artifacts/who-2022-va-icd-cod-2026-04-27/WHO_2022_VA_RTA_NonRTA_Review.xlsx`

## Import commands

Run inside Docker:

```bash
docker compose exec minerva_app_service uv run flask cod-buckets import-srs-india
docker compose exec minerva_app_service uv run flask cod-buckets import-cmea10
docker compose exec minerva_app_service uv run flask cod-buckets import-who-2022-va
docker compose exec minerva_app_service uv run flask cod-buckets list
```

Each import replaces the scheme's nodes and ICD mappings and increments that
scheme's `mapping_version`.

Mapping integrity rules:

- `map_icd_cod_buckets` is logically one row per `(scheme, age_scope, icd_code)`
- all-ages mappings are stored with `age_scope = NULL`, but they are still
  treated as unique per ICD inside a scheme
- JSON import now coalesces exact duplicate mapping rows and rejects
  conflicting duplicate ICD targets within the same age scope
- a null-safe unique index backs that rule at the database level so duplicate
  all-ages mappings cannot be reinserted

Imported schemes can then be maintained in the admin COD Buckets panel. The
current editor supports:

- selecting a scheme and age scope from top-level scheme cards
- exporting any scheme as JSON from its scheme card
- importing an exported JSON snapshot back into a selected scheme from its
  scheme card; the import fully replaces that scheme's age bands, nodes, and
  ICD mappings while keeping the selected scheme code stable
  - this importer accepts only COD bucket scheme export JSON
  - it does not accept ICD policy review artifacts such as
    `who_2022_icd10_2019_2_policy_reviewed.json`
- exporting a scheme-level bucket XLSX workbook from its scheme card, including
  bucket hierarchy rows and ICD mapping rows with manual override status
- creating a new scheme with age bands, min/max age bounds, units, and level count
- editing an existing scheme's name and age-band metadata from the scheme card
- resetting a built-in source-backed age band from the editor heading bar with
  confirmation
- resetting an entire built-in source-backed scheme from the `Edit COD Scheme`
  modal with confirmation
  - built-in reset-default always reloads from the frozen migration-artifact
    workbook copy, not from mutable working workbooks under
    `docs/icd-causegrp-mappings/ICD-to-VA-Buckets/`
- editing category/subcategory/field labels
- editing display `sort_order`
- loading ICD mappings on demand only for the selected last-level disease leaf
- searching within the selected leaf's mapped ICD list in the right-side card
- adding ICD codes through a modal ICD search that shows the current mapped
  path for each result, can be filtered to unmapped codes only, and keeps
  non-assignable master ICD rows available with a `Currently not assignable in
  coding` marker
- showing a scheme-wide grid of active ICD master rows not yet mapped anywhere
  in the selected scheme, across all age groups, as a single ICD code list,
  including non-assignable rows flagged as `Currently not assignable in coding`
- showing finalized COD and SmartVA usage counts in that unmapped ICD grid so
  operators can see whether an unmapped ICD is already present in active
  outcome data
- including the SmartVA pseudo-codes `UU1` and `UU2` in that reporting-side
  unmapped/searchable ICD catalog so schemes can map them explicitly even
  though they do not exist in the ICD-10 master
- filtering that unmapped ICD grid to codes already used in finalized COD
  outcomes, so operationally observed non-default ICDs can be reviewed and
  manually allocated
- filtering that unmapped ICD grid independently by finalized COD usage and by
  SmartVA usage
- bulk-allocating selected rows from that unmapped ICD list to a chosen age
  band and disease leaf in the current scheme
- filtering the selected disease leaf's mapped ICD list to manual overrides or
  source-derived mappings
- unmapping an ICD code directly from the selected disease leaf
- deleting a bucket level from the edit modal with a choice to either:
  - unmap affected ICD codes
  - move affected ICD codes to an `Unmapped` replacement branch
- remapping an ICD code to exactly one disease leaf within the selected
  scheme + age scope

For the built-in WHO 2022 VA scheme, the migration-artifact source XLSX is the
default mapping baseline. Admin edits are marked as manual overrides only when
the saved ICD-to-bucket target differs from that XLSX-derived default, or when
the ICD code is absent from the source workbook. If an admin moves a code back
to its XLSX default bucket, the editor restores the source metadata instead of
leaving a manual override marker.

The admin ICD picker used in the COD bucket editor now searches the ICD-10
2019 master table (`mas_icd10_2019_2`) and returns active 3-character or
detailed ICD rows. It does not apply age or sex policy filtering inside the COD
bucket editor, and rows that are not currently assignable in coding remain
available for bucket mapping with an explicit warning marker.

Age band bound semantics are:

- lower bound: inclusive (`>=`)
- upper bound: exclusive (`<`)
- all scheme age bands persist explicit min/max bounds; there are no open-ended
  `NULL` ranges
- built-in open-ended scopes use `120 years` as the explicit upper cap

Age-band normalization in COD reporting uses:

- `days` -> `1`
- `months` -> `365 / 12`
- `years` -> `365`

The admin creator shows gap and overlap feedback using that same conversion logic.
Those warnings are surfaced on scheme cards and age-band buttons as hover help,
but they do not block scheme creation or update.

## Aggregation input contract

Bucketed aggregation is driven from:

- `va_submission_analytics_core_mv`
- `va_submission_analytics_demographics_mv`
- `va_submission_cod_detail_mv`

The aggregate query uses:

- authoritative `final_icd`
- demographics-derived age band
- the active scheme mapping
- optional reporting-only legacy ICD alias normalization before scheme lookup
- the caller's allowed `(project_id, site_id)` scope pairs from
  `dm_scoped_forms(...)`
- a small reporting-only legacy ICD normalization layer before bucket lookup
  for selected historical codes that no longer exist in the ICD-10 2019 master

Current normalization baseline:

- `A90` -> `A97`
- `A91` -> `A97`
- `I84` -> `K64`

Current command-line aggregation:

```bash
docker compose exec minerva_app_service uv run flask cod-buckets aggregate --scheme-code SRS_INDIA
docker compose exec minerva_app_service uv run flask cod-buckets aggregate --scheme-code CMEA10
```

The `/data-management/cod-buckets` page now renders separate tables per age
scope. Each table shows:

- `Main Group`
- `Subgroup`
- `Disease`
- `Count`
- `Total (%)`

If coded submissions in an age group have a final ICD that does not map to any
active node in the selected scheme, those submissions are not rendered as
hierarchy rows. Instead, the page shows a note beneath that age-group table
stating how many submitted CODs were dropped because they did not match any
configured category. That note now includes a modal link showing two tabulated
sections for the same age group:

- ICD codes not included in the selected scheme's CoD categories for that age group
- ICD codes not eligible for coding

Rows are sorted by the active scheme hierarchy display order, using the stored
`sort_order` values on category, subcategory, and field nodes rather than label
sorting or count sorting.

## Important behavior

- submission COD rows remain unchanged when reporting mappings change
- selected historical ICD codes may normalize to current ICD-10 2019
  three-character equivalents for reporting only; this does not rewrite stored
  final COD values
- reporting schemes are versioned separately from coding data
- SRS chooses a mapping branch by age scope
- CMEA10 does not branch by age scope
