# Handoff

## Start here

Continue field acceptance of the owner-approved 2026-10-28 Plus release candidate.
All implementation and combined gates are recorded in CHANGELOG.md. Read AGENTS.md
and the consent/collection policies. Owner allowed local APK/web builds in this
session and now authorizes staging deployment (hs7e.17), lifting the earlier freeze.
AWS browser sign-in is pending; no deployment has occurred yet. No Play upload or
public WHO engine publication was authorized. Preserve unrelated loadtest, manuscript,
tool-config and unreviewed Play artwork edits. Do not reset or stash.

## Ranked next steps

1. digitva-hs7e.17: commit/push reviewed source, publish matched web release,
   update Compose web pins, build Server images and deploy through
   deploy-staging.sh after AWS sign-in. Compatibility review finds additive
   receipts safe for old APKs; refusal-held work needs updated app and three-
   device accounts may need admin decommission. Existing public APK must stay.
   Proper release-signed Plus APK is building locally for controlled sharing.
2. digitva-hs7e.15.2: design an authorized, audited release for a submitted
   shared-case refusal hold. Current behavior safely blocks other open attempts;
   no in-app release exists. Prior lawful submissions and identity stay intact.
   The hard refusal boundary is implemented; hs7e.15 remains open for this child.
3. Remaining physical acceptance: full/interrupted submissions (5mbn), second
   phone restore (5bzf.8), share sheet, cluster codeinfo (5bzf.3), revise (owbz),
   picker (e1t9), small layout (46xk), decommission/login/receipts and complete
   interview-to-autorun workflow. Engines and hooks passed separate functional
   and regression checks; a full interview was not completed on the phone.
4. digitva-91f2: final artwork, signing, declarations and submission. WHO offline
   software redistribution and bundled Hindi review/redistribution remain open.
   Software notices inventory identifies missing local texts and excludes the
   separate Android/Maven/runtime inventory; complete that release review too.
5. New password-enrolment and refusal APIs are not deployed yet. Recheck live
   staging SHA (recorded c8b749f7b) after AWS authentication; use the verified
   backup/migration/health path and retain rollback. Compatibility review is done.
6. Other prior backlog: 07lz DB-test memory, uf9j huge upload queues, yeg3.1
   own-collector exclusion outside self-coding, 5bzf.11/.12 translations/form
   pinning, qwvt AI follow-ups, ydnl correction loop; discuss bx43/ve8n.

## Settled boundaries

- Standalone never connects/syncs to a server; available only after explicit
  logout of ALL accounts in both Active and Demo. Expiry is not logout. Enrolled
  and Demo support online/offline work with separate target servers. Banners
  include forms, unlock and Settings. Colliding server user IDs fail closed;
  token/account writes are serialized. Retained encrypted work is preserved.
- Device coding preference starts OFF. Enabling it grants no project rights and
  downloads/starts no engine. Online coding always uses the chosen server;
  eligible local coding uses packaged engines. Same-project self-coding and
  actual coder access remain mandatory outside standalone's local flow.
- SmartVA automatically follows valid local completion and fills missing/stale
  results on coding entry; manual Run/Regenerate remains. Frozen exact options,
  both consents, preference and permissions are rechecked. Missing country or
  explicit mortality settings require profile/config repair; never guess them.
  Completion does not wait for engine success; interruption retries on entry.
- Either WHO or DP refusal stops the interview/coding. Only broad deceased
  age/sex and consent/system metadata remain. Fresh grant can resume an unsent
  attempt; version barriers prevent old answers returning. Registrations with
  earlier lawful data/finalized submissions remain immutable. Registration-only
  staff can save identity-free refusal receipts online or in the offline queue.
- Standalone English/Hindi consent notices are editable in Settings. Each draft
  consent keeps the full rendered notice/hash/version. Server/demo notices stay
  project-managed. Hindi questionnaire v6 remains experimental/in_review.
- Screenshot allowance covers normal APK/AAB and Plus until
  2026-11-25T08:12:11Z; timer/foreground checks depend on device clock. First-run
  safe area, mode banners and Settings were checked. Normal Collect untouched.

## Evidence and artifact

- Backend: 7013 passed, 6 skipped, 5469 subtests, 9 warnings (1329s, -n2).
  Mobile: 232 suites/3322 tests; TypeScript and web export passed. Final audits
  found no blocking issue after fixes. Post-format smoke: 5+32 passed.
  Rust: default10/mobile-core8 tests. No server migration added; b4e7c2a9d6f3.
- Private local release APK: digitva-plus-final-autorun.apk, 141185658 bytes,
  SHA256 cdf2f3ea9920c7d22aef52c64dbded7a0436927534ced560b64abd0e47fd2dc4.
  TargetAPI36, collection min24; engines checked on13+. All33 native libraries
  are16KB aligned. Debug-key-signed release is a test artifact, not store signing.
- Installed -r on Samsung SM-E146B Android15/API35 and emulator5580
  DigitVA_API33_Check Android13. Both passed offline SmartVA and ICD/DORIS,
  expected BA41.Z and three exact synthetic SmartVA projections. Not clinical
  accuracy validation. Phone SmartVA setup93ms, scores245/34/28ms, warm62ms;
  WHO init18.309s, DORIS84.5/warm6.3ms. Sampled PSS engine peaks: SmartVA61.5,
  WHO830.3MiB; steady59.5/525.9MiB. Earlier clean setup reached1191MiB WHO.
- Logs/APKs/screenshots/CSVs/JSON stay PRIVATE/ignored under
  private/engine-measurements/20261028-sm-e146b/. No binaries published.
  SmartVA mobile-core source790af12 pushed to owner fork vg-work/android-mobile-core.
- Phone synthetic profile EngineBenchmark; emulator EngineBenchmark13. Unlock
  details stay in the private test context. Preserve current profiles/drafts;
  OLD Plus data alone was cleared
  earlier with owner permission. Recheck/restore phone airplane0/WiFi1/data1 and
  stay_on_while_plugged_in15 before leaving further tests.
- Tests used own modes_20261028 (+gw0/gw1), consent_boundary_20261028,
  coding_refusal_20261028 and refusal_register_20261028 databases. Cleanup only
  these after confirming idle; never touch minerva_test or another session's DB.
