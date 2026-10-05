# Per-project self-coding (digitva-xuxk)

- Status: server built 2026-10-05; app half `digitva-xuxk.1` (expo-handoff.md section 10)
- Priority: P2
- Created: 2026-10-05

## Goal

In a self-coding project the medical officer interviews and then codes their
own case. Off by default.

## Owner decisions

- SmartVA runs on completion (`digitva-533t`, done).
- Browser submit reply and the app offer "Code this case now".
- In a self-coding project the Coder role gets the Interviewer role
  automatically (2026-10-05).
- 2026-10-05, replaces "only the submitter codes it": the two flows are
  linked, not exclusive. The case still enters the normal pool and any coder
  may take it. One allocation at a time stays; a coder can release their
  allocation, and the existing auto release (1 h) stays.
- Review stays as the project sets it; corrections after self-coding follow
  the revision / send-back rules.

## Design (advisor-checked)

1. `va_project_master.self_coding_enabled` boolean, default false, additive
   migration. Admin project PUT/POST; refuse on when `web_intake_mode` is
   `off` (`interviewer_context` skips such projects).
2. Coder implies interviewer, derived at read time, no extra grant rows:
   `ProjectSettings.self_coding` in `app/services/authz/grants.py`; `_resolve`
   emits one non-virtual interviewer `Grant` per coder grant on a
   self-coding project (same scope, same `opens_gate`). Add the column to
   `grant_cache._GLOBAL_COLUMNS`, bump `_FORMAT`. Then route the DB-direct
   readers through it: `VaUsers.is_interviewer()` -> `role_flags`;
   `interviewer_context` inputs from `resolve_grants(user).of({interviewer},
   virtual=False)`; `_interviewer_grant_scopes` in
   `web_intake_readiness_service.py` adds coder grants on self-coding
   projects. Rejected: writing paired interviewer rows (seven grant write
   sites, revoke/backfill/flip-off cleanup, rows visible in the grant UI).
3. No pool change: no submitter-only predicate.
4. "Code this case now": allocate that va_sid to the submitter when the
   project is self-coding, the user owns the submitted `VaWebIntakeDraft`,
   the case is `ready_for_coding` and the user holds no other allocation.
   Works in random and pick mode (relax the pick-mode check in
   `coder_workflow_service.allocate_pick_form` for this case only). Case
   still `smartva_pending` -> 409 with `workflow_state`; client retries.
   Taken by another coder -> refused.
5. Coder "Release" action on their own active allocation, reusing
   `coding_allocation_service._release_coding_allocation` (same effect as
   the timeout: unfinished Step 1 / first-pass work on that case is
   deactivated, case back to `ready_for_coding`).
6. The MO's own completed interviews awaiting coding show "Code now" on
   the interviewer worklist.

## Defaults taken (tell the owner; change if they object)

- Mentor-institute members: their Coder grant does not imply interviewing
  (they may not interview, `check_mentor_grant`).
- No cadre check on the implied interviewer (cadre is write-time only).
- Only a coder grant that codes implies interviewing (an above-scope
  view-only coder does not interview).
- Admin refuses web intake `off` while self-coding is on, and the reverse.
- A coder release is audited under the coder's own user id.
- "Code this case now" is also 409 while attachments are pending.

Policy baseline written 2026-10-05: `docs/policy/web-intake.md`,
`coding-workflow-state-machine.md`, `coding-allocation-timeouts.md`,
`access-control-model.md`, `roles-explained.md`.
