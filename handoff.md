# Handoff

## Start here

Fully offline DORIS coding in Collect Plus (`digitva-9cll`). Staging runs
`3ab5c2d69` (deployed 4 Nov: Statistics dashboards, ICD-11 caches, web
`expo-web-v2026.11.04.1`); phones there are on 0.3.19 or older.
Collect Plus 0.3.17 is on the USB Samsung. main carries 0.3.18 plus, since
1 Nov, browser interview attachments (`digitva-e621`), the ICD-10 search fix
(`digitva-zqk2`) and Expo ICD-10 parity (`digitva-tk7j`); 0.3.19 (published
1 Nov) carries all three. The CI APK in `build/ci-plus/` (0.3.18, built from
`79889d9b3`) predates them. Never reset or stash; preserve the unrelated
`scripts/loadtest/restore.sh`, manuscript decks, `.claude/launch.json`, the
InterVA `.tasks` note and Play artwork. WHO notes, parity
runs and phone measurements live in `private/` (git-ignored; also holds keys).

Owner rule (bd memory `coding-parity-all-surfaces`): coding works the same on
the web, Collect online and Collect Plus online and offline. NQA and Social
Autopsy follow the project setting online and for enrolled accounts; standalone
has neither, and its coding is one direct step with SmartVA visible.

## Ranked next steps

1. Staging runs `f01f3e68f` (deployed 5 Nov; web `expo-web-v2026.11.05.1`;
   old-APK audit since `3ab5c2d69` found nothing; cod-bucket rows rebuilt).
   Rollback:
   `sudo -Hu ubuntu env SKIP_BACKUP=1 bash scripts/deploy-server.sh 3ab5c2d69bfa166d95d2d5923e43babab71823e1`.
   `minerva_icd_cache_redis` (128 MB) holds the ICD-11 caches; staging
   has ~0.8 GB free RAM and no swap; the database is a separate deployment.
   `/download/android` and `/download/android/plus` serve 0.3.19 from the
   hand-kept `private/android-hosted`, which the deploy never touches.
   Dev `/app/` serves `mobile/digitva-collect/dist`: rebuild it locally to
   see new screens on dev.
2. Security audit run-5 fixes (`digitva-ssg7`, CHANGELOG 2026-11-06) are on
   main, not staging. Before deploying: count active
   `va_reviewer_initial_assessments` rows with NULL `payload_version_id` (they
   stop counting as Step 1; dev has none); PII is now per project, so check a
   multi-project user's case list and export on staging. Audit report:
   `/Users/vivekgupta/security-audit-skill/DigitVA/run-5/`.
3. On staging, check by hand: refuse then re-consent a direct interview
   (HIV/malaria presets come back, `digitva-lgzl`); a DORIS cluster such as
   BD1Z with a causing condition shows the whole title on the certificate
   line (`digitva-iae8`); the other-interviewer banner names them.
4. Verify on the USB Samsung (RZCW81QZT2Z): install
   `build/ci-plus/digitva-collect-plus-0.3.18-arm64-v8a.apk` (release-signed,
   updates 0.3.17 in place) for the 0.3.18 checks and the offline workspace;
   the 0.3.19 build for the rest.
   - 0.3.18: icons and confirmations, Hindi wrap (Id10128/Id10129/Id10484),
     certificate camera and preview, standalone document questions, tabs and
     row buttons, no error after Complete (`digitva-ljx2`), Send now disabled,
     DORIS warm on the Pending tab (`digitva-4j8h`; ICD11WARM in logcat) and
     the spinner. Then close `digitva-9l5c`, `digitva-ljx2`, `digitva-4j8h`.
   - Offline full coding workspace (`digitva-9cll.22.8`): categories, history
     colours, summary, attachments open on tap, private note, SmartVA in the
     COD section, DORIS save; then close the bead. Known gaps: `.22.3`
     native category view, `.22.4` NQA/SA not cached, the phone strips with
     the bundled instrument rather than the draft's pin, `.22.9` label split.
