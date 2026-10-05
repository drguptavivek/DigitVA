---
title: ICD-11 COD Bucket Schemes
doc_type: policy
status: active
owner: engineering
last_updated: 2026-10-06
---

# ICD-11 COD Bucket Schemes

Baseline for placing ICD-11-coded deaths into cause-of-death buckets. Extends
[COD Bucket Reporting](cod-bucket-reporting.md); the ICD-11 catalogue is
[ICD-11 Reference Catalog](icd11-reference-catalog.md). Decisions and open items:
[ICD-10 to ICD-11 Transition](icd10-to-icd11-transition.md).

## Decision

A bucket scheme has at most one **ICD-11 method**: `native`, the scheme's own
ICD-11 to bucket mappings. The `crosswalk` method (ICD-11 to ICD-10 through
WHO's 11-to-10 table, then the ICD-10 buckets) was withdrawn and never built
(owner, 2026-09-24, decision 6 of
[ICD-10 to ICD-11 Transition](icd10-to-icd11-transition.md)). WHO's 11-to-10
table is kept as an offline cross-check only: the generator compares every
generated code against it and lists disagreements for review
(`app/services/cod_bucket_icd11_generator.py`).

- An ICD-10-only scheme has no ICD-11 method (`icd11_method` null) and is
  unchanged. Only `WHO_2022_VA_2026` has native ICD-11 rows today, and only
  that scheme is bucketed through them in submission analytics
  (`app/services/submission_analytics_mv.py`, `_who_2026_bucket_sql`).
- The **source ICD-11 code is always the record of truth**. Buckets are
  derived and can be recomputed or re-derived in data management from an
  export; no bucket assignment replaces or rewrites the coded value.
- There is no per-death fallback from one method to the other. Data that mixes
  ICD-10 and ICD-11 is bucketed in one scheme: each value goes through the
  rows of its own classification, which its code shape decides (the ICD-10 and
  ICD-11 shapes do not overlap). ICD-10 values use the scheme's `icd10` rows,
  ICD-11 values its `icd11` rows.
- Every bucket result records its **provenance**, as a
  `*_who_bucket_provenance` column beside each bucket in the submission COD
  snapshot (`app/services/submission_analytics_mv.py`): `icd10`,
  `icd11_native`, `unmapped`, or NULL when there is no coded value. A report
  can therefore say how much rests on ICD-11 rows. SmartVA causes are ICD-10
  and carry only `icd10` or `unmapped`.

## Project ICD classification

A project declares how its deaths are coded: `icd10` or `icd11`
(`va_project_master.icd_classification`, check-constrained to those two
values in `app/models/va_project_master.py`). It covers ODK and web-form
submissions alike. ICD-11 always means DORIS entry (`cod_entry_mode='doris'`).
The per-form ODK setting (`map_project_site_odk.icd_classification`) is
deprecated and no longer read (owner, 2026-09-24). The `selectable`
classification, where the coder chose per death, was retired (digitva-0n3,
2026-09-27). Rules, the migration of per-form values and the retirement:
[VA Form Project Configuration](va-form-project-configuration.md), "5. ICD
classification". This is not a bucket-scheme link; a project's setting decides
how its deaths are coded, and a value saved while the project was still
`selectable` keeps its own classification by code shape, so bucketing needs no
project lookup.

## Native method

- Mappings are ICD-11 codes (ranges expanded against the catalogue at import)
  to the scheme's buckets, per age band, like ICD-10 mappings.
- Lookup is the exact code, then its ancestors along the catalogue's parent
  chain. ICD-11 codes are not prefix-ordered the way ICD-10 codes are, so no
  string truncation.
- A post-coordinated ICD-11 value (`1G40&XN...`, `1G40/...`) is bucketed by its
  first stem; extension codes are ignored.
- **Selectability is separate from bucketing (owner, 2026-09-21).** What a
  coder may select is governed only by the classification's own policy:
  the ICD-10 policy (ICD-10 browser) for ICD-10 codes, the ICD-11 policy
  (`is_coding_selectable`, sex and age, ICD-11 browser) for ICD-11 codes. A
  bucket mapping decides only which bucket a selected code falls in; it never
  makes a code selectable or unselectable. (This replaces an earlier draft
  rule that tied selectability to the mapping.)
  - A selectable code with no bucket in a scheme reports as `unmapped` in that
    scheme and is listed for review.
  - Changing a mapping never re-codes a recorded death.
- A code with no mapping on its chain in a given native scheme is `unmapped`
  in that scheme's reports and listed for review.
- The WHO 2022 VA 2026 revision is seeded from the ICD-11 column of
  `docs/icd-causegrp-mappings/ICD-to-VA-Buckets/who_2022_va_cause_list_icd10_icd11.csv`,
  ranges expanded against the 2026-01 catalogue (owner, 2026-09-21):
  - **More specific wins.** Where a code falls in more than one cause's range
    (e.g. a specific cause and a residual "other/unspecified" range), the
    narrower range wins; a tie is not guessed but listed for review.
  - Ranges the cause list shares between causes are split **per code**, as
    the owner already did for ICD-10: `PA0x` (traffic events) → road traffic
    accident, `PA1x`-`PA5x` (nontraffic, water, air, other) → other transport
    accident; `PJ2x` (maltreatment) → Assault (owner decision 2).
    Within `PA1x`-`PA5x`, the "unknown whether traffic" codes `PA22`-`PA29`,
    `PA2E`, `PA2F`, `PA2Y` and `PA2Z` go to Road traffic instead (owner
    decision 17, 2026-09-25, `docs/policy/icd10-to-icd11-transition.md`
    section 6), by the same WHO chapter-note assumption applied to ICD-10
    `V10`-`V82`/`V87` (decision 16). `PA20`, `PA21` and `PA2A`-`PA2D` stay
    Other transport.
  - Every generated code is cross-checked against the owner's curated ICD-10
    scheme through WHO's 11-to-10 crosswalk; disagreements are listed for
    review, never silently resolved.
  - Codes no range covers stay unmapped (selectability is unaffected) and are listed
    with the crosswalk's suggestion.

## Data

- `map_icd_cod_buckets.icd_classification` (`icd10` | `icd11`, default
  `icd10`) is part of the unique key; existing rows are `icd10`.
- `mas_cod_bucket_schemes.icd11_method` is `native` or null.
  `apply_icd11_generation` replaces only the scheme's `icd11` rows, sets
  `native` and bumps `mapping_version`; a whole-scheme reset from the workbook
  rebuilds the ICD-10 table, clears `native`, and so needs
  `flask cod-buckets generate-icd11` again
  (`app/services/cod_bucket_mapping_service.py`,
  `_replace_scheme_contents`). The column's check constraint and the JSON
  import still accept `crosswalk`, but nothing reads or writes it.
- There is no crosswalk table; WHO's 11-to-10 files are read from
  `docs/icd-causegrp-mappings/migration-artifacts/` by the generator only.
- Additive migrations only; nothing existing is remapped.

## Open

- Circumstance-split causes in the native WHO scheme.

## Reset safety net (owner, 2026-09-25, digitva-tet)

"Reset from source" rebuilds a scheme's nodes and mappings from its workbook,
which destroys anything the workbook does not know about: admin edits,
ICD-11 rows, manual overrides. Every reset -- age-band or whole-scheme, from
the admin panel or via `flask cod-buckets import-*` over an existing scheme
-- now snapshots the whole scheme as JSON into `va_cod_bucket_scheme_snapshots`
first, in the same transaction as the reset. If the snapshot fails, the reset
is refused; nothing is lost or half-applied. Restore is the existing JSON
import (`import_cod_bucket_scheme_json` / Import JSON in the admin panel) --
there is no dedicated restore endpoint. The admin panel lists an age band or
scheme's 10 most recent snapshots and downloads any of them; the browser also
auto-downloads the snapshot the moment a reset completes. No retention/prune
job exists yet for this table -- add one once it grows large enough to
matter.
