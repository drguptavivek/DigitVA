# Prefill the DORIS certificate from the VA interview

- Status: Plan (2026-09-29); mapping to be verified and clinically reviewed before build
- Priority: P2
- Created: 2026-09-29
- Bead: `digitva-hln`
- Related: `docs/current-state/doris-cod-workflow.md`,
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

## Proposed mapping (question names and choice values to verify against
`vendor/who-va-2022/src/generated/who-va-2022.instrument.json` and the
payload of ODK-synced cases; DORIS codes per the reference doc)

| DORIS field | VA source | Rule |
|---|---|---|
| `AdministrativeData\Sex` | Id10019 | as today |
| `AdministrativeData\DateBirth` | Id10021 when Id10020 = yes | exact date only |
| `AdministrativeData\DateDeath` | Id10023 (Id10023_a/_b) when Id10022 = yes | exact date only |
| `AdministrativeData\EstimatedAge` | ageInDays / ageInMonths / ageInYears | only when a date is missing; keep days and months for infants (today's whole-year rule drops them) |
| `FetalOrInfantDeath\Stillborn` | stillbirth section (Id10104 / Id10114 and related) | only for neonates / stillbirth path |
| `FetalOrInfantDeath\DeathWithin24h` | ageInDays / age in hours if recorded | neonate path |
| `FetalOrInfantDeath\BirthWeight` | Id10366 (grammes) | neonate / child path |
| `FetalOrInfantDeath\PregnancyWeeks` | Id10367 (months) | converted months -> weeks, marked estimated |
| `FetalOrInfantDeath\MultiplePregnancy` | the multiple-birth question in the neonatal sections | |
| `FetalOrInfantDeath\AgeMother` | mother's age if the neonatal section records it | |
| `MaternalDeath\WasPregnant` | pregnancy_women section (Id10305/Id10306/Id10310 family) | women 12-49 |
| `MaternalDeath\TimeFromPregnancy` | Id10308 / delivery-to-death interval questions | mapped to DORIS bands |
| `MannerOfDeath\MannerOfDeath` | injuries_accidents (Id10077 injury, intent questions) | accident / self-harm / assault / undetermined only when the interview states it |
| `MannerOfDeath\DateOfExternalCauseOrPoisoning` | injury date if recorded | |
| `MannerOfDeath\PlaceOfOccuranceExternalCause` | injury place if recorded | mapped to DORIS codes |
| `MannerOfDeath\DescriptionExternalCause` | injury type answers as text | |
| `Surgery\WasPerformed` / `Date` / `Reason` | health-service questions about an operation in the final illness | |
| `Autopsy` | none in VA | left empty (VA has no autopsy) |

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
4. **Same payload, both sources.** Works for ODK-synced and web-intake cases
   alike, reading the active payload version.
5. **Recorded.** The saved certificate envelope records which fields were
   prefilled and whether the coder changed them (for later quality review),
   without duplicating PII outside the envelope.
6. **Clinical sign-off.** The owner (or a designated physician) reviews the
   verified mapping table, especially maternal and fetal/infant rules, before
   it ships; the table moves into `docs/policy/doris-cod-workflow.md`.

## Work

1. Verify every VA question name, choice value and DORIS code; produce the
   final table with examples from real (dev) payloads; owner review.
2. Policy section in `docs/policy/doris-cod-workflow.md`.
3. One pure mapping function (`doris_prefill_from_payload(payload) ->
   partial certificate + provenance`), replacing `_doris_admin_defaults`,
   validated through `normalize_certificate`; table-driven tests per field,
   including dk/refused/missing and neonate/child/adult/maternal cases.
4. Editor shows the provenance markers; envelope stores prefilled/changed
   flags.
5. Browser check on a coding page for an adult, a woman of reproductive age,
   a neonate and an injury death.
