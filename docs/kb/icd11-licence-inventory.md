---
title: ICD-11 licence inventory (mappings, crosswalks, translations)
doc_type: kb
status: draft
owner: engineering
last_updated: 2026-10-22
---

# ICD-11 licence inventory

Input to the owner's decision on a separate WHO written agreement (licence
1.2.3: mappings/crosswalks and translations of ICD-11 need one). Bead
`digitva-zde8`. This lists what DigitVA ships; it does not decide anything.
Obligations we already meet in code are in
`docs/policy/icd11-local-api-runtime.md` ("ICD-11 licence obligations").

## A. Mappings and crosswalks involving ICD-11

| What | Where | Content |
| --- | --- | --- |
| WHO 2022 VA cause list, ICD-10 and ICD-11 columns | `resource/who_2022_va_cause_list_icd10_icd11.csv` (65 rows); copy at `docs/icd-causegrp-mappings/ICD-to-VA-Buckets/` | VA cause (`VAs-xx.yy`) to ICD-10 and ICD-11 code ranges. Source is the WHO 2022 VA instrument annex. |
| Owner decisions on the ICD-11 side | `docs/icd-causegrp-mappings/ICD-to-VA-Buckets/who_2022_va_icd11_owner_decisions.csv`; migrations `dc762caa67dd_*`, `d3a9c5e1f7b2_*` | DigitVA's own choices where WHO ICD-11 mapping was missing or disputed. |
| ICD-11 code to VA bucket, native (18,505 rows) | `resource/who_2022_va_2026_icd11_native_mappings.csv` (+ dated copy `_2026-09-21`); loaded by migration `6c11b620f48f_seed_who_2022_va_2026_icd11_native_mappings.py` into `map_icd_cod_bucket` (`app/models/mas_cod_bucket.py`) | One row per ICD-11 2026-01 code or range: scheme, `icd_code`, VA bucket node, match type, note. This is a DigitVA crosswalk ICD-11 to VA cause. |
| Generated draft and review files | `docs/icd-causegrp-mappings/migration-artifacts/who-2022-va-icd11-native-2026-09-21/` (`icd11_generated_mappings.csv`, `icd11_review.csv`) and `who-2022-icd11-policy-draft-2026-09-24/` (`icd11_policy_review.csv`, `who_2022_icd11_mms_2026_01_policy_draft.json`) | Generator output (`app/services/cod_bucket_icd11_generator.py`, `app/services/icd11_policy_draft_service.py`); repo-only, not served. |
| WHO ICD-10 to ICD-11 map tables (WHO's own files, redistributed in the repo) | `docs/icd-causegrp-mappings/migration-artifacts/icd11-icd10-mapping-tables-2025-01-base-2026-09-16/` (`10To11MapTo*Categor*.txt/.xlsx`, `11To10MapToOneCategory`, foundation variants); also `docs/kb/ICD10-ICD11-mapping*` | WHO-published crosswalk, unmodified. Used at runtime by `app/services/icd11_policy_draft_service.py::load_icd10_to_icd11` (reads `10To11MapToOneCategory.txt`). Check whether WHO's own redistribution terms cover the repo copy. |
| SmartVA cause to ICD-10 | `app/utils/va_smartva/va_smartva_01_icdcodes.py` (`VA_SMARTVA_ICDS`) | SmartVA cause name to one ICD-10 code per age group. ICD-10 only. |
| SmartVA ICD-10 result to ICD-11 display | `app/services/smartva_icd11.py` (`smartva_icd11_mapping`), applied to SmartVA results in `app/services/icd11_titles.py` and the coding screens | Looks up the SmartVA ICD-10 code in WHO's `10To11MapToOneCategory` table (above) and shows the full target expression. Read only, nothing stored. SmartVA itself (server and `desktop/crates/digitva-smartva`) emits no ICD-11. |
| Public mapping pages and CSVs | `app/services/va_code_mapping_public_service.py`, `app/routes/help.py` (`/help/va-code-mappings`, `/help/va-code-mappings.csv`, `/help/icd11-codes.csv`); annex file name `who_2022_va_cause_list_icd10_icd11.csv` | Serves the crosswalks above to anyone, and the ICD-11 state CSV (code, title, `linearization_uri`, chapter, block, policy, VA cause). |
| COD bucket schemes exports | `app/services/cod_bucket_mapping_service.py` (`export_cod_bucket_scheme_json`, `export_public_cod_bucket_scheme`, `export_cod_bucket_scheme_xlsx`) | ICD-10 and ICD-11 code to bucket mappings for the WHO, SRS India and CMEA10 schemes. These exports do not yet carry the WHO citation. |
| Search vocabulary | `resource/icd_search_vocabulary_seed.csv` (391 rows: 211 ICD-10, 177 ICD-11), table `mas_icd_search_terms` | Clinician terms (e.g. shorthand) mapped to an ICD code. 177 rows map a DigitVA term to an ICD-11 code. Admin can add terms and export CSV (`/admin/api/icd-search-vocabulary/export.csv`). |
| WHO-derived DORIS help examples | `resource/doris_help_examples.json` | Example certificates with ICD-11 codes written by DigitVA for the help page. |

## B. DigitVA fields added to ICD-11 concepts (licence 1.2.4)

| What | Where | Marked "not from WHO"? |
| --- | --- | --- |
| Coding policy per ICD-11 category: `policy_status`, `is_coding_selectable`, `sex_selectable`, `age_group_selectable`, `restriction_note` | table `mas_icd11_mms` (`app/models/mas_icd11_mms.py`), `resource/icd11_mms_2026_01_policy_signoff_2026_09_29.json`, admin ICD-11 browser and public `/help/icd11-codes` | No. Shown beside WHO titles in the browser; the page carries the WHO citation but no per-column label. Owner decision needed. |
| VA cause definitions | `resource/va_cause_definitions_who_2022.json`, table `mas_va_cause_definitions`, `/api/v1/va-definitions` | Yes: UI label and `source: "digitva"` in the coder API payloads. Text is from the WHO 2022 VA manual, not WHO ICD-11. |
| ICD-11 definitions | `resource/icd11_definitions_2026_01.json` | WHO text (from the WHO API), not a DigitVA addition. |

## C. ICD-11 translations

None found. The WHO ICD-11 engine is called with `Accept-Language: en` only
(`app/services/who_icd_api.py` lines 130 and 192). Hindi and other
translations in the repo cover the VA questionnaire and DigitVA UI text, not
ICD-11 titles:

- `resource/instrument_translations_hi_edited_2026_10_19.xlf`, `resource/instrument_notes_hi_2026_10_06.csv` (questionnaire).
- `resource/digitva_layer_translations_2026_09_20.csv` (214 rows, DigitVA instrument layer in about 15 locales).
- `mobile/digitva-collect/src/strings/hi.json` (app text). The ICD-11 citation key is English in `hi.json` on purpose: the licence wording is not ours to translate.

## D. Not an ICD-11 crosswalk, listed for completeness

- `resource/icd11_mms_2026_01_hierarchy.csv` (37,152 rows) and table `mas_icd11_mms`: WHO MMS 2026-01 linearization (code, title, hierarchy, URIs) as downloaded, plus the DigitVA policy columns in section B.
- ICD-10 2019 catalogue (`docs/icd-causegrp-mappings/migration-artifacts/icd10-2019-base-2026-04-27/`): ICD-10, outside this licence.
- SRS India and CMEA10 bucket files: ICD-10 to cause-group maps from third parties.

## Decisions for the owner

1. Is the WHO-VA-cause to ICD-11 crosswalk (section A, rows 1 to 4, and the public pages/CSVs that serve it) a "mapping" that needs the WHO agreement?
2. Does the repo copy of WHO's ICD-10/11 map tables, and its use for the SmartVA ICD-11 display, fall under WHO's own redistribution terms?
3. Should the policy columns (section B) get a visible "DigitVA addition" label in the ICD-11 browser?
4. Bucket-scheme exports (section A) still lack the WHO citation row; add it once the owner confirms they count as ICD-11 exports.
