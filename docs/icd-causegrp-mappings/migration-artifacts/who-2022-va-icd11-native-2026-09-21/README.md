---
title: WHO 2022 VA native ICD-11 buckets, generator report (WHO_2022_VA_2026)
doc_type: reference
status: draft
owner: engineering
last_updated: 2026-09-21
---

# WHO 2022 VA native ICD-11 buckets: generator report (WHO_2022_VA_2026)

Written by `flask cod-buckets generate-icd11`. Policy: `docs/policy/icd11-cod-bucket-schemes.md`. Source: `docs/icd-causegrp-mappings/ICD-to-VA-Buckets/who_2022_va_cause_list_icd10_icd11.csv`, catalogue release `2026-01`, crosswalk `docs/icd-causegrp-mappings/migration-artifacts/icd11-icd10-mapping-tables-2025-01-base-2026-09-16/11To10MapToOneCategory.txt` (2025-01, 2026-01 codes translated through the change list).

## Totals

- Catalogue categories (chapter X excluded): 18505
- Generated mappings: 16154 (range 16078, split 76)
- Unmapped: 2351 no_range 2351

## Review items (`icd11_review.csv`)

- `crosswalk_disagreement`: 916
- `node_matched_by_label`: 1
- `pa_split`: 71
- `pj2x_owner_decision`: 5
- `range_issue`: 5
- `range_past_end`: 3

## Codes per cause

| VA code | Cause | Codes |
|---|---|---:|
| VAs-01.01 | Sepsis | 2 |
| VAs-01.02 | Acute respiratory infection, including pneumonia | 77 |
| VAs-01.03 | HIV/AIDS related death | 27 |
| VAs-01.04 | Diarrheal diseases | 67 |
| VAs-01.05 | Malaria | 16 |
| VAs-01.06 | Measles | 5 |
| VAs-01.07 | Meningitis and encephalitis | 52 |
| VAs-01.08 | Tetanus | 2 |
| VAs-01.09 | Pulmonary tuberculosis | 4 |
| VAs-01.10 | Pertussis | 5 |
| VAs-01.11 | Haemorrhagic fever | 50 |
| VAs-01.12 | Dengue fever | 4 |
| VAs-01.13 | Coronavirus disease (COVID-19) | 2 |
| VAs-01.99 | Unspecified infectious disease | 865 |
| VAs-98 | Other and unspecified non-communicable disease | 6168 |
| VAs-02.01 | Oral neoplasms | 34 |
| VAs-02.02 | Digestive neoplasms | 139 |
| VAs-02.03 | Respiratory neoplasms | 73 |
| VAs-02.04 | Breast neoplasms | 15 |
| VAs-02.05 | Female reproductive neoplasms | 66 |
| VAs-02.06 | Male reproductive neoplasms | 19 |
| VAs-02.99 | Other and unspecified neoplasms | 901 |
| VAs-03.01 | Severe anaemia | 118 |
| VAs-03.02 | Severe malnutrition | 8 |
| VAs-03.03 | Diabetes mellitus | 14 |
| VAs-04.01 | Acute cardiac disease | 46 |
| VAs-04.02 | Stroke | 98 |
| VAs-04.03 | Sickle cell with crisis | 15 |
| VAs-04.99 | Other and unspecified cardiac disease | 558 |
| VAs-05.01 | Chronic obstructive pulmonary disease (COPD) | 21 |
| VAs-05.02 | Asthma | 17 |
| VAs-06.01 | Acute abdomen | 10 |
| VAs-06.02 | Liver cirrhosis | 10 |
| VAs-07.01 | Renal failure | 15 |
| VAs-08.01 | Epilepsy | 88 |
| VAs-09.01 | Ectopic pregnancy | 6 |
| VAs-09.02 | Abortion-related death | 57 |
| VAs-09.03 | Pregnancy-induced hypertension | 25 |
| VAs-09.04 | Obstetric haemorrhage | 24 |
| VAs-09.05 | Obstructed labour | 30 |
| VAs-09.06 | Pregnancy-related sepsis | 9 |
| VAs-09.07 | Anaemia of pregnancy | 1 |
| VAs-09.0 | Ruptured uterus | 2 |
| VAs-09.99 | Other and unspecified maternal cause | 366 |
| VAs-10.01 | Prematurity or low birth weight | 48 |
| VAs-10.02 | Birth asphyxia | 22 |
| VAs-10.03 | Neonatal pneumonia | 8 |
| VAs-10.04 | Neonatal sepsis | 1 |
| VAs-10.05 | Neonatal tetanus | 1 |
| VAs-10.06 | Congenital malformation | 1376 |
| VAs-10.99 | Other and unspecified perinatal cause of death | 552 |
| VAs-11.01 | Fresh stillbirth | 1 |
| VAs-11.02 | Macerated stillbirth | 1 |
| VAs-12.01 | Road traffic accident | 18 |
| VAs-12.02 | Other transport accident | 53 |
| VAs-12.03 | Accidental fall | 3 |
| VAs-12.04 | Accidental drowning and submersion | 4 |
| VAs-12.05 | Accidental exposure to smoke, fire and flames | 13 |
| VAs-12.06 | Contact with venomous animals and plants | 2 |
| VAs-12.07 | Accidental poisoning and exposure to noxious substance | 17 |
| VAs-12.08 | Intentional self-harm | 99 |
| VAs-12.09 | Assault | 114 |
| VAs-12.10 | Exposure to force of nature | 9 |
| VAs-12.99 | Other and unspecified external cause of death | 2563 |
| VAs-99 | Unknown and ill-defined cause of death | 1118 |

## Notes

- Stillbirths: ICD-11 splits them (KD3B.1 intrapartum fetal death -> VAs-11.01 Fresh stillbirth, KD3B.0 -> VAs-11.02 Macerated stillbirth). ICD-10 cannot: P95 stays with Macerated stillbirth in the ICD-10 rows, so the two classifications count fresh stillbirths differently.

## Files

- `icd11_generated_mappings.csv`: one row per generated mapping, with the crosswalk ICD-10 target and its bucket in the curated `WHO_2022_VA` scheme and in this scheme's own ICD-10 rows.
- `icd11_review.csv`: ties (not mapped), PJ2x owner decisions, PA split verification, crosswalk disagreements, range issues and ranges reaching past their written end.
- `icd11_unmapped_with_suggestion.csv`: catalogue codes without a mapping, with the crosswalk's suggested bucket (not applied).
