---
title: WHO CoDEdit and DORIS report message identifiers (reference copy)
doc_type: kb
status: reference
owner: engineering
last_updated: 2026-09-27
---

> Reference copy of WHO's page "CODEDIT Report Message Identifiers (ICD-API documentation)" on icd.who.int, saved 2026-09 and
> converted to Markdown. WHO's page is authoritative. DigitVA's generated message table is `app/static/js/codedit_messages.js` (`scripts/generate_codedit_messages.py`).

# CODEDIT Report Message Identifiers

This document describes the identifiers used in CODEDIT report messages.

## Identifier Structure

The identifiers used in CODEDIT and DORIS follow the structure:

``` text
{Source}-{System}-{RuleID}  
```

Where:

| Component | Description |
|----|----|
| Source | Specifies where the rule is evaluated. Currently supported values are: `FER` (Front-End Rule) and `BER` (Back-End Rule). |
| System | Specifies the system associated with the rule. Currently supported values are: `CE` (CoDEdit) and `DRS` (DORIS). |
| RuleID | Numeric or textual identifier associated with the specific rule, validation, or recommendation. |

Examples:

| Identifier | Description                                |
|------------|--------------------------------------------|
| FER-CE-873 | Front-end CoDEdit rule with identifier 873 |
| BER-CE-2   | Back-end CoDEdit rule with identifier 2    |

## Front-End Rule Identifiers (FER)

Front-end rule identifiers follow the structure:

``` text
FER-CE-{RuleID}
```

The `RuleID` corresponds to the same identifier used in the Mortality Platform rules documentation.\
For this reason, the full list of FER rules is not duplicated in this document and should be consulted directly in the Mortality Platform.

Example:

| Identifier | Description                                       |
|------------|---------------------------------------------------|
| FER-CE-873 | Front-end CoDEdit validation rule with RuleID 873 |

------------------------------------------------------------------------

## Back-End Rule Identifiers (BER)

Back-end rule identifiers follow the structure:

``` text
BER-CE-{RuleID}
```

The following table lists the currently available back-end rule identifiers.

| Identifier | Message Identifier / Description |
|----|----|
| BER-CE-1 | An injury has been reported ({0}) without a corresponding external cause code. It is recommended to review the MCCD and ensure that the appropriate external cause code is included in accordance with ICD mortality reporting standards. |
| BER-CE-2 | The sex of the deceased is missing. It is recommended to review the MCCD and complete this mandatory field to ensure data completeness and quality. |
| BER-CE-3 | The age of the deceased is missing. Please include the value and units where applicable. It is recommended to review the MCCD and complete this mandatory field to ensure data completeness and quality. |
| BER-CE-4 | No cause(s) of death are recorded in Part I or Part II of the MCCD. It is recommended to review the certificate and enter at least one cause of death in Part I to ensure data completeness. |
| BER-CE-5 | Age cannot be calculated as the date of birth provided is later than the date of death. |
| BER-CE-6 | Sex value is not valid: Only values 1: Male, 2: Female, 9: Unknown are recognized values. |
| BER-CE-7 | The interval entered ({0}) is not in a valid format. It is recommended to check the format of the duration and correct it on the MCCD. |
| BER-CE-8 | {0} could not be found in the linearization MMS. |
| BER-CE-9 | The selected code - {0} - and URI - {1} - correspond to different ICD entities for the same condition. Please verify that the code and the associated URI refer to the same ICD category. |
| BER-CE-10 | {0} is not a terminal code in the MMS linearization. |
| BER-CE-11 | SurgeryWasPerformed value is not valid: The values 0: No, 1: Yes, 9: Unknown are recognized values. |
| BER-CE-12 | AutopsyWasRequested value is not valid: The values 0: No, 1: Yes, 9: Unknown are recognized values. |
| BER-CE-13 | AutopsyFindings value is not valid: The values 0: No, 1: Yes, 9: Unknown are recognized values. |
| BER-CE-14 | MannerOfDeath value is not valid. The values 0: Disease, 1: Accident, 2: Intentional self harm, 3: Assault, 4: Legal intervention, 5: War, 6: Could not be determined, 7: Pending investigation, 9: Unknown are recognized values. |
| BER-CE-15 | PlaceOfOccuranceExternalCause value is not valid. The values 0: At home, 1: Residential institution, 2: School, other institution, public administration area, 3: Sports and athletics area, 4: Street and highway, 5: Trade and service area, 6: Industrial and construction area, 7: Farm, 8: Other place, 9: Unknown are recognized values. |
| BER-CE-16 | FetalOrInfantDeathMultiplePregnancy value is not valid: The values 0: No, 1: Yes, 9: Unknown are recognized values. |
| BER-CE-17 | FetalOrInfantDeathStillborn value is not valid: The values 0: No, 1: Yes, 9: Unknown are recognized values. |
| BER-CE-18 | MaternalDeathWasPregnant value is not valid: The values 0: No, 1: Yes, 9: Unknown are recognized values. |
| BER-CE-19 | MaternalDeathTimeFromPregnancy value is not valid: The values 0: At time of death, 1: Within 42 days before the death, 2: Between 43 days up to 1 year before death, 3: One year or more before death, 9: Unknown are recognized values. |
| BER-CE-20 | MaternalDeathPregnancyContribute value is not a valid value: The values 0: No, 1: Yes, 9: Unknown are recognized values. |
| BER-CE-21 | The reported duration of the condition - {0} - exceeds the age of the deceased. Please verify the interval and age information for plausibility. |
| BER-CE-22 | The reported duration of the condition – {0} – exceeds the duration of the last condition in Part I. Please verify the intervals for plausibility. |
| \> **Note:** In some back-end rule messages, placeholders such as `{0}` and `{1}` are used. These placeholders are dynamically replaced with the condition or diagnosis involved in the corresponding validation or recommendation message. |  |
| \> |  |
| --- |  |

