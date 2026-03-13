---
title: Social Autopsy Analysis Policy
doc_type: policy
status: draft
owner: engineering
last_updated: 2026-03-13
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
- it is available only in coder-facing coding flows
- it stores one active analysis record per `(va_sid, coder)`
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

- save requests replace the coder's current active Social Autopsy analysis for the
  submission
- every delay level must have an explicit saved answer before the analysis is
  considered complete; if no delay factor applies, the coder must select `none`
- multiple selected options per delay level are allowed
- each delay level also provides an explicit `none` option
- `none` is exclusive within its delay level; if `none` is selected, other options
  for that same delay level must not be stored
- duplicate option selections in the same request must be ignored
- invalid delay/option combinations must be rejected
- optional free-text remarks may be stored on the parent analysis row

## Visibility

Current baseline:

- the form is shown only in coder coding flows:
  - `vastartcoding`
  - `varesumecoding`
  - `vademo_start_coding`
- it is not currently a reviewer or site-PI form

## Completion Requirements

Current baseline:

- when the Social Autopsy analysis form is present, it must be completed before
  the coder can move past the `social_autopsy` category
- when the Social Autopsy analysis form is present, final COD submission must be
  blocked until the coder has saved a complete analysis

## Change Control

Any future change must explicitly document:

- whether the form becomes configurable via category component placement
- whether reviewer or site-PI visibility is added
- whether final COD submission depends on Social Autopsy analysis completion
- whether reporting uses a materialized view or direct normalized queries