5. Browser interview attachments (`digitva-e621`): on staging after a deploy
   (owner's go), camera, image upload, audio and a PDF in Chrome on a phone and
   a desktop; submit and check the files reach the case; sign out with an
   unsent file (warning, deleted). Hindi strings: `digitva-ygo5`.
6. Expo ICD-10 parity (`digitva-tk7j`): checked on dev web without a save. Try
   a save on web and coding online on the phone. Flask's previous
   immediate/antecedent final causes are not in the workspace API. Check
   `digitva-2q7c` (workspace reloads when its tab becomes visible again) in a
   normal browser.
7. Standalone engine (`digitva-xw1s`): CI green on `6be9169` (Linux
   integration 8/8 incl. WHO's certificates); `v0.1.0` tagged 1 Nov and its
   draft release built (4 archives, each only binary + LICENSE + NOTICE +
   README). The owner publishes the draft; then close the bead. Built
   binaries not yet run on Linux or Intel Mac; no Windows build
   (`src/hostfxr.rs`); Linux needs glibc 2.39+. The React DORIS component is
   not started.
8. `digitva-9cll.5` phone proof: standalone certificate steps (search, Use,
   Build/axes, details, hierarchy, XK8G/NC72 refusals, DORIS, CoDEdit, save
   shows Coded), then an enrolled TST001 coder offline (the owner signs in),
   incl. when `:icd11` starts. Capture so far:
   `private/engine-measurements/20261030-coding-journey`.
9. `digitva-9cll.22` coding parity children: `.22.2` online phone attachments
   never load, `.22.4`, `.22.3`, `.22.5` offline not-codeable/remark, `.22.6`
   SmartVA sex raw code, `.22.9`.
10. `digitva-9cll.23` standalone direct coding; `digitva-9cll.24` coded-case
   summary with Revise.
11. `digitva-gt2v`, `digitva-bged`: offline reply-shape and Build/axes bugs.
12. DORIS validation gaps (`docs/current-state/doris-validation-checks.md`):
    `digitva-l0ey`, `digitva-2j57`, `digitva-e505`, `digitva-giym`,
    `digitva-o16a`, `digitva-37gr`.
13. `digitva-9cll.11` CI engine build not byte-identical; `digitva-9cll.13`–`.21`
    Android ICD/DORIS review findings.
14. `make collect-plus-local`: container mode untested end to end (Docker 12 GB
    or more); `NATIVE=1` works on the Mac (4.5 min, debug-signed, never
    distributed).

## Open owner decisions

- Send the WHO technical note (`docs/manuscript/who-technical-note-offline-icd11-doris.md`,
  one `[OPEN]`: a WHO contact email).
- Engine repo `tests/fixtures/doris_help_examples.json`: provenance unconfirmed
  (looks like WHO's DORIS help pages); kept in git, kept out of the crate.
- `digitva-9cll.14`: should an enrolled phone send the interview when its
  offline coding is rejected or stale?
- `digitva-dn15`: should the ECT selection check also refuse non-leaf categories?
- Hindi strings awaiting approval (`digitva-ygo5`, 0.3.17's tab, Settings and
  backup strings; `src/i18n.ts` REVIEW NEEDED note).
- WHO data files' duplicated sha256 values: keep both, or add a drift check.
- CI as the engine release source (after `digitva-9cll.11`).
- Statistics Hindi strings, including the new singular forms, and the new
  stale-save strings ("Use my answers", who changed it) need a native
  speaker's review (`digitva-omqx`).
- InterVA2022/InSilicoVA2022 as experimental algorithms
  (`.tasks/2026-10-30-interva2022-insilicova2022-experimental.md`): needs a go.

## Boundaries still true

- Golden corpora are owner-approved and frozen (`scripts/icd11-golden/README.md`).
- Release builds only on CI; local debug builds for development only. Engine
  bundles use only public, unrestricted inputs. Publishing releases and tags is
  the owner's command; the agent approves gates.
- On the owner's real phone: no PINs, passwords or system settings; leave the
  "vivekdemo" account alone. Emulator accounts: `private/emulator-test-accounts.md`.
- Plus stays prerelease; WHO has not answered the licence points in writing.
- Device ICD/DORIS coding starts off; enabling grants no permission.
- No Fable agents (weekly usage).

## Caveats

- Old APKs show "The selected code does not match its WHO URI." for the
  extension/category refusals (same `INVALID_SELECTION` 422).
- 0.3.16 phones: the standalone home list is stale until Lock and unlock.
- Local vendor `dist` may lag the engine source: run `npm run vendor:build` in
  `mobile/digitva-collect` before a local device build.
- `build/collect-plus-local/…-LOCAL.apk` (31 Oct) was built mid-edit of
  `SimpleCodPanel.tsx`; do not test from it.
