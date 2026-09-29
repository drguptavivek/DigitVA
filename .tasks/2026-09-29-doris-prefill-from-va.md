# Prefill the DORIS certificate from the VA interview

- Status: Done (built 2026-09-29). Follow-ups are owner steps listed in handoff.md; `digitva-zyf` for override-message translation.
- Priority: P2
- Created: 2026-09-29
- Bead: `digitva-hln`
- Related: `docs/kb/DORIS/who-va-2022-to-doris.md` (verified mapping notes; keep it current), `docs/current-state/doris-cod-workflow.md`,
  `docs/kb/DORIS/who-doris-death-certificate-json-format.md`,
  `app/services/doris_certificate.py` (`normalize_certificate`),
  `app/routes/va_form.py` (`_doris_admin_defaults`),
  `.tasks/2026-09-28-interviewer-worklist.md` (prefill map for the WHO form)

## Goal

When a coder opens a new DORIS certificate, fill every non-cause field DORIS
accepts from what the interview already recorded, so the coder writes causes
and checks, rather than re-typing, the administrative, maternal, fetal/infant
and external-cause data that WHO's rules use. Causes (Part I and II) stay the
coder's own; nothing here suggests a cause.

## Today

`_doris_admin_defaults` seeds `AdministrativeData\Sex` and a whole-year
`EstimatedAge` from the interview; under one year is left to the coder.
Everything else starts empty.

## Decisions (2026-09-29, owner)

- Extra questions live in a new extension, `doris_support_whova_2022`
  (ninth name in `enabled_extensions`; update the tables in
  `docs/policy/va-form-project-configuration.md` and
  `docs/policy/va-web-form-options.md`).
- **ODK workbooks get three changes** (owner, 2026-09-29), with the same
  names and relevance as the web form: the birth-weight grams check on
  Id10366, the partial birth date (`dob_precision`, `dob_month_year`,
  `dob_year`), and `doris_hours_survived`. Deliverable: the XLSForm rows
  (survey + choices) ready to paste into each of the ten deployed
  workbooks; deploying them to ODK Central is the owner's step.
- **Superseded later the same day (owner, 2026-09-29):** ODK rows are
  produced for **all ten** changes in Annex A of
  `docs/kb/DORIS/who-va-2022-doris-consistency-proposal.md`, as a
  paste-ready `.xlsx` (survey + choices) with the three agreed first marked;
  the owner decides what to deploy per site. The web form and the ODK rows
  use **Annex A's names and rules exactly** (e.g. `doris_injury_date_known`
  + `doris_injury_date` + `doris_injury_month_year`,
  `doris_surgery_when_unit`, `Id10366_confirm`,
  `doris_pregnancy_weeks` 8-48), so both sources share one payload shape.
- **Every DORIS question in every web form** (owner, 2026-09-29,
  widening an earlier "dob and birth weight for all projects"): the whole
  `doris_support_whova_2022` extension, including A9/A10, is on for every
  web project, not derived from `cod_entry_mode == "doris"`. The extension
  name stays (it groups the questions and the ODK rows); only its gating
  changes to always-on, like `digitva_core`. Prefill still runs only where
  the DORIS editor is shown.
- **ODK rows are generated from the extension itself** (owner,
  2026-09-29): the XLSForm rows (survey + choices) come out of the
  extension's own definition (via the generated
  `digitva-layers.reference.json` or equivalent), not from a separately
  written row list, so web and ODK cannot drift. This is the first slice of
  `digitva-aek` (project ODK form as an output); a hand-written row list or
  a script with its own copy of the rows is replaced by it.
- The web form also applies the two WHO-question fixes: Id10308 required,
  and Id10340 asked only after a pregnancy event (A9, A10). Documented as a
  deliberate difference from WHO V1.1. ODK-synced
  cases get prefill only from the WHO questions they already carry (the
  fallbacks in the table); the coder fills the rest. Keep the `doris_*` names
  stable so an ODK change later can reuse them.
- All added questions ship, autopsy included; **every one is optional** (not
  required, with dk/refused/unknown choices).
- Maternal bands checked against the instrument's relevance chain (below).
- Surgery: ask it directly (`doris_surgery_performed`, DORIS's own 4-week
  wording). Id10426 (1 month) and Id10340 (hysterectomy) are fallbacks for
  cases without the direct answer. Hysterectomy counts as surgery.
- Autopsy: both DORIS questions are asked (requested; findings used).
- Pregnancy weeks: convert Id10367 months when the weeks answer is absent.
- Birth weight has no unknown code in the form or in DORIS: 0 means blank.
- Id10340 (hysterectomy) counts as surgery **only with a pregnancy event**
  (any yes in Id10305..Id10308): the form asks it of every post-menopausal
  woman, and dev's 13 yes answers are all women 62-92 with no pregnancy.
- Birth weight gets a grams check in the web form **and the ODK workbooks**:
  a hard error below 100 ("enter grams, not kilograms"), and an interviewer
  confirmation outside 500-6000 g.
- Hours survived: a newborn whose recorded dates of birth and death are the
  same day gets `doris_hours_survived` (0-23), since the form asks
  `age_neonate_hours` only when a date is missing.
