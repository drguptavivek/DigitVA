---
title: ODK XLSForm rows for DORIS prefill support
doc_type: kb
status: active
owner: engineering
last_updated: 2026-09-29
---

# ODK XLSForm rows for DORIS prefill support

Generated from the web form's `doris_support_whova_2022` extension
(`vendor/who-va-2022/src/digitva-extension.ts`) by
`tooling/who-va-2022/build-odk-doris-rows.mjs` and
`tooling/who-va-2022/build_odk_doris_rows.py`; edit the extension, not
this file. The same rows, paste-ready with ND01's own columns, are in
`docs/kb/WHO_VA_2022_Docs/odk-doris-support-rows.xlsx` (sheets `survey`,
`choices`, and `notes` saying where each block goes).

The rows are Annex A (A1-A10) of
`docs/kb/DORIS/who-va-2022-doris-consistency-proposal.md`. Every web form
asks them, so ODK and web payloads share one shape and
`app/services/doris_prefill.py` reads both alike (bead `digitva-hln`).
A1, A2 and A3 are agreed for deployment; the rest are proposed, and the
owner decides what each site deploys. Deploying to ODK Central (bump
`settings.version`) is the owner's step.

Positions are rows of the ND01 workbook (`ND01_ICMRVA_WHOVA2022.xlsx`).
ND01 row numbers are those of the unmodified workbook: apply the blocks bottom-up (A8, A7, A4, A2, A5, A10, A9, A6, A3, A1) so the numbers stay valid. Add the choices at the end of the choices sheet. Hindi and other label columns follow each workbook's languages. Bump settings.version before deploying.
The other nine deployed workbooks carry the same questions at equivalent
places. Columns not shown stay empty; only English is given.
Integers follow the form's 88 = refused, 99 = don't know. `YES_NO_DK_REF`
is the workbook's existing list.

## A1. Partial date of birth (agreed for deployment)

- Add `dob_precision`, `dob_month_year`, `dob_year` after `Id10021` (ND01 row 51).

| type | name | label::English (en) | relevant | constraint | constraint_message | required | appearance |
|---|---|---|---|---|---|---|---|
| select_one dob_precision | dob_precision | Is the month and year, or only the year, of birth known? | `selected(${Id10020}, 'no') or selected(${Id10020}, 'ref')` |  |  |  |  |
| date | dob_month_year | In which month and year was the deceased born? | `selected(${dob_precision}, 'month_year')` | `. <= today() and (string-length(${Id10023}) = 0 or . <= ${Id10023})` | Cannot be in the future or after the death |  | month-year |
| date | dob_year | In which year was the deceased born? | `selected(${dob_precision}, 'year')` | `. <= today() and . >= date('1900-01-01')` | Cannot be in the future |  | year |

Choices:

| list_name | name | label::English (en) |
|---|---|---|
| dob_precision | month_year | Month and year known |
| dob_precision | year | Only the year known |
| dob_precision | neither | Neither known |

Id10020/Id10021 keep WHO's meaning (full date only) and the WHO age questions still run, so ageInDays and the age groups are unchanged. ODK stores dob_month_year as YYYY-MM-01 and dob_year as YYYY-01-01. Id10023 is calculated later in the form; while it is empty the death check is skipped. Interviewer guidance for Id10020: answer YES only when day, month and year are all known; never enter the 1st or 1 January for an unknown day or month.

## A2. Birth weight check (agreed for deployment)

- Replace ND01 row 479 (`Id10366`): constraint, constraint_message.
- Add `Id10366_confirm` after `Id10366` (ND01 row 479).

| type | name | label::English (en) | relevant | constraint | constraint_message | required | appearance |
|---|---|---|---|---|---|---|---|
| integer | Id10366 | (Id10366) What was the weight (in grammes) of the deceased at birth? |  | `. >= 100 and . <= 9999` | Enter the weight in grammes, not kilogrammes. 1 kg = 1,000 g. | yes |  |
| acknowledge | Id10366_confirm | A birth weight of ${Id10366} g is unusual. Check the card and confirm the weight is in grammes. | `${Id10366} < 500 or ${Id10366} > 6000` |  |  | yes |  |

