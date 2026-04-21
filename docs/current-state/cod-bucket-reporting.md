---
title: COD Bucket Reporting
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-04-21
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

## Storage model

The reporting layer uses four tables:

- `mas_cod_bucket_schemes`
  - one row per reporting taxonomy, for example `SRS India` or `CMEA10`
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

- [`docs/icd-causegrp-mappings/ICD-to-VA-Buckets/icd-10-CODES_SRS_India.xlsx`](../icd-causegrp-mappings/ICD-to-VA-Buckets/icd-10-CODES_SRS_India.xlsx)

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

- [`docs/icd-causegrp-mappings/ICD-to-VA-Buckets/icd-10-CODES_CMEA10_mapped.xlsx`](../icd-causegrp-mappings/ICD-to-VA-Buckets/icd-10-CODES_CMEA10_mapped.xlsx)

Characteristics:

- flat mapping
- no age scope
- hierarchy depth:
  - field only

## Import commands

Run inside Docker:

```bash
docker compose exec minerva_app_service uv run flask cod-buckets import-srs-india
docker compose exec minerva_app_service uv run flask cod-buckets import-cmea10
docker compose exec minerva_app_service uv run flask cod-buckets list
```

Each import replaces the scheme's nodes and ICD mappings and increments that
scheme's `mapping_version`.

Imported schemes can then be maintained in the admin COD Buckets panel. The
current editor supports:

- selecting a scheme and age scope from top-level scheme cards
- exporting any scheme as JSON from its scheme card
- creating a new scheme with age bands, min/max age bounds, units, and level count
- editing an existing scheme's name and age-band metadata from the scheme card
- resetting a built-in source-backed age band from the editor heading bar with
  confirmation
- resetting an entire built-in source-backed scheme from the `Edit COD Scheme`
  modal with confirmation
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
- bulk-allocating selected rows from that unmapped ICD list to a chosen age
  band and disease leaf in the current scheme
- unmapping an ICD code directly from the selected disease leaf
- deleting a bucket level from the edit modal with a choice to either:
  - unmap affected ICD codes
  - move affected ICD codes to an `Unmapped` replacement branch
- remapping an ICD code to exactly one disease leaf within the selected
  scheme + age scope

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
- reporting schemes are versioned separately from coding data
- SRS chooses a mapping branch by age scope
- CMEA10 does not branch by age scope
