---
title: WHO DORIS simple tabular death certificate format (reference copy)
doc_type: kb
status: reference
owner: engineering
last_updated: 2026-09-27
---

> Reference copy of WHO's DORIS documentation page "Simple Tabular Death
> Certificate exchange format" (icd.who.int, DORIS tool), saved 2026-09 and
> converted to Markdown. WHO's page is authoritative. Samples:
> [sample.xlsx](sample.xlsx), [sample.csv](sample.csv).

# Simple Tabular Death Certificate exchange format

This is a specific format used by the Doris Tool as a simple tabular alternative to the standard JSON format.

This format can be used as an Excel (.xlsx) file or as a comma separated text file (.csv).

## Sample Files

You may download small sample files from here:

- [Excel sample (.xlsx)](sample.xlsx)
- [CSV sample (.csv)](sample.csv)

Detailed descriptions of the fields are explained below:

## Used Data types

The data types used are:

| Type | Description |
|---|---|
| string | in CSV files, alphanumeric values need to be in quotation marks ". |
| integer | Numeric field, whole numbers allowed |
| boolean | The values allowed are true and false |
| date | The date field used in the certificate is using the format defined in the W3C. In CSV files, the date value need to be between quotation marks ". |
| durations | Durations define the amount of intervening time in a time interval used in the certificate for the interval field. The format is defined in the ISO_8601. In CSV files, the duration value need to be insert between quotation marks ". |

### Example of date

```text
    Year:
        YYYY (eg 1997)
    Year and month:
        YYYY-MM (eg 1997-07)
    Complete date:
        YYYY-MM-DD (eg 1997-07-16)
    Complete date plus hours and minutes:
        YYYY-MM-DDThh:mmTZD (eg 1997-07-16T19:20+01:00)
    Complete date plus hours, minutes and seconds:
        YYYY-MM-DDThh:mm:ssTZD (eg 1997-07-16T19:20:30+01:00)
    Complete date plus hours, minutes, seconds and a decimal fraction of a second
        YYYY-MM-DDThh:mm:ss.sTZD (eg 1997-07-16T19:20:30.45+01:00)
where:
     YYYY = four-digit year
     MM   = two-digit month (01=January, etc.)
     DD   = two-digit day of month (01 through 31)
     hh   = two digits of hour (00 through 23) (am/pm NOT allowed)
     mm   = two digits of minute (00 through 59)
     ss   = two digits of second (00 through 59)
     s    = one or more digits representing a decimal fraction of a second
     TZD  = time zone designator (Z or +hh:mm or -hh:mm)
```

### Example of duration

The duration is represented by the format P[n]Y[n]M[n]DT[n]H[n]M[n]S, P[n]W or `P<date>T<time>`

In these representations, the [n] is replaced by the value for each of the date and time elements that follow the [n]. Leading zeros are not required, but the maximum number of digits for each element should be agreed to by the communicating parties. The capital letters P, Y, M, W, D, T, H, M, and S are designators for each of the date and time elements and are not replaced.

```text
where:
    P is the duration designator (for period) placed at the start of the duration representation.
    Y is the year designator that follows the value for the number of calendar years.
    M is the month designator that follows the value for the number of calendar months.
    W is the week designator that follows the value for the number of weeks.
    D is the day designator that follows the value for the number of calendar days.
    T is the time designator that precedes the time components of the representation.
    H is the hour designator that follows the value for the number of hours.
    M is the minute designator that follows the value for the number of minutes.
    S is the second designator that follows the value for the number of seconds.
```

To resolve ambiguity, "P1M" is a one-month duration and "PT1M" is a one-minute duration.

### Practical examples

```text
    "PT10S" is a ten seconds duration
    "PT10M" is a ten minutes duration
    "PT10H" is a ten hours duration
    "P5D" is a five days duration
    "P2W" is a two weeks duration
    "P10M" is a ten months duration
    "P10Y" is a ten years duration
    "", "P" or "PT" is used for unknown interval.
```

Note: CauseOfDeath fields can be provided either as code, URI or text. we have individual columns for them. Having just one of them is necessary.

## Field descriptions

