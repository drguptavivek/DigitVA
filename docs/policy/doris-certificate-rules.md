---
title: DORIS Certificate Field Rules
doc_type: policy
status: active
owner: engineering
last_updated: 2026-10-12
---

# DORIS Certificate Field Rules

Owner decisions on which certificate controls the coder sees, which are
greyed, and which draw a soft warning. This is the shared source of truth for
the Flask editor (`app/static/js/doris_rules.js`), the server guard
(`drop_inapplicable_sections` in `app/services/doris_certificate.py`) and the
Expo editor (TypeScript port). Where a rule and an implementation disagree,
this file wins.

## Vocabulary

- **hide**: the control is not shown and its keys are removed from the
  certificate sent to `/process` and saved. Hiding clears the control, so
  when the section re-appears the coder must re-enter it; old values are
  never resurrected.
- **not applicable (N/A) note**: used when a whole card does not apply. The
  card's title stays and a compact yellow note strip (the warning alert
  style, light and dark, readable at phone width) replaces its fields: no
  fields, no greyed controls. The card's keys are removed exactly as for
  **hide**.
- **disable**: the control is shown greyed and cannot be changed (existing
  behaviour for the interval units, V9). The pregnancy follow-ups are no
  longer disabled-with-value: see V3.
- **warn**: an inline message under the offending field, in the form-text
  style. Never blocks Process or Save.

## Inputs

| Input | Source | Notes |
| --- | --- | --- |
| reported age | `AdministrativeData.EstimatedAge`, prefilled from the interview via `age_field()` (rule V7) and editable | ISO duration. In days: Y 365.25, M 30.4375, W 7, D 1, H 1/24. If blank the age is unknown (no fallback to the dates). |
| sex | `AdministrativeData.Sex`: 1 Male, 2 Female, 9 Undetermined, blank not stated | |
| certificate answers | the other certificate fields | |

**Unknown age.** When the age is blank and cannot be computed, the age rules
V1 and V2 do not hide anything (nothing is known to rule the card out) and
V3 age warning, V9 and the unit greying stay silent. Sex rules treat blank
sex as "not Female".

## Code lists (follow the server, not DORIS prose)

`MannerOfDeath` as `doris_certificate.py` accepts it: 0 Disease, 1 Accident,
2 Intentional self-harm, 3 Assault, 4 Legal intervention, 5 War,
6 Could not be determined, 7 Pending investigation, 9 Unknown. The owner's
original list numbered these from 2 and shifted them by one; the codes below
are the stored ones. "External-cause details shown" means Manner is 1 to 7.

## Rules

| Rule | Inputs | Effect | Severity |
| --- | --- | --- | --- |
| V1 | reported age | "Fetal or infant death *" card fields shown only when reported age is under 1 year. Otherwise the card keeps its title and shows the N/A note "This section is not applicable when it is not a fetal or infant death"; every `FetalOrInfantDeath.*` key removed. | N/A note |
| V2 | reported age, `FetalOrInfantDeath.Stillborn` | "If death within 24h specify number of hours survived" (`DeathWithin24h`) shown only when reported age is under 7 days and Stillborn is not Yes (1). Otherwise hidden and the key removed. | hide |
| V3 | sex, `MaternalDeath.WasPregnant`, reported age | "Information on pregnancy" card fields shown only when sex is Female (2). Otherwise the card keeps its title and shows the N/A note "This section is not applicable when the selected sex is male" for Male (1), "This section is not applicable when the selected sex is not female" for Undetermined and not stated; `MaternalDeath.*` removed. "Time from pregnancy" and "Pregnancy contributed" stay disabled until "For women, was the deceased pregnant?" is Yes (1); while WasPregnant is not Yes they are blank and are not sent (`MaternalDeath.TimeFromPregnancy` and `MaternalDeath.PregnancyContribute` removed), also on the server. When WasPregnant is Yes and the reported age is outside 10 to 54 years (constant `PREGNANCY_AGE_BAND = (10, 54)`), warn "Pregnancy is unusual at this age". | N/A note / disable + drop / warn |
| V4 | `Surgery.WasPerformed` | "Date of surgery" and "reason for surgery" shown only when "Was surgery performed within the last 4 weeks?" is Yes (1). Otherwise hidden and `Surgery.Date`, `Surgery.Reason` removed. | hide |
| V5 | `Autopsy.WasRequested` | "If yes were the findings used in the certification?" shown only when "Was an autopsy requested?" is Yes (1). Otherwise hidden and `Autopsy.Findings` removed. | hide |
| V6 | `MannerOfDeath.MannerOfDeath` | "Date of injury", "Please describe how external cause occurred" and "Place of occurrence of the external cause" shown only when Manner is 1 to 7 (Accident, Intentional self-harm, Assault, Legal intervention, War, Could not be determined, Pending investigation). Hidden for 0 Disease, 9 Unknown and not stated; `DateOfExternalCauseOrPoisoning`, `DescriptionExternalCause`, `PlaceOfOccuranceExternalCause` removed. | hide |
| V7 | interview | Always prefill `AdministrativeData.EstimatedAge` from the reported age, even when both dates are known, with provenance. ISO duration in the reported unit: `PT{n}H` for neonates under a day, `P{n}D` for other neonates, else `P{n}Y`, `P{n}M` or `P{n}D`. | prefill |
| V8 | interview | Prefill `FetalOrInfantDeath.BirthWeight` (grams) from `Id10366` and `PregnancyWeeks` (completed weeks) from `doris_pregnancy_weeks`, else `Id10367` months converted to weeks, each with "from interview" provenance and bounds checking. Both already existed; see the prefill table in `doris-cod-workflow.md`. | prefill |
| V9 | interval, reported age, line order | A Part I or Part II interval longer than the age at death warns "Interval is longer than the age at death". Interval unit options longer than the age at death (for example Years for an age under 1 year) are greyed, except the unit already selected. A Part I line below the first whose interval is shorter than the nearest line above that has one warns "Usually longer than the line above". | warn / disable |
| V10 | dates | Warn when: `DateBirth` is after `DateDeath` ("Date of birth is after the date of death"); `DateDeath` is after today in the user's timezone ("Date of death is in the future"); date of injury is before birth or after death ("Date of injury is outside birth to death"); date of surgery is outside the 4 weeks before death ("Outside the 4 weeks before death"); `EstimatedAge` differs from the age computed from the two dates by more than 1 year ("Estimated age differs from the dates by more than a year"). Dates are compared at the coarser precision of the two, and a rule that needs a full date stays silent without one. `DateDeath` is a full date (a plain calendar input). The 4-week surgery check needs a full surgery date and a full death date: a year or year-month surgery date does not trigger it. | warn |
| V11 | values | Warn: birth weight outside 200 to 7000 g; pregnancy weeks outside 20 to 45; age of mother outside 10 to 60; hours survived outside 0 to 24. Messages: "Unusual birth weight (200 to 7000 g)", "Unusual number of weeks (20 to 45)", "Unusual age of mother (10 to 60)", "Hours survived should be 0 to 24". | warn |
| V12 | all | Messages sit under the offending field in the existing form-text style. Nothing blocks Process or Save. | warn |