- Manner with no yes among the intent answers: all asked answers no -> 6
  (could not be determined); any dk/ref -> 9.
- Manner of death: one added question after an injury death,
  `doris_injury_legal_war`, supplies DORIS codes 4 and 5; Id10098-10100 keep
  supplying 1-3. Not a full DORIS manner question, which would repeat them.
  Asked after every injury death (Id10077 = yes), not only assaults.
- Field names: `doris_` + snake case, as proposed (DORIS's own attribute
  names carry a misspelling, `PlaceOfOccurance`, and mixed case); the table
  below maps each to its DORIS attribute.
- Everything lands in code and is committed together when the build is
  ready, not piecemeal.

## Verified against the instrument (names from `who-va-2022.instrument.json`)

| DORIS field | VA source | Rule |
|---|---|---|
| `Sex` | Id10019 | female 2, male 1, undetermined/other 9 |
| `DateBirth` | Id10021 when Id10020 = yes | DORIS takes `YYYY`, `YYYY-MM`, full date. A 1 January date at age >= 50 is sent as `YYYY` (owner 2026-09-29: interviewers key year-only answers as 1 January; see `docs/kb/WHO_VA_2022_Docs/odk-training-date-of-birth.md`) |
| `DateDeath` | Id10023 (`_a`/`_b`) when Id10022 = yes; else Id10024 (year) | as above |
| `EstimatedAge` | `age_group`, `age_neonate_hours/days`, `age_child_*`, `age_adult` | ISO duration (`PT5H`, `P3D`, `P8M`, `P40Y`); only when a date is missing |
| `BirthWeight` | Id10366 | grammes, direct; 0 -> empty. Only asked from a health card (`Id10366_check` = yes), under one year |
| `Stillborn` | any of Id10104 (cried), Id10109 (moved), Id10110 (breathed) = yes -> 0 (Id10114 is then not asked); else Id10114: yes 1, no 0, dk/ref 9 | neonates only |
| `DeathWithin24h` | `age_neonate_hours` when < 24 | DORIS wants **hours survived**, not a flag (tabular spec; our editor already does this). Days-only answer of 0 -> empty; stillbirths -> empty |
| `MultiplePregnancy` | Id10354 only | Id10317 (twins/triplets) is the *mother's* pregnancy in a maternal death, so it feeds nothing here; Id10309 (months pregnant at death) likewise unused |
| `MaternalDeath\WasPregnant` | (Id10308 is optional in the form: blank is not no) any of Id10305, Id10312, Id10314, Id10306, Id10334, Id10308 = yes -> 1; Id10313 = yes with no time answer -> 1; else Id10310 (confirm) -> 0; all asked answers dk/ref -> 9 | section only exists for adults recorded female/undetermined (`pregnancy_women`); nothing asked (girls, men, menopause + age >= 50) -> empty |
| `MaternalDeath\TimeFromPregnancy` | Id10305 or Id10312 -> 0; Id10314, Id10306 or Id10334 = yes -> 1 (42 days = the VA's 6 weeks); Id10308 = yes -> 2; Id10313 = yes but every time answer dk/ref -> 9 | Id10308 is only asked after the 6-week answers are no, so yes means 43 days to 1 year. Band 3 (>= 1 year) never derived: Id10310 says no pregnancy in the last 12 months, not one before. Id10313 = yes with Id10308 = no (birth more than a year before death) has no bearing on a maternal death: owner 2026-09-29, band left empty, WasPregnant from Id10310 as usual. Labour/delivery (Id10312) -> 0 confirmed by owner 2026-09-29 (pregnancy not ended at death). |
| `MannerOfDeath\MannerOfDeath` | Id10077 no -> 0; `doris_injury_legal_war` legal -> 4, war -> 5 (wins over 1-3); else Id10095 (force of nature) = yes -> 1 (intent questions are skipped then); Id10098 -> 1; Id10099 -> 2 (asked age >= 10 only); Id10100 -> 3; injury with none answered -> 6 | 7 (pending investigation) stays the coder's |
| `MannerOfDeath\DescriptionExternalCause` | injury-type flags Id10079..Id10097 as text | composed |
| `Surgery\WasPerformed` | `doris_surgery_performed` no -> 0, dk/ref -> 9; yes with `doris_surgery_when` <= 28 days -> 1, longer -> 0; else Id10340 = yes with a pregnancy event -> 1; else Id10426 yes 1 / no 0 | Id10340 alone is ignored (asked of every post-menopausal woman). Id10426 is never asked of neonates and Id10425 says "had *or needed*", so neonates without the direct answer stay empty |
| `Surgery\Reason` | "`doris_surgery_type` for `doris_surgery_reason`"; else "Hysterectomy" from Id10340 with a pregnancy event | `Surgery\Date` is never prefilled: only time elapsed is asked |
| `FetalOrInfantDeath\PregnancyWeeks` | `doris_pregnancy_weeks`; else floor(Id10367 months x 4.345), skipping 88/99 | converted value marked as a suggestion |
| don't know / refused | | 9 where DORIS has it, else empty |

Not from the VA, so the coder's: `PregnancyContribute` (a physician
judgement), `PerinatalDescription`, causes and intervals.

