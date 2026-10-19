# Handoff

## Start here

Read `AGENTS.md` and `docs/current-state/README.md`. Shared checkout: preserve
unrelated dirty changes, never stash, stage explicit paths from `git diff`.
Use Docker/uv for backend work and a dedicated test database. User requested
no full suite until implementation was complete; final combined validation
passed after implementation. Do not deploy code
without authorization. Use beads for durable tasks.

## Ranked next steps

1. Final combined validation is complete: backend **4,539 tests + 2,406
   subtests passed, 3 skipped** (tests/migrations excluded); earlier targeted
   demo migration/schema-drift/no-app-import checks passed (26 tests/3 subtests).
   Mobile **96 suites/1,303 tests**, TypeScript, web export and four JS behavior
   harnesses passed. Code-quality audit cleared. Land and push the verified
   explicit file list (exclude unrelated dirty docs below). Dedicated runner DB
   `minerva_test_d045_20261019` retained until landing; drop only after no active
   connections. Code tasks closed; runtime deployment still separate.
2. Android `digitva-hhbh`: dedicated release key generated under ignored
   `private/android-signing/`, mode 0600, independent checksum-verified backup
   `/Users/vivekgupta/dailybackups/DigitVA/android-release/20261019` (0600 files).
   Never print or commit secrets. Four environment-scoped signing secrets and
   public certificate fingerprint variable configured on GitHub in protected
   `android-release` environment: required reviewer drguptavivek, main-only
   deployment branch. Workflow manual/main-only, versionCode github.run_number,
   exact version tag before publication. No signed APK built/published yet.
   After landing, dispatch, complete environment approval, verify actual APK
   certificate, origin, version code and checksum, publish requested release,
   then configure download URL. Do not invent an APK link.
3. Demo activation on staging is not authorized/completed. Local DEMO01 has
   four signed-in accounts (`digitva-ic8v` closed),
   no anonymous access. Sunday 23:00 Asia/Kolkata reset, opt-in configuration
   AND DB flag, verified backup and scoped atomic reseed with audit and locks.
   Never reset TST001 or clinical projects. Disposable real backup/restore drill
   passed (394,334-byte archive, checksum verified, exact account/grant/data
   recovery plus retained physical attachment). Local target configured in .env,
   app/worker/beat restarted; actual scheduler row enabled Sunday23 Asia/Kolkata,
   dryrun validates baseline4deaths3submissions3workflows. Credentials are in
   ignored private/organization-demo/local-demo-credentials.json (0600).
   No staging demo seeded or weekly reset enabled there.
4. Auth acceptance `digitva-p6fs.5`: physical Android/iOS PIN/biometric work
   pending: unlock, cancellation/PIN fallback, background/restart lock, device
   privilege denial. Native passkeys stay deferred (`digitva-uwbg` / `.3`).
   Actual macOS 26.6.2 (25G83), Codex app 26.1013.40934; browser engine version
   not established. Local browser privileged password/no OTP verified earlier;
   optional passkey visible. No physical biometric acceptance claimed.
5. Retain earlier ranked follow-ups: intake media browser acceptance `digitva-ej1`,
   project setup clickthrough `r1p`, WHO Id10365 report `0lf7`, five translation
   readers `fb5`, WHO reply `mdj`, `ddv.5`; Expo queues `p6fs.4.3`, `p6fs.27`,
   `p6fs.32`, vendor checks `i793`/`surw` and `3jj`, coder UI `r0fa`, `uoe5`,
   `ks4m`, signout `rcte`; Data page `4ufj`, intake 422 `gqtp`.

## Current implementation boundaries

- Worker account/grants follow configured level-cadre default roles only;
  empty defaults remain roster-only. Admin creates; PI links existing active
  accounts only. Existing profiles/passwords unchanged. New form email and
  confirmation OR explicit No email and matching raw ten-digit mobiles;
  browser and server validation, optional birth year/sex new accounts only.
  Main Users form has same mobile confirmation. Email verification ends on
  dedicated no-store confirmation page; password email already has login link.
- Interviewer was missing from staging Grant Access dropdown/filter (`8y41`);
  local template fix plus rendered-select and unit-grant API regressions added.
  Run focused target after active full suite, no staging code change yet.
- Profile job-title/year/sex reminder every web login until complete, dismiss
  for session. Flask and Expo web; native unlock semantics unchanged.
- Mentoring institutes panel is platform-admin-only. Role help link in cadre
  permissions. XLSX active units and dependent cadre validation; actual download
  structurally checked, native Excel dropdown interaction remains unverified.
- Web accepts password OR passkey for all roles; no TOTP or mandatory factor.
  Auth `02ec694d`, bead `74ni` closed. Historical TOTP rows inert; no destructive
  migration. Native password establishes enrolled-device session, PIN/optional
  biometrics unlock local encrypted data. Device tokens cannot carry admin,
  DM, PI or supervisory powers, even mixed roles; eligibility still required.
- New local demo migration `b8d2f4a6c901` applied to dev, single head. Not staged.
- Preserve unrelated preexisting dirty `docs/current-state/README.md`,
  `docs/current-state/installation.md`, untracked split-production-deploy.md.

## Staging verified 2026-10-19 (`digitva-evtq`)

SSM ap-south-1 instance i-0b2caee6465bfcac1, ubuntu `/data/DigitVA`.
URL https://digitvav3.causeofdeathindia.com. Code shallow HEAD a26171f,
DB a4c9e1f2b7d3. Auth route hash matches committed 02ec694d. App, Celery
worker/beat, Redis, ICD API, public DORIS and ingress observed running.
No new feature code from this batch deployed. Backup before translation writes:
S3 db-backups/minerva/pg_dump_minerva_20261019T084044Z.dump, 34,308,446 bytes,
SHA256 bfe563fb142c10735ad96df9e5e5f8e5507a1a33bd9c18bb60240ec026020e33.
Owner authorized importing all local questionnaire sources: thirteen imported
atomically, all remain inactive drafts. English only active/approved. Hindi
source ND01_ICMRVA_WHOVA2022.xlsx coverage1069/1490; other locales ta/kn/mr/ml/
kha/or/bn/fr/pt/ar/sw/es imported. Automatic missing-source hook is local only;
startup/seed imports never approve/activate. Human translation review remains.

Aakanksha read-only diagnostic: active/verified/password present; successful
password login and terms at 14:24 IST. No grants. Phone value is not valid
canonical ten digits and mobile_login absent. Owner said wait: do not modify
account, grants or password. Anmol seen active HP0001 Project PI and platform
admin in current staging screen; no assignment made. User requested how-to.

## Operational caveats

No production deployment or physical Android/iOS biometric acceptance completed.
Synthetic reset retains physical attachment objects for backup recovery; check
real restore drill and schedule before enabling. No destructive clinical action.
Full migration directory is slow: run only relevant migration+drift+no-import.
Dev serves working tree; rebuild Expo via `npm run export:web`, not plain export.
Keep existing runtime/secrets/volumes. Earlier stash is not this session's work.
