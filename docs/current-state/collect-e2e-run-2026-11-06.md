---
title: Collect end-to-end run 2026-11-06
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-11-07
---

# Collect end-to-end run 2026-11-06

This run tested Collect Plus by hand on the Android emulator (DigitVA_Pixel_7, emulator-5554) and
the iOS simulator (iPhone 17 Pro, iOS 27.2). The app used the local dev server (localhost:8051) and
the seeded TST001 accounts. One Sonnet coordinator per platform sent Haiku drivers to operate the
device, then checked the drivers' claims against screenshots, server logs, psql and crash logs.
Screenshots are in `docs/current-state/collect-e2e-run-2026-11-06/{android,ios}/`. Results the
coordinator confirmed from a screenshot are marked (v). Results marked (d) rest on the driver's report.

## Coverage limits

- **Plain Collect was not tested properly.**
  - On Android, the plain build points at the remote demo host (digitvademo.causeofdeathindia.com),
    and its server field cannot be edited.
    - It offers only QR enrolment and "Try the demo".
    - It sets FLAG_SECURE, so no screenshots can be taken.
    - One sign-in attempt went to that remote host by mistake and was rejected.
  - On iOS, plain Collect is not installed on the 27.2 simulator.
  - Retesting needs a debug build of plain Collect that points at localhost.
- **QR enrolment:** neither simulator can present a QR code, and the app has no paste path.
- **Demo, standalone and W27 (standalone View/Revise):** not run. The welcome screen only appears
  when the phone holds no profiles, and clearing the profiles would delete the test data on the phone.
- **GPS:** neither platform has a GPS capture control. Android grep found no geopoint field and no
  expo-location in the app. W11 is therefore not applicable as written.
- **Coding and review (W24-W26):** blocked by digitva-frgn.
- **The digitva-lq5m photo tools:**
  - The scanner crop was verified on Android only. On iOS it crashes on a simulator with no camera.
  - The blur prompt and the viewer were verified on both platforms.

## Workflows and results (Collect Plus)

| ID | Workflow | Expected | Android | iOS |
|---|---|---|---|---|
| W01 | Cold start | Welcome or sign-in screen, no red box | PASS (v) | PASS (v) |
| W02 | Enrol by QR | Enrolled to TST001 | BLOCKED | BLOCKED |
| W03 | Enrol by email (test.cho.sc01) | Enrolled, PIN setup shown | PARTIAL: lands on GUJ026 (digitva-kspl) | PASS (d) |
| W04 | Demo | Demo workspace | NOT-RUN | NOT-RUN |
| W05 | Standalone | Standalone home | NOT-RUN | NOT-RUN |
| W06 | PIN set and unlock | Unlocks | PASS on cold start; no PIN prompt after only backgrounding the app | PASS (d) |
| W07 | PIN lockout | Lockout after the limit | PASS (v): lockout after 7 attempts, "Try again in 1 min". Recovery unclear | PASS (v) |
| W08 | Forgot PIN | New PIN set, data kept | PASS | PASS (v) |
| W09 | Record a death | Death listed | PASS (v) SC01-000164 | PASS (v) |
| W10 | Update a death | Edit persisted | FAIL: no edit route found (possibly by design) | PASS (d) |
| W11 | GPS | Coordinates captured | N/A, no feature | N/A, no control |
| W12 | Interview start | Consent screen | PASS | PASS (d) |
| W13 | Consent approve | Questions follow | PASS (v) | PASS (v) |
| W14 | Consent refuse | Refusal recorded | PASS (v), server shows `refused` | PASS, server rows with consent=no |
| W15 | Stop and resume | Answers and attachments intact | PASS (v) | PASS (d), red box on reopen (digitva-961u) |
| W16 | Narrative audio | Record, pause, stop, play and delete all work | PASS (v) | PASS (d) |
| W17 | Document scanner | Cropped document attached | PARTIAL (v): works, but one run crashed (digitva-d9zg) | FAIL: crash with no camera (digitva-1wov) |
| W18 | Blur prompt | Retake or Keep offered | PASS (v) | PASS (d) |
| W19 | Full-screen viewer | Opens, zooms, closes | PARTIAL: zoom not testable via adb | PASS (d) |
| W20 | Reopen ready interview | Reopens | PASS; misleading message when opening an uncached case offline (digitva-c86x) | PASS (d), item becomes Draft |
| W21 | Sync | Uploaded | PASS on the server; app still shows refused cases as To do (digitva-vpez) | PARTIAL: "Sent 2" (v), same To do issue |
| W22 | Update after sync | Update reaches the server | FAIL: HTTP 422 invalid_extensions (digitva-cy9u) | BLOCKED, no safe Sent record |
| W23 | Resend | Resent | NOT-RUN, no Resend control found | NOT-RUN |
| W24 | In-app coding online | Saved on server | BLOCKED (digitva-frgn) | BLOCKED (digitva-frgn) |
| W25 | In-app coding offline | Queued, then synced | BLOCKED | NOT-RUN |
| W26 | Reviewer workflow | Review saved | BLOCKED | BLOCKED |
| W27 | Standalone View/Revise | Revision saved | NOT-RUN | NOT-RUN |

