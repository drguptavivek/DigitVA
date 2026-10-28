# Handoff

## Start here

Continue the owner-approved public Collect / Collect Plus 0.3.13 release
(`digitva-hs7e.17`) and server API compatibility check (`digitva-hs7e.18`).
Read AGENTS.md and consent/collection policies. Staging freeze is lifted.
Owner explicitly overrode the earlier public Plus hold on 2026-10-28 and asked
for BOTH variants and APK sizes on the download page. WHO written redistribution
confirmation is still pending; owner authorization is not WHO permission.
Local APK/web builds are authorized this session. No Play upload authorized.
Preserve unrelated loadtest, manuscript, tool-config and Play artwork edits.
Never reset or stash.

## Ranked next steps

1. digitva-hs7e.18: version endpoint and manual native Settings compatibility
   check implemented, under final validation. Contract/API compatibility=1;
   deployed SHA is diagnostic, never an exact-match access requirement.
   Mobile 232 suites/3329 tests, types and web export passed. Backend full:
   7015 passed/1 query-count failure/6 skipped; 20-test file passed serial
   and two-worker reruns (hs7e.19 follow-up). Scoped audit found
   Plus tag identity issue, fixed with validated runtime pin/null fallback.
2. digitva-hs7e.17: both local signed 0.3.13 APKs are verified under
   private/android-artifacts/0.3.13/ (verified-artifacts.json). Normal installed
   preserving data; both copied/hash-verified in phone Downloads. Publish, set
   normal/Plus Compose pins. Deploy variant-safe source BEFORE adding Plus to
   hosted override; old lexical selector would expose Plus as normal.
   Variant isolation and size-aware download page are implemented. Run matched
   web release, update pins, build server image, get protected approval, deploy
   only via deploy-staging.sh and verify both public downloads/version endpoint.
3. digitva-hs7e.15.2: authorized/audited release of a submitted shared-case
   refusal hold still needs design. Prior lawful submissions remain immutable;
   current hard hold safely blocks further work. hs7e.15 remains open for it.
4. Physical acceptance: full/interrupted submissions (5mbn), second-phone restore
   (5bzf.8), share sheet, cluster codeinfo (5bzf.3), revise (owbz), picker (e1t9),
   layout (46xk), decommission/login/receipts and full interview-to-autorun flow.
5. digitva-91f2: artwork, declarations and store submission. WHO offline and
   bundled Hindi review/redistribution questions remain. Notices inventory still
   has missing local texts and excludes separate Android/Maven/runtime inventory.
6. Other backlog: 07lz DB-test memory, uf9j huge queues, yeg3.1 collector exclusion,
   5bzf.11/.12 translations/form pinning, qwvt AI follow-ups, ydnl correction loop;
   discuss bx43/ve8n.

## Deployment and artifacts

- Live staging is 3147fc3a43b8db0e504bd1e8f029395e9a30dab0, deployed through
  the wrapper after owner-approved image run 40679243131. Backup succeeded:
  pg_dump_minerva_20261028T115844Z.dump (35821624 bytes, S3). Current=head is
  b4e7c2a9d6f3; app/WHO/DORIS healthy, worker/beat running, public /health healthy.
- Web expo-web-v2026.10.28.1 is matched to efe8bd636; public manifest/WHO hashes
  checked. Public Collect0.3.10 APK unchanged at that deployment. Rollback:
  sudo -Hu ubuntu env SKIP_BACKUP=1 bash scripts/deploy-server.sh c8b749f7b88a1a853dcd1e7e83d2070bb76624f4
- API/dual-release source is not deployed yet. Public app and Flask sign-in pages
  rendered; a signed-in interview flow was not repeated after that deployment.
- Previous signed Plus0.3.12/code3122 is verified and copied into phone Downloads
  for sharing. Private filename digitva-collect-plus-0.3.12-arm64-v8a-signed.apk;
  SHA2561879fdd0f1564f6e7c0b07d6e148868b4373645b7de4cf5abdb0e01e969c5eaf.
  Installed benchmark copy uses a different debug signature: do not uninstall or
  replace it and lose current drafts. Normal Collect is a separate package.
- All binaries/logs/screenshots remain ignored under private/. Main source
  71566ecd and SmartVA source790af12 are pushed; main also includes web pins.
- Earlier combined backend:7013 passed,6 skipped,5469 subtests. Native engine
  checks passed offline on SamsungSM-E146B Android15 and emulator5580 Android13.
  Phone SmartVA scores245/34/28ms; DORIS84.5ms, WHOinit18.309s; expected BA41.Z
  and three synthetic SmartVA projections. Not clinical validation. WHO sampled
  peak830.3MiB, earlier first-setup1191MiB; steady525.9MiB. All33 libs16KB aligned.

## Settled boundaries

- Standalone never calls/syncs a server and requires explicit logout of ALL Active
  and Demo accounts. Enrolled/demo keep distinct servers, profiles and caches.
- Device ICD/DORIS coding starts OFF. Eligible online coding uses the server;
  eligible local coding uses packaged engines. Enabling grants no permission.
  Same-project self-coding AND coder rights are required outside standalone.
- SmartVA autoruns after valid local completion and fills missing/stale results
  on coding entry; manual regeneration remains. Frozen options/consents/access
  rechecked; interrupted completion retries on entry. No runtime engine download.
- WHO or DP refusal stops collection/coding in every mode; only broad deceased
  age/sex and consent/system metadata remain. Fresh grant can resume an unsent
  attempt; stale answers cannot return. Prior lawful/finalized records immutable.
- Standalone English/Hindi notices editable; each draft retains full wording/hash.
  Server/demo notices project-managed. Hindi questionnaire remains in_review.
- Screenshots allowed until2026-11-25T08:12:11Z (device-clock dependent).
- Preserve phone benchmark profile/draft; phone network restored airplane0/WiFi1/
  data1. Prior six test DBs dropped idle. Current tests own version_20261028 and
  release_version_20261028 (+gw0/gw1); clean only those after final commit.
