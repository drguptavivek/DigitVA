# Handoff

## Start here

Read `AGENTS.md`, `docs/current-state/README.md` and the relevant policy.
Owner focus: DigitVA web app, training and Android. Product branding is DigitVA.
Preserve unrelated `scripts/loadtest/restore.sh` and orientation files.
Use Docker for commands. Owner authorized local Docker web exports for diagnosis
on 2026-10-25; published releases/APKs remain CI-built. HMR: localhost:8051.
Owner accepts roughly 1.5 s slower cold direct interview; do not implement the
proposed startup-overlap optimization. Owner's DORIS target stays 1.1.176 pending
an official WHO image approved for upgrade. Preserve the immutable WHO image
digest; verify the runtime DLL version rather than trusting the Compose comment.

## Ranked next steps

1. `digitva-5mbn`: remaining web acceptance and a separately approved
   staging window. Follow docs/current-state/split-production-deploy.md's
   matched web release sequence. Published expo-web-v2026.10.25.2 from source
   1892f085ddb5ca41ca6ee1c7d0449ef0470f8b9d; CI40200511607 all jobs passed.
   App tarball SHA256:
   63c9db9b987498a9c85c061278e46ebdbdb3c7093c319820349ae41b571a45f0.
   Both archive checksums, matching WHO/app metadata and strict profile verified
   after download. digitva-9f8n closed. Compose pins remain .1; next commit app
   release pins, then build the server image of that pin commit. Do not deploy the web
   source SHA with old pins and expect new browser code. Remaining acceptance:
   physical device, complete interview submission and mid-transfer interruption;
   the blocked-chunk retry and offline edit/reconnect/save/reload passed Chrome.
2. `digitva-e1t9`: intermittent ICD picker backdrop without panel; logs did not
   prove a root cause. `digitva-lo67`: empty text child toast remains untraced.
3. `digitva-dv58`: WHO vendor Docker serial Vitest933/935; draft-save-order
   failure repeats on unchanged8b79f0b5 baseline; navigation passes both isolated
   reruns. Build/typecheck/entrypoint regressions pass. No assertions skipped.
4. `digitva-bx43`: optional DORIS hints only, discuss first; no mandatory fields.
   `digitva-ve8n`: Expo login idea, discussion only. TanStack Router discussed:
   keep Expo Router this release; web-only shell migration needs its own plan.

## Runtime and release caveats

Staging digitvav3 (i-0b2caee6465bfcac1, ap-south-1, profile digitva, /data/DigitVA)
last verified image d7f8ac86e, web expo-web-v2026.10.25.1; no deployment for this
work. Recheck live state before a future deployment. Migration head at acceptance
c3f9a1d7e2b4. Preserve APK0.3.10 override
DIGITVA_ANDROID_APK_DIR=/app/private/android-hosted. DORIS_CALL_LOG=1 remains on.
TRN01: single-stage, masked_cod_required=False, NQA=False, standard intake welcome
and seeded DPDP consent enabled (`docs/policy/training-demo-project.md`); discuss
before changing. Three-tier Inside vs Outside health-system PII model, 7-level
default hierarchy (`State / Province` at depth 1), and parent-unit deactivation
choice are live in policy and backend (`docs/policy/access-control-model.md`,
`docs/policy/organization-model.md`).
Use scripts/deploy-staging.sh with the full CI-built server SHA and its printed
rollback. Previous rollback reference73561675a must be refreshed from live host.

The public WHO package is a verified CI build input. Browser WHO chunks remain
part of the complete matched app archive, lazy-loaded or warmed after eligible
login. Never deploy the WHO archive as an independent frontend or cache APIs/
answers/private definitions. Preserve canonical clinical rules and native entrypoints.
Updates wait for old tabs to close; don't force worker activation mid-interview.
Closed work: digitva-k2s1, digitva-k2s1.1, digitva-bc56, digitva-ydgv, digitva-idvp,
digitva-eiym, digitva-ewa5, digitva-2yo5, digitva-0v8f, digitva-9qoq.
Evidence and limits are in `docs/current-state/expo-connectivity-profile.md`;
history is in CHANGELOG.md.

Local HMR /app redirects to root (Expo57 dev base URL behavior). The old8053
comparison export is obsolete; use8051 HMR for development. Profiling containers
are temporary and removed at closeout. Local traces and downloaded CI artifacts
remain under /private/tmp/digitva-web-profile-20261025 and
/private/tmp/digitva-paired-ci-40198746587. No HMR timing claims.
Owned synthetic fixture: death1cdfce1e-e2ea-41e2-8fae-9265bbe3ac6b,
training draftb869db8f-25f9-45bf-bc88-ccc865e7b4fb (test age changed to99);
normal profiling draft1edc4153-3e5b-4f70-8f56-1db4f95b3e0c.
Do not alter other testadmin drafts. Screenshot of exact CI artifact:
/private/tmp/digitva-ci-training-recovery.png. Saved answers survived reload;
Save and leave returned to /app/training/interview without identifier warnings.

## Other queued work

Collect Plus/phaseB digitva-hs7e, DORIS demo parity digitva-knh9, screenshot
allowance removal after2026-10-30 digitva-om65, P1s digitva-fvbc/owbz/46xk/342x,
mentor view digitva-oux5, Hindi review remain queued. KEM001 has24 attachment
sync-pending submissions. Consent notices await legal review. Unattached Docker
volumes need explicit inventory/approval before deletion. SmartVA Redis batch
claiming assumes one Celery worker; strengthen before increasing concurrency.
