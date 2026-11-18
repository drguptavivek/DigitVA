# Handoff

## Start here

Staging runs `f2333a29e` (deployed 2026-11-18 on the owner's go; backup
verified by the script; rollback:
`sudo -Hu ubuntu env SKIP_BACKUP=1 bash scripts/deploy-server.sh 560dafe5e27385a1823906481db07e46d0e47145`).
It carries web `expo-web-v2026.11.18.4`, Collect `android-v0.3.25` and Collect
Plus `collect-plus-v0.3.25-plus.1`; both 0.3.25 APKs were copied into
`private/android-hosted` (older files kept), and both downloads and
`/api/v1/app/android/latest` (both variants) return the 0.3.25 checksums.
The Play AAB (run 44257815327) awaits the owner's Play upload. Old-APK
check `c7e473ab8..560dafe5e`: only the web intake page's script changed on
the server; no API, shape or migration change.

Old-APK audit: `b95f26e4a..0fd111363` (2026-11-18) SAFE WITH NOTES: no
migration, additive `code_titles`; moving or deactivating a worker's
placement now revokes their unit roles, so a collector with unsent work
cannot upload until re-granted (tell admins). Earlier: `019e8ac7e..e6a17915d` is done (additive migration
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

0. iPhone 17e wraps "VA Interview" onto two lines in the bottom bar.
   Attachment eviction after 7 days in Safari: `digitva-fllj`, unverified.
   Earlier phone coding checks on 0.3.24 (real phone) still open.
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
5. Collect 0.3.24 (Android 9 photo and keyboard fixes, phone coding
   layout, ICD code titles): release APK, Play AAB, web export and server
   image built on CI 2026-11-18 (see CHANGELOG); Play upload and any deploy
   are the owner's. `digitva-iycg`: after a final save the Code queue showed
   the finished case as active until its reload landed (~6 s on the Android 9
   debug emulator); check on a release build. Real-phone document scan
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
