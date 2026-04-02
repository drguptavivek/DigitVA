---
title: Social Autopsy Analysis Policy
doc_type: policy
status: active
owner: engineering
last_updated: 2026-04-02
---

# Social Autopsy Analysis Policy

## Purpose

This document defines the baseline behavior for the app-owned Social Autopsy
analysis form shown within the `social_autopsy` coding category.

## Baseline

Social Autopsy analysis is a coding workflow artifact, not synced ODK submission
data.

Current baseline:

- it is rendered inside the `social_autopsy` category after the mapped Social
  Autopsy submission questions
- the app-owned Social Autopsy analysis form is controlled by the project-level
  `social_autopsy_enabled` flag
- when `social_autopsy_enabled = false`, the mapped `social_autopsy` category
  may still render its synced submission fields, but the app-owned Social
  Autopsy analysis form must not be shown
- it is available only in coder-facing coding flows
- it is payload-version aware
- the current Social Autopsy analysis for a coder is the active row whose
  `payload_version_id` matches the submission's current
  `active_payload_version_id`
- each delay factor selection is stored as a normalized child row, not flattened
  into submission JSON
- saving the analysis must create an audit log entry against the submission

## Question Model

The analysis form has three delay levels:

- `delay_1_decision`
- `delay_2_reaching`
- `delay_3_receiving`

Each delay level supports multiple selected options.

## Storage Model

The source of truth is normalized:

- parent analysis row for the coder/submission
- child selection rows for `(delay_level, option_code)`

This is preferred over boolean columns for each option so the questionnaire can
evolve without forcing schema expansion for every option change.

If reporting later needs a flattened shape, a materialized view may be added on
top of the normalized write model.

## Save Semantics

Current baseline:

- save requests target the submission's current active payload version
- if the coder already has an active Social Autopsy row for that payload, that
  row is updated in place
- if the payload has changed, a new row is created for the new payload and the
  coder's older active row is deactivated
- every delay level must have an explicit saved answer before the analysis is
  considered complete; if no delay factor applies, the coder must select `none`
- multiple selected options per delay level are allowed
- each delay level also provides an explicit `none` option
- `none` is exclusive within its delay level; if `none` is selected, other options
  for that same delay level must not be stored
- duplicate option selections in the same request must be ignored
- invalid delay/option combinations must be rejected
- optional free-text remarks may be stored on the parent analysis row

## Upstream Change Handling

Current baseline:

- `Accept And Recode` after upstream ODK change deactivates the old active
  Social Autopsy analysis because the case returns to coding against new data
- `Keep Current ICD Decision` promotes the new ODK payload and rebinds the
  preserved active Social Autopsy analysis to the new current payload

## Simple Examples

### Example: normal coding

1. Submission `SID-1` currently uses payload `P1`
2. Coder saves Social Autopsy analysis
3. DigitVA stores one active Social Autopsy row for `(SID-1, coder, P1)`

### Example: payload changed before coder saves again

1. ODK data changes and DigitVA now uses payload `P2`
2. Coder saves Social Autopsy again
3. DigitVA deactivates the coder's old active row for `P1`
4. DigitVA creates a new active row for `P2`

### Example: keep current ICD decision

1. `SID-1` was finalized on payload `P1`
2. ODK sends a new payload `P2`
3. Data manager chooses `Keep Current ICD Decision`
4. DigitVA promotes `P2` and rebinds the active Social Autopsy row from `P1`
   to `P2`

## Visibility

Current baseline:

- the form is shown only in coder coding flows:
  - `vastartcoding`
  - `varesumecoding`
  - `vademo_start_coding`
- it is not currently a reviewer or site-PI form

## Completion Requirements

Current baseline:

- when the Social Autopsy analysis form is enabled and present, it must be completed before
  the coder can move past the `social_autopsy` category
- when the Social Autopsy analysis form is enabled and present, final COD submission must be
  blocked until the coder has saved a complete analysis

## Change Control

Any future change must explicitly document:

- whether the form becomes configurable via category component placement
- whether reviewer or site-PI visibility is added
- whether final COD submission depends on Social Autopsy analysis completion
- whether reporting uses a materialized view or direct normalized queries