Plain Collect results: W01 PASS on Android from a UI dump. Every other workflow was BLOCKED or
NOT-RUN on both platforms, for the reasons under Coverage limits.

## Findings

Each finding has one bead.

1. **digitva-frgn (P1): request storm on `GET /api/v1/me/access`, and coder roles never load.**
   - Evidence: 1,554 calls in the last 6 h of the server log (lead checked), some of them 429.
   - "Profile and project access" stays on "Loading...".
   - test.all holds active coder and reviewer grants on TST001 (psql), but the app shows it as
     "Death reporter" on GUJ026 only.
   - Repro: Switch profile > Add profile, sign in as test.all@digitva.com, set a PIN, open Settings >
     Profile and project access, then run
     `docker compose logs minerva_app_service | grep me/access`.
2. **digitva-d9zg (P1): native crash (SIGSEGV) in expo-sqlite.**
   - Android: `libexpo-sqlite.so`, about 47 s after tapping Next on the scan review. Seen once; a
     second run did not crash.
   - iOS: `SQLiteModule.step -> sqlite3_mutex_enter` during the Test ALL session
     (`DigitVACollectPlus-2026-11-07-002053.ips`). This looks like a database handle used after it
     was closed.
3. **digitva-cy9u (P2): Revise on a Sent case fails with "HTTP 422 invalid_extensions".**
   - Repro: Revise on PHC01-000025.
   - The failing definition request sends extensions `abha,death_summary,digitva_core,doris_support_whova_2022,geography,intake_screen,medical_records,narration_language`.
   - The earlier request that returned 200 sent only abha, death_summary, medical_records and
     narration_language.
4. **digitva-vpez (P2): a refused case still looks open after sync.**
   - The server marks it `refused`, but the app list shows "To do" with Start and the detail shows
     "Registered".
   - The refusal is missing from the Sent filter.
   - Seen on both platforms (SC01-000160, PHC01-000163).
5. **digitva-kspl (P2): the app picks the wrong project.**
   - After enrolling, test.cho.sc01 lands on GUJ026 instead of TST001.
   - The project selector also switches back to GUJ026 after the user leaves the Interviews tab or
     taps Save or Send.
6. **digitva-1wov (P3, iOS): "Scan document" crashes the app when there is no camera.**
   - Repro: tap Scan document, then Allow camera access.
   - Crash: uncaught `NSInvalidArgumentException` from `-[UIImagePickerController setSourceType:]`
     in expo-image-picker.
7. **digitva-961u (P3, iOS dev): a red box appears on reopening a draft with a photo.**
   - Message: "No suitable image URL loader found for who-va-attachment:<uuid>".
   - The image still renders after the red box is dismissed.
8. **digitva-c86x (P3, Android): misleading message when a case is opened offline before it was
   cached.**
   - The screen shows "unavailable or outside your access" together with "Could not reach the
     server".
   - The same case opens offline once it has been opened online.

Observations not filed as beads (each needs an owner decision or a clean recheck):
- Android has no route to edit a registered death (W10).
- On Android, unlocking after a lockout once went to "Sign in again" (W07). The driver's tap may
  have been wrong.
- On Android, the app did not ask for the PIN after it was only backgrounded (W06).
- Refused interviews are listed as "Untitled interview <uuid>".
- On Android, the scan buttons wrap their labels ("Scan docu ment").

## Data left behind (dev)

