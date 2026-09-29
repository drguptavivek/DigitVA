---
title: Proposal to WHO, aligning the WHO 2022 VA instrument with the DORIS death certificate
doc_type: kb
status: draft
owner: engineering
last_updated: 2026-09-29
---

# Proposal: aligning the WHO 2022 VA instrument with the DORIS death certificate

Draft for the WHO VA reference group and the maintainers of the WHO VA
XLSForm (SwissTPH/WHO-VA). Not yet sent. Bead `digitva-hln`.

## Summary

Physicians who certify a verbal autopsy in WHO DORIS fill the international
death certificate: Part I/II causes plus administrative, fetal or infant,
maternal, external cause, surgery and autopsy items. The WHO 2022 VA
interview already answers most of those items, but some cannot be taken
from it, some only approximately, and a few questions produce data that
look more precise than they are.

We propose ten small, backward-compatible changes to the 2022 instrument:
new optional questions, one new check on an existing answer, one required
flag and one relevance fix. None changes an existing variable's meaning, so
the InterVA / InSilicoVA / SmartVA inputs and existing analyses are
unaffected. Annex A gives each change as XLSForm rows, based on the V1.1
form (`va_who_2022`, version `2023072701`).

Evidence comes from 8,271 interviews collected with the deployed V1.1
XLSForm in a multi-site verbal autopsy programme (aggregate counts only; no
site or individual is identifiable).

## How the VA maps to DORIS today

| DORIS item | Taken from the VA | Gap |
|---|---|---|
| Sex, date of birth, date of death, estimated age | Id10019, Id10020/21, Id10022/23/24, age questions | date of birth has no partial form (proposal 1) |
| Stillborn | Id10104, Id10109, Id10110, Id10114 | none |
| Death within 24 h (hours survived) | `age_neonate_hours`, only asked when a date is missing | proposal 3 |
| Multiple pregnancy | Id10354 | none |
| Birth weight | Id10366 | units (proposal 2) |
| Pregnancy length (completed weeks) | Id10367 is in months | proposal 4 |
| Mother's age | not asked | proposal 5 |
| Pregnant / time from pregnancy | Id10305, 10312, 10313, 10314, 10306, 10334, 10308, 10310 | Id10308 optional (proposal 9) |
| Manner of death | Id10077, 10095, 10098, 10099, 10100 | legal intervention and war (proposal 6) |
| Date and place of external cause | Id10077_a (<= 7 days or more); Id10058 is place of death | proposal 6 |
| Surgery within 4 weeks, date, reason | Id10425/Id10426 ("have or need"; 1 month; not for neonates) | proposal 7 |
| Autopsy requested; findings used | not asked | proposal 8 |
| Pregnancy contributed; perinatal description; causes | certifier's judgement | none (stays with the physician) |

## Proposals

### 1. Partial date of birth

**Problem.** Id10021 is a full-date entry. WHO's guidance says to answer
"no" to Id10020 when the full date is unknown, but interviewers who know
the year (or month and year) answer "yes" and key 1 January (or the 1st).
In our data 39% of "known" birth dates at age 50+ are 1 January (45% fall
on the 1st of a month), against about 0.3% expected; children's dates are
unaffected. Age then carries false precision, and the partial knowledge is
lost when interviewers follow the guidance correctly.

**Change.** Keep Id10020/Id10021 as they are (yes = full date). When
Id10020 is no or refused, ask:

- "Is the month and year, or only the year, of birth known?" (month and
  year / year only / neither)
- a month-year date (`appearance: month-year`) or a year date
  (`appearance: year`), as two questions, since an XLSForm appearance is
  fixed per question.

The existing age questions still run, so `ageInDays` and the age groups are
unchanged. Add to the interviewer manual: never key the 1st or 1 January for
an unknown day or month.

### 2. Birth weight units

**Problem.** Id10366 accepts 0-9999 and asks for grammes, yet values such
as 2 and 3 (kilogrammes) are recorded.

**Change.** Reject values under 100 with "Enter the weight in grammes, not
kilogrammes", and ask the interviewer to confirm values outside 500-6000 g.

### 3. Hours survived for same-day neonatal deaths

**Problem.** The certificate asks for hours survived when a baby dies within
24 hours. The VA asks `age_neonate_hours` only when a date is missing; when
both dates are known (113 of 125 neonates in our data) a same-day death has
no hours.

**Change.** When the recorded dates of birth and death are the same day,
ask "How many hours did the baby live?" (0-23).

### 4. Pregnancy length in completed weeks

**Problem.** Id10367 records months; the certificate and ICD perinatal
rules use completed weeks.

**Change.** Beside Id10367, optionally ask the length in completed weeks
(when known, e.g. from an antenatal card), keeping Id10367 for the
algorithms.

### 5. Mother's age for deaths under one year

