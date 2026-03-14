---
title: Admin Activity Log Policy
doc_type: policy
status: active
owner: engineering
last_updated: 2026-03-13
---

# Admin Activity Log Policy

## Baseline

DigitVA exposes an admin-only workflow activity log sourced from
`va_submissions_auditlog`.

The purpose of the panel is to let admins inspect coder workflow progression for
submissions, including milestone events such as:

- coding started
- Social Autopsy analysis saved
- Narrative Quality Assessment saved
- Step 1 COD submitted
- Step 2 COD submitted

## Source of truth

The activity log must read from the existing submission audit log table rather
than introducing a parallel workflow-event store.

Workflow features that represent meaningful coder progress should write
auditable events into `va_submissions_auditlog`.

## Access

The current activity log panel is admin-only.

Project PI users may continue to access the broader admin shell where allowed,
but the workflow activity log is not part of their current baseline access.
