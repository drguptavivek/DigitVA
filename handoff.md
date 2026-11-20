# Handoff

## Start here

Staging runs `c622782` (deployed 2026-11-20 on the owner's go; backup
verified; migrations at head `f4c2a8e6b1d9`; rollback:
`sudo -Hu ubuntu env SKIP_BACKUP=1 bash scripts/deploy-server.sh f2333a29e8b35c330f1463e2228bff36a2304947`).
It bakes web `expo-web-v2026.11.20.1`. Collect 0.3.26 (`f01f7ed`, version
bump only) APK and AAB builds are on CI; device check before the Play upload.

`main` is ahead of staging with the 2026-11-19 work (CHANGELOG.md): bottom bar
labels, roster codes for active accounts only, the dictation tip, Statistics
wording, the public DORIS demo rebuilt on the web editor, the web DORIS
editor matching the frozen Collect screen, Collect with no WebView (in-app
picker, Selected ICD Codes list, Coding languages screen, in-app "I have a
code" and "Forgot password"), the 16-character mobile rule and the
rate-limit log fix, plus the 2026-11-20 HMAC limit keys and web masked
Step 2 parity. Deploy is the owner's go. The old-APK audit (2026-11-20)
found it safe; check the old-APK ICD picker by hand first (its JS changed).
Known changes, all additive or a refusal with existing shapes: `GET /profile/` adds `available_languages`; the device
token may now `PATCH /profile/languages`; new `POST /auth/forgot-password`;
the sign-in APIs refuse a mobile over 16 characters with 400
`invalid_request` (apps send 13). The Collect changes need a new CI-built
APK (`react-native-webview` was removed, a native change): CI run
44591287344 built it (passed) but predates the diagnostics opt-in and the
offline NQA; build a new APK before the device check.

Also on `main` since 2026-11-20 (CHANGELOG.md): diagnostics opt-in, Users
page revoke, own-case coding block, offline NQA gates, home totals + JSON,
the web mentor view (migration `e3b7c9d1f5a2`, the only migration since
staging). Re-audit for old APKs before deploy: additive fields and existing
refusal codes only, but a coder holding their own case outside self-coding
loses coding access to it.

Owner rules: coding works the same on the web, Collect online and Collect
Plus online and offline (bd memory `coding-parity-all-surfaces`); Collect
screens are frozen (`docs/design/collect-petrol-theme/README.md`) and are the
DORIS reference the web follows; the Collect app uses no WebView or web page
for any screen (the WHO ICD browser, privacy and data requests, store links
and maps stay in the browser).

## Ranked next steps

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

- Staging deploy of `main` and its timing.
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
- Full-suite noise under `-n 4`: `digitva-6igh`, and the export streaming
  tests (`digitva-jaea`) that pass serially.
- Untracked on purpose: the orientation deck files under `docs/manuscript/`,
  `.claude/launch.json`, the Play screenshots.
- Dev DB: DEMO01 has narration languages enabled (english, hindi).
- Test databases still present: `minerva_test_codeapp`, `_consent`, `_pii`,
  `_tst002` (and their `_gw*`).
- `npm run vendor:build` reinstalls the vendor package: stop Metro first
  and restart it with `--clear`.
