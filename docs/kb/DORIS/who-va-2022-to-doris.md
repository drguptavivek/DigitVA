---
title: WHO VA 2022 to DORIS certificate, field mapping and gaps
doc_type: kb
status: working notes
owner: engineering
last_updated: 2026-09-29
---

Working notes for prefilling the DORIS death certificate (non-cause fields)
from the WHO 2022 verbal autopsy interview. Question names are from
`vendor/who-va-2022/src/generated/who-va-2022.instrument.json`; DORIS fields
from `who-doris-death-certificate-json-format.md`. Plan and build tracking:
`.tasks/2026-09-29-doris-prefill-from-va.md` (bead `digitva-hln`). Add to
this page as more is verified; the mapping becomes policy only after owner
sign-off.

## Decisions

- Gap questions live in a new extension, `doris_support_whova_2022`.
- The ODK workbooks get the birth-weight grams check, the partial birth
  date (`dob_precision`, `dob_month_year`, `dob_year`) and
  `doris_hours_survived`. The other added questions are web form only; ODK
  cases use the WHO-question fallbacks below and the coder fills the rest.
- Every added question is optional, with dk / refused / unknown choices.
- Prefill is a suggestion the coder can edit; causes and intervals stay the
  coder's. dk / refused / missing leave the DORIS field empty, or 9 where
  DORIS has an unknown code and the interview said so.

## Mapping

