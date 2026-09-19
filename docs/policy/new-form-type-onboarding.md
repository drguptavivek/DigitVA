---
title: New Form Type Onboarding
doc_type: policy
status: active
owner: engineering
last_updated: 2026-09-19
---

# New Form Type Onboarding

## Purpose

DigitVA runs one questionnaire today (`WHO_2022_VA`, with its
`WHO_2022_VA_SOCIAL` variant). Every mechanism that protects personal data
and feeds SmartVA was built against that instrument's field ids. This policy
sets what must be true before a second form type (PHMRC, Ballabgarh, or any
other) is used with real submissions, so the checks happen because the
procedure demands them and not because someone remembered.

It is the baseline for `.tasks`, tests and admin guidance whenever a form
type is added. See `docs/policy/access-control-model.md` ("The PII set must
be confirmed per form type") for the redaction rule this relies on and
`docs/policy/smartva-generation-policy.md` for SmartVA gating.

## Layers, not instruments

A DigitVA form type is usually a *layer* on a standard instrument, not a
questionnaire of its own. `WHO_2022_VA_SOCIAL` adds the social autopsy
sections to the one standard WHO 2022 VA instrument; which layers apply is
`enabled_extensions` from `/form-options`, and the instrument itself is
selected by the form type's `instrument_code`
(`docs/policy/va-web-form-options.md`). So a new `WHO_2022_VA_*` code renders
on the bundled instrument with no client change, while a genuinely new
instrument (PHMRC, Ballabgarh) needs its own bundled instrument. Which
instrument a form type layers on is recorded per form type in
`mas_form_types.base_instrument_code` (landed 2026-09-19); there is no naming
convention behind it any more. Either way the sequence below applies in full:
the PII set is per form type.

## Core rule

**A form type is not live until its PII set is confirmed and its SmartVA
input has been checked against real fields.** Registering the form type and
syncing its fields does neither. Until both are done, the system fails
closed on personal data and the form type is treated as under test.

## Sequence

1. **Register.** `flask form-types register --code <CODE> --name "<Name>"`
   or the admin panel's New Form Type. The form type has no fields yet, so
   nothing about PII can be decided here; the registry runs and creates only
   its three redaction-only rows.
2. **Map and sync.** Link the ODK form to a project-site pair with the new
   form type in the Project Forms panel and run the schema sync. Fields now
   exist as `mas_field_display_config` rows with `odk_label` set.
3. **Record the base instrument.** Set `base_instrument_code` to the standard
   instrument this form type layers on — `WHO_2022_VA` for a WHO 2022 layer,
   the new instrument's own code for a new instrument family — through
   `PATCH /admin/api/form-types/<code>`. It is shown by
   `GET /admin/api/form-types` and `flask form-types list`. A form type with
   no `base_instrument_code` has no bundled questionnaire: the web form
   refuses to render it and a project may not be configured to collect on it.
4. **Confirm the PII set.** In the field-mapping panel, flag every field
   that carries personal data as **Is PII**: at minimum the deceased's and
   respondent's names, any national or health identifier, free-text place
   fields, and the interviewer's name and id. The form type's card shows a
   standing warning until at least one owned field is flagged; the warning
   clearing means the set is confirmed, not that it is complete. Completeness
   is the reviewer's job in step 6.
5. **Check SmartVA input.** Run the SmartVA input export for a test
   submission on the new form type and confirm the columns SmartVA needs are
   present and the flagged PII fields are absent. This export is deliberately
   not withheld while the set is unconfirmed, so it can be checked in either
   order; the log line
   `pii set unconfirmed | <CODE> | smartva input export not withheld` is
   expected during this step and must be gone once step 4 is done.
6. **Review before real data.** Someone other than the person who did step 4
   compares the flagged set against the questionnaire and signs off. Record
   the sign-off in the form type's description or a `.tasks` entry with the
   date. Only then do real submissions sync against the form type.

## What the system does on its own

- **Unconfirmed fails closed.** A plain `collaborator` sees no payload on a
  submission page, and the submissions CSV export writes payload columns
  empty for every role. Nothing is silently exported in the clear.
- **The SmartVA input export is the one exemption.** It strips flagged
  fields but never withholds, so a new questionnaire can be tested with
  SmartVA before the set is final. It is a data-manager and admin feed, not a
  viewer surface.
- **Status is visible** in the field-mapping panel, in `GET
  /admin/api/form-types`, in form-type stats, and in `flask form-types list`
  and `stats`.
- **Flag changes take effect immediately** on every worker; the PII set is
  not cached across edits.

## What the system does not do

- It does not know which of a new form's fields are personal data. The
  registry's field list is WHO-keyed and will not flag PHMRC or Ballabgarh
  ids. Step 4 is manual by design.
- It does not block registering or activating an unconfirmed form type.
  Refusing activation was rejected because a form has no fields at
  registration; the sequence above is the guard instead.
- It does not withhold the SmartVA input for a form whose form type cannot
  be resolved at all. That path applies only the hardcoded omit list and is
  unchanged from before the confirmation rule existed.

## Tests to add when a second form type lands

- A fixture with the new form type's real name and identifier field ids,
  asserting they are present in an unfiltered payload and absent from the
  submissions export and the viewer render once flagged.
- A SmartVA input export test on the new form type asserting the required
  input columns are present and every flagged field is absent.
- Both must assert the subject is present before asserting it is absent, per
  `docs/policy/test-harness.md`.
