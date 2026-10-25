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

1. `digitva-k2s1`: versioned public web-asset manifest/cache and lazy interview,
   registration/case-detail loading implemented, focused tests pass. Final audit passed;
   CI export size comparison and slow/interrupted-browser profiling pending.
   Browser CDP enable stalled for about 58 minutes; no reliable profile captured.
   Owner approved the exact 57-file commit and CI-only export (2026-10-25),
   including running Beads checks separately and skipping the local export hook.
   Exact scope: /private/tmp/digitva-web-reviewed-files.txt.
   No new staging deployment yet. Native/offline engine is outside this task.
2. `digitva-akbt`: per-tab COD reload recovery and WHO-prefill reset implemented.
   Retain nested COD lines/intervals/selection/remarks/pending private notes;
   exclude demographic fields and processing proof. Fresh authorized context
   required; restored certificates must be processed again. Clear final submit,
   release/lost access, next form, logout/expiry. SmartVA/saved notes reload from
   server; reset keeps them. Local Chrome SADEMO acceptance passed: ICD selection,
   3-day interval, pending note and chosen cause survived reload; proof required
   reprocessing. Reset retained note/WHO defaults and did not resurrect causes
   after reload. No assessment submitted. Screenshot in /private/tmp/digitva-local-coding-acceptance.png.
3. `digitva-55zu`, `digitva-dmcl`, `digitva-dmcl.1`, `digitva-26h6`: inline VA
   code/title + case-definition note, hide year-only technical note, SmartVA
   auto-start/status polling and enqueue guard, Docker HMR implemented. Prior
   final audit passed after documentation fix. HMR Fast Refresh visibly verified.
   These changes are in the shared dirty tree awaiting integrated landing.
   Local Chrome shows inline VA mapping/right-hand definition and masked SmartVA
   status Done. Narrow/Step2 browser checks pending. RN development toast warns
   about unexpected text node '.' (`digitva-lo67`); source unverified. Chip text
   omitted from AX because its explicit label is Remove condition N, not a proven
   missing visual code. Browser-control calls later stopped before dispatch.
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
