# Handoff

## Start here

Continue field/store acceptance of Collect and Collect Plus (`digitva-hs7e`,
`digitva-91f2`). The API-version and public APK release work (.18/.17) is closed;
implementation and validation details are in CHANGELOG.md and current-state docs.
Owner lifted staging freeze and authorized local release builds in this session.
Preserve unrelated loadtest, manuscript, tool-config and Play artwork changes.
Never reset or stash. No Play submission has been authorized/performed.

## Ranked next steps

1. digitva-hs7e.15.2: design an authorized/audited release of a submitted shared-
   case refusal hold. Current hold safely blocks further work; prior lawful
   submissions remain immutable. Parent hs7e.15 stays open for this child.
2. Physical acceptance: full/interrupted submissions (5mbn), second-phone restore
   (5bzf.8), share sheet, cluster codeinfo (5bzf.3), revise (owbz), picker (e1t9),
   small layout (46xk), decommission/login/receipts and a complete interview-to-
   SmartVA autorun flow. Engines and hooks were verified separately; a complete
   interview was not performed on the phone. Native new Settings compatibility
   UI has unit coverage/live API checks, not a fresh signed-in phone walkthrough.
3. digitva-hs7e.19: investigate the unexplained full-suite query-count fluctuation
   (17 vs19) in coding paging. Exact test passed, entire20-test file passed both
   serial and two-worker reruns, measured code unchanged. Do not weaken the
   assertion or claim a cache cause without bounded instrumentation/evidence.
4. digitva-91f2: artwork, declarations and store submission. WHO written offline
   redistribution confirmation and bundled Hindi review remain pending. Notices
   inventory has missing local texts and excludes Android/Maven/runtime inventory.
5. Other backlog:07lz DB-test memory, uf9j huge queues, yeg3.1 collector exclusion,
   5bzf.11/.12 translations/form pinning, qwvt AI follow-ups, ydnl correction loop;
   discuss bx43/ve8n before starting work beyond the ranked scope.

## Owner decisions and boundaries

- hs7e.17: owner explicitly authorized public signed BOTH Collect and Collect
  Plus APKs on2026-10-28, overriding the earlier Plus hold. WHO written clearance
  is still pending; owner publication authorization is not WHO permission. Plus
  stays prerelease/experimental. Do not separately publish the engine bundle.
- hs7e.6/.7/.11: Standalone makes no server/update/compatibility requests and
  requires explicit logout of ALL Active and Demo accounts. Enrolled/demo keep
  distinct targets, profiles and caches. Expiry is not explicit logout.
- hs7e.5/.13: device ICD/DORIS coding starts OFF. Eligible online coding uses
  the selected server; local coding uses packaged engines. Enabling grants no
  permission. Same-project self-coding AND coder rights required outside local
  standalone. No runtime engine/data download. SmartVA autoruns after valid
  completion, fills missing/stale results on coding entry, retains manual run,
  rechecks frozen options/consents/access and retries interruption on entry.
- hs7e.15/.16: WHO or DP refusal stops collection/coding in every mode; retain
  only broad deceased age/sex and consent/system metadata. Fresh grant may
  resume an unsent attempt; stale answers cannot return. Earlier lawful/finalized
  records immutable. Standalone English/Hindi notices editable; drafts retain
  full wording/hash. Server/demo notices project-managed; Hindi is in_review.
- hs7e.14: screenshot capture allowed until2026-11-25T08:12:11Z, dependent on
  device clock; normal and Plus release builds included.

## Current runtime and release caveats

- hs7e.17/.18: staging36c30e3f35c033216f46844ff64bbb8c71264c86, web
  expo-web-v2026.10.28.2 from9ea377d7b. Public /api/v1/app/version returns
  compatibility1 and that deployed SHA, no-store. Contract equality is diagnostic
  and non-blocking; source SHA equality is never a permission requirement.
- Server backup verified pg_dump_minerva_20261028T125120Z.dump (S3,35825187bytes),
  current=head b4e7c2a9d6f3, app/WHO/DORIS healthy and worker/beat running.
  Rollback: sudo -Hu ubuntu env SKIP_BACKUP=1 bash scripts/deploy-server.sh 3147fc3a43b8db0e504bd1e8f029395e9a30dab0
- Public /help/mobile-app shows separate0.3.13 Collect/Plus downloads and actual
  file sizes; /download/android remains normal, /download/android/plus is Plus.
  Both public downloaded bodies matched size/SHA; older0.3.10 APK preserved.
  Pins and artifact records: docs/current-state/android-release-builds.md.
  The hosted override must be populated separately after variant-safe code is
  live, using verified image files and atomic renames; deploy alone preserves it.
- Phone normal0.3.13/code3132 installed without data clearing. Both signed0.3.13
  APKs in phone Downloads and private/android-artifacts/0.3.13/, verified against
  release cert. Preserve the different-signature Plus benchmark installation
  and its current draft; do not uninstall it to install the public Plus APK.
- Final mobile232suites/3329tests, TypeScript/web passed. Backend7015passed,
  1 query-count failure,6skipped,5475subtests; final API8tests/10subtests and
  paging20test reruns pass. hs7e.19 tracks the residual; never call full run green.
- hs7e.13: engine cores byte-identical to measured Android13/15 candidate. Phone
  SmartVA245/34/28ms, WHOinit18.309s/DORIS84.5ms; expected synthetic outputs,
  not clinical validation. WHO sampledpeak830.3MiB, earlier first setup1191MiB.
  All native libs16KB aligned (normal28/Plus33). Logs stay ignored/private.
- All ten session test DBs dropped only after idle verification. Phone network
  restored airplane0/WiFi1/data1; preserve profiles/drafts. Benchmark unlock
  details remain in private test context, never in public docs or releases.
