---
title: ODK training lesson, date of birth entered as 1 January
doc_type: kb
status: active
owner: DigitVA Data Collection
last_updated: 2026-09-29
---

# ODK training lesson: date of birth entered as 1 January

## What happens

In every deployed WHO VA 2022 workbook (the ten project forms and both WHO
releases in this folder), the date of birth is one question:

- Id10020 "Is the date of birth known?" (yes / no / refused)
- Id10021 "When was the deceased born?", a full day/month/year entry
  (`type: date`, `appearance: no-calendar`). ODK offers no year-only or
  month-year entry here, and it never fills in 1 January by itself.

WHO's guidance on Id10020: "If you do not know the full date of birth,
select the option 'NO'". That path asks the age instead (`age_group`,
`age_adult`, `age_child_*`, `age_neonate_*`).

Interviewers who know only the year, or the month and year, answer "yes"
and key 1 January, or the 1st of the month. The form accepts it as a real
date.

Id10021 is the only date-of-birth field. It feeds `ageInDays`
(`Id10023 - Id10021`, or `Id10024 - Id10021`), from which the form derives
age in years and the neonate / child / adult split that the WHO algorithms
and SmartVA use. The age questions are skipped whenever both dates are
known.

(Id10024, year of death, is different: it uses `appearance: year`, and ODK
stores that as `YYYY-01-01`. That 1 January is expected.)

## Evidence (dev database, 2026-09-29, 3,554 deaths with "date of birth known")

| Age at death | Birth date 1 January | Birth date on the 1st of any month |
|---|---|---|
| under 5 | 1 of 221 | 14 |
| 5-14 | 1 of 34 | 2 |
| 15-49 | 158 of 779 (20%) | 182 |
| 50+ | 991 of 2,520 (39%) | 1,135 (45%) |

By site, 1 January share: TR01 138 of 176, RJ01 190 of 293, OD01 251 of
622, ND01 148 of 301, NC01 136 of 395, PY01 137 of 925, MH01 77 of 196,
ML01 7 of 371. Children's dates are genuine (from birth records); the
problem is adult dates and it varies with training, not with the form.

## Effect

- Age is off by up to a year for these adults. Age bands rarely change, but
  certificate and algorithm inputs carry a precision the interview does
  not have.
- The DORIS prefill sends a 1 January date of birth at age 50 or over as
  the year only (`docs/policy/doris-cod-workflow.md`, "Prefill from the
  interview").

## Training point

> Answer **yes** to Id10020 only when the day, month and year of birth are
> all known (a birth certificate, ID card or health card). If only the year,
> or the month and year, is known, answer **no** and record the age in the
> age questions. Never key 1 January or the 1st of the month to stand in for
> an unknown day or month.

Supervisors can spot the pattern in their own data: a high share of 1
January birth dates among adults means the point needs repeating.

## Form change under discussion

When Id10020 is not yes, ask `dob_precision` (month-year / year only /
neither), then `dob_month_year` (`appearance: month-year`) or `dob_year`
(`appearance: year`). XLSForm appearance is fixed per question, hence two
date questions. Id10021 keeps meaning a full date and the WHO age questions
still run, so age derivation is unchanged.
See `.tasks/2026-09-29-doris-prefill-from-va.md` (bead `digitva-hln`).
