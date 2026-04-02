---
title: Narrative Quality Assessment Policy
doc_type: policy
status: active
owner: engineering
last_updated: 2026-04-02
---

# Narrative Quality Assessment Policy

## Purpose

This document defines the baseline behavior for coder Narrative Quality
Assessment (NQA) in DigitVA.

## Baseline

Narrative Quality Assessment is a coder-owned supporting artifact. It is not
ODK data and it is not the final COD decision.

Current baseline:

- it is available only in coder-facing coding flows
- it stores the coder's scored assessment of narrative quality
- it is payload-version aware
- the current NQA for a coder is the active row whose `payload_version_id`
  matches the submission's current `active_payload_version_id`
- saving NQA creates an audit log entry against the submission

## Save Semantics

Current baseline:

- save requests target the submission's current active payload version
- if the coder already has an active NQA row for that payload, the row is
  updated in place
- if the payload has changed, a new row is created for the new payload and the
  coder's older active row is deactivated
- historical NQA rows may remain in the table as inactive history

## Workflow Rules

Current baseline:

- first-pass timeout deactivates active NQA for that coding session
- recode timeout preserves active NQA when the payload did not change
- `Accept And Recode` after upstream ODK change deactivates the old active NQA
  because the case returns to coding against new data
- `Keep Current ICD Decision` after upstream ODK change promotes the new ODK
  payload and rebinds the preserved active NQA to that new payload

## Simple Examples

### Example: normal first-pass coding

1. Coder opens submission `SID-1`
2. Current payload version is `P1`
3. Coder saves NQA
4. DigitVA stores one active NQA row for `(SID-1, coder, P1)`

### Example: same payload recode

1. `SID-1` is reopened for recode without any ODK data change
2. Current payload version is still `P1`
3. Existing active NQA remains current
4. If coder edits NQA, DigitVA updates the same active row

### Example: upstream change accepted for recoding

1. `SID-1` was finalized on payload `P1`
2. ODK sends changed data and DigitVA creates pending payload `P2`
3. Data manager chooses `Accept And Recode`
4. DigitVA promotes `P2` to current, deactivates the old active NQA, and
   reopens coding
5. The next coder NQA save creates a new active NQA row for `P2`

### Example: upstream change kept without recoding

1. `SID-1` was finalized on payload `P1`
2. ODK sends changed data and DigitVA creates pending payload `P2`
3. Data manager chooses `Keep Current ICD Decision`
4. DigitVA promotes `P2` to current, keeps the finalized ICD decision, and
   rebinds the active NQA from `P1` to `P2`

## Change Control

Any future change must explicitly document:

- whether reviewer-owned NQA follows the same payload-version rule
- whether NQA becomes configurable outside coder flows
- whether NQA contributes to workflow gating beyond the current final-COD block
