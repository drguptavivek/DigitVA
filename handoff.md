# Handoff

## Start here

Read `AGENTS.md`, `docs/current-state/README.md` and the relevant policy.
Owner focus: DigitVA web app, training and Android. The ordinary product is
**DigitVA**; digitva-collect is a technical folder/package name, not web branding.
Build production web exports and APKs only on GitHub Actions. Local development
uses `make dev-hmr` (Docker bind mount + Metro, same-origin Flask at port 8051).
DORIS stays 1.1.176 until an official WHO image supplies the approved replacement.
Preserve unrelated dirty `scripts/loadtest/restore.sh` and orientation files.

## Ranked current work (2026-10-25)

1. `digitva-k2s1`: approved WHO runtime isolation and authenticated background
   asset caching implemented in the working tree; CI export and final browser
   acceptance remain open. One async web WHO core+renderer boundary; local small
   UI controls and browser-safe case/revision utilities remove eager imports.
   Native retains static WHO runtime. Public manifest warming requires interview
   access, foreground/online/4G/no-save-data; verified completed chunks survive
   cancellation/retry. Full Jest180/2705, typecheck, Node18 and backend519/125
   subtests passed on the integrated change. CI profiles all initial scripts
   and canonical instrument placement, not only entry.
   Baseline artifact a14f6fa24 is mounted on8053, candidate on8054 after CI;
   own container digitva_web_profile. Sanitized traces in
   /private/tmp/digitva-web-profile-20261025. No staging deploy.
   `digitva-bc56`: profiling exposed training by-ID scope omissions; backend
   guards and browser propagation tested, namespace implemented at owner request:
   /training/interview, /training/coding, /training/reporting, /training/reviewing
   plus child details/forms, legacy redirects. Keep stable API area keys.
   Live HMR synthetic training draft opens and saves; screenshot
   /private/tmp/digitva-training-canonical-form.png. Final CI/browser acceptance
   still required before closing these beads.
   `digitva-bc56.1`: final audit found pre-existing workspace auxiliary APIs
   ignoring training scope; shared case-SID guard planned before release.
   CI-only frontend profiling may proceed while that backend fix is completed.
2. Closed `digitva-grmg`: subsequent owner-reported whiteout on death-registration
   navigation/reload fixed locally: themed WebShell/loading status plus
   public/index.html prepaint. Full Jest175/2689, typecheck, Node7 and final audit
   pass. Chrome html/body/root now opaque theme. CI40185993778 passed a14f6fa24;
   final HTML startup/theme and manifest source verified, SHA
   f26da943c1a5e0e8118f466d49d952eb5ec5b8e6e363b60776651733ae205327.
   Owner-reported root reload delay resolved; owner confirmed loaded now.
   `digitva-cklz` closed: exact /vaindex,/index routes proxied to Flask, both
   Admin shortcuts and logo verified. Only HMR ingress recreated.
3. Closed implementation beads digitva-akbt/55zu/dmcl/dmcl.1/26h6: pushed
   b133babc1, CI pass, Chrome recovery/reset/note/VA-card and SmartVA checks pass.
   Screenshots: /private/tmp/digitva-local-coding-acceptance.png,
   digitva-admin-console-verified.png and digitva-loading-theme-verified.png.
   Remaining rendering toast tracked digitva-lo67; no missing visual code proven.
4. `digitva-ydgv`: approved training interview welcome + existing DPDP consent
   flow not implemented yet. Reuse current notices/audit; do not invent legal
   approval or change masking/NQA. New and existing TRN01 need idempotent setup.
5. `digitva-e1t9`: intermittent ICD picker backdrop without panel. Browser/server
   logs did not establish root cause; static responses healthy, browser request
   delay observed. Not fixed. Do not claim a proven listener race.
6. `digitva-bx43`: optional DORIS hints only, discuss before implementation; no
   new mandatory fields. `digitva-ve8n`: Expo login idea, discussion only.
7. `digitva-5mbn`: remaining web acceptance; user authorized all staging test
   cases as disposable. Do not manipulate the phone; user chose local Chrome.

## Runtime and verification

Staging digitvav3 (`i-0b2caee6465bfcac1`, ap-south-1, profile digitva,
`/data/DigitVA`) runs image d7f8ac86e, web expo-web-v2026.10.25.1.
Migration head c3f9a1d7e2b4. Preserve APK 0.3.10 override
`DIGITVA_ANDROID_APK_DIR=/app/private/android-hosted`.
Use `scripts/deploy-staging.sh <full-sha>` after CI; rollback image
73561675ad00fe510ab7237925df86f59509f767. `DORIS_CALL_LOG=1` remains on.
No image build should run concurrently with a push to main.

TRN01 is intentionally single-stage, masked_cod_required=False and NQA=False.
Owner explicitly chose keep configuration/discuss first. SmartVA training19
completed in 1.64 s server-side; stale browser Running motivated lifecycle fix.
HMR Chrome test account is signed in locally; localhost /app redirects to root
because Expo 57 ignores the production base URL in dev. No local export needed.

Validation: full Jest 175 suites/2688 tests passed; typecheck passed. Broad backend
(non-migrations, two workers) 6212 passed/5 skipped/4505 subtests, one enqueue race
failed. Fixed that race; final affected backend 172 passed/36 subtests, including
the deterministic concurrency regression. Node cache tests 6 passed. Final audit
found no remaining material defects. Four-worker attempt had a worker crash;
its isolated test passed, and two-worker rerun completed. Earlier intake query
ceiling 75 versus72 was baseline-identical (`digitva-5dxf`) and did not reproduce
in the latest broad run; retain investigation for order/cache sensitivity.
Redis SmartVA batch claiming assumes current single Celery worker; strengthen
before increasing worker concurrency. Standalone deploy script guard: digitva-22lb.

## Other queued work and owner decisions

Collect Plus release/phase B `digitva-hs7e`, DORIS demo parity `digitva-knh9`,
screenshot allowance removal after 2026-10-30 `digitva-om65`, P1s digitva-fvbc,
digitva-owbz/46xk/342x, mentor view digitva-oux5, Hindi review remain queued.
KEM001 has 24 attachment_sync_pending submissions. Unattached Docker volumes need
explicit inventory/approval before deletion. Consent notices remain pending legal
review. See CHANGELOG for landed deployments; preserve private data and volumes.
