---
title: ICD-11 COD Bucket Schemes
doc_type: policy
status: draft
owner: engineering
last_updated: 2026-09-24
---

# ICD-11 COD Bucket Schemes

Baseline for placing ICD-11-coded deaths into cause-of-death buckets. Extends
[COD Bucket Reporting](cod-bucket-reporting.md); the ICD-11 catalogue is
[ICD-11 Reference Catalog](icd11-reference-catalog.md). Decisions and open items:
[ICD-10 to ICD-11 Transition](icd10-to-icd11-transition.md).

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

> **Withdrawn (owner, 2026-09-24).** The crosswalk method will not be built.
> Projects that mix ICD-10 and ICD-11 bucket each death through the rows of
> its own classification in the native scheme. WHO's 11-to-10 table stays
> as an offline cross-check. The text below is kept as the record of what
> was considered. See [ICD-10 to ICD-11 Transition](icd10-to-icd11-transition.md),
> decision 6.

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
    accident; `PJ2x` (maltreatment) listed for owner review.
  - Every generated code is cross-checked against the owner's curated ICD-10
    scheme through WHO's 11-to-10 crosswalk; disagreements are listed for
    review, never silently resolved.
  - Codes no range covers stay unmapped (selectability is unaffected) and are listed
    with the crosswalk's suggestion.

## Data

- `map_icd_cod_buckets` gains `icd_classification` (`icd10` | `icd11`,
  default `icd10`), part of the unique key; existing rows are `icd10`.
- Scheme gains `icd11_method` (`crosswalk` | `native` | null).
- New crosswalk table holding WHO's rows and release.
- Additive migrations only; nothing existing is remapped.

## Open

- Override list for the crosswalk's known misses (sepsis first): owner review.
- Circumstance-split causes in the native WHO scheme.
