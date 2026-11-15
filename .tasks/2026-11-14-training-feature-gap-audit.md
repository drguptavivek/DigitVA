# Training feature (TRN01) gap audit, Fable, 2026-11-14

- Status: findings, not fixed
- Source: read-only Fable audit (owner-approved one-off Fable subagent); pytest not run.

1. HIGH: trainee `reviewer_data_manager` gets a real `data_manager` grant on the session root
   (`app/services/training_demo_service.py:156-162`); users/grants APIs have no training scope
   (`app/routes/api/users.py`, `app/services/authz/grant_writes.py:242-245`,
   `app/services/authz/actions.py:155-161`). The trainee can list co-trainees (names, emails,
   phones), add/revoke their TRN01 grants, and via `sign_in_qr_service.may_issue`
   (`app/services/sign_in_qr_service.py:113-126`) issue a sign-in QR for a co-trainee whose only
   grants are training interviewer/death_reporter. Not exercised end to end. Staging S001: 3 active
   reviewer_data_manager trainees, 2 non-admin.
2. MEDIUM: training impossible on the phone by design (`src/AppState.tsx:601-602`,
   `app/routes/api/intake.py:107-141`, `app/services/access_summary_service.py:119-122`).
3. MEDIUM: answer key reaches coders: coder + reviewer_data_manager reads `reference_cause` in the
   report/cases.csv (`app/services/training_report_service.py:91-112`); every session copies the
   same corpus in the same order (`training_demo_service.py:393-406,426-457`), so one key fits all
   sessions.
4. LOW-MEDIUM: ODK `deviceid` survives pseudonymisation (`training_demo_service.py:509-511`,
   `app/services/training_pseudonymiser.py`); 200/200 copies on dev. Address/phone handling
   unverified on staging data.
5. LOW: sign-in QR can pick TRN01 as enrolment project (`sign_in_qr_service.py:87-110`,
   `web_intake_service.py:345,473`).
6. LOW: trainer report double-counts multi-role staff (`training_report_service.py` ~150-178,
   271-292); `_coded_counts_stmt` (`training_demo_service.py:892-902`) counts tester finals.
7. LOW: sessions cannot be resized/reassigned/deleted; removed coder keeps slot
   (`:1243-1251`); creation is synchronous (`app/routes/admin_training.py:84-97`).
8. LOW: `map_training_participants.user_id` lacks a general index (`mas_training.py:132-136`).
9. LOW docs: policy says "21st coder refused" (code uses coder_slots); cross-project reporting
   section contradicts exclusion; DeviceID claim; dead `get_session_cases` (`:974-998`).

Verdict: fix 1, then 3 and 4, before building session types.
