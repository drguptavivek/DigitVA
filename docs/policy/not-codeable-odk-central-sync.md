---
title: Not Codeable ODK Central Sync Policy
doc_type: policy
status: active
owner: engineering
last_updated: 2026-03-14
---

# Not Codeable ODK Central Sync Policy

## Baseline

When a coder marks a submission as Not Codeable in DigitVA:

- the local DigitVA workflow outcome must be saved first
- the coding allocation must be released locally
- the case must not be blocked by ODK Central availability or API failures

Updating ODK Central review state is a follow-up sync step, not the source of
truth for the local Not Codeable decision.

## Required Behavior

DigitVA must:

- save the local `va_coder_review` record
- write the local audit trail for the Not Codeable decision
- release the active coding allocation
- then attempt to set ODK Central review state to `hasIssues`

If the ODK Central write-back succeeds:

- update local submission review-state cache as applicable
- write a success audit event

If the ODK Central write-back fails:

- do not roll back the local Not Codeable outcome
- write a failure audit event
- surface a warning to the user that local save succeeded but ODK Central
  update failed

## Operational Intent

This split exists so that:

- coder workflow is not blocked by temporary ODK Central issues
- DigitVA remains the local record of the coding action
- failures are diagnosable and repairable later through audit logs and admin
  review

## Audit Expectations

The audit trail should make these states visible:

- Not Codeable saved locally
- ODK revision flag applied
- ODK revision flag update failed

The failure path must remain discoverable in admin activity views and logs so
operators can diagnose and fix Central sync issues separately.
