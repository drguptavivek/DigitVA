# Maestro e2e suite (local only, never CI)

Flows for the Collect Plus debug build on the Android emulator `emulator-5554`
(never a real phone; the wrapper refuses any other serial). Test data only.
Metro must serve the bundle on 8081 and the app must point at the dev server
(`http://10.0.2.2:8051`). Bead digitva-xjpk; scenario list in
`.tasks/2026-11-12-maestro-e2e-scenarios.md`.

Run everything: `make maestro-android` (= `.maestro/run-suite.sh`). A subset:
`make maestro-android FLOWS="10-consent 30-media"`.

`run-suite.sh` does, in order:

1. `flask seed e2e-users create`, then exports the credentials from
   `private/e2e-users.json` and a random 6-digit run PIN as `MAESTRO_*`
   environment variables. Nothing secret is on a command line or in a file here,
   and Maestro's output is masked before it is printed.
2. `adb shell pm clear` on the app: every run starts with no profiles and no
   device enrolment, so the emulator is test-only (owner 2026-11-13).
3. `setup/enrol-users.yaml`: signs in the interviewer, interviewer2, reporter and
   coder users and sets the run PIN on the phone.
4. Every `flows/*.yaml` as its own `maestro test` run (continue on failure, one
   retry when the Maestro driver dies), then the `checks/<flow>.sh` server check
   when there is one (SQL on counts and statuses, no personal columns).
5. On exit, always: network back on, `flask seed e2e-users teardown --run <this
   run>` (never unscoped: another run may be live), `rm -rf ~/.maestro/tests/*`.
   A hard stop (`kill -9`) skips this; tear the run down by its id afterwards.

## Flows

| Flow | Scenarios | User |
| --- | --- | --- |
| `10-consent-cancel` | I02, I03: consent No, Cancel twice, leave, reopen: Yes and answers kept | interviewer |
| `20-draft-reopen` | I07, P02: leave a draft on section 3, reopen; force-stop, relaunch, unlock, reopen | interviewer |
| `30-media-survives` | M01, M03, M06, P01, P02, P03, U02: audio and camera photo survive Home and return, force-stop, lock, profile switch | interviewer |
| `40-lock-unlock` | P03: Lock now and unlock, counts and answers intact | interviewer |
| `50-switch-profile` | U02: switch to interviewer2 and back, each sees only its own drafts | interviewer |
| `60-register-death` | R04, R01: half-done registration kept across Home, then saved twice (regA, regB) | reporter |
| `70-interview-send` | I01: full interview of regA from To do (consent, every question, Complete), sent; server receipt checked (case `submitted`) | interviewer |
| `80-offline-1-prepare`, `80-offline-2-queue`, `80-offline-send` | I09: online start and refresh; wifi and data off, interview of regB queued Unsent with the Offline chip showing, send attempt does not send; network back, sent once | interviewer |
| `81-register-interview-tst002` | R01, I01 on TST002: reporter_t2 registers a death, interviewer_t2 does the full interview from To do (social autopsy questions), Complete, sent | reporter_t2, interviewer_t2 |
| `82-code-tst001-two-step` | C01, C04 phone path: masked two-step coding on the Code tab (Step 1 then final cause, CA40.Z) | coder |
| `83-code-tst002-single-step` | PS25, PS31, PS33, PS39, C32: NQA (Cannot grade) and social autopsy (None) saved, then single-step "Save cause of death" | coder |
| `90-profile-signout` | U01, U03: two profiles listed; sign out with nothing unsent keeps the data, sign in again and PIN | reporter |
| `92-pin-recovery` | Forgot PIN: password sign-in resets the PIN, counts unchanged | interviewer |
| `95-delete-guard` | Delete profile: refused while drafts are unsent, allowed with nothing unsent | interviewer, coder |

The three 80 parts run in order and share the phone's state. A flow whose file starts with `# wrapper: offline-before` or `# wrapper: online-before` makes `run-suite.sh` run `svc wifi` and `svc data` disable or enable (adb, emulator only) before it, because Maestro cannot run adb itself and the app must not be relaunched while offline. On a failure the wrapper prints one `failed-step:` line (first FAILED line of the masked log). Order matters only for 60 -> 70 -> 80 -> 81 -> 82 -> 83 (83's check counts 82's final cause too) (the interviews start the deaths 60
registers) and 95 last. Each of the others creates its own draft and asserts
Drafts / To do before and after. `sub/` holds the subflows, never run alone.

## Debug-build behaviour the flows work around

- A tapOn costs about 11 s whatever the options (the app never settles for the
  driver); a flow with 40 taps takes 8 minutes. The whole suite takes hours.
- The debug build's LogBox warning toast is hidden (`app/_layout.tsx`), so there is no
  dead zone at the bottom of the screen: taps use text or id, no coordinates.
- Taps right after a cold start are sometimes dropped: tab taps are repeated
  until the screen shows (`sub/refresh.yaml`).
- The soft keyboard hides the tab bar and the choices below the field: tap a
  label (not `hideKeyboard`, which sends Back on Android) before leaving a field.
- A text box keeps its caret where it was tapped: tap its right end, `eraseText`,
  then `inputText`. The PIN goes whole into the debug-only `pin-input` field; interviews pass the consent screens through `sub/consent-grant.yaml`. Order after choosing the site: "Respondent consent" (scroll for Select all, mode "Tapped on the device", then "Respondent agrees"), "Before you begin" ("Start questionnaire"), then the form.
- Going offline also cuts Metro: never relaunch the app while offline. `setAirplaneMode` does not make the app show Offline on the emulator, so flow 80 uses the wrapper's `svc wifi/data` switch. The wrapper turns the network on at exit.
- Screenshots are black (FLAG_SECURE): debug with `maestro hierarchy`.
- "Device server died": `adb -s emulator-5554 forward --remove-all; adb -s
  emulator-5554 shell am force-stop dev.mobile.maestro; adb -s emulator-5554 shell
  am force-stop dev.mobile.maestro.test`. The wrapper does this before each flow.
- Teardown revokes the phone's device; the next run's first sign-in is refused
  once, the app forgets the device and `sub/enrol.yaml` enrols again.
- A profile with unsent drafts cannot be deleted in the app, so the interviewer
  profile of each run stays on the phone (the list grows by one row per run).

## Web check: supervisor sees the sent case

Supervision exists only in the browser app, so this one is Playwright, not Maestro:
`.maestro/web/supervisor-sees-case.spec.ts` signs in on the dev web app (`make dev-hmr`,
http://localhost:8051) as the run's `supervisor`, opens `/death-registration?view=mine&preset=supervision`,
picks "Total in scope" and asserts `E2E<run id>regA` (the case 70-interview-send sent) is listed.
Run it after a Maestro run while that run's users still exist (before the wrapper's teardown, so
not after `make maestro-android` has finished; or against users you made with
`flask seed e2e-users create --out <file>`): `.maestro/run-web-supervisor.sh [users-file]`
(default `private/e2e-users.json`). The script puts E2E_SUPERVISOR_EMAIL, E2E_PASSWORD and
E2E_RUN_ID in its environment only. Playwright comes from `vendor/who-va-2022/node_modules`
(this app has none) and drives the installed Google Chrome; trace, video and screenshots are off
so the password is not recorded.
