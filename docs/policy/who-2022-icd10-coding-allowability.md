---
title: WHO 2022 ICD-10 Coding Allowability Policy
doc_type: policy
status: active
owner: engineering
last_updated: 2026-09-25
---

# WHO 2022 ICD-10 Coding Allowability Policy

## Purpose

This policy defines the ICD-10 2019-2 rows that are selectable during WHO 2022
verbal autopsy ICD coding.

This policy controls ICD coding search and selection only. COD bucket grouping,
road-traffic versus other-transport bucket mapping, and ambiguous bucket
resolution are out of scope for this step.

## Baseline Source

The WHO 2022 VA crosswalk workbook is the baseline source for ICD coding
allowability. A generated policy JSON is a full replacement import payload, not
an overlay. When imported, editable ICD rows absent from the generated JSON
become not selectable through the existing overwrite-style import behavior.

Default allowed WHO ICD rows use:

- `is_coding_selectable=true`
- `sex_selectable=both`
- `age_group_selectable=all`

Exception rules override those defaults.

## Age Groups

ICD coding age allowability supports:

- `all`
- `neonate`
- `infant`
- `child`
- `adult`

Submission age classification is:

- `neonate`: `0` to `<28 days`
- `infant`: `28 days` to `<365 days`
- `child`: `365 days` to `<12 years`
- `adult`: `>=12 years`

Policy matching is exact-or-all. A code marked `all` is available to every age
group. A code marked `infant` is available only to submissions classified as
`infant`.

## Allowability Rules

Allowed ICD rows are active ICD10-2019-2 editable rows referenced by
`WHO_2022_VA_Crosswalk.xlsx`, after expanding raw ICD expressions against the
existing ICD10 master.

Expansion preserves the granularity shown by WHO:

- a three-character code such as `C50` selects only `C50`
- a three-character range such as `C51-C58` selects only three-character rows in
  that range
- a dotted code such as `I11.0` selects only that dotted code
- a dotted range such as `V10.4-V10.9` selects only dotted rows in that dotted
  range

Never selectable:

- `S00-T99`, including all active editable rows in that range

Road-traffic footnote codes are selectable for both sexes and all ages. This
only affects ICD coding allowability; road-traffic versus other-transport COD
bucket mapping is deferred.

Transport codes are selectable only at the level where WHO decides the bucket
(owner decision, 2026-09-25, `digitva-g2n`):

- The three-character codes `V01`-`V89` and `Y85` are **not selectable**.
  WHO 2022 VA footnote f separates Road traffic accident (`VAs-12.01`) from
  Other transport accident (`VAs-12.02`) only by the fourth character
  (`V01.1` ... `V87.0-V87.9`, `V89.2-V89.3`, `Y85.0` are road traffic). A
  three-character pick cannot be placed by that rule and fell to Other
  transport, under-counting road deaths. Every one of these codes has
  selectable fourth-character subcodes, so a coder always has a target.
- `V90`-`V99` stay selectable at three characters: footnote f lists them
  whole, as Other transport.
- Final assessments already saved with a three-character code keep it; the
  change governs new selections only. Re-coding them is a separate decision.
- Applied by data migration (prior values captured, downgrade restores them).
  Re-importing the released 2026 ICD-10 policy JSON would undo it, as with
  the `Q00`-`Q99` decision.

Neonate-only, both sexes:

- `P05`, `P07`
- `P20-P22`
- `P23-P24`
- `P36`
- `A33`
- `Q00-Q99`
- `P00-P04`
- `P08-P15`
- `P25-P35`
- `P37-P94`
- `P96`
- `P95`

Infant-only, both sexes:

- `R95`

Female-only, adult-only:

- all WHO maternal `O` code rows

Sex-specific neoplasms:

- `C51-C58`: female-only, all ages
- `C60-C63`: male-only, all ages
- `C50`: both sexes, all ages
- `D25-D28`: female-only, all ages
- `D29`: male-only, all ages

These sex-specific neoplasm restrictions are deliberate deviations from the
default WHO residual bucket allowability. For example, WHO bucket `VAs-02.99`
lists the broad residual range `C64-D48`; the generated ICD selection policy
still narrows genital-organ neoplasm rows such as `D26` to the anatomically
applicable sex. The COD bucket assignment remains unchanged and is not resolved
by this ICD selection policy.

## 2026 Annex Adjustments