**Change.** For neonates and children under 12 months (the Id10354 group),
ask the mother's age in completed years. Optional.

### 6. External cause: date, place, legal intervention and war

**Problem.** Id10077_a only says whether death was within 7 days of the
injury; Id10058 is the place of death, not of the injury; Id10098-Id10100
cannot express legal intervention or war (certificate codes 4 and 5).

**Change.** After Id10077 = yes, optionally ask the date of the injury
(full, month-year or unknown), the place of occurrence (the certificate's
ten ICD place categories) and "Was the injury from police or legal action,
or from war?" (legal intervention / war / neither / don't know). Id10098 to
Id10100 are unchanged.

### 7. Surgery

**Problem.** Id10425 asks "Did (s)he have (or need) an operation", so a yes
does not establish that one was done; Id10426 uses one month rather than the
certificate's four weeks and is not asked for neonates; nothing records the
operation or its reason.

**Change.** Ask every death except stillbirths "Did (s)he have an operation
before death?", then how long before death (number and unit), what
operation was done, and for what illness or condition. Keep Id10425/Id10426
for the algorithms.

### 8. Autopsy

**Change.** Near the death-certificate questions (Id10462 onward), ask
whether an autopsy was requested and, if yes, whether its findings were
available. Optional.

### 9. Id10308 required like its neighbours

