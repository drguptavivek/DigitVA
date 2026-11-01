# Handoff

## Start here

Fully offline DORIS coding in Collect Plus (`digitva-9cll`). Staging runs
`04d824757` (0.3.19 server and web, deployed 1 Nov); phones there are on
0.3.16 or older.
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

1. Staging runs `04d824757` (deployed 1 Nov; web `expo-web-v2026.11.01.1`;
   old-APK audit since `3d5cf4f06` found nothing). Rollback:
   `sudo -Hu ubuntu env SKIP_BACKUP=1 bash scripts/deploy-server.sh 3d5cf4f06818148cc231fd1500891415423bdf81`.
   `/download/android` still serves 0.3.16: staging's `.env` points it at the
   hand-kept `private/android-hosted`, which the deploy never touches; the
   owner copies the 0.3.19 APKs there from `minerva_app:/opt/digitva/android`.
   Dev `/app/` serves `mobile/digitva-collect/dist` (last built 24 Oct):
   rebuild it locally to see the new screens on dev.
2. Verify on the USB Samsung (RZCW81QZT2Z): install
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
3. Browser interview attachments (`digitva-e621`): on staging after a deploy
   (owner's go), camera, image upload, audio and a PDF in Chrome on a phone and
   a desktop; submit and check the files reach the case; sign out with an
   unsent file (warning, deleted). Hindi strings: `digitva-ygo5`.
4. Expo ICD-10 parity (`digitva-tk7j`): checked on dev web without a save. Try
   a save on web and coding online on the phone. Flask's previous
   immediate/antecedent final causes are not in the workspace API. Check
   `digitva-2q7c` (workspace reloads when its tab becomes visible again) in a
   normal browser.
5. Standalone engine (`digitva-xw1s`): the engine repo's CI has its first run on
   the 1 Nov push; once green, the owner tags `v0.1.0` and publishes the draft
   release. Linux and Intel Mac untried; no Windows build (`src/hostfxr.rs`);
   Linux needs glibc 2.39+. The React DORIS component is not started.
6. `digitva-9cll.5` phone proof: standalone certificate steps (search, Use,
   Build/axes, details, hierarchy, XK8G/NC72 refusals, DORIS, CoDEdit, save
   shows Coded), then an enrolled TST001 coder offline (the owner signs in),
   incl. when `:icd11` starts. Capture so far:
   `private/engine-measurements/20261030-coding-journey`.
7. `digitva-9cll.22` coding parity children: `.22.2` online phone attachments
   never load, `.22.4`, `.22.3`, `.22.5` offline not-codeable/remark, `.22.6`
   SmartVA sex raw code, `.22.9`.
8. `digitva-9cll.23` standalone direct coding; `digitva-9cll.24` coded-case
   summary with Revise.
9. `digitva-gt2v`, `digitva-bged`: offline reply-shape and Build/axes bugs.
10. DORIS validation gaps (`docs/current-state/doris-validation-checks.md`):
    `digitva-l0ey`, `digitva-2j57`, `digitva-e505`, `digitva-giym`,
    `digitva-o16a`, `digitva-37gr`.
11. `digitva-9cll.11` CI engine build not byte-identical; `digitva-9cll.13`–`.21`
    Android ICD/DORIS review findings.
12. `make collect-plus-local`: container mode untested end to end (Docker 12 GB
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
