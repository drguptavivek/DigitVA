# Handoff

## Start here

Read `AGENTS.md` and `docs/current-state/README.md`. Preserve unrelated dirty
changes, never stash, stage explicit paths (`grep -Ev` filters, check the staged
list). Backend work uses Docker/uv. Tests: parallel `-n 4` is the default now
(`docs/policy/test-harness.md`, ~8 min instead of ~24); one run at a time per
base database. Use beads. Owner approved staging code only: no staging DEMO01
seed, accounts or weekly reset activation. Aakanksha account changes remain on
hold. Owners may independently edit accounts and translations: reread live state.
The owner owns `vendor/who-va-2022`; edit it freely, it ships in this repo.

## Ranked next steps

1. Deploy this batch to staging only when the owner says. Staging is at
   119384c72 and clean (checked 2026-10-20: no stash, no local commits, no hand
   edits). Needs app/worker/beat image rebuild (pytest-xdist is dev-only), Expo
   web export, no migration (head b8d2f4a6c901 unchanged). Restore Hindi edits:
   `flask instrument-translations import-xliff WHO_2022_VA hi
   resource/instrument_translations_hi_edited_2026_10_19.xlf --as edited`
   (36 units; locale lifecycle unchanged; an approved locale needs
   `--acknowledge-demotion`). Staging Hindi 40 in_review is the owner's live
   state: never overwrite.
2. Supervision lives in the Deaths tab only (`digitva-a5jf`): preset of the
   shared list, tiles Needs my decision / Overdue revisits / Stuck (30 days) /
   total, no Awaiting QA, `/supervision` redirects, drop the DM Supervision tab
   (`digitva-yeg3.25` superseded). Supervisor = health supervisor at a PHC who
   supervises ANM/MPW. Policy: `docs/policy/case-list-views.md`.
3. Death registration identifiers (`digitva-kzyp`, policy
   `docs/policy/death-registration-identifiers.md`, proposed, all owner questions
   answered except google-re2 as second regex guard). Per-project types with
   length/char-type/regex, always CAPITALS, monospaced entry, column-level
   encryption (AES-256-GCM, DEK wrapped by ML-KEM-768+X25519, HMAC-SHA-512 blind
   index). Needs `cryptography>=48` (installed 46.0.5 has no ML-KEM; 48.0.0 added
   it; latest 50.0.2): review 46->50 breaking changes, rebuild three images. Needs
   a migration: chain on committed revisions only.
4. Shared case list service (`digitva-pt0s`): list_cases per policy; first step
   is live (Deaths list and /collection?tab=deaths share DeathsList over
   GET /intake/cases; reporters admitted for own deaths, reverses t6q).
5. Offline attachments for the native app (`digitva-jkvl`): audio+images+
   documents, block submit until uploaded, resumable upload, server re-encode and
   deflate-bomb checks, encrypted chunked file store. Native sync-status chip
   `digitva-gyt9`. Docs cleanup after the supervision move `digitva-ipv1`.
6. Physical auth acceptance `digitva-p6fs.5`: install the signed Android testing
   release (0.1.0/build 6, Actions 39234202987) and verify PIN/biometrics, lock,
   device-token privilege denial. No physical Android/iOS acceptance is complete.
   Native passkeys deferred `digitva-uwbg`/`.3`.
7. Translation review remains an owner decision; never auto-approve/activate.
   Follow-up `digitva-xzdm` stale sibling counts. Staging demo activation excluded
   (local DEMO01 only; credentials in ignored `private/organization-demo/`).
8. Earlier follow-ups: intake media acceptance `ej1`, project setup clickthrough
   `r1p`, WHO Id10365 `0lf7`, `fb5`, `mdj`, `ddv.5`; Expo queues `p6fs.4.3`,
   `p6fs.27`, `p6fs.32`; coder UI `r0fa`, `uoe5`, `ks4m`, signout `rcte`; Data
   page `4ufj`, intake 422 `gqtp`; vendor `digitva-3jj` draft-save-order flake,
   inherited vendor lint. `digitva-ecpm` root cause: 308d15979 removed one
   expression (pin now 560).

## What landed in this batch (2026-10-20, one commit)

