# Demo reviewing

Status: done 2026-09-27
Priority: P1
Created: 2026-09-27

## Goal

Let trainees practise the reviewer flow on demo/training projects. Owner
decisions (2026-09-27): reviewer availability is always on in demo mode, and
when the coder's demo final code expires, the review on that case expires
with it.

## Design (no migration)

1. **Reviewable immediately.** For projects with `demo_training_enabled`,
   the coder final save moves the case `coder_finalized -> reviewer_eligible`
   at once through the existing system transition
   `mark_reviewer_eligible_after_recode_window`. Admin-started demo sessions
   on ordinary projects keep the 24-hour recode window.
2. **Open reviewer access.** Demo project forms join the reviewer scope in
   `VaUsers._get_granted_va_forms`, as they already join coder, coding
   tester and data manager scope (app/models/va_users.py:467-468).
3. **Expiry cascades by case.** When `cleanup_expired_demo_coding_artifacts`
   expires a case's demo coder final, it also deactivates that case's active
   reviewer final and initial assessments, reviewer review, NQA and social
   autopsy rows (reviewer rows carry no `demo_expires_at`), and its active
   reviewing allocation, with audit rows; then resets the case. Expiry is
   tied to the coder final, so no per-row reviewer expiry column is needed.
4. **Reset from reviewer states.** `reset_demo_state` accepts
   `reviewer_eligible`, `reviewer_coding_in_progress` and `reviewer_finalized`
   as sources (system/admin actors only). Without this a reviewed demo case
   makes the whole cleanup run raise before its commit.
5. **Authority.** `upsert_final_cod_authority` already clears the reviewer
   pointer; the reviewer finals are deactivated so the active-reviewer
   fallback cannot surface them.

## Out of scope

- Reviewer-is-not-the-coder rule (none exists today; not added for demo).
- Reviewer-side demo expiry stamps or a separate reviewer retention window.

## References

- docs/policy/demo-coding-retention.md (baseline updated first)
- app/services/coding_allocation_service.py (cleanup)
- app/services/workflow/transitions.py (reset_demo_state, reviewer transitions)
- app/services/reviewer_coding_service.py (start_reviewer_coding)
- app/services/payload_bound_coding_artifact_service.py (deactivate helpers)
- app/services/final_cod_authority_service.py

## Outcome

Implemented as designed and checked end to end on SADEMO: a demo coder save
made the case reviewer-eligible at once, a user with no reviewer grant ran
the DORIS reviewer editor and saved a reviewer final, and running the demo
cleanup past the coder's expiry deactivated the reviewer final, NQA and
reviewing allocation, cleared authority and reset the case.

Found in review and fixed: the coder's NQA and Social Autopsy expire before
the coder final, so cleanup could reset a case under review while the coder
final was live. Cases in reviewer states are now reset only when the coder
final itself expires. Side effect accepted with the owner decision: demo
cases leave coder_finalized at once, so demo recode is no longer offered.
The unmasked reviewer form now shows SmartVA, as the approved unmasked
design (digitva-ddv.1) specifies.
