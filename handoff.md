# Handoff

## Start here

Read `AGENTS.md`, `docs/current-state/README.md`, then the policy for the piece
you take: `docs/policy/offline-api-contract.md`,
`docs/policy/offline-bundle-and-transfer.md`, `docs/policy/pii-envelope-format.md`,
`docs/policy/offline-phc-desktop-edition.md`, `docs/policy/icd11-local-api-runtime.md`,
`docs/policy/pii-encryption-at-rest.md` (+ `docs/kb/pii-slice-*.md`),
`docs/policy/death-registration-identifiers.md`. Stage explicit paths (`grep -Ev`
filters, check the staged list), never stash, one full parallel run (`-n 4`) on a
database of your own, one test database per concurrent agent. **The owner decides
commit timing: hold all commits until the owner says go, then one commit.** The
owner owns `vendor/who-va-2022`. Owners may edit accounts and translations: reread
live state. Staging Hindi 40 in_review is the owner's live state: never overwrite.

## State (2026-10-22, evening)

`main` = `origin/main` = `9a92932a5` (offline PHC landing `3dbd60206` + beads).
The main checkout holds a second UNCOMMITTED, tested batch (full run green:
pytest -n 4 5493 passed; Jest 1783; tsc; cargo workspace; single head
`a7c3e9f1d5b2`). Commit only on the owner's go:

- `digitva-qfh8` /area/ extended and simplified for district offices and
  mentors (period filter, pending backlog, SmartVA failed, medians, top causes
  with n<5 suppression and hide under 20 coded, stations, CSV of aggregates;
  `collaborator` allowed for mentors). Design record
  `.tasks/2026-10-22-area-dashboard-district-mentor.md`. Migration
  `e2b7d4a9c6f1` (index `ix_va_death_register_va_sid`). Closes the area half of
  `yeg3.27`.
- `digitva-ww5u` + `digitva-0trb` (Fable review): client keeps the newest
  CSRF token from every response, retries once on `csrf_failed`; bootstrap
  identity kept when only the token changed; access reload only on
  `terms_required` / `project_forbidden` / codeless 403; interview saves and
  flushes before a same-account reset.
- `digitva-igq7`: one active coding and one active reviewing allocation per
  user (partial unique index `uq_va_allocations_active_to_for`, migration
  `a7c3e9f1d5b2`, dedupe keeps the newest); allocators resume on a refused
  insert.
- `docs/current-state/data-model.md` lines for both indexes.

Dev is upgraded to `a7c3e9f1d5b2`. After the commit, tell the "Full Training
and Demo module" session the head id: it chains its `e3b7d1a9c4f2` onto it
(its work lives only in `.claude/worktrees/demo-training`; leave that worktree,
`minerva_test_vd0g*`, `minerva_test_drift`, `minerva_test_training_sessions`).
Drop `minerva_test_area`, `minerva_test_alloc` after the commit.

## Ranked next steps

1. Remaining Fable review findings: `digitva-owqc` (N+1 in the allocation
   sweep), `digitva-en2g` (admin NQA/SA without scope), `digitva-2s6p` (station
   sign-out, duplicate React key, UTC dates, non-object JSON 500). Review
   gotchas worth deciding: allocation timeout counts from start not last
   activity; coding queue shows the data collector's name; hard-coded English
   in workspace/queue/DORIS.
2. `digitva-tz7b` station: five DORIS guidance routes (postcoordination offline),
   picker assets in the export, Mac app shipping .NET 10 + WHO data, SIGTERM.
3. `digitva-hs7e` ICD-11 + DORIS on the Expo Android app: NativeAOT library
   proven in-app on an emulator (12/12 parity, ~0.9 GB peak); ~2–3 weeks to
   integrate. Awaiting WHO's reply to the owner's email.
4. Staging deploy (owner's word): PII + bundle signing keys
   (`make ensure-secrets-prod`), image rebuild (now includes `smartva-rs`),
   ICD service image + `icd11_runtime` volume, Expo export, migrations in a
   maintenance window, verified dump; then `digitva-ddfx` Aadhaar sweep.
5. Older: `9ffj`, `fx2c`, `pt0s`, `jkvl`, `athy` web consent UI, `ke83.11` Hindi
   for ~100 station strings (English copies in `hi.json`), Tauri app, Android
   release signing and per-ABI APK split, `ke83.9` SmartVA whitepaper fixes.

## Open owner decisions

- ICD-11 licence inventory (`docs/kb/icd11-licence-inventory.md`): crosswalks
  and their public serving, WHO map tables in the repo, labelling policy
  columns, citation on bucket exports.
- Server accepts a bundle made under an expired (but issued) station config;
  refuse it? Related: grace period for superseded configs' rosters.
- Server ICD host uses more memory than the WHO container (535–680 MB idle,
  1.13 GB peak, 2 GB cap); `DOTNET_gcServer=0` trades 2–3x latency under load.
- Masked projects get no station coding (no Step 1 on the station).
- Revoke dialog second confirm; parents' names consent coverage; retention and
  legal review (Aadhaar vault, DPDP); seal `Id10021`?

## Decisions already made (do not reopen)

Supervision only in the Deaths tab; admin is a PII holder; Aadhaar last 3
digits; phones encrypted but shown; key files outside the repo; offline
informant fields always need consent; station coding mode = project mode;
station coding gate = registered station + rostered coder; Python is the rule
authority (Rust/TS follow via shared vectors); server runs SmartVA and ICD-11 on
Rust; ICD service stays a separate container (one engine copy for all workers);
station runs the engine in-process.

## Caveats

- Station needs `DIGITVA_ICD11_BUNDLE_DIR` (and .NET 10) for ICD-11 + DORIS;
  `/tmp/icdapi_portable` works on this Mac. After the engine loads, the station
  ignores SIGTERM: stop it with SIGKILL.
- Fixture generators: `python -m tests.test_station_config_fixture --write` hits
  a pre-existing circular import; run it through `runpy` after `import app.utils`
  (see the command in the station-config fixture test history) or the env-gated
  pytest for bundle vectors (`DIGITVA_WRITE_BUNDLE_VECTORS=1`).
- `cargo` is at `~/.cargo/bin` only. Other people's stations may run on
  18420/18421; use another port.
- `resource/smartva-phmrc-dataset/` (49 MB) is untracked and not part of this
  work. Dev `.env` holds throwaway keys under `private/`.
