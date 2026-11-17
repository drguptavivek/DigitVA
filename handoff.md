# Handoff

## Start here

Staging runs `e6a17915d` (deployed 2026-11-17 with `scripts/deploy-staging.sh`
on the owner's direct go in session "Handoff and open issues"; backup
verified, migrations at head; rollback:
`sudo -Hu ubuntu env SKIP_BACKUP=1 bash scripts/deploy-server.sh 019e8ac7ec24380e21a9840c4157b6435313fb27`).
That deploy ran after the training hold below was recorded: check with the
owner that the staging training was not disrupted. Staging's
`/download/android` still serves 0.3.20: its hosted folder
`private/android-hosted` has nothing newer; copying 0.3.23 in (runbook in
`docs/current-state/android-release-builds.md`) awaits the owner's go.
Main is at `4a2080879` (coding parity PR #775 merged; full backend suite
7771 passed, Jest 5306 passed, `make check-web` green). Images exist for
`798d811d8` and `2e7a51a17`; any newer deploy needs the owner's go.

Old-APK audit: `019e8ac7e..e6a17915d` is done (additive migration
`d8a2f4c6e1b3`, `access_changed` notification accepted by old apps).
`e6a17915d..b95f26e4a` adds no migration; old APKs see new refusals with
existing shapes: non-admin on-screen sign-in QR for verified-email / live
phone / outside-member accounts -> 404; revoked interviewer revising a
submitted case -> 404; closed-session trainee drafts -> 403; social
autopsy remark over 4000 chars -> 422 (old APKs have no maxLength).

Owner rule (bd memory `coding-parity-all-surfaces`): coding works the same on
the web, Collect online and Collect Plus online and offline. Design rule:
Collect screens are frozen (`docs/design/collect-petrol-theme/README.md`);
any change to one is re-checked against `frozen/` and refrozen.

## Ranked next steps

0. **HOLD: no staging deploy while a training is running on staging (owner
   2026-11-17); wait for the owner to lift it.** On staging check: the
   roster person page (`digitva-eyp3`, closed), and on a phone consent
   "No" then back (Id10013 fill). Verified on the emulator against dev
   (Plus debug of main, 2026-11-17): ICD-11 first-launch prompt, phone
   grid, pager with NQA blocked reason, Notes on every page, symptoms card
   after the narrative, NQA "0 / 10 · Cannot Grade", DORIS sex prefill,
   Step 2 card order. Not verified: the phone media gallery (no dev case
   with attachments that `test.all` can code). Six seeded TST001 cases from
   2026-11-08 carry Id10023 without Id10022, so neither web nor phone
   prefills their date of death (test data, not a parity gap).
1. Training (`digitva-9qer`, `digitva-q3iu`): owner supplies
   `app/services/training_corpus/english_v1.txt`; Maestro flows 96–98 need a
   trainee setup role; training media scope; refuse outdated apps (N11);
   hide DEMO01 in graduation; participant roles by session type.
2. Prove the full offline coding flow on a phone (`digitva-9cll.5`),
   standalone then as an enrolled TST001 coder. Coding parity remainder:
   `digitva-9cll.22` (`.22.3`–`.22.6`, `.22.8`, `.22.9`); ICD-10 parity
   `digitva-tk7j`.
3. Backend performance epic `digitva-f41g` (21 beads, filed not fixed,
   owner: "dont fix for now"). P1s `.1`–`.5`: repair batching, SmartVA
   pending scan, backfill stats filesystem checks, coder gate computed three
   times, non-concurrent MV refresh after DM actions. Unmeasured: confirm on
   production stats first. `.10` and `.20` need an old-APK check.
4. Roster follow-ups: `digitva-sjts` (grant-then-issue QR), `digitva-42yo`
   (code endpoint vs grid for deactivated accounts). Optional, offered and
   not approved: hide other projects' actor names in the person page's
   account events.
5. Collect 0.3.24 (`68f418d71`, Android 9 photo and keyboard fixes): CI APK
   and Play AAB built; Play upload is the owner's. Real-phone document scan
   check `digitva-e2ju`. Not built: recovering the camera result after
   Android kills the app on low-RAM phones (`ImagePicker.getPendingResultAsync`).
   Collect: TalkBack/VoiceOver (`digitva-eizq`), Play screenshots
   (`digitva-fthd`; raw captures untracked in
   `mobile/digitva-collect/store/play/screenshots/`), arm64 engine
   `load_failed` (`digitva-rih6`), SM-E146B speed (`digitva-xxfz`), web
   attachments (`digitva-e621`). Owner review of the Hindi strings.
6. Offline PHC station macOS security acceptance (`digitva-xt9y`).
   Standalone engine `v0.1.0` draft awaits owner publish (`digitva-xw1s`).
7. Help chatbot PII redaction (`digitva-wawz`). DORIS validation gaps
   (`docs/current-state/doris-validation-checks.md`). iOS simulator CI
   workflow (`digitva-bfq3`).

## Open owner decisions

- Staging deploy: which sha (`e6a17915d` approved; `798d811d8` adds run-7
  fixes and the roster export) and timing (waiting on AWS sign-in).
- Run-7 decisions are recorded in `docs/policy/mobile-sign-in.md`,
  `dm-user-grant-management.md`, `web-intake.md`, `training-demo-project.md`.
- When to start `digitva-f41g` fixes.
- Send the WHO technical note (one `[OPEN]`: a WHO contact email).
- Engine `tests/fixtures/doris_help_examples.json` provenance; WHO data
  files' duplicated sha256 values; CI as engine release source.
- InterVA2022/InSilicoVA2022 experimental: no go yet.
- AI interview-quality checks on hold (`digitva-qtmq`).

## Boundaries still true

- Staging deploys only via `scripts/deploy-staging.sh <full sha>` on the
  owner's go. `server-images.yml` needs the full 40-char sha.
- Release builds only on CI; local debug builds for development only.
  Publishing releases and tags is the owner's command.
- Golden corpora are owner-approved and frozen.
- On the owner's real phone: no PINs, passwords or system settings.
- Plus stays prerelease; device ICD/DORIS coding starts off.
- No Fable agents.

## Caveats

- Full-suite noise under `-n 4`: `digitva-6igh`, and 9 export streaming
  tests (`digitva-jaea`) that pass serially.
- Untracked on purpose: the orientation deck files under `docs/manuscript/`
  (owner: don't commit), `.claude/launch.json`, the Play screenshots.
  Full parity TSVs live in `private/icd11-parity/results/`.
- Dev DB: DEMO01 has narration languages enabled (english, hindi) for the
  narration image question; revert if unwanted.
- Test databases still present for other work: `minerva_test_codeapp`,
  `_consent`, `_pii`, `_tst002` (and their `_gw*`).
- `npm run vendor:build` reinstalls the vendor package: stop Metro first
  and restart it with `--clear`.
- Old APKs show "The selected code does not match its WHO URI." for the
  extension/category refusals (same `INVALID_SELECTION` 422).
