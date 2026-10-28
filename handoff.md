# Handoff

## Start here

Continue device acceptance and release preparation for Collect/Plus 0.3.12.
Read `AGENTS.md`, `docs/current-state/README.md` and
`docs/current-state/app-release-review.md`. Preserve unrelated
`scripts/loadtest/restore.sh`, orientation files under `docs/manuscript/`,
local tool configs and unreviewed Play artwork. No staging deploy, Play upload
or public offline-engine publication is authorized.
Migration head: `b4e7c2a9d6f3` (additive account-deletion requests).

## Ranked next steps

1. Existing device acceptance: full/interrupted submission (`digitva-5mbn`),
   second-phone backup restore (`5bzf.8`), share sheet, cluster codeinfo
   (`5bzf.3`), revise (`owbz`), blank picker (`e1t9`), small-phone revise
   layout (`46xk`). Include device decommission/re-login and coding receipts.
2. `digitva-5bzf.11` / `.12`: standalone translations and definition pinning;
   related `digitva-tb0j`. Adoption push needs one real dev acceptance check.
3. `digitva-91f2`: review Play artwork/screenshots, final declarations and
   signing continuity. Release information is prepared; CI supports signed
   AAB and downloadable APKs. Public build stays engine-free. Review the
   deployed privacy/deletion paths only after an owner-authorized deploy.
4. WHO call 2026-10-29: private deck
   https://claude.ai/artifact/Y6g1epS6LgVieFQg8mtJcL ; obtain written licence
   2.3/2.4 confirmation in `docs/policy/icd11-local-api-runtime.md`.
5. `digitva-07lz`: measure PostgreSQL test memory; use two workers or serial
   migrations with the current 1 GB database limit. `digitva-uf9j`: bounded
   pages/fair resumption for very large offline upload queues.
6. `digitva-qwvt` AI follow-ups; correction loop `digitva-ydnl`; discuss
   `digitva-bx43` / `digitva-ve8n`; other backlog remains in Beads.

## Open owner decisions

- `digitva-8kud`: SmartVA consent-no row with age data (Python scores, Rust
  refuses); behaviour remains unresolved.
- `digitva-fb5`: 16 translation rows need a speaker; Hindi equity review.
- `digitva-sxg9`: narrative AI and consent item 7 await sign-off/legal review.
- Public page legal review `digitva-gyfj` / `digitva-athy` remains open.

## Caveats still true

- Validation baseline: backend 6750 passed / 6 skipped / 5401 subtests with
  `-n2`; mobile 207 suites / 3025 tests and TypeScript passed. Final telemetry
  bounded-reader/logger checks: 25 tests / 3 subtests passed. One Luna low
  runner owns private DB `minerva_test_merge_20261028`; no competing tests.
  Four-worker migration run exhausted the 1 GB Postgres limit and recovered;
  two-worker full run passed. Do not weaken query ceilings or assertions.
- Plus debug APK is installed on arm64 `emulator-5554`; HMR was verified with
  PID unchanged. Host Metro 8082 maps device 8081; original host 8081 stays
  untouched. Helper: `mobile/digitva-collect/scripts/android-debug-hmr.sh`.
  Actual signed-in clinical flows still need device acceptance above.
- Seven old worktree directories are retired; only main remains. Existing
  branch refs and verified source archives/older phonefix APKs remain in
  `private/worktree-archives/20261028/` (596 MB); keep this private/uncommitted.
- Staging/demo last recorded at `c8b749f7b`, Expo `expo-web-v2026.10.27.1`;
  not reverified here. Staging requires owner go. Demo purge remains off
  pending backup/restore gates (`digitva-77v5.7`).
- `digitva-yacr`: code fix is on main; recheck live KEM001 pending count
  before an owner-authorized repair. No live clinical data repaired here.
- Offline coding requires self-coding AND actual coder/codes access in the
  same project; direct-interview mode is unrelated. Preserve distinct stores,
  explicit adoption, editor/upload leases and matching coding receipts.
- Own-server diagnostics are enabled with Settings off control. Only aggregate
  diagnostics enter analytics; row-level interview/coding timelines stay in
  authorized submission metadata. See telemetry policy.
- WHO server stays official ICD-API 2.6.0/DORIS 1.1.176. Offline redistribution
  remains experimental; no startup-overlap optimization.
- Never run memory/CPU/disk/lock bomb SQL against shared dev Postgres.
- Preserve TRN01 training policy and APK hosting overrides; `DORIS_CALL_LOG=1`.
- `digitva-dv58` vendor save-order/timing failures remain unresolved; the
  midnight-UTC daily-limit test has a known boundary flake. `digitva-5dxf`
  query-budget order sensitivity remains open (current intake check passed).
- `digitva-om65`: screenshot allowance removal after 2026-10-30.