- Server: deaths SC01-000164 (in progress), "Test Death", "Refuse Test" and "Ready Test".
- Server: refusals SC01-000160 and PHC01-000163, plus two `web-` rows with consent=no.
- Both devices hold the profiles Test CHO SC01 and Test ALL, with PIN 246810 on both.

## Recommendation: repeatable script

Use Maestro, not Detox. It drives both platforms from YAML without changing the native build, and
its accessibility-id taps avoid the adb text and PIN-entry flakiness seen here. Two things are
needed first:
- `testID`s on the PIN pad, the project selector and the scan controls.
- A debug plain-Collect build that points at localhost.

Start with W01, W03, W06-W09 and W12-W16.

## Retest 2026-11-07 (plain Collect, local debug builds)

- **Setup:** owner scoped the retest to plain DigitVA Collect only. Local debug builds (bundle
  com.causeofdeathindia.digitvacollect) on iPhone 17 Pro iOS 27.2 and emulator-5554, server
  http://localhost:8051, Metro 8082. The Plus prebuilds were moved to
  `mobile/digitva-collect/ios.plus-bak` and `android.plus-bak` (untracked).
- **Screenshots:** `docs/current-state/collect-e2e-run-2026-11-06/retest-2026-11-07/{ios,android}/`.
  A Sonnet reviewer checked the key ones (v); others rest on driver reports (d).
- **Drivers:** Haiku. Stale device sessions for test.all and test.cho.sc01 were decommissioned
  through `decommission_account_device` to free slots.

| ID | Workflow | Android | iOS |
|---|---|---|---|
| W01 | Cold start | PASS (v) | PASS (v), debug banner, no red box |
| W03 | Enrol by email | PASS (d); home project still GUJ026 (kspl enrol default, owner decision) | test.cho.sc01 blocked by 3-phone limit; test.all PASS (d) |
| W03b | Project pick persists (kspl) | PASS: TST001 kept after relaunch (v); tab-switch screenshot weak | NOT-RUN |
| W04 | Demo | Opens Demo Mode, no account created (d) | Opens Public demo, cancelled (d) |
| W05/W27 | Standalone | N/A, not offered in plain Collect | N/A |
| W06 | PIN | PASS (d) | PASS set (d) |
| W09 | Register with GPS | GPS FAIL: Google Location Accuracy dialog, "No thanks" then "Location is not available on this device. You can still save without it." (v); death saved without GPS | GPS PASS: "Location captured, accurate to about 5 m" (v), second tap needed after first permission grant; save refused 422 "Date of death cannot be in the future." (server UTC date, digitva-vz9f), refusal not shown on the case screen (fixed since, not re-run) |
| W10 | Edit registered death | PASS: "W09 TestDeathEdited" saved (v) | BLOCKED, no saved death |
| W14/W21 | Refuse and sync (vpez) | Batch 1: refusal never uploaded, case stayed To do (digitva-xq0i); batch 2: PASS, SC01-000014 under Sent with submitted time, To do empty (v); case detail still says in progress | NOT-RUN |
| W15 | Draft photo reopen | PASS (v) | BLOCKED (961u not re-run) |
| W17 | Scan document | PASS, scan.jpg attached, blur prompt (v) | BLOCKED (1wov not re-run) |
| W20 | Reopen offline uncached (c86x) | BLOCKED, no unopened case reachable offline | N/A, simulator cannot go offline |
| frgn | Profile and project access (test.all) | PASS: loads in ~8 s, Coder + Reviewer on TST001 (v) | PASS: loads in <5 s, Coder/Death reporter/Reviewer on Intake Test (v) |
| W22 | Revise Sent (cy9u) | BLOCKED, no Revise on plain Collect Sent cases | BLOCKED |
| W24-W26 | Coding/review | N/A: plain Collect shows no coding entry for test.all (Home, Register, Sync only) | N/A, same |

- **Request rate (frgn):** before the poll fix, the foreground poll paired `GET /me/access` with
  `/me/notifications` every 30 s per phone (about 120/h per phone, matching the 1,554 in 6 h).
  After the fix, 5 idle minutes with both phones open: 2 `/me/access`, 15 `/me/notifications`.
