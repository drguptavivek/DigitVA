# Handoff

## Start here

Staging runs `1dc8322` (deployed 2026-11-23 on the owner's go; web
`expo-web-v2026.11.23.1`; no migration; rollback:
`sudo -Hu ubuntu env SKIP_BACKUP=1 bash scripts/deploy-server.sh 2549743b06d2ed2b44ac0e8e2afbf524708bc923`).
Collect 0.3.29 APK, Collect Plus APK and Play AAB were built on CI from
`30b1578`; device-check them before any publish or Play upload (owner's
command). 0.3.28 and older builds are stale: do not publish.

In progress in other sessions, uncommitted, not landed: interview supervisor
corrections (`.tasks/2026-11-23-supervisor-corrections.md`, policy docs,
mobile web screens, migration `a7d3e9c5b2f1`) and the spaghetti code audit.
Leave their files alone.

Owner rules: coding works the same on the web, Collect online and Collect
Plus online and offline (bd memory `coding-parity-all-surfaces`); Collect
screens are frozen (`docs/design/collect-petrol-theme/README.md`) and are the
DORIS reference the web follows; the Collect app uses no WebView or web page
for any screen (the WHO ICD browser, privacy and data requests, store links
and maps stay in the browser).

## Ranked next steps

- Device-check 0.3.29: re-enrol from Sign in again (`digitva-dbcw`), DORIS
  interview/report death dates, case summary, Reset DORIS dialog, COD form
  PDF on staging. Flaky under `-n 4`: `digitva-9czl`, `digitva-wd09`.
- Bulk invitations: owner gets the mail host's SMTP limits and relay logs
  for 21 and 23 Nov, then tune pace and backoff (`digitva-povs`). Pacing is
  per import only. 86 staging users whose 21 Nov invitations failed still
  need a resend from Users if the owner wants it; find unsent ones by
  grepping celery_tasks.log / errors.log for "gave up".
0. Consent withdrawal landed (`digitva-4gu7`); erasure of a withdrawn case
   is not built (owner to decide). Migrations since staging:
   `e3b7c9d1f5a2`, `f4c2a8e6b1d9`. Follow-ups: phone SA panel
   (`digitva-088j`), native mentor view (`digitva-3vj8`). Do not retire the
   server picker page before 2027-01-20 (`digitva-dxg1`).
1. Device check of today's Collect changes on a CI-built APK
   (`digitva-9m8o`). Earlier phone checks still open: offline coding journey
   (`digitva-9cll.5`), coding parity remainder (`digitva-9cll.22`), ICD-10
   parity (`digitva-tk7j`), real-phone document scan (`digitva-e2ju`).
2. Training (`digitva-9qer`, `digitva-q3iu`): owner supplies
   `app/services/training_corpus/english_v1.txt`; Maestro flows 96-98 need a
   trainee setup role; training media scope; refuse outdated apps (N11);
   hide DEMO01 in graduation; participant roles by session type.
3. Retire the server picker page after the APK rollout (`digitva-dxg1`).
4. Ready P1 beads audited 2026-11-19: none secretly done except `rou1`
   (closed). Open with code ready, owner action left: `yacr` (re-count KEM001
   and run the repair), `ddfx` (Aadhaar sweep on staging), `77ti` (count on
   staging), `zkgx` (Hindi review). Partly done: `yeg3.1`, `9cll.22.3`,
   `r9lk`, `xjpk`, `xk41`, `rpqp`. Open: `yeg3.18`, `yeg3.24`, `342x`,
   `bx43`, `7amd.27` (due 2027-10), `9cll.18`, `1b50`, `p8uj`, `oux5`.
5. Backend performance epic `digitva-f41g` (owner: "dont fix for now").
6. Collect: TalkBack/VoiceOver (`digitva-eizq`), Play screenshots
   (`digitva-fthd`; raw captures untracked), SM-E146B speed (`digitva-xxfz`),
   camera result after Android kills the app (not built). Owner review of the
   Hindi strings, including today's new ones.
7. Offline PHC station macOS acceptance (`digitva-xt9y`). Help chatbot
   (`digitva-wawz`): unbuilt; must use a CPU or edge small model, no paid API.

## Open owner decisions

- Golden postcoordination fixtures: 12 re-recorded on 2026-11-19 then the
  change reverted; the corpus is unchanged and approved.
- `kkdb` step 2 (on-device Dictate button); `wawz` start.
- Send the WHO technical note (one `[OPEN]`: a WHO contact email).
- Engine fixture provenance; WHO data files' duplicated sha256 values; CI as
  engine release source; InterVA2022/InSilicoVA2022 experimental: no go yet.
- AI interview-quality checks on hold (`digitva-qtmq`).
- Owner items: DORIS production ingress (`ddv.2`), engine v0.1.0 publish
  (`xw1s`), Play listing (`91f2`), translations (`fb5`), manuscript
  (`3kpb`), legal review (`gyfj`), engine pin on CI (`9cll.10`), rotated
  staging passwords (`jb4t`).

## Boundaries still true

- Staging deploys only via `scripts/deploy-staging.sh <full sha>` on the
  owner's go. Release builds only on CI; publishing is the owner's command.
- Golden corpora are owner-approved and frozen.
- Required ICD-11 postcoordination is a picker rule; the server accepts a
  bare stem (docs/policy/icd11-code-selection-principles.md section 4).
- On the owner's real phone: no PINs, passwords or system settings.
- Plus stays prerelease; device ICD/DORIS coding starts off. No Fable agents.

## Caveats

- Docker's disk on this Mac filled on 2026-11-19 and stopped the dev
  database; rebuildable cache was cleared and `.dockerignore` now drops local
  APK build folders. Rebuilding `doris_public_service` (`--profile icd11`)
  still costs several GB; run `docker builder prune -f` after.
- Full-suite noise under `-n 4`: `digitva-6igh`, contact form
  (`digitva-wd09`). The export streaming failures were a leaked
  `DB_BACKUP_TMP_DIR`, fixed in `f34093911`.
- Untracked on purpose: the orientation deck files under `docs/manuscript/`,
  `.claude/launch.json`, the Play screenshots.
- Dev DB: DEMO01 has narration languages enabled (english, hindi).
- Test databases still present: `minerva_test_codeapp`, `_consent`, `_pii`,
  `_tst002` (and their `_gw*`).
- `npm run vendor:build` reinstalls the vendor package: stop Metro first
  and restart it with `--clear`.
