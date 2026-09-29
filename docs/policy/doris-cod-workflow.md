---
title: DORIS COD Workflow Policy
doc_type: policy
status: active
owner: engineering
last_updated: 2026-09-29
---

# DORIS COD Workflow Policy

## Project modes

**ICD-11 means DORIS (implemented, `digitva-0n3` phase 1).** Choosing
`icd_classification='icd11'` always sets `cod_entry_mode='doris'`; choosing
`icd10` always means simple entry. The `selectable` classification (ICD-10
or ICD-11 chosen per death) is retired; the migration moved every dev
project on it to `icd10`. Masked and DORIS may now combine at the settings
level (`masked_cod_required` no longer forbids `cod_entry_mode='doris'`);
masked ICD-11 has its own Step 1/Step 2 flow (below). A project's settings
do not rewrite completed assessments.

Masked/simple retains the current two-step coder and reviewer workflow.
Unmasked/simple has one final assessment with an independently validated
immediate COD, underlying COD and optional associated-condition free text.
The underlying COD alone controls final authority and VA bucket reporting.
Unmasked/DORIS keeps today's one-step DORIS final assessment. Masked
ICD-11 is described below.

### Masked ICD-11 (`digitva-0n3`: coder and reviewer flows implemented)

Owner decision in docs/policy/doris-cod-workflow.md; design record
`.tasks/2026-09-27-icd11-means-doris.md`. DigitVA is not deployed anywhere,
so no production data is affected.

- **Masked ICD-11** keeps the two steps. Step 1 is the DORIS certificate,
  entered and processed without SmartVA. Step 2 only confirms the final
  underlying COD, which may be the DORIS result, the SmartVA result or the
  coder's own judgement; its code entry is the DORIS picker's ICD-11 search
  (the shared `digitva_icd11_picker.js` module), with no second certificate.
- **The masked ICD-11 reviewer** does the same. Their Step 1 certificate
  starts as a copy of the coder's Step 1 certificate (or their own saved
  one); they process it with DORIS themselves and confirm their own
  underlying cause. The coder's records never change. Their Step 2 confirms
  the final underlying COD with the same three choices.
- **SmartVA for the masked reviewer.** The masked reviewer sees SmartVA in
  Step 2 (never in Step 1) for every masked project, ICD-10 included.
- The local ICD-11 catalogue search (`search_icd11_mms`) remains for the
  admin ICD-11 browser and Help pages, not for ICD-11 coding.

## DORIS entry and confirmation

The MO enters an ordered Part I/II certificate. One interval applies to each
line and is copied onto every condition on that line in the WHO request.
New blank editors show three Part I lines. Unused blank lines are omitted
from the processed certificate; filled lines retain their visible order.
A blank line between filled lines must be filled or removed before processing.
After a line's condition codes, the editor asks for the interval from onset
to death as a value and time unit. It serializes the answer as the WHO
certificate's ISO 8601 `Interval`, while existing saved durations remain
lossless on load and resubmission. Changing either interval control
invalidates current processor results and the final UCOD.
The server rejects nonempty intervals that are not valid ISO 8601 durations;
an empty interval and WHO unknown-duration markers remain valid.
Unknown fetal or infant measurements are omitted, rather than represented
by `9`. Every selected code/URI pair is checked against the pinned WHO
release before processing. DORIS computes guidance; CoDEdit findings are
advisory. Neither automatically sets the MO's final underlying COD.

The certificate picker may start with an ICD-11 stem, show its location in
the WHO hierarchy, and show matching terms, related maternal/perinatal
categories, and extension axes and choices supplied by the pinned WHO release.
Required postcoordination is identified before selection. A selected
extension or additional stem produces one complete condition expression
and WHO URI expression, using WHO's `&` or `/` separator as applicable;
the UI must not split it into separate certificate conditions or lines.
The same picker is available for coder, reviewer and synthetic Help entry.
The completed expression goes through the existing server selection check
before it is added. Changing a chosen extension has the same invalidation
effect as any other certificate edit.

Extension axes follow WHO's presentation: required axes come first, each
axis is its own section in WHO order with WHO's instruction wording, and
each axis offers a search limited to that axis's WHO subtree. A final
"Other postcoordination?" search over the extension-code chapter appears
only for MMS category stems outside that chapter, as WHO's coding tool
does. Uncoded WHO folders can be expanded to their coded children but are
never selectable themselves. Related maternal or perinatal panels present
WHO's exact composite category first, before the broader category list.

Editing any certificate input clears the displayed processor results and
the MO's final UCOD choice. Save remains disabled until the edited form is
processed and the MO confirms a final UCOD again. A clinical Process response
includes a short-lived signed token binding certificate and result digests
to the case, allocation, payload version, WHO release and image. At final
save, the server checks the submitted certificate and processor outputs
against that token. If the certificate changed, it reprocesses it, returns
`409 DORIS_CERTIFICATE_CHANGED` with fresh results, saves nothing and asks
for reconfirmation. If the token and data match, it saves the final
certificate, verified DORIS/CoDEdit outputs and the MO's separate final UCOD
atomically. It does not store drafts or intermediate Process responses.

DORIS never fills the final UCOD on its own. A "Use DORIS result" button in the
final UCOD step copies DORIS's suggested code into the field only when the MO
clicks it; the code is checked through WHO `codeinfo` and the selection check
like a searched code, and the MO may replace it before saving.

A DORIS or CoDEdit failure does not by itself bar a human final UCOD when
independent WHO codeinfo validation works. A whole WHO API outage blocks
ICD-11 final-code provenance validation and final save. Coder and reviewer
assessments remain separate; the reviewer may start from the coder's saved
certificate but never changes it.