Adopted 2026-09-18. Only three of the 2026 annex's four ICD-10 differences
change this policy; `VAs-12.99`'s change is punctuation only (`S00-T99` is
already never-selectable, see above) and needs no action.

**`VAs-98` (Other and unspecified non-communicable disease):** the allowed
range's floor moves from `K77` to `K70`, and `G43-G47` is added.

- `G43`, `G44`, `G45`, `G46`, `G47` become selectable (three-character
  granularity), both sexes, all ages.
- `K72`, `K73`, `K75`, `K76` become selectable (three-character granularity),
  both sexes, all ages.
- `K70` and `K71` are NOT made selectable at three-character granularity,
  because that would swallow the existing liver-cirrhosis carve-out below.
  Instead, every dotted (detailed) code under `K70` and `K71` other than
  `K70.2`, `K70.3` and `K71.7` becomes selectable, both sexes, all ages.
  `K74` was already selectable at three-character granularity and is
  unaffected.

**`VAs-06.02` (Liver cirrhosis) carve-out — unchanged:** `K70.2`, `K70.3`,
`K71.7`, `K74` remain reserved to `VAs-06.02` and are excluded from the
`VAs-98` grant above.

**`VAs-99` (Unknown and ill-defined cause of death):** the allowed range
expands from `R95-R99` to `R00-R09; R11-R94; R96-R99`.

- `R00`, `R01`, `R02`, `R03`, `R04`, `R05`, `R06`, `R07`, `R09` become
  selectable (three-character granularity; `R08` does not exist in ICD-10),
  both sexes, all ages.
- `R11`-`R94` become selectable (three-character granularity). `R10` is not
  part of this grant; it has its own rule under `VAs-06.01` below.
- `R96`-`R99` were already selectable and are unchanged.

**`VAs-06.01` (Acute abdomen):** `R10` becomes selectable (three-character
granularity), both sexes, all ages, bucketed to `VAs-06.01` in the
`WHO_2022_VA_2026` scheme, as the WHO annex lists it. Before 2026-09-19 `R10` was
not selectable and the live `WHO_2022_VA` scheme mapped it by manual override to
the non-WHO bucket "Other Gastrointestinal Diseases"; that override is
deliberately not carried into `WHO_2022_VA_2026`. `WHO_2022_VA` is unchanged.

**`VAs-10.99` (Other and unspecified perinatal cause of death):** `R95` moves
into this bucket's range from the earlier `VAs-99`/"Cause of death unknown"
assignment. `R95`'s selectability policy is unchanged (infant-only, both
sexes, listed under "Infant-only, both sexes" above); only its WHO bucket
assignment moves, from "Cause of death unknown" to `VAs-10.99`. See the COD
bucket mapping (`who_2022_va_2026` scheme) rather than this ICD-selection
policy for the bucket change itself.

## Overlap Rules

Never-selectable rules win over all other rules. Age and sex exceptions win over
default WHO allowability. Within exceptions, the most restrictive applicable
rule wins. Bucket ambiguity may be recorded in notes where useful but is not
resolved by this policy.

A more specific ICD code wins over a broader range it falls inside, whenever
the two are assigned to different buckets or carry different exceptions. This
is why the `VAs-98` grant of `K70-K76` (2026 Annex Adjustments, above) does not
override the dotted `K70.2`, `K70.3`, `K71.7` codes already carved out to
`VAs-06.02`: those three dotted codes are more specific than the three-character
`K70`/`K71` range and win the conflict. The same rule applies to any future
range expansion that overlaps an existing dotted-code exception.

## Carried-forward overrides in WHO_2022_VA_2026

The `WHO_2022_VA_2026` COD bucket scheme carries forward 33 manual bucket
overrides that already existed in the live `WHO_2022_VA` scheme, so the 2026
revision does not regress prior clinical curation. Of those 33, the 16 below
land in a different bucket from the one the WHO 2026 annex (Annex 1 Table A1,
`docs/icd-causegrp-mappings/ICD-to-VA-Buckets/who_2022_va_cause_list_icd10_icd11.csv`)
would give the code; the remaining 17 agree with the annex and need no record
here.

"Bucket the annex gives" is derived by expanding the annex ICD-10 ranges with
the granularity rules under "Allowability Rules" and the specific-beats-range
rule under "Overlap Rules". `(none)` means no annex range covers the code at
its own granularity: `UU1` and `UU2` are local pseudo-codes that are not ICD-10
at all, `U07` appears in the annex only as the dotted `U07.1`/`U07.2`, `I11`
falls between the annex's `I11.0` and `I11.9-I15`, and `Y91` is in no annex
range.

