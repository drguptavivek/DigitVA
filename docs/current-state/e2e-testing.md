---
title: End-to-end testing (Collect Plus on the emulator, supervisor on the web)
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-11-13
---

# End-to-end testing

Local only, against the dev stack: never CI, never staging, never a real phone. Maestro drives the
Collect Plus debug build (Metro on 8081) on the Android emulator; one Playwright spec checks the
supervisor on the web app. Scenario list and owner decisions:
`.tasks/2026-11-12-maestro-e2e-scenarios.md`. Flow-level detail:
`mobile/digitva-collect/.maestro/README.md`.

## Running

```bash
make maestro-android                                   # every flow, emulator-5554
make maestro-android FLOWS="60-register 70-interview"  # subset (file-name substrings)
mobile/digitva-collect/.maestro/run-suite-2.sh 60-register 70-interview   # second emulator, emulator-5556
```

`run-suite-2.sh` is a copy of `run-suite.sh` for emulator-5556 with its own users file
(`private/e2e-users-2.json`), so two runs can go at once. It also runs the web supervisor check
right after flow 70; `run-suite.sh` does not yet.

## What a run does

1. `flask seed e2e-users create`: a fresh set of single-role users for this run
   (`e2e.<run>.<role>@e2e.causeofdeathindia.com`, one random password), on TST001 and TST002,
   plus a mentor in the test mentoring institute TSTMI01.
2. `pm clear` on the app: every run starts with no profiles and no device enrolment.
3. `setup/enrol-users.yaml` enrols every user once; flows switch profiles, never re-enrol.
4. Each `flows/*.yaml` runs as its own Maestro run, continuing on failure. A flow with
   `checks/<name>.sh` is then checked on the server (scalar counts only, no personal columns).
5. Always, on exit: `flask seed e2e-users teardown --run <run>`. It deactivates this run's
   users, revokes their grants and cancels their open cases (audited transitions). Never run
   teardown without `--run`: another run may be live.

## Secrets

The password and the run's PIN live only in the script's `MAESTRO_*` environment. Maestro and
Playwright output is masked before it is kept; a failed flow prints one `failed-step:` line.
Never print run logs, credentials or process arguments. Playwright records no trace, video or
screenshots.

## Flows

| Flow | Covers |
| --- | --- |
| 10 | Consent cancel |
| 20, 30, 40, 50 | Draft reopen; media survives Home, kill, lock and profile switch; lock/unlock; switch profile |
| 60 | Death reporter registers a death (TST001) |
| 70 | Interviewer opens it from To do, consent, full questionnaire, Complete, sent |
| web supervisor | `web/supervisor-sees-case.spec.ts`: e2e supervisor sees the run's case in the supervision view |
| 80 (three parts) | Queue offline, send online; the wrapper switches wifi and data between parts (`# wrapper:` markers) |
| 81 | TST002: reporter registers, interviewer completes from To do |
| 82 | TST001 masked two-step coding on the phone (COD Assessment, DORIS) |
| 83 | TST002 single-step coding with narrative QA and social autopsy (online) |
| 90, 92, 95 | Sign out, PIN recovery, delete-profile guard |

Order matters: 82 and 83 code the cases 70 and 81 sent, and 95 deletes the coder profile.

## Test projects

- TST001: masked two-step coding, DPDP consent on (`test-project-tst001.md`).
- TST002: single-step coding, narrative QA and social autopsy on.
- Every new project gets the default DPDP consent; unset contact values read "DIGITVA Team"
  and info@causeofdeathindia.com, never placeholders (`docs/policy/respondent-consent-notice-draft.md`).

## Known limits (2026-11-13)

- The full questionnaire in 70 and 81 takes about 45 minutes per interview.
- The debug build's LogBox toast is hidden (`app/_layout.tsx`) because it swallowed taps near
  the bottom of the screen.
- Both scripts empty `~/.maestro/tests` after each flow, so two parallel runs delete each other's
  Maestro debug output (results are unaffected).
- Not yet green: the full suite twice in a row, flow 80 part 2, the coding flows 82 and 83.
- Planned: spare users for sign-out, PIN reset, delete profile and access removed; conflict
  flows with the other actor played through the server.