**Problem.** Id10308 ("Did she die less than 1 year after delivery,
abortion or miscarriage?") is the only question in the maternal timing
chain without `required = yes`, so a blank cannot be told from "no".

**Change.** Make it required, with the same don't know / refused choices.

### 10. Id10340 relevance

**Problem.** Id10340 ("Did she have an operation to remove her uterus
shortly before death?") is asked of every post-menopausal woman because its
relevance includes `selected(${Id10299}, 'yes')`. In our data 675 of its 685
answers come from that path; all 13 "yes" answers are women aged 62-92 with
no pregnancy recorded, and four of them said no operation within a month
(Id10426), so these are past hysterectomies, not recent obstetric surgery.

**Change.** Limit Id10340 to deaths with a recorded pregnancy event
(Id10312, Id10313, Id10334 or Id10308 = yes), as its hint ("relevant for
cases of obstructed labour and ruptured uterus") intends.

## Mapping notes WHO may wish to publish

For implementers, the maternal chain maps to the certificate's time from
pregnancy as follows: Id10305 or Id10312 yes = at time of death; Id10314,
Id10306 or Id10334 yes = within 42 days; Id10308 yes = 43 days to 1 year
(it is asked only after the 6-week answers are no); Id10310 confirmed = not
pregnant in the past year. The VA cannot establish "one year or more", and a
birth more than a year before death has no bearing on a maternal death.

## Annex A: proposed XLSForm rows

Names are provisional (WHO would assign `Id` numbers); they match the
names already used in our implementation, so data collected now maps
directly. Columns not shown are empty. `YES_NO_DK_REF` is the form's
existing list. Integer answers follow the form's convention of 88 =
refused, 99 = don't know. Every new question is optional
(`required` empty) unless stated.

### A1. Partial date of birth (after Id10021)

| type | name | label (en) | relevant | constraint (message) | appearance |
|---|---|---|---|---|---|
| select_one dob_precision | dob_precision | Is the month and year, or only the year, of birth known? | `selected(${Id10020}, 'no') or selected(${Id10020}, 'ref')` | | |
| date | dob_month_year | In which month and year was the deceased born? | `selected(${dob_precision}, 'month_year')` | `. <= today() and (string-length(${Id10023}) = 0 or . <= ${Id10023})` (Cannot be in the future or after the death) | month-year |
| date | dob_year | In which year was the deceased born? | `selected(${dob_precision}, 'year')` | `. <= today() and . >= date('1900-01-01')` (Cannot be in the future) | year |

Choices `dob_precision`: `month_year` Month and year known; `year` Only the
year known; `neither` Neither known.

Guidance for Id10020 (addition): "Answer YES only when the day, month and
year are all known. Never enter the 1st of the month or 1 January for an
unknown day or month; answer NO and use the next question."

### A2. Birth weight check (Id10366, and a new confirmation after it)

| type | name | label (en) | relevant | constraint (message) | required |
|---|---|---|---|---|---|
| integer | Id10366 (changed constraint) | *(unchanged)* | *(unchanged)* | `. >= 100 and . <= 9999` (Enter the weight in grammes, not kilogrammes. 1 kg = 1,000 g.) | *(unchanged)* |
| acknowledge | Id10366_confirm | A birth weight of ${Id10366} g is unusual. Check the card and confirm the weight is in grammes. | `${Id10366} < 500 or ${Id10366} > 6000` | | yes |

### A3. Hours survived (neonatal section, after Id10114)

| type | name | label (en) | relevant | constraint (message) |
|---|---|---|---|---|
| integer | doris_hours_survived | For how many hours did the baby live? | `selected(${isNeonatal}, '1') and selected(${Id10020}, 'yes') and selected(${Id10022}, 'yes') and ${ageInDays} = 0 and not(selected(${Id10114}, 'yes'))` | `(. >= 0 and . <= 23) or . = 88 or . = 99` (Enter 0 to 23 hours) |

### A4. Pregnancy length in weeks (after Id10367)

| type | name | label (en) | relevant | constraint (message) |
|---|---|---|---|---|
| integer | doris_pregnancy_weeks | How many completed weeks long was the pregnancy? (only if known, e.g. from an antenatal card) | same as Id10367: `selected(${isNeonatal}, '1') or (selected(${isChild}, '1') and ${ageInMonthsByYear} < 12)` | `(. >= 8 and . <= 48) or . = 88 or . = 99` (Enter 8 to 48 weeks). Deliberately wide: it rejects only impossible values, since a live birth before 20 weeks is still a live birth and dating is often uncertain. |

### A5. Mother's age (after Id10354)

| type | name | label (en) | relevant | constraint (message) |
|---|---|---|---|---|
| integer | doris_mother_age | How old was the baby's mother, in completed years, when the baby was born? | same as Id10354 | `(. >= 10 and . <= 60) or . = 88 or . = 99` (Enter 10 to 60 years) |

### A6. External cause (after Id10077_a)

| type | name | label (en) | relevant | constraint (message) | appearance |
|---|---|---|---|---|---|
| select_one injury_date_known | doris_injury_date_known | Is the date of the injury known? | `selected(${Id10077}, 'yes')` | | |
| date | doris_injury_date | On what date was (s)he injured? | `selected(${doris_injury_date_known}, 'full')` | `. <= today() and (string-length(${Id10023}) = 0 or . <= ${Id10023})` (Cannot be after the death) | no-calendar |
| date | doris_injury_month_year | In which month and year was (s)he injured? | `selected(${doris_injury_date_known}, 'month_year')` | as above | month-year |
| select_one injury_place | doris_injury_place | Where did the injury happen? | `selected(${Id10077}, 'yes')` | | |
| select_one legal_war | doris_injury_legal_war | Was the injury from police or legal action, or from war? | `selected(${Id10077}, 'yes')` | | |

Choices `injury_date_known`: `full` Full date; `month_year` Month and year;
`unknown` Not known. Choices `injury_place` (the certificate's ICD place
categories): `0` At home; `1` Residential institution; `2` School, other
institution, public administration area; `3` Sports and athletics area;
`4` Street and highway; `5` Trade and service area; `6` Industrial and
construction area; `7` Farm; `8` Other place; `9` Unknown. Choices
`legal_war`: `legal` Police or legal action; `war` War; `neither` Neither;
`dk` Doesn't know.

### A7. Surgery (after Id10426)

| type | name | label (en) | relevant | constraint (message) |
|---|---|---|---|---|
| select_one YES_NO_DK_REF | doris_surgery_performed | Did (s)he have an operation before death? | `not(selected(${Id10114}, 'yes'))` | |
| integer | doris_surgery_when | How long before death was the operation? (number) | `selected(${doris_surgery_performed}, 'yes')` | `. >= 0 or . = 88 or . = 99` |
| select_one time_unit | doris_surgery_when_unit | Unit | `selected(${doris_surgery_performed}, 'yes') and ${doris_surgery_when} < 88` | |
| text | doris_surgery_type | What operation was done? | `selected(${doris_surgery_performed}, 'yes')` | |
| text | doris_surgery_reason | For what illness or condition was it done? | `selected(${doris_surgery_performed}, 'yes')` | |

Choices `time_unit`: `days` Days; `weeks` Weeks; `months` Months; `years`
Years. The certificate's "surgery within the last 4 weeks" is then
`doris_surgery_when` <= 28 days.

### A8. Autopsy (after Id10462 to Id10473)

| type | name | label (en) | relevant |
|---|---|---|---|
| select_one YES_NO_DK_REF | doris_autopsy_requested | Was an autopsy (post-mortem examination) requested? | |
| select_one YES_NO_DK_REF | doris_autopsy_findings | Were the autopsy findings made available? | `selected(${doris_autopsy_requested}, 'yes')` |

### A9. Id10308

Set `required` to `yes` (no other change).

### A10. Id10340

Replace `relevant` with:

```
(selected(${Id10312}, 'yes') or selected(${Id10313}, 'yes')
 or selected(${Id10334}, 'yes') or selected(${Id10308}, 'yes'))
and not(selected(${Id10077_a}, 'less'))
```

## Contact

[Proposer name and affiliation]. A field-by-field mapping of the
instrument to the certificate, with the rules we apply, is available on
request.
