---
title: WHO 2022 ICD-11 coding-selectability policy draft (2026-01)
doc_type: migration-artifact
status: approved
owner: engineering
last_updated: 2026-09-29
---

# WHO 2022 ICD-11 coding-selectability policy draft (2026-01)

Written by `flask icd11 policy-draft` (`app/services/icd11_policy_draft_service.py`). Rules: `docs/policy/who-2022-icd11-coding-allowability.md` (approved 2026-09-29). No migration reads this folder: migration `a7c3e9f1b5d2` ships a frozen byte-equal copy, `resource/icd11_mms_2026_01_policy_signoff_2026_09_29.json`, and a test keeps the two equal. Regenerating the draft after sign-off needs a new migration.

Sources: annex ICD-11 ranges `docs/icd-causegrp-mappings/ICD-to-VA-Buckets/who_2022_va_cause_list_icd10_icd11.csv`; catalogue `mas_icd11_mms` release `2026-01`; ICD-10 restrictions `docs/icd-causegrp-mappings/migration-artifacts/who-2022-va-icd-cod-2026-revision/who_2022_icd10_2019_2_policy_reviewed.json`; ICD-10 to ICD-11 map `docs/icd-causegrp-mappings/migration-artifacts/icd11-icd10-mapping-tables-2025-01-base-2026-09-16/10To11MapToOneCategory.txt` (2025-01 codes translated to 2026-01 through the `MovedTo` rows of `docs/icd-causegrp-mappings/migration-artifacts/icd11-mms-changes-2026-01-vs-2025-01-2026-09-16/changes_MMS_2026-01_2025-01-main.xlsx`).

Owner decisions of 2026-09-24 applied: chapter 20 (LA-LD) is all ages (no neonate chapter rule), and ICD-10 O/P/Q restrictions (blanket chapter rules) are never carried to any ICD-11 code; chapters 18 and 19 take their chapter rules instead.

Owner decision 18 (2026-09-25, digitva-g2n) applied: `KD3B` and `KD3B.Z` (time of fetal death not specified) are not selectable, so every ICD-11 stillbirth lands in Fresh (`KD3B.1` intrapartum) or Macerated (`KD3B.0` antepartum). It is part of the signed-off, migrated policy.

## Files

- `who_2022_icd11_mms_2026_01_policy_draft.json`: the selectable categories in the format `flask icd11 policy-import` and the admin ICD-11 browser import read. It is a full replacement: every active category it does not list (chapter X included) is reset to not selectable with no sex/age/note. Items carry no `policy_status`, so an import leaves each row's status as it is.
- `icd11_policy_review.csv`: every category outside chapter X, with the rule that decided it, its sex/age, where they came from, and review flags.

## Totals

- Active categories: 35664
- Selectable: 16387 (residual 4861, with children 2382)

## Categories per rule

| Rule | Categories |
|---|---:|
| `annex` | 16154 |
| `decision_18_not_selectable` | 2 |
| `decision_5a` | 48 |
| `excluded_chapter` | 19260 |
| `excluded_emergency` | 15 |
| `not_in_annex` | 185 |

## Selectable per chapter

| Chapter | Categories | Selectable |
|---|---:|---:|
| 01 | 1025 | 1025 |
| 02 | 1247 | 1247 |
| 03 | 262 | 262 |
| 04 | 257 | 257 |
| 05 | 637 | 637 |
| 06 | 858 | 858 |
| 07 | 79 | 79 |
| 08 | 842 | 842 |
| 09 | 703 | 703 |
| 10 | 151 | 151 |
| 11 | 583 | 583 |
| 12 | 344 | 344 |
| 13 | 970 | 970 |
| 14 | 785 | 785 |
| 15 | 426 | 426 |
| 16 | 545 | 545 |
| 17 | 68 | 68 |
| 18 | 522 | 522 |
| 19 | 625 | 623 |
| 20 | 1323 | 1323 |
| 21 | 1241 | 1241 |
| 22 | 1982 | 1982 |
| 23 | 909 | 909 |
| 24 | 851 | 0 |
| 25 | 20 | 5 |
| 26 | 1120 | 0 |
| V | 130 | 0 |
| X | 17159 | 0 |

## Sex and age restrictions (selectable rows)

| Sex | Age | Categories |
|---|---|---:|
| both | infant | 4 |
| both | neonate_infant | 624 |
| female | adult | 522 |
| female | all | 430 |
| male | all | 115 |

| Source of the restriction | Categories |
|---|---:|
| block | 545 |
| chapter 18 | 522 |
| chapter 19 | 623 |
| children | 1 |
| icd10 | 4 |

## Review flags (chapter X excluded)

| Flag | Categories |
|---|---:|
| `children_differ` | 1 |
| `past_written_end` | 12 |
| `rule_overrides_icd10` | 1 |

## Not selectable (rule 3 exclusions outside the excluded chapters)

The never-selectable chapters (`excluded_chapter`: Q, S, V, X) are counted in 'Selectable per chapter' above and not repeated here. Everything else rule 3 excludes: non-RA01 emergency codes (`excluded_emergency`) and KD3B/KD3B.Z (`decision_18_not_selectable`):

- `KD3B` Fetal death, cause not specified (decision_18_not_selectable)
- `KD3B.Z` Unspecified time of fetal death, cause not specified (decision_18_not_selectable)
- `RA00` Conditions of uncertain aetiology and emergency use (excluded_emergency)
- `RA00.0` Vaping related disorder (excluded_emergency)
- `RA04` International emergency code 05 (excluded_emergency)
- `RA05` International emergency code 06 (excluded_emergency)
- `RA06` International emergency code 07 (excluded_emergency)
- `RA07` International emergency code 08 (excluded_emergency)
- `RA08` International emergency code 09 (excluded_emergency)
- `RA09` International emergency code 10 (excluded_emergency)
- `RA20` National emergency code 01 (excluded_emergency)
- `RA21` National emergency code 02 (excluded_emergency)
- `RA22` National emergency code 03 (excluded_emergency)
- `RA23` National emergency code 04 (excluded_emergency)
- `RA24` National emergency code 05 (excluded_emergency)
- `RA25` National emergency code 06 (excluded_emergency)
- `RA26` National emergency code 07 (excluded_emergency)

## Range issues

- none