UX audit epic `digitva-yeg3` fixes: nav is Home / Deaths / VA Interview / VA Code
/ VA Review / Statistics / More (left menu wide, bottom bar phone, no top tabs, one
Help, one logo); per-role Home blocks from `GET /api/v1/me/home`; percentages only
when part<=whole and denominator>=20; Organization cards per project with roles
per level; shared deaths list with Mine/All and Last 30 days toggles, Project and
Area inside Advanced filters, accessible case cards (14px, 7:1, labelled values,
map pin); Direct VA interview panel; interview screen: case strip pinned, chrome
scrolls away, four equal footer buttons (vendor FormFooter edited), leave guard
with autosave wording, interviewer age prefill from profile year_of_birth (reverses
q219), HIV/malaria presets inherit from org units; phone 3-3-4 validation;
DOB-or-age mandatory (server authoritative); compact Address/Remarks; reviewer
queue defaults and coder-COD card; GPS only in organization projects for PII
callers and own registrations; contextual help flyout, mentoring screen. Beads
`digitva-yeg3.3/.5/.7/.8/.9/.11/.12/.13/.19/.20/.21` are done; earlier-session
beads `531a`, `zv2o`, `fqer`, `750z` ride in the same commit.

## Current runtime baseline

SSM ap-south-1 i-0b2caee6465bfcac1, ubuntu `/data/DigitVA`.
https://digitvav3.causeofdeathindia.com runs application 119384c72, database
single head b8d2f4a6c901, Expo web export from 4527580c2. App healthy,
worker/beat running; ingress/Redis/ICD/DORIS retained. External-DB and runtime
health overlays must be preserved; never start the bundled DB there. Static asset
version 20261019.filters1. Rollback images keep tag rollback-pre-choicekeys-20261019.
Fresh S3 backup `digitvav3/db-backups/minerva/pg_dump_minerva_20261019T112139Z.dump`
(34,663,268 bytes, SHA256 e6142142f196b67bfdc59b7c54c7f51ed4310b45a2a9eeed2e4c085d124f1353).
Protected env/runtime backups and translation snapshots: ubuntu
`dailybackups/digitva-code-only-20261019`. No database downgrade.

Mobile Help links to the signed testing APK at GitHub release `android-v0.1.0`
(`org.digitva.collect`, version 6, minSDK 24, target 36, four ABIs). Signing
material ignored under `private/android-signing` (0600), independent backup
`/Users/vivekgupta/dailybackups/DigitVA/android-release/20261019`. Never print or
commit secrets; keep the same signing key for updates.

## Policy and validation boundaries

Worker grants follow configured level-cadre defaults; empty defaults stay
roster-only. Admin creates; PI links existing active accounts. Explicit no-email
needs matching raw ASCII 10-digit mobiles. Web password OR optional passkey for
every role; native password enrolls a device, PIN/biometrics unlock encrypted local
data; native tokens never carry admin/DM/PI/supervisory powers.
`mobile/digitva-collect` pins reanimated 4.5.1, worklets 0.10.1,
`source-map-js >=1.2.2` (`digitva-dd67`).

Interviewers and death reporters in ORGANIZATION projects have PII access and may
see case GPS (rows and detail) only there; a reporter's own registration keeps its
GPS on edit surfaces. Registration numbers: CSV export only for PII exporters,
duplicate number warns, closed cases editable by supervisors/in-charge only.

## Verification and caveats

Last full run (2026-10-20, combined tree): pytest `-n 4` 4693 passed, 3 skipped,
0 failed in 470 s (serial 24 min); jest 102 suites / 1534 tests; vendor vitest 39
files / 818 tests; `tsc` clean; one migration head b8d2f4a6c901. ruff reports
1266 mostly style findings in app/tests (not compared to a baseline). Not verified:
real iPhone/Android clipping (16px field rule added), wide-window Chrome layouts,
native devices, Hindi strings (marked REVIEW NEEDED).

Dev only (not in git): testadmin@digitva.com has extra grants on ICMR01, HP2026,
GUJ026 (all roles but death_reporter/supervisor on ICMR01, which has no org tree),
HP2026/GUJ026 root units carry HIV/malaria presets, local Hindi has the 36 staging
edits (backup `local_translations_before.sql` was in the session scratchpad). Dev
serves `mobile/digitva-collect/dist`; run `npm run export:web`. `app/static/expo-client/`
is a stale untracked export, not committed. Preserve runtime/secrets/volumes and
unrelated stashes. Deployment details: `runtime-and-operations.md`,
`split-production-deploy.md`.