# Dashboard Groupings

Within DORIS / CoDEdit Desktop, report message identifiers are grouped into dashboard validation categories.

## Dashboard Validation Groups

| Dashboard Group | Included Identifiers |
|----|----|
| Demographic Plausibility Checks | FER-CE-873, FER-CE-874, FER-CE-899, FER-CE-923, FER-CE-892, FER-CE-893, FER-CE-896, FER-CE-897, FER-CE-900, FER-CE-901, FER-CE-903, FER-CE-907, FER-CE-909, FER-CE-911, FER-CE-912, FER-CE-921, FER-CE-922, FER-CE-908, FER-CE-898, FER-CE-902, FER-CE-904, FER-CE-905, FER-CE-906, FER-CE-915, FER-CE-916, FER-CE-910, FER-CE-913, FER-CE-914, FER-CE-917, FER-CE-918, FER-CE-920, FER-CE-919, FER-CE-924, FER-CE-894, FER-CE-891, FER-CE-895, FER-CE-935, FER-CE-990 |
| Public Health Surveillance Checks | FER-CE-888, FER-CE-994 |
| Medical Certification Quality Checks | FER-CE-931, FER-CE-932 |
| Minimum Recommended Data Entry Check | BER-CE-2, BER-CE-3, BER-CE-4 |
| Maternal & Pregnancy-Related Checks | FER-CE-993, FER-CE-997, FER-CE-933, FER-CE-928 |
| Fetal & Perinatal Checks | FER-CE-929, FER-CE-934, FER-CE-987 |
| ICD-11 Coding Validity Checks | BER-CE-8, BER-CE-9, BER-CE-10 |
| Injury & External Cause Checks | BER-CE-1, FER-CE-890 |
| Formatting Checks | BER-CE-5, BER-CE-6, BER-CE-7, BER-CE-11, BER-CE-12, BER-CE-13, BER-CE-14, BER-CE-15, BER-CE-16, BER-CE-17, BER-CE-18, BER-CE-19, BER-CE-20, FER-CE-883 |
| Duration & Chronological Consistency Checks | BER-CE-21, BER-CE-22 |
| Other checks | No identifiers currently assigned |
