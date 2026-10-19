# Handoff

## Start here

Read `AGENTS.md` and `docs/current-state/README.md`. Preserve unrelated dirty
changes, never stash, and stage explicit paths. Backend work uses Docker/uv
and dedicated test databases. Use beads. Owner approved staging code only:
no staging DEMO01 seed, accounts or weekly reset activation. Aakanksha account
changes remain on hold; do not change her password or grants on the owner's
behalf. Owners may independently edit accounts: reread live state first.

## Ranked next steps

1. Physical auth acceptance `digitva-p6fs.5`: install the signed Android testing
   release and verify local PIN/optional biometrics, cancellation/PIN fallback,
   background/restart lock, and device-token privilege denial. No physical
   Android/iOS acceptance is complete. Native passkeys remain deferred under
   `digitva-uwbg` / `.3`. The APK is version 0.1.0/build 6 from Actions 39234202987;
   Expo config, release verifier, and workflow release title now use the app
   label `DigitVA` (`docs/current-state/android-release-builds.md`).
   This is a testing release, not a separate production rollout.
2. Translation review remains an owner decision. Last staging snapshot: Hindi 40,
   inactive/in_review; owner continues editing, so reread live state. Never
   overwrite edits or automatically approve/activate a language. Editor uses
   authoritative reference choice keys, not runtime language/en. Missing includes
   blank and unaccepted machine text; popup names Hint / note and outstanding
   fields. Dirty drafts must be saved, never silently accepted. Follow-up
   `digitva-xzdm`: shared-list sibling rows may show stale counts until modal
   closes/reloads; backend values are correct. Startup imports missing sources only.
3. Staging demo activation is deliberately excluded. Local DEMO01 has four
   signed-in synthetic accounts; Sunday 23:00 Asia/Kolkata reset requires both
   configured target and DB flag, verified backup, scoped reseed/audit/locks.
   Credentials: ignored `private/organization-demo/local-demo-credentials.json`,
   mode 0600. Local scheduler and dry run verified; disposable real backup/restore
   drill passed and drill DBs were dropped. Never reset TST001/clinical projects.
4. Vendor residuals: `digitva-ecpm` expression assertion expects 561 vs 560,
   reproduced on original source; assertion retained. `digitva-3jj` draft-save
   order flake and inherited vendor lint remain. Type fixes `i793`/`surw` are
   closed: typecheck/build including DTS, 38 focused tests and 32/32 generated
   subset equivalence pass; generated artifact/version unchanged. Full vendor
   suite is not green.
5. Earlier follow-ups: intake media browser acceptance `ej1`, project setup
   clickthrough `r1p`, WHO Id10365 `0lf7`, translation readers `fb5`, WHO reply
   `mdj`, `ddv.5`; Expo queues `p6fs.4.3`, `p6fs.27`, `p6fs.32`; coder UI
   `r0fa`, `uoe5`, `ks4m`, signout `rcte`; Data page `4ufj`, intake 422 `gqtp`.

## Current runtime baseline

SSM ap-south-1 i-0b2caee6465bfcac1, ubuntu `/data/DigitVA`.
https://digitvav3.causeofdeathindia.com runs application 119384c72, database
single head b8d2f4a6c901, and Expo web export from 4527580c2. App healthy,
worker/beat running; ingress/Redis/ICD/DORIS retained. External-DB and runtime
health overlays must be preserved; never start the bundled DB there.
Static asset version: 20261019.filters1. Rollback app/worker/beat images retain
rollback-pre-choicekeys-20261019 tags. Protected env/runtime backups and translation
snapshots are in ubuntu's `dailybackups/digitva-code-only-20261019` directory.
Fresh S3 backup: `digitvav3/db-backups/minerva/pg_dump_minerva_20261019T112139Z.dump`,
34,663,268 bytes; SHA256 `e6142142f196b67bfdc59b7c54c7f51ed4310b45a2a9eeed2e4c085d124f1353`.
Remote object size verified; no database downgrade or destructive clinical work.