| DORIS field | VA source | Rule |
|---|---|---|
| `Sex` | Id10019 | female 2, male 1, undetermined 9 |
| `DateBirth` | Id10021 when Id10020 = yes | DORIS accepts `YYYY`, `YYYY-MM`, full date; 1 January at age >= 50 -> `YYYY` (see `../WHO_VA_2022_Docs/odk-training-date-of-birth.md`) |
| `DateDeath` | Id10023 (`_a`/`_b`) when Id10022 = yes, else Id10024 (year) | as above |
| `EstimatedAge` | `age_group`, `age_neonate_hours/days`, `age_child_*`, `age_adult` | ISO duration (`PT5H`, `P3D`, `P8M`, `P40Y`); only when a date is missing |
| `FetalOrInfantDeath\BirthWeight` | Id10366 (grammes); 0 -> empty | recorded only from a health card (`Id10366_check` = yes), under one year; no unknown code in the form or DORIS |
| `FetalOrInfantDeath\Stillborn` | Id10104, Id10109 or Id10110 = yes -> 0; else Id10114 yes 1, no 0, dk/ref 9 | neonates only; Id10114 is skipped when any sign of life is recorded |
| `FetalOrInfantDeath\DeathWithin24h` | `age_neonate_hours` when < 24 | hours survived (DORIS tabular spec), not a flag; days-only 0 -> empty |
| `FetalOrInfantDeath\MultiplePregnancy` | Id10354 | Id10317 is the mother's pregnancy; Id10309 likewise; neither used |
| `FetalOrInfantDeath\PregnancyWeeks` | new `doris_pregnancy_weeks`; else floor(Id10367 months x 4.345), 88/99 skipped | converted value is a suggestion |
| `FetalOrInfantDeath\AgeMother` | new `doris_mother_age` | VA never asks it |
| `FetalOrInfantDeath\PerinatalDescription` | none | coder |
| `MaternalDeath\WasPregnant` | (Id10308 is optional: blank is not no) any of Id10305, 10312, 10314, 10306, 10334, 10308 = yes -> 1; Id10313 = yes with no time answer -> 1; else Id10310 -> 0; asked answers all dk/ref -> 9 | empty when nothing asked |
| `MaternalDeath\TimeFromPregnancy` | Id10305 or 10312 -> 0; Id10314, 10306 or 10334 = yes -> 1; Id10308 = yes -> 2; Id10313 = yes but time answers dk/ref -> 9 | band 3 never derived (see below) |
| `MaternalDeath\PregnancyContribute` | none | physician judgement, coder |
| `MannerOfDeath\MannerOfDeath` | Id10077 no -> 0; new `doris_injury_legal_war` (asked after every injury) legal -> 4, war -> 5 (wins over 1-3); else Id10095 force of nature -> 1 (intent is skipped then); Id10098 -> 1; Id10099 -> 2; Id10100 -> 3; injury with no intent answered -> 6 | 7 (pending investigation) stays the coder's |
| `MannerOfDeath\DescriptionExternalCause` | injury-type flags Id10079..Id10097 composed as text | |
| `MannerOfDeath\DateOfExternalCauseOrPoisoning` | new `doris_injury_date` | VA only has Id10077_a (<= 7 days or more) |
| `MannerOfDeath\PlaceOfOccuranceExternalCause` | new `doris_injury_place` (DORIS's ten choices) | Id10058 is place of death, not injury |
| `Surgery\WasPerformed` | new `doris_surgery_performed` + `doris_surgery_when` (time elapsed; <= 28 days -> 1); else Id10340 hysterectomy = yes with a pregnancy event -> 1; else Id10426 (1 month) yes 1 / no 0 | Id10340 alone ignored; Id10426 is not asked of neonates, Id10425 is "had or needed" |
| `Surgery\Reason` | new `doris_surgery_type` + `doris_surgery_reason`; "Hysterectomy" from Id10340 with a pregnancy event | no surgery date asked; `Surgery\Date` stays the coder's |
| `Autopsy\WasRequested`, `Autopsy\Findings` | new `doris_autopsy_requested`, `doris_autopsy_findings` | findings only if requested = yes |

## Maternal question chain (how the VA reaches TimeFromPregnancy)

The `pregnancy_women` section shows only for adults recorded female or
undetermined; girls, men and children never see it. Each question is skipped
once an earlier answer settles it:

1. Id10305 pregnant, not in labour, at death (skipped after menopause with
   age >= 50, or when Id10296/Id10299 say so).
2. Id10312 died in labour or delivery (asked if Id10305 is no/dk/ref).
3. Id10313 died after delivering (skipped if Id10305 or Id10312 = yes).
4. Id10314 within 24 hours of delivery (only if Id10313 = yes).
5. Id10306 within 6 weeks of delivery (only if Id10314 is no/dk/ref).
6. Id10334 abortion or miscarriage within 6 weeks (skipped if any of the
   above = yes).
7. Id10308 died less than 1 year after delivery, abortion or miscarriage
   (asked only when none of Id10305, 10312, 10314, 10306, 10334 = yes, so a
   yes means 43 days to 1 year).
8. Id10310 confirms none of it happened in the last 12 months. It says
   nothing about a pregnancy earlier than that, so DORIS band 3 (one year or
   more) cannot be derived. Id10313 = yes with Id10308 = no (a birth more than a
   year before death) has no bearing on a maternal death (owner,
   2026-09-29): band stays empty, WasPregnant comes from Id10310.

Id10312 (labour or delivery) maps to "at time of death" (owner, 2026-09-29):
the pregnancy had not ended when she died. `group_maternal` (Id10309 onward) is hidden when Id10310 = yes
or the injury death was within 7 days (Id10077_a = less); the Id10305 chain
still runs in that case.

## Gating to respect

- Fetal or infant fields: deaths under one year only. Id10354, Id10366 and
  Id10367 are gated in the form to neonates and children under 12 months.
- The stillbirth section (Id10104..Id10116) is neonate-only.
- Id10354, Id10366, Id10367 sit in `neonatal_childA` (neonate and child).

## Gaps the WHO form does not cover

Mother's age, pregnancy length in weeks, injury date and place, legal
intervention and war as manner of death, surgery in the last 4 weeks with
date and reason, and autopsy requested / findings used all get added
questions (web form only). `PregnancyContribute`, `PerinatalDescription`,
causes and intervals stay with the coder.

## Dev data check (2026-09-29, 8,271 active payloads, all ODK-synced)

- Payload values arrive as strings or numbers (`isNeonatal` `"1"` or `1`;
  `"9.0"`, `2000.0`). Id10023 carries a timestamp with offset
  (`2025-08-04T00:00:00.000+05:30`): take the date part. Id10024 is stored
  as `YYYY-01-01`: send the year only.
- Date of birth "known": 1,151 of 3,554 (32%) are 1 January, so many are
  year-only answers entered as full dates.
- Neonates: 113 of 125 have both dates and no `age_neonate_hours`, so
  `DeathWithin24h` is prefilled for only 6.
- Stillborn: 94 neonates showed a sign of life (Id10114 not asked -> 0);
  all 29 Id10114 = yes had none.
- Birth weight: 21 recorded; two are `2` and `3` (kilogrammes entered
  despite the instruction).
- Pregnancy months: mostly 9; `0` twice and `88` twice.
- Manner: 847 accidental; 45 all three intent answers no (-> 6); a handful
  all dk; one force of nature.
- Id10340 (uterus removed): asked of every post-menopausal woman (its
  relevance includes Id10299 = yes), 675 of 685 answers. All 13 yes answers
  are women aged 62-92 with no pregnancy recorded, and four of them answered
  Id10426 (operation within a month) no. Not a recent-surgery signal outside
  a maternal event.
- Maternal: 20 cases with any yes; the chain behaves as mapped.
