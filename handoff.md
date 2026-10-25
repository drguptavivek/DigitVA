# Handoff

## Start here

Read `AGENTS.md`, `docs/current-state/README.md` and the relevant policy.
Owner focus: DigitVA web app, training and Android. Product branding is DigitVA.
Preserve unrelated `scripts/loadtest/restore.sh` and orientation files.
Use Docker for commands. Owner authorized local Docker web exports for diagnosis
on 2026-10-25; release artifacts/APKs remain CI-built. HMR is at localhost:8051.
DORIS stays 1.1.176 pending an approved official WHO image.

## Ranked work

1. `digitva-k2s1`: finish production browser acceptance and the paired build CI.
   Pushed 8b79f0b5d and 3b6befa11. CI40191960858/40194481274 correctly failed the
   WHO-in-initial-common gate. Local source maps exposed the remaining cause:
   native whoControls.ts won over whoControls.web.tsx. Working tree now has a
   .web.ts shim to whoControlsWeb.tsx; WHO preloaded entry avoids the other nested
   import edge. Local Docker export passed: initial2341188 raw/597461 gzip,
   WHO runtime1246324 raw/250155 gzip deferred, zero WHO sources in initial JS.
   Owner accepts the cold direct-interview trade-off (~1.5 s); do not add the
   proposed startup-overlap optimization. Local browser medians (three trials,
   1.6 Mbps down/512 kbps up/400 ms): home6.269->4.990 s; cached1.948->1.944 s;
   interview cold9.405->10.897 s; cached4.851->4.880 s. Cache/retry/save checks
   still pending. Traces: /private/tmp/digitva-web-profile-20261025.
   `digitva-k2s1.1`: two CI jobs/outputs, one matched release, implemented in
   working tree. WHO package artifact+who-build.json -> verified app build;
   public manifest pins WHO version/commit/archive+dist hashes. Complete app
   archive/Docker contract unchanged. No independently deployed WHO frontend.
   Final app Jest180/2706, typecheck, Node33, helper CLI round trip and YAML pass;
   backend519/125 subtests passed before packaging-only changes. Audit ready.
2. `digitva-bc56`: training routes and read scopes implemented; finish acceptance
   then close. Canonical /training/interview (case/form children), /training/coding
   (case), /training/reporting and /training/reviewing (case), with legacy redirects.
   Keep server areas interview/coding/review. HMR synthetic training form opens
   and saves. Back-to-collection now uses its explicit list route for deep links.
   The identifier warning on8053 is the old comparison build; current8054 has none.
   Broader case-by-ID guard finding bc56.1 was withdrawn: the documented workspace
   API retains specific-form grants and owned allocation checks; do not change it.
3. `digitva-dv58`: WHO vendor Docker serial Vitest933/935; draft-save-order failure
   repeats on unchanged8b79f0b5 baseline; navigation test passes both isolated
   reruns. Build/typecheck/entrypoint regressions pass. No assertions skipped.
4. `digitva-ydgv`: training interview welcome + existing DPDP consent not yet
   implemented. Reuse notices/audit; no invented legal approval or NQA changes.
5. `digitva-e1t9`: intermittent ICD picker backdrop without panel; logs did not
   prove a root cause. `digitva-lo67`: empty text child toast remains untraced.
6. `digitva-bx43`: optional DORIS hints only, discuss first; no mandatory fields.
   `digitva-ve8n`: Expo login idea, discussion only. TanStack Router discussed:
   keep Expo Router for this release; a web-only shell migration needs its own plan.
7. `digitva-5mbn`: remaining web acceptance. Owner authorized disposable staging
   test cases, and chose local Chrome rather than native phone testing.

## Runtime and verification

Staging digitvav3 (i-0b2caee6465bfcac1, ap-south-1, profile digitva, /data/DigitVA)
remains image d7f8ac86e, web expo-web-v2026.10.25.1; no deployment for this work.
Migration head c3f9a1d7e2b4. Preserve APK0.3.10 override
DIGITVA_ANDROID_APK_DIR=/app/private/android-hosted. DORIS_CALL_LOG=1 remains on.
TRN01 stays single-stage, masked_cod_required=False, NQA=False: discuss before
changing. Use scripts/deploy-staging.sh after approved CI; rollback73561675a.

Local HMR /app redirects to root (Expo57 dev base URL behavior). The own profiling
container digitva_web_profile serves old baseline on8053 and current local export
on8054; prefer8051/8054 for current tests. Restore temporary CDP flags and remove
only own profiling container when finished. Never treat HMR timings as production.
Own synthetic fixture: death1cdfce1e-e2ea-41e2-8fae-9265bbe3ac6b,
training draftb869db8f-25f9-45bf-bc88-ccc865e7b4fb; normal profiling draft
1edc4153-3e5b-4f70-8f56-1db4f95b3e0c. Do not alter other testadmin drafts.
Screenshots: /private/tmp/digitva-training-canonical-form.png and
/private/tmp/digitva-current-training-worklist.png. Public cache inventory proves
WHO cached with no WHO script element on home; no API/private data cached.

## Other queued work

Collect Plus/phaseB digitva-hs7e, DORIS demo parity digitva-knh9, screenshot
allowance removal after2026-10-30 digitva-om65, P1s digitva-fvbc/owbz/46xk/342x,
mentor view digitva-oux5, Hindi review remain queued. KEM001 has24 attachment
sync-pending submissions. Consent notices await legal review. Unattached Docker
volumes need explicit inventory/approval before deletion. SmartVA Redis batch
claiming assumes one Celery worker; strengthen before increasing concurrency.