Owner edits continued during validation: Hindi advanced 34->40, so pre/post
translation snapshots differ; do not restore an older snapshot. Startup
imported 0/skipped 13/written 0; no deployment translation writes or activation.
No account/grant/password changes were made by acceptance checks.
Weekly demo target is empty, synthetic reset flags 0; no DEMO01 was seeded.
Existing SADEMO training configuration is separate and preserved.

Browser checks: Interviewer create/filter selectable; Users no-email mode and
nine-digit rejection; Add worker confirmation fields/max length 10; mentor panel;
actual HP0001 XLSX download with hidden references and dependent cadre validation;
translation narration missing-options row, five DORIS option lists and editable
orphan-list modal; footer opens Expo coding interface. No translation save was
performed on staging. Native Excel dropdown interaction remains unverified.
Latest browser check: ABHA Hint / note and accepted-state summary visible;
language options 1/2/3 and canonical layer choices editable, synthetic en absent.
No save/accept was performed on staging by acceptance checks. API save/export
verified in isolated tests. Screenshot:
`/private/tmp/digitva-staging-note-review-20261019.png`.
Earlier unsaved modal fields were copied locally to ignored/private
`private/translation-drafts/hindi-editor-20261019.json` (0600); this is a historical
snapshot, not necessarily the owner's latest draft. Never overwrite newer text.
Actual macOS 26.6.2 (25G83), Codex 26.1013.40934 recorded; browser engine version
not independently established. Mail delivery and physical devices remain separate.

Mobile Help now links to the signed testing APK at GitHub release
`android-v0.1.0`. Anonymous download 200, uploaded digest matches verified local APK.
Package `org.digitva.collect`, version 6, minSDK 24, target 36, four ABIs,
non-debuggable. Certificate/origin/checksum verified. Dedicated signing material
is ignored under `private/android-signing` (0600); protected independent backup:
`/Users/vivekgupta/dailybackups/DigitVA/android-release/20261019`. Never print or
commit secrets. GitHub `android-release` environment has owner review/main-only
policy and four scoped secrets. Keep the same signing key for updates.

## Policy and validation boundaries

Worker grants follow configured level-cadre defaults only; empty defaults remain
roster-only. Admin creates; PI links existing active accounts. Existing profiles
and passwords stay unchanged. Explicit no-email requires matching raw ASCII
10-digit mobiles; browser/server validation applies to any supplied new phone.
Optional birth year and sex apply on both main Admin New User (`digitva-4fwy`)
and worker creation, as well as admin/self profile edits; existing profiles are
never backfilled automatically. Verification ends on a no-store completion page;
password email includes the login link.

Web password OR optional passkey works for every role, without OTP/TOTP or
mandatory factor setup. Auth 02ec694d/74ni closed; historical TOTP remains inert.
Native password enrolls a device; PIN/optional biometrics unlock encrypted local
data. Native tokens cannot carry admin/DM/PI/supervisory powers, even for mixed
roles; collection/coding eligibility remains required.

`mobile/digitva-collect` pins `react-native-reanimated` (`4.5.1`),
`react-native-worklets` (`0.10.1`), and `source-map-js >=1.2.2` (`digitva-dd67`;
remaining inherited SDK 57 advisories are build/CLI-only or gated on an SDK 58
major upgrade, documented in `docs/current-state/android-release-builds.md`).

Final backend: 4544 tests + 2406 subtests passed, 3 skipped (migrations excluded),
exit 0 in 443.57s; focused intake/profile/account tests (22 passed), JS checks,
mobile `app-config` Jest suite (5 passed), and TypeScript check passed. Ruff/diff
check passed; quality gate cleared with xzdm residual above. Do not claim full
vendor/device acceptance. Dev serves the working tree; use `npm run export:web`.
Preserve runtime/secrets/volumes and unrelated stashes. Current-state deployment
details: `runtime-and-operations.md` and `split-production-deploy.md`.