Gating to respect: `FetalOrInfantDeath` fields are for deaths under one year
only; Id10354, Id10366 and Id10367 are already gated to neonates and
children under 12 months in the form.
`Id10305` is skipped after menopause with age >= 50; the maternal group
(`group_maternal`: Id10309 onward) is hidden when Id10310 = yes or the
injury death was within 7 days (Id10077_a = less), but the Id10305 chain still
runs then.

## Added questions, extension `doris_support_whova_2022` (proposed names)

| Field | Where | Feeds |
|---|---|---|
| `doris_mother_age` (years) | beside Id10354: neonate, or child under 12 months | `FetalOrInfantDeath\AgeMother` |
| `doris_pregnancy_weeks` (8-48; owner 2026-09-29) | beside Id10367, neonate and child | `PregnancyWeeks` (Id10367 months only as fallback) |
| `doris_injury_date` (date or year-month, unknown allowed) | after Id10077 = yes | `DateOfExternalCauseOrPoisoning` |
| `doris_injury_place` (DORIS's ten choices) | after Id10077 = yes | `PlaceOfOccuranceExternalCause` |
| `doris_injury_legal_war` (legal intervention / war / neither / dk) | after Id10077 = yes | `MannerOfDeath` codes 4 and 5 |
| `doris_surgery_performed` "Did (s)he have an operation before death?" (yes/no/dk/ref) | health-service section, every death except stillbirths | no -> `WasPerformed` 0 |
| `doris_surgery_when` (number + days/weeks/months/years) | after `doris_surgery_performed` = yes | `WasPerformed`: 1 if <= 28 days, else 0 |
| `doris_surgery_type` "What operation was done?" (text) | after yes | `Surgery\Reason`, with the next |
| `doris_surgery_reason` "For what illness or condition?" (text) | after yes | `Surgery\Reason` ("<type> for <reason>") |
| `doris_hours_survived` (0-23) | newborn whose birth and death dates are the same day | `DeathWithin24h` |
| `dob_precision` "Is the month and year, or only the year, of birth known?" (month-year / year only / neither) | Id10020 = no or ref | picks the next question |
| `dob_month_year` (date, `appearance: month-year`, stored `YYYY-MM-01`) | `dob_precision` = month-year | `DateBirth` as `YYYY-MM` |
| `dob_year` (date, `appearance: year`, stored `YYYY-01-01`) | `dob_precision` = year | `DateBirth` as `YYYY` |

Partial birth date (owner 2026-09-29): an XLSForm `appearance` is fixed per
question, so month-year and year-only need two questions. Id10020 / Id10021
keep WHO's meaning (full date only) and the WHO age questions still run
when Id10020 is not yes, so `ageInDays` and the age groups are untouched.
Both new dates: not after today, not after the death date.

No surgery date is asked (owner 2026-09-29), only time elapsed; `Surgery\Date`
stays the coder's.
| `doris_autopsy_requested`, `doris_autopsy_findings` (findings only if requested = yes) | end of the death-circumstances area | `Autopsy\WasRequested`, `Autopsy\Findings` |

Work touches: `vendor/who-va-2022/src/digitva-extension.ts` (fields,
relevance, layer gating; rebuild the bundle), web payload handling so the
fields survive, and the extension tables in
docs/policy.

## Rules

1. **Suggestions, never locked.** Every prefilled field is editable; the
   certificate is the coder's. Each prefilled field shows a small "from
   interview (Id…)" marker so the coder knows where it came from.
2. **Only what the interview states.** "Don't know" / "refused" / missing
   answers leave the DORIS field empty (DORIS "unknown" only where DORIS has
   such a code and the interview explicitly said so). No inference beyond the
   table (e.g. never derive manner of death from a symptom).
3. **Masked Step 1 is unaffected.** These are interview facts, not SmartVA
   output; masking hides SmartVA only.
4. **Both sources, one function.** Reads the active payload version; ODK
   cases simply lack the `doris_*` answers and use the fallbacks.
5. **Recorded.** The saved certificate envelope records which fields were
   prefilled and whether the coder changed them (for later quality review),
   without duplicating PII outside the envelope.
6. **Clinical sign-off.** The owner (or a designated physician) reviews the
   verified mapping table, especially maternal and fetal/infant rules, before
   it ships; the table moves into `docs/policy/doris-cod-workflow.md`.

## Work

1. Pull real dev payload examples for each verified row above; owner review
   of the maternal bands and the added-question list.
2. Policy section in `docs/policy/doris-cod-workflow.md`.
3. One pure mapping function (`doris_prefill_from_payload(payload) ->
   partial certificate + provenance`), replacing `_doris_admin_defaults`,
   validated through `normalize_certificate`; table-driven tests per field,
   including dk/refused/missing and neonate/child/adult/maternal cases.
4. Editor shows the provenance markers; envelope stores prefilled/changed
   flags.
5. Browser check on a coding page for an adult, a woman of reproductive age,
   a neonate and an injury death.