Replace the existing Id10366 row, then add Id10366_confirm after it, inside group g10366 (whose relevance already limits both to under one year with the health card). A card without a weight is answered Id10366_check = no; 0 is no longer accepted.

## A3. Hours survived (agreed for deployment)

- Add `doris_hours_survived` after `Id10114` (ND01 row 165).

| type | name | label::English (en) | relevant | constraint | constraint_message | required | appearance |
|---|---|---|---|---|---|---|---|
| integer | doris_hours_survived | For how many hours did the baby live? | `selected(${isNeonatal}, '1') and selected(${Id10020}, 'yes') and selected(${Id10022}, 'yes') and ${ageInDays} = 0 and not(selected(${Id10114}, 'yes'))` | `(. >= 0 and . <= 23) or . = 88 or . = 99` | Enter 0 to 23 hours |  |  |

In the stillbirth group. ageInDays is ${Id10023} - ${Id10021}, so 0 exactly when the recorded birth and death dates are the same day; age_neonate_hours is asked only when a date is missing.

## A4. Pregnancy length in weeks (proposed)

- Add `doris_pregnancy_weeks` after `Id10367` (ND01 row 483).

| type | name | label::English (en) | relevant | constraint | constraint_message | required | appearance |
|---|---|---|---|---|---|---|---|
| integer | doris_pregnancy_weeks | How many completed weeks long was the pregnancy? (only if known, e.g. from an antenatal card) | `selected(${isNeonatal}, '1') or (selected(${isChild}, '1') and ${ageInMonthsByYear}<12)` | `(. >= 8 and . <= 48) or . = 88 or . = 99` | Enter 8 to 48 weeks |  |  |

## A5. Mother's age (proposed)

- Add `doris_mother_age` after `Id10354` (ND01 row 475).

| type | name | label::English (en) | relevant | constraint | constraint_message | required | appearance |
|---|---|---|---|---|---|---|---|
| integer | doris_mother_age | How old was the baby's mother, in completed years, when the baby was born? | `selected(${isNeonatal}, '1') or (selected(${isChild}, '1') and ${ageInMonthsByYear}<12)` | `(. >= 10 and . <= 60) or . = 88 or . = 99` | Enter 10 to 60 years |  |  |

## A6. External cause (proposed)

- Add `doris_injury_date_known`, `doris_injury_date`, `doris_injury_month_year`, `doris_injury_place`, `doris_injury_legal_war` after `Id10077_b` (ND01 row 200).

| type | name | label::English (en) | relevant | constraint | constraint_message | required | appearance |
|---|---|---|---|---|---|---|---|
| select_one injury_date_known | doris_injury_date_known | Is the date of the injury known? | `selected(${Id10077}, 'yes')` |  |  |  |  |
| date | doris_injury_date | On what date was (s)he injured? | `selected(${doris_injury_date_known}, 'full')` | `. <= today() and (string-length(${Id10023}) = 0 or . <= ${Id10023})` | Cannot be after the death |  | no-calendar |
| date | doris_injury_month_year | In which month and year was (s)he injured? | `selected(${doris_injury_date_known}, 'month_year')` | `. <= today() and (string-length(${Id10023}) = 0 or . <= ${Id10023})` | Cannot be after the death |  | month-year |
| select_one injury_place | doris_injury_place | Where did the injury happen? | `selected(${Id10077}, 'yes')` |  |  |  |  |
| select_one legal_war | doris_injury_legal_war | Was the injury from police or legal action, or from war? | `selected(${Id10077}, 'yes')` |  |  |  |  |

Choices:

| list_name | name | label::English (en) |
|---|---|---|
| injury_date_known | full | Full date |
| injury_date_known | month_year | Month and year |
| injury_date_known | unknown | Not known |
| injury_place | 0 | At home |
| injury_place | 1 | Residential institution |
| injury_place | 2 | School, other institution, public administration area |
| injury_place | 3 | Sports and athletics area |
| injury_place | 4 | Street and highway |
| injury_place | 5 | Trade and service area |
| injury_place | 6 | Industrial and construction area |
| injury_place | 7 | Farm |
| injury_place | 8 | Other place |
| injury_place | 9 | Unknown |
| legal_war | legal | Police or legal action |
| legal_war | war | War |
| legal_war | neither | Neither |
| legal_war | dk | Doesn't know |