## Server guard

`normalize_certificate` calls `drop_inapplicable_sections` after validating
values, so a stale client cannot send for example `FetalOrInfantDeath` for an
adult; the prefill applies the same function so the interview never prefills
a hidden control. The guard uses only the certificate's own `Sex`,
`EstimatedAge`, `Stillborn`, `WasPregnant` (the two V3 follow-ups are dropped unless it is Yes),
`WasPerformed`, `WasRequested` and `MannerOfDeath`.

## Layout

- **N/A cards.** Only whole cards (V1, V3) use the title plus note. A single
  follow-up inside a card that shows (surgery date and reason before
  Surgery is Yes, autopsy findings before Autopsy is Yes, the external-cause
  fields before a non-natural manner, hours survived) stays hidden with no
  note.
- **Onset to death.** Each Part I line and Part II shows one label "Onset to
  death" followed by a number box (placeholder "Interval") and a unit select
  whose blank option reads "Units", wrapping on a phone. The Estimated age
  control keeps "Age" and "Age unit". The stored value is the same ISO
  duration.
- **Section spacing.** "Frame A: Medical data", "Part 1: Cause of death"
  and "Part 2: Other significant conditions contributing to death" use the
  same heading spacing, with about 1.25rem clear above Part 2.
- **Add line.** Each Part I line has its own "Add line" button that inserts
  an empty line directly below it. The cap is 5 lines (the button is
  disabled at the cap, as is the header "Add line", which still appends at
  the end). Letters A to E renumber. An empty line between filled ones is
  still rejected at Process; trailing empty lines are ignored.

## Date precision

Exactly three dates take a partial value, each with a small select beside the
input (aria-label "<field> precision"): **Date of birth**
(`AdministrativeData.DateBirth`), **Date of injury**
(`MannerOfDeath.DateOfExternalCauseOrPoisoning`) and **Date of surgery**
(`Surgery.Date`).

| Select | Input | Stored and sent |
| --- | --- | --- |
| Date (default) | calendar | `YYYY-MM-DD` |
| Year-Month | month picker | `YYYY-MM` |
| Year | 4-digit numeric text, digits only, `maxlength` 4, placeholder `YYYY` | `YYYY` |

- A saved or prefilled value opens in its own precision. Switching keeps only
  what fits: Date to Year-Month keeps `YYYY-MM`, to Year keeps `YYYY`;
  widening (Year to Year-Month or Date, Year-Month to Date) keeps nothing.
  Clearing the value keeps the chosen precision. A hide rule (V4, V6) resets
  it to Date.
- A half-typed value (for example `20` in Year) is not sent.
- **No `max`, `min` or `pattern`** on any date, month or year input: the
  editor sits in an htmx form and native validation would block Save. A year
  in the future or before 1900 is not blocked; V10 warns where it applies.
- **Date of death** (`AdministrativeData.DateDeath`) is a plain
  `<input type="date">`, no select. A saved partial value (older data) is
  shown in a text input that can be replaced, and is sent unchanged until the
  coder replaces or clears it; it is never dropped silently.

## Clear button

Every question of Administrative Data, Manner of death, Fetal or infant
death, Information on pregnancy, Surgery and Autopsy has a clear button (an
inline SVG cross, `btn-sm`, 44 px target, aria-label "Clear <question>") at
the top right of its label row, shown only while the question has a value.
The Part I and II line cards keep their own Remove and the line search boxes
have no clear button. Free-text and number inputs also carry a small cross
inside their right edge and the two textareas one at their top right corner.

Clearing empties the question's controls (the precision select keeps its
choice), removes its "from interview" badge, and takes the normal edit path:
the certificate is invalidated, the rules re-run and warnings update. For
Estimated age it empties both the number and the unit.

## Search auto-start

A search box (each Part I and II line, and the Step 2 final-cause box) starts
searching on its own once its trimmed text has at least 3 characters and the
coder pauses for about 500 ms. On a line this opens the search modal already
searching that text. 1 or 2 characters never start it; Search and Enter stay
immediate; a term starts once (it can start again after the box drops below
3 characters or is cleared); leaving the box, clearing it or opening the modal
cancels the pending start. Once the modal is open, its own typing pause
(250 ms) applies and nothing else fires, so one request goes out per term.
