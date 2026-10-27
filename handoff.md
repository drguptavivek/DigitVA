# Handoff

## Start here

Read `AGENTS.md`, `docs/current-state/README.md` and the relevant policy.
Owner focus: DigitVA web app, training, Android (Collect) and Collect Plus
standalone. Product branding is DigitVA. Use Docker for commands. HMR:
localhost:8051. Preserve unrelated `scripts/loadtest/restore.sh` and the
orientation files under `docs/manuscript/`.
Owner's DORIS target stays 1.1.176 pending an official
WHO image; preserve the immutable WHO image digest and verify the runtime DLL
version, not the Compose comment. Owner accepts about 1.5 s slower cold direct
interview; do not implement the startup-overlap optimization.
Migration head: `f3d9b5c7a2e4` (run `flask db heads` before adding one).

## Ranked next steps

1. **Staging is on `17e43e4d8`** (deployed 2026-10-27): AI reader set up
   (`digitva-weiq`), Vertex `gemini-3.5-flash` working, `PUBLIC_*` set, contact
   form live. Still open: legal review of the public pages (`digitva-gyfj`,
   `digitva-athy`); a first real contact-form submission and AI question by
   the owner. Staging's checkout still has the old `deploy-server.sh`, so on
   the next deploy that changes `uv.lock` remove `digitva_minerva_venv` by hand
   first. Request Vertex quota for `gemini-3.5-flash-lite` in `asia-south1`
   before switching to it. The demo portal is not deployed; its public keys
   are `DEMO_PUBLIC_*` in `/data/digitva-demo.env`.
2. Collect Plus next: `digitva-5bzf.11` (bundled translations) and `.12`
   (pin definition version); related `digitva-tb0j`. S5b landed but is
   tested only against a mocked network: check one adoption push against
   dev. Audio on tree projects can stall at the file step (draft endpoint
   needs a unit).
3. **Device checks** (Collect Plus and phone fixes, none done on hardware):
   - encrypted backup restored on a second phone (`digitva-5bzf.8`);
   - the share sheet saving export and backup;
   - the cluster codeinfo on the device engine (`digitva-5bzf.3`);
   - the `digitva-owbz` revise reference on 0.3.10;
   - `digitva-e1t9` on staging after the web export;
   - the `digitva-46xk` revise layout on a small phone.
4. `digitva-5mbn`: remaining web acceptance and a separately approved staging
   window; follow `docs/current-state/split-production-deploy.md`. Published
   expo-web-v2026.10.25.2 (source 1892f085d); Compose pins remain .1: commit
   release pins, then build the server image of that pin commit. Remaining:
   physical device, complete interview submission, mid-transfer interruption.
5. `digitva-fb5`: label-code fix, 16 rows need a speaker (owner decision below).
   `digitva-e1t9` (blank ICD picker, retry added, root cause unproven),
   `digitva-owbz` (partial), `digitva-lo67` (empty text child toast untraced).
6. WHO ICD-11 call 2026-10-29: deck https://claude.ai/artifact/Y6g1epS6LgVieFQg8mtJcL
   (private; share before the call). Ask WHO for written licence 2.3/2.4
   confirmation; record in `docs/policy/icd11-local-api-runtime.md`. Deck
   reflects the 2026-10-27 allowability changes.
7. `digitva-qwvt` AI questions follow-ups (policy
   `docs/policy/ai-analytics-questions.md`): `ai_interviewer` from
   `va_data_collector`; level-type column; senility ICD breakdown inside
   "Cause of death unknown"; intake source dimension; equity dimensions
   (gender, district first); ECharts for Chart.js; question-bank marking.
   Gemini needs Vertex settings in `.env`.
8. Correction loop `digitva-ydnl` (policy only), `digitva-bx43` (DORIS
   hints, discuss first), `digitva-ve8n` (discussion only), `digitva-hs7e`,
   `digitva-knh9`, `digitva-342x`, `digitva-oux5`, Hindi review.
9. Policies recorded, built later (each may need a migration): `digitva-r9lk`
    equity web extension beyond S1, `digitva-v1oi` geography codes and boundary
    packs, `digitva-6383` per-project AI keys, `digitva-lep4` ODK credentials to
    the post-quantum envelope, `digitva-1835` DHS links, `digitva-fixy` and
    `.1` interview support edge model, `digitva-13gs` EAVA and InterVA5,
    `digitva-sxg9` / `.1` narrative AI and document vision-language model,
    `digitva-2476` DuckDB in the next version.

## Open owner decisions

- Case-list "Pending Coding" wording.
- S5a interpretations (`digitva-5bzf.6`): forced review skips the recode
  window; an unknown bundle hash is refused.
- `digitva-8kud`: SmartVA consent-"no" row with age data (Python scores it,
  Rust refuses); which behaviour is right.
- `digitva-fb5`: 16 translation rows need a speaker to decide.
- Machine Hindi for the equity questions: accept as is or review first.
- `digitva-sxg9` narrative AI policy draft and consent item 7 await sign-off
  and legal review.

## Approved, not started

Collect Plus translations, pinning (above); epic decisions 1 to 8
accepted 2026-10-27 (`digitva-5bzf` notes). Screenshot allowance removal
after 2026-10-30 (`digitva-om65`).

## Caveats still true

- **Staging freeze:** nothing from 2026-10-27 is deployed. Staging digitvav3
  (i-0b2caee6465bfcac1, ap-south-1, profile digitva, /data/DigitVA) last
  verified image d7f8ac86e, web expo-web-v2026.10.25.1. Recheck live state
  before deploying; use `scripts/deploy-staging.sh` with the full CI-built
  server SHA and its printed rollback (refresh the old rollback from the host).
- **Before staging:**
  - the migrating DB user needs CREATEROLE and `SET ON PARAMETER
    temp_file_limit`;
  - set `TYPESENSE_API_KEY` and run `flask ai-search reindex`;
  - drain, or expect the "unregistered task" log for, queued
    `recompute_kpi_days_for_submission` messages (the task is deleted);
  - run `digitva-77ti` (read-only count of saved finals on chapter 22 or
    `KD3B*`) before migrations `b8d4f2a6c1e9` and `c5e8a2f4b7d1`.
- **Dev rule:** never run memory, disk or lock bomb SQL against dev Postgres.
- **Flaky test:** `test_org_unit_coding_gates.py::test_daily_limit_counted_once_across_gated_subtree`
  failed once at the midnight-UTC boundary; check how it computes "today".
- Keep APK 0.3.10 override `DIGITVA_ANDROID_APK_DIR=/app/private/android-hosted`; `DORIS_CALL_LOG=1` stays on.
- TRN01: single-stage, masked_cod_required=False, NQA=False, standard intake
  welcome and seeded DPDP consent enabled
  (`docs/policy/training-demo-project.md`); discuss before changing.
- The public WHO package is a CI build input; never deploy the WHO archive as
  an independent frontend or cache APIs, answers or private definitions.
  Updates wait for old tabs to close; do not force worker activation.
- `digitva-dv58`: WHO vendor Docker Vitest failures (draft-save-order repeats
  on an unchanged baseline); no assertions skipped.
- KEM001: 24 attachment sync-pending submissions. Unattached Docker volumes
  need approval before deletion. SmartVA Redis claiming assumes one worker.
