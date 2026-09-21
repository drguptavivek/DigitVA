---
title: ICD-11 COD Bucket Schemes
doc_type: policy
status: draft
owner: engineering
last_updated: 2026-09-21
---

# ICD-11 COD Bucket Schemes

Baseline for placing ICD-11-coded deaths into cause-of-death buckets. Extends
[COD Bucket Reporting](cod-bucket-reporting.md); the ICD-11 catalogue is
[ICD-11 Reference Catalog](icd11-reference-catalog.md).

## Decision (owner, 2026-09-21)

A bucket scheme has exactly one **ICD-11 method**. There is no per-death
fallback from one method to the other.

| Method | For | How an ICD-11 code finds its bucket |
|---|---|---|
| `crosswalk` | Projects whose data mixes ICD-10 and ICD-11 | ICD-11 code → ICD-10 through WHO's 11-to-10 crosswalk → the scheme's existing ICD-10 buckets |
| `native` | Projects coded in ICD-11 only | The scheme's own ICD-11 → bucket mappings |

- An ICD-10-only scheme (today's schemes) has no ICD-11 method and is
  unchanged.
- The **source ICD-11 code is always the record of truth**. Buckets are
  derived and can be recomputed or re-derived in data management from an
  export; no bucket assignment replaces or rewrites the coded value.
- The scheme is chosen **per report**, whichever suits the data (owner,
  2026-09-21): a crosswalk scheme for mixed ICD-10/ICD-11 data, a native one
  for pure ICD-11 data. Nothing ties a project to a scheme.
- Every bucket result records its **provenance**: `icd10`, `icd11_native`,
  `icd11_crosswalk`, or `unmapped`, so a report can say how much rests on
  the crosswalk.

## Project ICD classification (owner, 2026-09-21)

A project declares how its deaths are coded: `icd10`, `icd11`, or
`selectable` (the coder chooses ICD-10 or ICD-11 for each death). This is not
a bucket-scheme link; schemes stay a per-report choice.

- Today the classification is per ODK form mapping
  (`map_project_site_odk.icd_classification`), and a web-form submission has
  no such row, so it always resolves to `icd10`. The project setting closes
  that gap.
- With `selectable`, the coded value carries its classification, so a
  project's data may be mixed; that is the case the crosswalk method serves.
- Open: whether the per-form ODK setting stays as an override of the project
  setting, or is retired in favour of it.

## Crosswalk method

- Source: WHO `11To10MapToOneCategory` (one ICD-10 target per ICD-11 code),
  loaded into its own table with the WHO release it came from. The
  multiple-category table is not used.
- A crosswalk target may be an ICD-10 **block** (e.g. `A30-A49`) rather than a
  code. It is looked up as a range against the scheme's ICD-10 mappings; a
  block that spans more than one bucket is `unmapped`, never guessed.
- A combined (post-coordinated) ICD-11 code is bucketed by its **first stem**;
  extension codes are ignored.
- Release: the crosswalk is WHO 2025-01 while the catalogue is 2026-01. A
  2026-01 code absent from the crosswalk is translated through WHO's
  2026-01-vs-2025-01 change list before lookup; if it still has no entry it is
  `unmapped`.
- Known limits, measured 2026-09-21 against WHO's own VA cause list (ICD-11
  ranges run through the crosswalk, compared with the same causes' ICD-10
  ranges; weighted by codes, not deaths): 88.6% land in the same VA cause,
  9.6% in another, 1.9% have no ICD-10 target. Some misses are systematic and
  clinically material: sepsis `1G40` → block `A30-A49` and `1G41` → `R57.2`
  (ill-defined), so crosswalked sepsis never reaches the sepsis bucket;
  pregnancy-related sepsis agrees 11%; meningitis/encephalitis 71%;
  haemorrhagic fever 54%. A crosswalk scheme may carry **overrides** for
  specific ICD-11 codes to correct these; an override is an explicit, audited
  mapping, not a change to WHO's table.

## Native method

- Mappings are ICD-11 codes (ranges expanded against the catalogue at import)
  to the scheme's buckets, per age band, like ICD-10 mappings.
- Lookup is the exact code, then its ancestors along the catalogue's parent
  chain. ICD-11 codes are not prefix-ordered the way ICD-10 codes are, so no
  string truncation.
- **Selectable codes come from the mapping (owner, 2026-09-21).** A coder can
  select only ICD-11 codes that appear in a native scheme's mapping table. The
  rule is global: there is no per-project scheme setting (owner, 2026-09-21).
  - With more than one native scheme, a code is selectable if it appears in
    any of them.
  - The catalogue's own policy (`is_coding_selectable`, sex and age
    restrictions, edited in the ICD-11 browser) still applies on top: a code
    is offered only if it is in a native mapping **and** allowed by the
    catalogue policy for that death's sex and age.
  - Changing a mapping later does not invalidate codes already recorded; a
    recorded code that is no longer mapped is reported as `unmapped` and
    listed for review, never silently re-coded.
- A code with no mapping on its chain in a given native scheme is `unmapped`
  in that scheme's reports and listed for review.
- The WHO 2022 VA 2026 revision is seeded from the ICD-11 column of
  `docs/icd-causegrp-mappings/ICD-to-VA-Buckets/who_2022_va_cause_list_icd10_icd11.csv`.
  Causes the cause list splits by circumstance rather than by code (e.g. road
  traffic vs other transport, both `PA00-PA5Z`) need an owner rule before
  seeding.

## Data

- `map_icd_cod_buckets` gains `icd_classification` (`icd10` | `icd11`,
  default `icd10`), part of the unique key; existing rows are `icd10`.
- Scheme gains `icd11_method` (`crosswalk` | `native` | null).
- New crosswalk table holding WHO's rows and release.
- Additive migrations only; nothing existing is remapped.

## Open

- Override list for the crosswalk's known misses (sepsis first): owner review.
- Circumstance-split causes in the native WHO scheme.
