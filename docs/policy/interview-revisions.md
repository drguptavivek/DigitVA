---
title: Interview Revisions Policy (editing submitted interviews)
doc_type: policy
status: draft
owner: engineering
last_updated: 2026-10-04
---

# Interview Revisions Policy

Owner decisions of 2026-10-04, bead `digitva-bhpl`. Baseline written before
implementation. It covers interviews from the browser and from the app.

Not built yet (`digitva-bhpl`): everything below, including the
`interviewer_revision` audit reason. Today a submitted web case
cannot be edited ([Web Intake Policy](web-intake.md)).

## Rules by stage

1. **Before upload.** The interviewer edits freely, including after marking
   the interview complete.
2. **After upload, until the coder finalises.** Only the interviewer who did
   the interview may revise it. A reason is required. There is no approval
   step, no supervisor gate and no time window (owner: friction free). A
   revision during active coding drops the coder's unfinished work and sends
   the case back to `smartva_pending`, as an ODK edit does (owner,
   2026-10-04: match ODK exactly).
3. **Once the coder finalises.** The case is locked for the interviewer. Only
   a coder or reviewer can send it back for revision. Sending back reopens it
   for the interviewer; coding restarts on the new version.
4. **After final COD.** The case is locked. Only a supervisor or admin may
   reopen it, with a reason. The interviewer then revises and the case is
   recoded from scratch. The earlier COD is kept in history.

### Where the lock starts

This uses the workflow states from
[Coding Workflow State Machine](coding-workflow-state-machine.md) and the
protection classes of [ODK Sync Policy](odk-sync-policy.md) ("Workflow State
Guards").

- **Open to the interviewer**: `consent_refused`, `screening_pending`,
  `smartva_pending`, `ready_for_coding`, the not-codeable states, and the
  active coding states `coding_in_progress`, `partial_coding_saved`,
  `coder_step1_saved` (a revision there releases the allocation, drops the
  unsaved and partial coding, and re-routes to `smartva_pending`).
- **Locked for the interviewer**: every ODK-protected state
  (`coder_finalized`, `finalized_upstream_changed`, `reviewer_eligible`,
  `reviewer_coding_in_progress`, `reviewer_finalized`, legacy `closed`).
- Send-back mirrors ODK's needs-revision path (`mark_submission_needs_revision`
  in `app/services/odk_review_service.py`): a coder or reviewer sends the case
  back with a comment, and the data then changes under the existing
  upstream-change handling. In a non-final state the case re-enters at
  `smartva_pending`. In a protected state it goes through the reopen rule (4)
  and the earlier COD is kept.

## What a revision is

- **A partial submission** (case paused) is finished by revising the same
  submission, not by a fresh draft. A revision that changes the outcome to
  completed runs the completion branch: the case goes to `submitted`, the
  submission id is set and the submission enters coding. The partial version
  stays in history.
- **Not a case transition.** `submitted` stays terminal for the case. A
  revision is a new payload version plus a workflow move on the submission.
- **No-change rule.** A revision whose fingerprint equals the current version
  does nothing: no allocation release and no SmartVA rerun. This is the ODK
  rule ([ODK Sync Policy](odk-sync-policy.md), "Allocations During Sync":
  a case whose payload did not change keeps any coder session untouched).
- **During active coding** the revision reuses ODK's release code path
  (allocation deactivated, case re-routed to `smartva_pending`;
  `app/services/va_data_sync/va_data_sync_01_odkcentral.py`, ~lines 897-925)
  rather than a second implementation. It audits with its own reason,
  `interviewer_revision`, separate from ODK's
  `va_allocation_released_during_datasync`, so coder statistics can tell them
  apart (owner, 2026-10-04).
- **A revision starts from the raw stored answers**, all sections as the
  interviewer submitted them, not the stripped coding payload. Answers to
  questions that were irrelevant at submit time are not lost.

## Revising on the phone and in the browser

- Revision works in both. In the app, the submitted answers are downloaded on
  demand when the interviewer taps Revise. They sit on the device only while
  revising and are purged like other case data
  ([Field Data Collection Policy](field-data-collection.md)).
- The revision uploads as a new version. It is offline-safe and idempotent
  like any interview: client draft id, exact answers text and SHA-256, delete
  only after a matching acknowledgement ([Field Data Collection
  Policy](field-data-collection.md), "Upload integrity under connection
  drops").
- The phone needs a "my submitted interviews" list to revise from. Not built
  yet: the app drops submitted cases from its store today.
  `GET /api/v1/intake/drafts?status=submitted` and `GET /intake/drafts/<id>`
  already return the owner's submitted envelope.
- Locked prefill answers stay locked in a revision.
- A superseded copy cannot be revised
  ([Web Intake Policy](web-intake.md), "Parallel interviews").

## Versions and fingerprints

- Every version is kept and never overwritten.
- Each version records who, when, the reason, which answers changed, and its
  own SHA-256 answer fingerprint, taken over the exact answers text the
  interviewer's client sent.
- The current version is the one coding reads. Earlier versions and earlier
  COD are history.
- Every revision, send-back and reopen is audited: actor, case, reason, time.
  Reasons carry no personal data.

## Related

- [Web Intake Policy](web-intake.md)
- [Field Data Collection Policy](field-data-collection.md)
- [ODK Sync Policy](odk-sync-policy.md)
- [Coding Workflow State Machine Policy](coding-workflow-state-machine.md)
- [Final COD Authority Policy](final-cod-authority.md)
