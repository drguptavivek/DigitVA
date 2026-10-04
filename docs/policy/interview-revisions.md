---
title: Interview Revisions Policy (editing submitted interviews)
doc_type: policy
status: draft
owner: engineering
last_updated: 2026-10-05
---

# Interview Revisions Policy

Owner decisions of 2026-10-04, bead `digitva-bhpl`. Baseline written before
implementation. It covers interviews from the browser and from the app.

## Status (`digitva-bhpl`)

**Built (part A)**: rules 1 and 2, the partial-finish rule and the no-change
rule, on the server: `POST /api/v1/intake/submissions/<va_sid>/revisions`
([Device Collection API](../current-state/device-collection-api.md), "Interviewer
revisions"), the shared release `release_coding_for_changed_payload`
(`app/services/coding_release_service.py`, called by ODK sync and by the
revision), the `interviewer_revision` audit reason, and the payload-version
columns `revision_reason_code` and `answers_sha256`. A submitted draft keeps its
complete raw answers in a `final` section. The revision reasons are fixed codes:
`interviewer_correction`, `respondent_correction`, `more_information`,
`finish_partial`.

**Built (part B)**: rules 3 and 4. `POST /api/v1/coding/submissions/<va_sid>/send-back`
(the coder who finalised it, a reviewer working on or eligible for it) and
`POST /api/v1/intake/supervision/submissions/<va_sid>/reopen-for-revision`
(interview supervisor, data manager, admin), both in
`app/services/interview_send_back_service.py`. They move the submission to
`finalized_upstream_changed` (transition reason `sent_back_for_revision` /
`reopened_for_revision`), which `revision_unlocked(submission)` in
`app/services/web_intake_service.py` reads. The reason codes are fixed, no free
text: send-back `missing_information`, `inconsistent_answers`,
`wrong_respondent_or_case`, `needs_clarification`; reopen `cod_review_requested`,
`new_information`, `data_correction`. The code is recorded on the submission's
audit row (`sent_back_for_revision:<code>`). The COD and coding artifacts stay
active until the revision arrives. The interviewer's changed revision then
restarts coding at once (no data-manager accept step) through the data
manager's accept block, shared as `reopen_coding_after_revision`
(`app/services/coding_release_service.py`), under a system actor with the
reason `interviewer_revision`; any lingering pending upstream payload version
is rejected. An unchanged revision leaves the case sent back. A data manager's
reject of the upstream change cancels a send-back or reopen: the case returns
to the state it came from. Only web and device interviews: an ODK submission is
refused (409 `not_web_submission`), ODK has its own needs-revision path.

**Not built**: the phone's Revise screen and "my submitted interviews" list,
and a browser screen for revising. Every ODK-protected state stays locked to
the interviewer unless the case was sent back or reopened.

Decisions made while building part A:

- A revision starts a new version only when the coding payload's canonical
  fingerprint differs. The no-change rule is about coding: a change to an
  answer that is irrelevant (stripped) makes no new version, no release, no
  SmartVA rerun and no routing, but the raw answers are kept (owner,
  2026-10-05): the previous ones as a history row, the new ones as the
  submission's raw answers, with the sent hash, so nothing typed is lost and
  the phone's acknowledgement matches. Raw answers with the stored hash write
  nothing. The interview times (`startedAt`, `completedAt`) are part of the
  payload: a new `completedAt` is a change.
- Only answers and interview times can change the fingerprint. The submitter's
  name, the organization-unit codes and names and the register's ABHA are taken
  from the version being replaced, and locked answers the submit held keep
  their stored value, so renaming the interviewer or a unit after the submit
  does not turn a resend of the same answers into a release.
- A revision from one incomplete outcome to another (partially completed,
  respondent unavailable, refused) moves the case to that outcome's state, as
  a submit does. If the case is no longer waiting for this interview (a
  teammate's complete submission won) the revision is refused
  (`case_state_conflict`) rather than leave case and submission disagreeing.
- Finishing a partial requires a live, placed organization unit, as a submit
  does.
- A completed-to-completed revision syncs the form's name, date of death and
  sex onto the case again: the winning submission is the one corrected.
- A revision keeps the original submission date, masked id and source of the
  interview; only the answers and times can change the fingerprint.
- The release runs for every changed revision, as ODK's does for every changed
  payload: a data manager's or coder's not-codeable exclusion is cleared too.
- A revision of a case that is `duplicate` or `cancelled` is refused
  (`case_closed`); finishing a partial after a teammate's complete submission
  is refused (`case_already_submitted`).

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
   a coder or reviewer can send it back for revision (built). Sending back
   reopens it for the interviewer; coding restarts on the new version, as soon
   as it arrives. Who: the coder who authored the final COD (from
   `coder_finalized`, `reviewer_eligible`), a reviewer in scope on a
   `reviewer_eligible` submission, the reviewer holding the session
   (`reviewer_coding_in_progress`, released first) or the reviewer who
   finalised it (`reviewer_finalized`).
4. **After final COD.** The case is locked. Only a supervisor, data manager
   or admin may reopen it, with a reason (built). Open to them from every
   state that holds a final COD (`coder_finalized`, `reviewer_eligible`,
   `reviewer_finalized`); not during a live reviewer session. The interviewer
   then revises and the case is recoded from scratch at once (no accept step,
   owner 2026-10-04). The earlier COD is kept in history.

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
  `reviewer_coding_in_progress`, `reviewer_finalized`, legacy `closed`),
  except a `finalized_upstream_changed` case that was sent back or reopened.
  An ODK upstream change on a `finalized_upstream_changed` case stays locked.
- Send-back mirrors ODK's needs-revision path (`mark_submission_needs_revision`
  in `app/services/odk_review_service.py`): a coder or reviewer sends the case
  back with a fixed reason code, and the data then changes under the existing
  upstream-change handling (`finalized_upstream_changed`). The revision
  re-enters the case at `smartva_pending`; the earlier COD is kept as history.

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
  `release_coding_for_changed_payload` in
  `app/services/coding_release_service.py`, the one implementation both
  use) rather than a second implementation. It audits with its own reason,
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
  return the owner's submitted draft; the envelope holds the complete raw
  answers and the reply carries their `answers_sha256`.
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
