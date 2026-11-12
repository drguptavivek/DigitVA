# Handoff

## Start here

Continue fully offline DORIS coding in Collect Plus (`digitva-9cll`). The
staging runs `22a9fca67` (12 Nov), hosting Collect and Collect Plus 0.3.20. Verify the installed build and enrollment before device
acceptance. Preserve shared checkout edits, including the iOS and SmartVA
work, parity tooling, manuscript files and Play assets. WHO notes, parity
runs and phone measurements live in `private/`.

Owner rule (bd memory `coding-parity-all-surfaces`): coding works the same on
the web, Collect online and Collect Plus online and offline. Design rule:
Collect screens are frozen (`docs/design/collect-petrol-theme/README.md`);
any change to one is re-checked against `frozen/` (light, dark, high
contrast, Large text) and refrozen.

## Ranked next steps

1. Prove the full offline coding flow on a phone (`digitva-9cll.5`), first
   standalone and then as an enrolled TST001 coder. Re-enrol the Samsung
   for device checks. Remaining coding parity work is under
   `digitva-9cll.22`, including `.22.3`–`.22.6`, `.22.8` and `.22.9`.
2. Collect redesign follow-ups: TalkBack and VoiceOver on a real phone
   (`digitva-eizq`), Hindi review of the new theme strings (`digitva-jt1w`),
   Play screenshots in the new theme (`digitva-fthd`), offline engine
   `load_failed` on the arm64 emulator (`digitva-rih6`, so the coding tools
   and Demo mode were never design-reviewed), app speed on the SM-E146B with
   the CI APK (`digitva-xxfz`).
3. Verify device handling of "Saved on server" attachments (`digitva-n3ec`
   closed for implementation). On staging check saved web audio after
   leaving and returning (`digitva-oll6`), and the sent read-only media view
   (`digitva-e621`). Hindi attachment and camera strings need owner review.
4. Run-6 audit (`digitva-9xn9`) is closed: every item landed 2026-11-12 and
   none is deployed (CHANGELOG). Before the next staging deploy, run the new
   restore swap and staging backup checker once under supervision
   (`digitva-rbj8`), and audit for old APKs: a changed coding now gets a
   receipt instead of 409 `coding_conflict`; non-leaf ICD-11 codes get 422
   `non_leaf_category`. Check on a phone: consent "No" Cancel (verified on
   web), station key confirm and PIN lockout, offline non-leaf child list,
   ICD-10 coding online (`digitva-tk7j`; web save verified). Open small
   follow-up: web client sends explicit nulls for cleared answers (D22
   remainder). Run-5 acceptance still open: a multi-project user's
   supervision views for per-project PII. For the offline PHC station, run
   the packaged macOS security acceptance with dummy data (`digitva-xt9y`).
5. On staging, by hand, refuse then re-consent a direct interview
   (`digitva-lgzl`); a DORIS cluster such as BD1Z shows the whole title
   (`digitva-iae8`); the other-interviewer banner names them.
6. Check PIN lockout/reset, standalone erase, reopen, View/Revise and PDF
   viewer (`2d78e9660`) on the Samsung. Keep the in-place upgrade check for
   older APKs and verify icons, Hindi wrapping, certificate camera,
   standalone documents and warm DORIS (`digitva-9l5c`, `digitva-ljx2`,
   `digitva-4j8h`). The iPhone awaits an owner-approved CI/TestFlight build.
8. Standalone engine (`digitva-xw1s`): `v0.1.0` draft release built; the
   owner publishes it, then close. Not run on Linux/Intel Mac; no Windows.
9. Help chatbot (`digitva-wawz`, `docs/policy/help-chatbot.md`) still needs
   its PII redaction step. Manuscript owner inputs and reference gaps are
   listed in `docs/manuscript/LDH-manuscript-review-2026-11-06.md`.
10. `digitva-gt2v`, `digitva-bged`; DORIS validation gaps
    (`docs/current-state/doris-validation-checks.md`: `digitva-l0ey`,
    `digitva-2j57`, `digitva-e505`, `digitva-giym`, `digitva-o16a`,
    `digitva-37gr`); `digitva-9cll.11`, `.13`–`.21`.
11. `make collect-plus-local` container mode untested (Docker 12 GB+).

## Open owner decisions

- Send the WHO technical note (one `[OPEN]`: a WHO contact email).
- Engine `tests/fixtures/doris_help_examples.json` provenance.
- WHO data files' duplicated sha256 values; CI as engine release source.
- InterVA2022/InSilicoVA2022 experimental (`.tasks` note): candidates, no go yet.
- AI interview-quality checks are on hold (`docs/policy/ai-data-quality.md`,
  `digitva-qtmq` deferred).

## Boundaries still true

- Golden corpora are owner-approved and frozen (`scripts/icd11-golden/README.md`).
- Release builds only on CI; local debug builds for development only.
  Publishing releases and tags is the owner's command.
- On the owner's real phone: no PINs, passwords or system settings; leave
  "vivekdemo" alone. Emulator accounts: `private/emulator-test-accounts.md`.
- Plus stays prerelease; WHO has not answered the licence points in writing.
- Device ICD/DORIS coding starts off; enabling grants no permission.
- No Fable agents (owner; the screen-review exception has ended).

## Caveats

- Full-suite noise: a few tests fail only under `-n 4` (`digitva-6igh`).
- Still uncommitted from before 2026-11-12: public-demo config and docs,
  `va_smartva_02_prepdata.py`, `smartva-analysis.md`, parity tooling,
  `AGENTS.md`.
- The previous staging deployment was `210ea326e`. Use the release runbook
  and owner approval for a rollback (`docs/current-state/release-process.md`).
- `ios/` and `android/` are Collect Plus prebuilds. Plain Collect prebuilds
  are untracked in `ios.plain-bak/` and `android.plain-bak/`.
- On :8051, rebuild the vendor package and restart the web HMR container
  before verifying changes to the WHO interview component.
- `npm run vendor:build` reinstalls the vendor package: stop Metro first and
  restart it with `--clear`. Local vendor `dist` may lag the source.
- The emulator holds two test drafts ("Test Case", "Test Consent"; the latter
  synced to the local dev server only).
- Old APKs show "The selected code does not match its WHO URI." for the
  extension/category refusals (same `INVALID_SELECTION` 422).
- 0.3.16 phones: the standalone home list is stale until Lock and unlock.
- `build/collect-plus-local/…-LOCAL.apk` (31 Oct) was built mid-edit; do not
  test from it.