## Prefill from the interview (`digitva-hln`, approved 2026-09-29, built)

A new DORIS certificate starts with the non-cause fields the interview
already answers, so the coder checks rather than re-types them. Causes,
intervals, `PregnancyContribute` and `PerinatalDescription` are never
prefilled.

- Every prefilled value is a suggestion: editable, marked with its source
  question ("from interview, Id10312"), and recorded in the saved envelope
  with whether the coder changed it.
- Only what the interview states. Don't know / refused give DORIS `9` only
  where DORIS has that code and the question was asked; unasked or blank
  questions leave the field empty (a blank optional answer is not "no").
- Interview facts, not SmartVA output, so masked Step 1 shows them too.
- One function serves web and ODK cases from the active payload version.
  Extra questions (extension `doris_support_whova_2022`) fill the gaps the
  WHO questions leave; names and rules are Annex A of
  `docs/kb/DORIS/who-va-2022-doris-consistency-proposal.md`, for the web
  form and the ODK rows alike (`docs/kb/WHO_VA_2022_Docs/odk-doris-support-rows.md`).
  The partial birth date, `doris_hours_survived` and the birth-weight check
  are agreed for the ODK workbooks; the others are proposed there, and ODK
  cases without them use the WHO fallbacks. Integer answers 88 (refused)
  and 99 (don't know) prefill nothing, except as noted for surgery.
- Numbers may arrive as strings or floats (`"9.0"`, `2000.0`); flags as
  `"1"` or `1`. Dates take the calendar date as recorded (no time zone
  shift); a year-only death (Id10024) is sent as `YYYY`.

| DORIS field | Source, in order | Rule |
|---|---|---|
| `Sex` | Id10019 | male 1, female 2, undetermined 9 |
| `DateBirth` | Id10021 when Id10020 = yes; else `dob_month_year` -> `YYYY-MM`, `dob_year` -> `YYYY` | as recorded; 1 January at age >= 50 -> `YYYY` (year-only answers keyed as 1 January) |
| `DateDeath` | Id10023 when Id10022 = yes; else Id10024 year | |
| `EstimatedAge` | `age_neonate_*`, `age_child_*`, `age_adult` | ISO duration, only when a date is missing |
| `Stillborn` | Id10104, Id10109 or Id10110 = yes -> 0; else Id10114 | neonates; yes 1, no 0, dk/ref 9 |
| `DeathWithin24h` | `age_neonate_hours` < 24; else `doris_hours_survived` (asked when birth and death dates are the same day) | hours survived, not a flag |
| `MultiplePregnancy` | Id10354 | under one year |
| `BirthWeight` | Id10366 | grammes, 100-9999 only: below 100 (blank 0, or kilogrammes such as 2 or 3 in older answers) -> empty; health card only. The forms reject values under 100 and ask an acknowledgement outside 500-6000 g |
| `PregnancyWeeks` | `doris_pregnancy_weeks` (8-48); else floor(Id10367 months x 4.345) | weeks or months 88, 99 skipped, months 0 skipped; converted value marked |
| `AgeMother` | `doris_mother_age` (10-60) | 88, 99 -> empty |
| `WasPregnant` | Id10305, 10312, 10313, 10314, 10306, 10334, 10308 any yes -> 1; Id10310 confirmed -> 0; asked answers all dk/ref -> 9 | women only; nothing asked -> empty |
| `TimeFromPregnancy` | Id10305 or Id10312 -> 0; Id10314, 10306 or 10334 -> 1; Id10308 -> 2; Id10313 yes, timing dk/ref -> 9 | band 3 never prefilled |
| `MannerOfDeath` | Id10077 no -> 0; `doris_injury_legal_war` legal 4 / war 5; Id10095 force of nature -> 1; Id10098 -> 1; Id10099 -> 2; Id10100 -> 3; no yes: all no -> 6, any dk/ref -> 9 | 7 stays the coder's |
| `DescriptionExternalCause` | injury-type answers Id10079..Id10097 as text | |
| `DateOfExternalCauseOrPoisoning` | `doris_injury_date_known` full -> `doris_injury_date`; month_year -> `doris_injury_month_year` as `YYYY-MM` | unknown -> empty |
| `PlaceOfOccuranceExternalCause` | `doris_injury_place` | 9 = unknown |
| `Surgery\WasPerformed` | `doris_surgery_performed` no -> 0, dk/ref -> 9; yes with `doris_surgery_when` + unit <= 28 days -> 1, longer -> 0, `doris_surgery_when` 88/99 -> 9; else Id10340 = yes with a pregnancy event -> 1; else Id10426 (1 month, accepted for 4 weeks) | Id10340 alone is ignored (asked of every post-menopausal woman); neonates without the direct answer stay empty |
| `Surgery\Reason` | "`doris_surgery_type` for `doris_surgery_reason`"; "Hysterectomy" from Id10340 with a pregnancy event | `Surgery\Date` is never prefilled: only time elapsed is asked |
| `Autopsy\WasRequested`, `Autopsy\Findings` | `doris_autopsy_requested`, `doris_autopsy_findings` | |

Working notes and the question-by-question evidence:
`docs/kb/DORIS/who-va-2022-to-doris.md`.

## Public Help proof

The public Help proof uses six synthetic certificates and stores no clinical
record. Its Help page and APIs run on a dedicated same-origin service so
public WHO calls do not occupy clinical Flask request workers. Application
POSTs require CSRF; only the read-only WHO ECT proxy POST is exempt because
ECT cannot attach the token. Release validation must show five parallel
public Process submissions while clinical requests remain responsive.
Input, output, time and access-log limits apply before public release.