| Attribute | Input/Output | Type | Description |
|---|---|---|---|
| CertificateKey | input | string | Can be used to identify the certificate. |
| ICDVersion | input | string | Specify the ICD revision used for the coding of the certificate. DORIS currently supports ICD11 |
| ICDMinorVersion | input | string | Specify the ICD minor version used for the coding of the certificate associated to the ICD version. |
| Sex | input | string | 1: Male, 2: Female, 9: Unknown |
| DateBirth | input | date | see date format above |
| DateDeath | input | date | see date format above |
| EstimatedAge | input | durations | see durations format above |
| CauseOfDeathTextA | input | string | Cause field A. Textual conditions. |
| CauseOfDeathCodeA | input | string | Cause field A. Classification codes comma separated. Its allowed to use post coordination, i.e. “Stem A & Ext 1 / Stem B”. |
| CauseOfDeathURIA | input | string | Cause field A. Classification URI comma separated (Used only for ICD-11). Its allowed to use post coordination, i.e. “Stem A & Ext 1 / Stem B”. |
| IntervalA | input | durations | Time interval from onset to death for Field A. |
| CauseOfDeathTextB | input | string | Cause field B. Textual conditions. |
| CauseOfDeathCodeB | input | string | Cause field B. Classification codes comma separated. Its allowed to use post coordination, i.e. “Stem A & Ext 1 / Stem B”. |
| CauseOfDeathURIB | input | string | Cause field B. Classification URI comma separated (Used only for ICD-11). Its allowed to use post coordination, i.e. “Stem A & Ext 1 / Stem B”. |
| IntervalB | input | durations | Time interval from onset to death for Field B. |
| CauseOfDeathTextC | input | string | Cause field C. Textual conditions. |
| CauseOfDeathCodeC | input | string | Cause field C. Classification codes comma separated. Its allowed to use post coordination, i.e. “Stem A & Ext 1 / Stem B”. |
| CauseOfDeathURIC | input | string | Cause field C. Classification URI comma separated (Used only for ICD-11). Its allowed to use post coordination, i.e. “Stem A & Ext 1 / Stem B”. |
| IntervalC | input | durations | Time interval from onset to death for Field C. |
| CauseOfDeathTextD | input | string | Cause field D. Textual conditions. |
| CauseOfDeathCodeD | input | string | Cause field D. Classification codes comma separated. Its allowed to use post coordination, i.e. “Stem A & Ext 1 / Stem B”. |
| CauseOfDeathURID | input | string | Cause field D. Classification URI comma separated (Used only for ICD-11). Its allowed to use post coordination, i.e. “Stem A & Ext 1 / Stem B”. |
| IntervalD | input | durations | Time interval from onset to death for Field D. |
| CauseOfDeathTextE | input | string | Cause field E. Textual conditions. |
| CauseOfDeathCodeE | input | string | Cause field E. Classification codes comma separated. Its allowed to use post coordination, i.e. “Stem A & Ext 1 / Stem B”. |
| CauseOfDeathURIE | input | string | Cause field E. Classification URI comma separated (Used only for ICD-11). Its allowed to use post coordination, i.e. “Stem A & Ext 1 / Stem B”. |
| IntervalE | input | durations | Time interval from onset to death for Field E. |
| CauseOfDeathTextPart2 | input | string | Cause field Part2. Textual conditions. |
| CauseOfDeathCodePart2 | input | string | Cause field Part2. Classification codes comma separated. Its allowed to use post coordination, i.e. “Stem A & Ext 1 / Stem B”. |
| CauseOfDeathURIPart2 | input | string | Cause field Part2. Classification URI comma separated. Its allowed to use post coordination, i.e. “Stem A & Ext 1 / Stem B”. |
| SurgeryWasPerformed | input | integer | 0: No, 1: Yes, 9: Unknown |
| SurgeryDate | input | date | see date format above |
| SurgeryReason | input | string | If yes, specify reason for surgery (disease or condition). |
| AutopsyWasRequested | input | integer | 0: No, 1: Yes, 9: Unknown |
| AutopsyFindings | input | integer | 0: No, 1: Yes, 9: Unknown |
| MannerOfDeath | input | integer | 0: Disease, 1: Accident, 2: Intentional self harm, 3: Assault, 4: Legal intervention, 5: War, 6: Could not be determined, 7: Pending investigation, 9: Unknown |
| MannerOfDeathDateOfExternalCauseOrPoisoning | input | date | see date format above |
| MannerOfDeathDescriptionExternalCause | input | string | Description external cause. |
| MannerOfDeathPlaceOfOccuranceExternalCause | input | integer | 0: At home, 1: Residential institution, 2: School, other institution, public administration area, 3: Sports and athletics area, 4: Street and highway, 5: Trade and service area, 6: Industrial and construction area, 7: Farm, 8: Other place, 9: Unknown |
| FetalOrInfantDeathMultiplePregnancy | input | integer | 0: No, 1: Yes, 9: Unknown |
| FetalOrInfantDeathStillborn | input | integer | 0: No, 1: Yes, 9: Unknown |
| FetalOrInfantDeathDeathWithin24h | input | integer | If death within 24h specify number of hours survived. |
| FetalOrInfantDeathBirthWeight | input | integer | Birth weight (in grams). |
| FetalOrInfantDeathPregnancyWeeks | input | integer | Number of completed weeks of pregnancy. |
| FetalOrInfantDeathAgeMother | input | integer | Age of mother (years). |
| FetalOrInfantDeathPerinatalDescription | input | string | If death was perinatal, please state condition of mother that affected the fetus and newborn. |
| MaternalDeathWasPregnant | input | integer | 0: No, 1: Yes, 9: Unknown |
| MaternalDeathTimeFromPregnancy | input | integer | 0: "At time of death", 1: "Within 42 days before the death", 2: "Between 43 days up to 1 year before death", 3: "One year or more before death", 9: Unknown |
| MaternalDeathPregnancyContribute | input | integer | 0: No, 1: Yes, 9: Unknown |
| UnderlyingCauseOfDeath | input | string | Manually assigned underlying cause of death provided as code (optional) |
| UnderlyingCauseOfDeathURI | input | string | Manually assigned underlying cause of death provided as a linearization URI (optional) |
| Reject | output | boolean | false if the computation was able to select the underlying cause of death, true otherwise. The computation can fail for multiple reasons (codes not found in the specific linearization, implausibility of the coding, errors of the system.). The reason can be identified in the file logger or rule logger fields. |
| Report | output | string | Overview of the steps used by the rule engine to select the Underlaying cause of death. |
| Errors | output | string | Report field used in case errors occur during computation or rule engine has failed the computation. |
| Warnings | output | string | Report field used in case the rule engine triggered warnings during the computation. |
| UnderlyingCauseOfDeathComputed | output | string | Underlying cause of death computed by the system as code. (stem code only) |
| UnderlyingCauseOfDeathComputedURI | output | string | Underlying cause of death computed by the system as URI (stem code only) |
| UnderlyingCauseOfDeathComputedComplete | output | string | Underlying cause of death computed by the system (may include postcoordination combination) |
| UnderlyingCauseOfDeathComputedCompleteURI | output | string | Underlying cause of death computed by the system as linearization URI (may include postcoordination combination) |

