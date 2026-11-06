# Handoff

## Start here

Fully offline DORIS coding in Collect Plus (`digitva-9cll`). Staging runs
`f01f3e68f` (deployed 5 Nov; web `expo-web-v2026.11.05.1`); phones there are
on 0.3.19 or older. main now also carries the Collect Petrol redesign,
accessibility settings and server UI languages (CHANGELOG 2026-11-06), with
the iOS, SmartVA and standalone app work that shared its files. Never reset
or stash; preserve the unrelated `scripts/loadtest/restore.sh`, manuscript
decks, `.claude/launch.json`, the InterVA `.tasks` note and `store/play/`. WHO notes, parity runs and phone measurements
live in `private/` (git-ignored; also holds keys).

Owner rule (bd memory `coding-parity-all-surfaces`): coding works the same on
the web, Collect online and Collect Plus online and offline. Design rule:
Collect screens are frozen (`docs/design/collect-petrol-theme/README.md`);
any change to one is re-checked against `frozen/` (light, dark, high
contrast, Large text) and refrozen.

## Ranked next steps

1. Collection gate, app side (`digitva-dj29`, the iOS/Expo session): the
   Expo start check against `/me/access` "Collection gate"
   (`docs/current-state/device-collection-api.md`); the server side is on main
   (`87fff09cd`, `digitva-jeyy`). Before a staging deploy: run migrations
   `e4b7c2d9a6f1`..`c3f9a2d6e8b4` and audit old APKs (the access fields are
   additive; `collection_closed` is web-only). Project clock stage 2, dashboard
   and report days on the project timezone (`digitva-apee`). Help chatbot build
   (`digitva-wawz`, policy `docs/policy/help-chatbot.md`, decisions recorded;
   the PII redaction step is not built). Manuscript owner inputs: ethics,
   funders, authors, hosting and costs, literature screening counts, five
   references not in Zotero (`docs/manuscript/LDH-manuscript-review-2026-11-06.md`).
2. Collect redesign follow-ups: TalkBack and VoiceOver on a real phone
   (`digitva-eizq`), Hindi review of the new theme strings (`digitva-jt1w`),
   Play screenshots in the new theme (`digitva-fthd`), offline engine
   `load_failed` on the arm64 emulator (`digitva-rih6`, so the coding tools
   and Demo mode were never design-reviewed), app speed on the SM-E146B with
   the CI APK (`digitva-xxfz`).
3. Security audit run-5 fixes (`digitva-ssg7`) are on main, not staging.
   Before deploying: count active `va_reviewer_initial_assessments` rows with
   NULL `payload_version_id`; check a multi-project user's case list and
   export (PII is per project). Report:
   `/Users/vivekgupta/security-audit-skill/DigitVA/run-5/`. A deploy also
   needs the old-APK audit (the redesign changes no API shapes; the new
   `/api/v1/ui-strings` routes are additive).
4. Staging rollback:
   `sudo -Hu ubuntu env SKIP_BACKUP=1 bash scripts/deploy-server.sh 3ab5c2d69bfa166d95d2d5923e43babab71823e1`.
   `minerva_icd_cache_redis` (128 MB) holds the ICD-11 caches; ~0.8 GB free
   RAM, no swap. `/download/android*` serve 0.3.19 from `private/android-hosted`.
5. On staging, by hand: refuse then re-consent a direct interview
   (`digitva-lgzl`); a DORIS cluster such as BD1Z shows the whole title
   (`digitva-iae8`); the other-interviewer banner names them.
6. USB Samsung (RZCW81QZT2Z): 0.3.18 checks with
   `build/ci-plus/digitva-collect-plus-0.3.18-arm64-v8a.apk` (icons, Hindi
   wrap Id10128/Id10129/Id10484, certificate camera, standalone documents,
   `digitva-ljx2`, DORIS warm `digitva-4j8h`), then close `digitva-9l5c`,
   `digitva-ljx2`, `digitva-4j8h`; offline workspace `digitva-9cll.22.8`.
7. Browser interview attachments (`digitva-e621`) on staging after a deploy;
   Hindi `digitva-ygo5`. Expo ICD-10 parity (`digitva-tk7j`): try a save;
   `digitva-2q7c` in a normal browser.
8. Standalone engine (`digitva-xw1s`): `v0.1.0` draft release built; the
   owner publishes it, then close. Not run on Linux/Intel Mac; no Windows.
9. `digitva-9cll.5` phone proof (standalone certificate steps, then an
   enrolled TST001 coder offline); `digitva-9cll.22` children (`.22.2`,
   `.22.3`, `.22.4`, `.22.5`, `.22.6`, `.22.9`); `digitva-9cll.23`, `.24`.
10. `digitva-gt2v`, `digitva-bged`; DORIS validation gaps
    (`docs/current-state/doris-validation-checks.md`: `digitva-l0ey`,
    `digitva-2j57`, `digitva-e505`, `digitva-giym`, `digitva-o16a`,
    `digitva-37gr`); `digitva-9cll.11`, `.13`–`.21`.
11. `make collect-plus-local` container mode untested (Docker 12 GB+).

## Open owner decisions

- Send the WHO technical note (one `[OPEN]`: a WHO contact email).
- Engine `tests/fixtures/doris_help_examples.json` provenance.
- `digitva-9cll.14`: send the interview when offline coding is rejected?
- `digitva-dn15`: ECT check refuses non-leaf categories?
- Hindi strings: `digitva-ygo5`, `digitva-omqx`, `digitva-jt1w`.
- WHO data files' duplicated sha256 values; CI as engine release source.
- InterVA2022/InSilicoVA2022 experimental (`.tasks` note): needs a go.
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

- `npm run vendor:build` reinstalls the vendor package: stop Metro first and
  restart it with `--clear`. Local vendor `dist` may lag the source.
- The emulator holds two test drafts ("Test Case", "Test Consent"; the latter
  synced to the local dev server only).
- Old APKs show "The selected code does not match its WHO URI." for the
  extension/category refusals (same `INVALID_SELECTION` 422).
- 0.3.16 phones: the standalone home list is stale until Lock and unlock.
- `build/collect-plus-local/…-LOCAL.apk` (31 Oct) was built mid-edit; do not
  test from it.