After Id10077_a and its confirmation Id10077_b, so the two stay together.

## A7. Surgery (proposed)

- Add `doris_surgery_performed`, `doris_surgery_when`, `doris_surgery_when_unit`, `doris_surgery_type`, `doris_surgery_reason` after the `end group` of `health_service_utilization` (ND01 row 540).

| type | name | label::English (en) | relevant | constraint | constraint_message | required | appearance |
|---|---|---|---|---|---|---|---|
| select_one YES_NO_DK_REF | doris_surgery_performed | Did (s)he have an operation before death? | `not(selected(${Id10114}, 'yes'))` |  |  |  |  |
| integer | doris_surgery_when | How long before death was the operation? (number) | `selected(${doris_surgery_performed}, 'yes')` | `. >= 0 or . = 88 or . = 99` | Enter a number, 88 if refused or 99 if not known |  |  |
| select_one time_unit | doris_surgery_when_unit | Unit | `selected(${doris_surgery_performed}, 'yes') and ${doris_surgery_when} != 88 and ${doris_surgery_when} != 99` |  |  |  |  |
| text | doris_surgery_type | What operation was done? | `selected(${doris_surgery_performed}, 'yes')` |  |  |  |  |
| text | doris_surgery_reason | For what illness or condition was it done? | `selected(${doris_surgery_performed}, 'yes')` |  |  |  |  |

Choices:

| list_name | name | label::English (en) |
|---|---|---|
| time_unit | days | Days |
| time_unit | weeks | Weeks |
| time_unit | months | Months |
| time_unit | years | Years |

After the health_service_utilization group closes, still inside illhistory: that group is skipped for stillbirths and for injury deaths within 7 days, and surgery is asked of every death except stillbirths. The certificate's surgery within 4 weeks is doris_surgery_when <= 28 days.

## A8. Autopsy (proposed)

- Add `doris_autopsy_requested`, `doris_autopsy_findings` after `Id10473` (ND01 row 564).

| type | name | label::English (en) | relevant | constraint | constraint_message | required | appearance |
|---|---|---|---|---|---|---|---|
| select_one YES_NO_DK_REF | doris_autopsy_requested | Was an autopsy (post-mortem examination) requested? |  |  |  |  |  |
| select_one YES_NO_DK_REF | doris_autopsy_findings | Were the autopsy findings made available? | `selected(${doris_autopsy_requested}, 'yes')` |  |  |  |  |

Last rows of the deathcert group. The web form has DigitVA's medical-certificate upload after Id10473 and places these after it.

## A9. Id10308 required (proposed)

- Replace ND01 row 442 (`Id10308`): required.

| type | name | label::English (en) | relevant | constraint | constraint_message | required | appearance |
|---|---|---|---|---|---|---|---|
| select_one YES_NO_DK_REF | Id10308 | (Id10308) Did she die less than 1 year after delivery, abortion or miscarriage? | `not(selected(${Id10312}, 'yes')) and not(selected(${Id10305}, 'yes')) and not(selected(${Id10299}, 'yes') and ${ageInYears2}>49)   and not(selected(${Id10306}, 'yes')) and not(selected(${Id10334}, 'yes')) and not(selected(${Id10314}, 'yes'))` |  |  | yes |  |

## A10. Id10340 relevance (proposed)

- Replace ND01 row 471 (`Id10340`): relevant.

| type | name | label::English (en) | relevant | constraint | constraint_message | required | appearance |
|---|---|---|---|---|---|---|---|
| select_one YES_NO_DK_REF | Id10340 | (Id10340) Did she have an operation to remove her uterus shortly before death? | `(selected(${Id10312}, 'yes') or selected(${Id10313}, 'yes') or selected(${Id10334}, 'yes') or selected(${Id10308}, 'yes')) and not(selected(${Id10077_a}, 'less'))` |  |  | yes |  |