- **Crashes:** none (Android crash buffer empty; no new DigitVA `.ips` on iOS).
- **Bead status after retest:**
  - digitva-frgn closed (device-verified).
  - Still open: digitva-kspl (worklist pick verified; enrol default awaits owner), digitva-vpez
    (list fixed and verified; detail state stale), digitva-1wov and digitva-961u (fixed in code, not
    re-run on iOS), digitva-c86x (fixed in code, not reachable), digitva-cy9u (fixed in code; Revise
    not in plain Collect), digitva-d9zg (Plus only, unit-tested).
  - New: digitva-vz9f (server UTC date refuses today's date of death in IST evenings), digitva-xq0i
    (refusal not uploaded in batch 1), Android GPS needs a fallback when the user declines Google
    Location Accuracy.

### Later batches (owner decisions, 2026-11-07)

- **Owner decisions applied:**
  - kspl: when more than one project is eligible, enrolment asks the user to pick one. The old
    APK default is unchanged. The choice is set through POST /api/v1/auth/devices/current/project,
    which is refused with 409 `device_project_locked` for a device that holds station state.
  - vz9f: "today" for dates of death and birth is the project's day.
  - Android: GPS fallback, and a GPS warmup when the register screen opens. The warmup runs only
    when permission is already granted and never prompts.
  - Online Code and Review tabs in plain Collect.
  - Refreeze the register screen.

| Check | Android | iOS |
|---|---|---|
| kspl project picker | PASS: "Choose the project" listed GUJ026, TRN01, TST001; TST001 kept after relaunch (B4-6) | Adding a profile on an enrolled phone lands on TST001; picker not shown on that path |
| vz9f today's date | PASS: today's date saved (B4-2) | PASS: SC01-000169 dated 2026-11-07 accepted while UTC was 6 Nov; DB shows the fix at 5 m |
| GPS warmup, no prompt on open | PASS: no Google dialog on opening Register (B4-1a) | n/a |
| GPS after declining Location Accuracy | PASS: "Location captured, accurate to about 5 m" after "No thanks" (B5-gps-fallback.png; geo fix fed repeatedly) | n/a |
| GPS first tap | n/a | PASS: one tap captured (B3-2) |
| W10 edit | PASS earlier | PASS: "B2 Retest Edited" saved (B3-3) |
| c86x offline open | PASS: unopened SC01-000169 opened offline with the offline banner, no access message (B4-3) | n/a |
| Code tab (W24) | PASS: tab and coding queue load (B3-1) | PASS: tab loads; Step 1 assessment saved on OD01214123_144556478 (B3-1); Step 2 not done, case still held by Test ALL |
| Review tab (W26) | PASS: tab and reviewer queue load, 0 available, so no review saved | Same as Android |
| Register resume | PASS: site and unit kept after background/foreground (B6-register-resume.png). The earlier "No sites yet" after the Google dialog was a lost project selection on resume, now fixed | n/a |
| 1wov, 961u | n/a | BLOCKED: the document photo question needs the questionnaire completed past section 4 |
| vpez detail | BLOCKED: SC01-000014 no longer listed for this profile | n/a |

- **Refreeze:** register screen and tab bar refrozen 2026-11-07 (see
  `docs/design/collect-petrol-theme/README.md`).
  - Android: light, dark, high contrast and Large text for Register and the 4-tab bar.
  - iOS: light and high contrast, including the 5-tab Test ALL bar.
  - Not frozen: Android captured-location state in dark, high contrast and Large text; iOS dark
    (the app forces light); iOS Large text (header cramped, bead filed); Android 5-tab bar (no
    Test ALL profile on the emulator at that time).
- **Bead status at the end:**
  - Closed after device checks: digitva-frgn, digitva-kspl, digitva-vz9f, digitva-c86x,
    digitva-xpaf, digitva-b3hl.
  - Open: digitva-toyw and child digitva-toyw.1 (review save not exercised: empty queue),
    digitva-vpez (detail state), digitva-1wov and digitva-961u (not reached on iOS),
    digitva-cy9u (no Revise in plain Collect), digitva-d9zg (Plus only), digitva-xq0i, and two
    iOS refreeze beads (Large text header, forced light mode).

### Closing the open beads (2026-11-07)

| Bead | Fix | Device evidence |
|---|---|---|
| digitva-vpez | Detail shows Sent for a refused case whose refusal was submitted | Android: SC01-000173 refused, deaths 201 + submissions 201, list Sent, detail "Interview status: Sent", no Start |
| digitva-1wov | iOS simulator camera gate (expo-device) | iOS: Scan document and Camera show "No camera on this device", no crash |
| digitva-961u | No raw who-va-attachment URI to Image | iOS: library photo on draft reopen, no red box |
| digitva-xq0i | Not reproduced (4 attempts: online, offline then sync, existing case backgrounded, earlier repeat) | Every refusal POSTed `/intake/submissions` 201; closed, reopen with logcat if seen |
| digitva-toyw, digitva-toyw.1 | Code and Review tabs; server accepts `other_conditions` as a list for reviewing (was 400) | Review initial + finalize 200 on iOS and Android |
| digitva-cy9u | Tagged extensions only + server shim | Collect Plus debug iOS: Revise PHC01-000025 opens, definition GET 200 |
| digitva-d9zg | Guarded SQLite handle | Collect Plus debug: ~25 lock/background/switch cycles iOS, 15 sync+lock cycles Android, no crash |
| digitva-2gw7, digitva-35iw | iOS follows system appearance; header, banner and DEMO chip scale safely | iOS dark and Large text refrozen |
| digitva-6zib | Random-allocation coding queue uses the segmented Available / My coded cases layout; stuck Available tap fixed | Both platforms; frozen |
| digitva-6i9u | Death-reporter Home "Could not load": `GET /intake/deaths` 400 for a reporter who also holds an interviewer grant. Client sends `registered=mine`; server serves the own list for old APKs | iOS test.anm.sc01: 200, list loads |
| digitva-oll6 | Web saved audio loads back; stale playbackError cleared | Local store only (no S3/MinIO locally) |
| digitva-nih5 (open) | Web intake Camera now tries getUserMedia, falls back to file input, cancel resets | Built-in browser blocks camera: getUserMedia called and rejected, fallback opened; live preview still needs a real browser |

- **Narrative audio:** Replace and Delete now ask for confirmation (web, iOS and Android verified).
- **Role views:** CHO and ANM role views are in `docs/current-state/collect-e2e-run-2026-11-06/role-views/`.
- **Collect Plus native dirs:** restored to `ios/` and `android/`. Plain backups are `ios.plain-bak` and `android.plain-bak`.
- **Dev data:** reviewer test cases on SADEMO were coded by test.coder.nc01. Several device sessions were
  decommissioned through `decommission_account_device`.

## Widget matrix 2026-11-07

Each widget was checked on four platforms:

- iOS: plain Collect debug on the iOS simulator (iPhone 17 Pro, iOS 27.2).
- Android: plain Collect debug on the Android emulator (DigitVA_Pixel_7).
- Samsung: USB-connected SM-E146B with a real camera, microphone and GPS. Test account only.
- Web: the web app at localhost:8051 in the built-in browser. The camera, microphone and file
  chooser are blocked there, so stand-in streams and files were injected. The web rows test how
  the app handles those inputs, not the hardware.

The WHO VA interview has no file or PDF question. The PDF row was tested only on web, with the
certificate upload (Id10463).

Screenshots are in `docs/current-state/collect-e2e-run-2026-11-06/widget-matrix/ios/`,
`.../android-emulator/` and `.../samsung/`. Web screenshots stayed in the tool results folder and
are not in the repo.

| Widget | iOS sim | Android emulator | Samsung | Web |
|---|---|---|---|---|
| GPS capture (register) | PASS 5 m | PASS 5 m | PASS real fix 13 m | PASS (mocked) |
| GPS decline Location Accuracy fallback | n/a | PASS (geo fix fed) | dialog not shown | n/a |
| GPS warmup / Retake | PASS | PASS (delay) | PASS (coarser 100 m on retake) | n/a |
| GPS save + reopen keeps fix | PASS | PASS earlier (B5); B11 blocked by device Location Accuracy setting | PASS | n/a |
| GPS denied | n/a | n/a | n/a | PASS |
| Camera document photo | NOT TESTABLE (no camera; graceful alert PASS) | PASS | PASS real camera | PASS fallback file input; live getUserMedia called, pane denies (after fix + Metro web container restart) |
| Scan document | NOT TESTABLE (alert PASS) | PASS | PASS | n/a |
| Blur prompt | n/a | PASS | PASS | n/a |
| Full-screen viewer | PASS | PASS | PASS | n/a |
| Image remove with confirm | PASS | PASS | PASS | PASS (confirm added) |
| Gallery pick + preview | PASS | PASS | PASS | PASS |
| Audio record/stop/play | PASS (sim mic) | PASS | PASS incl. pause/resume | PASS (fake stream) |
| Audio Replace confirm | PASS | PASS | PASS | PASS (after Metro web container refresh) |
| Audio Delete confirm | PASS | PASS | PASS | PASS (after refresh) |
| PDF attach / open / remove | NOT TESTABLE (no file question) | NOT TESTABLE | NOT TESTABLE | PASS attach and remove; Open added and verified (blob 200 application/pdf) |
| States: Save draft + resume (relaunch) | PASS | PASS | PASS | PASS |
| Back/forward between sections | PASS (Sections menu; Back/Next partial) | PASS | PASS | PASS ("Leave this interview?" guard) |
| Offline attach | NOT TESTABLE | PASS (photo and audio offline) | not tested (no settings changes on owner phone) | NOT TESTABLE |
| After sync, sent read-only view | PASS for existing sent cases (detail) | PASS existing sent cases | NOT TESTED (interview not completed) | NOT TESTED |

### Failures and beads

- digitva-nih5: web live camera. The cause was a stale bundle in the Metro web container plus a
  missing export in web-preloaded.tsx. Both are fixed and getUserMedia is now called. A live
  preview needs a real browser, because the pane denies the camera. Refresh step for vendor
  changes: `npm --prefix vendor/who-va-2022 run build`, then `docker restart digitva-digitva_web_hmr-1`.
- Web confirmations and PDF Open: same stale container. The PDF Open control was added.
- digitva-bl3b (closed): Register showed "No sites yet" with two projects. The project id was
  empty coming from the worklist. Fixed.
- digitva-frnc (closed): Save with a missing field gave no visible feedback. It now scrolls to the
  message.
- digitva-w80u (open): a resumed draft showed "The saved recording could not be loaded from this
  device." for audio recorded in an earlier session, on both simulators. No code path that deletes
  the file was found. The likely cause is that the draft was re-imported from the server after the
  local store was cleared during testing (pm clear / re-sign-in), and the phone has no path to
  re-download a server attachment. Needs a device repro with logging.
- Interviews More sheet showed "Search units" and no active-chip highlight (digitva-aivk
  follow-up, being fixed).
- Not tested anywhere: the sent read-only view of an interview with media. It requires completing
  about 40 required questions.

## Follow-up 2026-11-07 (digitva-aivk, digitva-w80u)

- digitva-aivk (closed): the More chip now reads plain "More", unselected, at the default All filter, and
  "More: Sent" / "More: Revisions" highlighted otherwise (Jest: `phone-list-controls`, `phone-list-views`).
  Seed `test-project` now also grants `test.cho.sc02` the interviewer role at SC01 (a second interviewer in
  scope of SC01 cases); run on dev. To exercise the warning, a draft for SC01 case b9cf3f2c was started as
  test.cho.sc02 through `start_draft` (dev data only, not in the seed). On the Android emulator (plain Collect,
  Metro 8082) as test.cho.sc01 the card read "Test CHO SC02 started this on 7 Nov. Check with them before you
  start." and the More sheet had Sent / Revisions / All and no "Search units" box. Android `home.png`,
  `interviews-list.png`, `interviews-list-2.png` under `docs/design/collect-petrol-theme/frozen/` were refrozen.
  The emulator was on the PIN lock screen; signing in again with the password kept the local drafts
  ("the work on this phone is kept") and a new PIN was set.
- digitva-w80u (closed, not reproduced): on the emulator a narrative recording was made in a draft, saved,
  the app force-stopped and relaunched, the draft reopened: the recording loaded and played (00:08). Audio
  bytes live in the encrypted store (`attachments` table), not in a file path, so container or cache moves
  cannot break them; `resolveStored` writes a fresh playback copy each time. The error therefore only occurs when
  the answer references an attachment whose bytes are not on this phone (draft re-imported from the server after the
  local store was cleared; the phone cannot re-download server attachments). Fix: the message now says what
  to do ("This recording is not on this phone any more. Choose Replace audio to record it again."; the image
  message likewise) in `vendor/who-va-2022/src/i18n.ts`. The missing-bytes path is already covered by
  `attachment-capture.test.ts` (`resolveStored` returns undefined). `make check-web` passes.