| ICD-10 code | Title | Bucket kept | Bucket the annex gives | Decided by |
| --- | --- | --- | --- | --- |
| `G46` | Vascular syndromes of brain in cerebrovascular diseasesI60-I67 | `VAs-04.02` Stroke | `VAs-98` Other and unspecified non-communicable disease | clinical lead 2026-09-19 (keep) |
| `G47` | Sleep disorders | `VAs-99` Cause of death unknown | `VAs-98` Other and unspecified non-communicable disease | clinical lead 2026-09-19 (keep) |
| `I11` | Hypertensive heart disease | `VAs-04.01` Acute cardiac disease | (none) | clinical lead 2026-09-19 (keep) |
| `I46` | Cardiac arrest | `VAs-04.01` Acute cardiac disease | `VAs-04.99` Other and unspecified cardiac disease | clinical lead 2026-09-19 (keep) |
| `I50` | Heart failure | `VAs-04.01` Acute cardiac disease | `VAs-04.99` Other and unspecified cardiac disease | clinical lead 2026-09-19 (keep) |
| `K64` | Haemorrhoids and perianal venous thrombosis | Other Gastrointestinal Diseases | `VAs-98` Other and unspecified non-communicable disease | clinical lead 2026-09-19 (keep) |
| `K70` | Alcoholic liver disease | `VAs-06.02` Liver cirrhosis | `VAs-98` Other and unspecified non-communicable disease | clinical lead 2026-09-19 (keep) |
| `K72` | Hepatic failure, not elsewhere classified | `VAs-06.02` Liver cirrhosis | `VAs-98` Other and unspecified non-communicable disease | clinical lead 2026-09-19 (keep) |
| `K73` | Chronic hepatitis, not elsewhere classified | `VAs-06.02` Liver cirrhosis | `VAs-98` Other and unspecified non-communicable disease | clinical lead 2026-09-19 (keep) |
| `K75` | Other inflammatory liver diseases | Other Gastrointestinal Diseases | `VAs-98` Other and unspecified non-communicable disease | clinical lead 2026-09-19 (keep) |
| `K76` | Other diseases of liver | Other Gastrointestinal Diseases | `VAs-98` Other and unspecified non-communicable disease | clinical lead 2026-09-19 (keep) |
| `R50` | Fever of other and unknown origin | `VAs-01.99` Unspecified infectious disease | `VAs-99` Unknown and ill-defined cause of death | clinical lead 2026-09-19 (keep) |
| `U07` | Emergency use of U07 | `VAs-01.13` Coronavirus disease (COVID-19) | (none) | clinical lead 2026-09-19 (keep) |
| `Y91` | Evidence of alcohol involvement determined by level of intoxication | `VAs-99` Cause of death unknown | (none) | clinical lead 2026-09-19 (keep) |
| `UU1` | Other Non-communicable Diseases | `VAs-98` Other and unspecified non-communicable disease | (none) | clinical lead 2026-09-19 (keep) |
| `UU2` | Other Defined Causes of Child Deaths | Other Defined cause of Child Death | (none) | clinical lead 2026-09-19 (keep) |

**Rule.** These overrides are kept deliberately: the bucket in the artifact
wins over the annex-derived bucket for these codes. A future annex revision
re-evaluates each of them one at a time; none is dropped silently, and none is
"fixed" to the annex value without the clinical lead's sign-off. Titles are
reproduced verbatim from the derived workbook, including the `G46` title's
trailing `I60-I67` fragment, so the row stays traceable to its source.

None of the 16 codes is ICD-10 coding-selectable today; these are bucket
mappings for reporting and legacy-data coverage. Adding one to the selectable
set is a separate decision under "Allowability Rules".

**`R10` — confirmed 2026-09-19 by the clinical lead.** In `WHO_2022_VA_2026`,
`R10` is selectable, both sexes, all ages, and bucketed to `VAs-06.01` Acute
abdomen, as the WHO 2026 annex lists it (see "2026 Annex Adjustments" above).
The 34th manual override in the live `WHO_2022_VA` scheme, which mapped `R10`
to "Other Gastrointestinal Diseases", is deliberately not carried forward and
so does not appear in the table. The old `WHO_2022_VA` scheme keeps its own
mapping unchanged.
