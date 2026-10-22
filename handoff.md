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

## State (2026-10-22)

`main` = `origin/main` = `c8a20edf6`. The main checkout holds one large
UNCOMMITTED, tested change set (offline PHC landing). If it is still uncommitted
when you start, the owner has not said go yet. It contains:

- gb8w.2/.3/.4/.5/.8, ke83.10, PII slice 2 (from 2026-10-21) and six migrations:
  `d4f1b8c2a6e9 → e5a2c7b9d3f1 → b9e4f2a7c1d3 → e8c4f2a7b913 → f3a9c6d2e1b7 →
  a7d3e9b2c4f6 → c5e8a1f4b2d9` (dev is at the head; do not reorder).
- Station serves the real composed WHO VA form (byte-identical to the server,
  shared vectors), modules and languages from the signed config (7o4h); Settings:
  Facility details, interview modules, coding mode (locked by project policy).
- Station ICD-11 + DORIS in-process via `digitva-icd11` (r7gr): lazy engine
  (~13 s, ~0.65 GB with `DOTNET_gcServer=0`, set at startup), server-shaped
  DORIS seed, unmasked workspaces go straight to final.
- Offline consent: informant fields always need a granted consent against a
  notice version in the config (owner); `consent_notice_unavailable` when the
  project has none (no project has one yet). Bad records are held back and listed.
- Ingest accepts station coding (lmxr): station registered+active for the
  project, coder on its roster, `coding_mode` = project mode (config carries it;
  null = no station coding, incl. masked projects); icd11_doris held
  `doris_pending`, server re-runs DORIS in the Celery applier.
- Server SmartVA on the Rust engine `smartva-rs` (fy14; `SMARTVA_ENGINE=python`
  rolls back; engine recorded in `va_smartva_runs.run_metadata`); SmartVA
  metadata-column bug fixed (omn4).
- Server ICD-11 + DORIS via the Rust host `digitva-icd11-server` (cr3l) under the
  same service name/port; WHO container kept as profile `icd11-container`.
- ICD-11 licence: citation everywhere ICD-11 is used, URIs kept, DigitVA
  additions labelled, inventory `docs/kb/icd11-licence-inventory.md` (zde8).
- Bundle conformance vectors `tests/fixtures/bundles/vectors/` (gb8w.6/.7).
- `.gitmodules` points `vendor/smartva-analyze` at `drguptavivek/SmartVA-Analyze`.
- `desktop/scripts/package-macos.sh` (trial unsigned DigitVA.app).

End-to-end 2026-10-22: server flow and station flow (register → interview →
SmartVA → ICD-11/DORIS → .dvb → ingest → receipt → applier) both pass on GUJ026.
ICD-10 station flow not run (needs a second station; DEMO01).

## The commit (when the owner says go)

1. Commit and push the `vendor/who-icd11-api` working-tree change
   (`src/bootstrap.rs` second ICD-API.dll pin for linux/amd64,
   `tests/icd11_integration.rs`) to `drguptavivek/who-icd11-api`, then include
   the submodule pointer bump. Without it a fresh clone's ICD service crash-loops.
2. One commit in the repo's voice; build the list from `git diff` and untracked
   files. Exclude `docs/from-server/`, `resource/smartva-phmrc-dataset/`, build
   output (`app/static/expo-client/` is gitignored, `desktop/target/`).
3. `git pull --rebase && git push`; close gb8w.2/.3/.4/.5/.6/.7/.8, ke83.10,
   7o4h, r7gr, lmxr, omn4, r6fj, gmnm, pwh8, gxs0, fy14, cr3l, cfb1, ke83.12,
   zde8 (inventory decisions stay with the owner).
4. Drop test DBs `minerva_test_gb8w*`, `minerva_test_ke8310`,
   `minerva_test_consentfix`, `minerva_test_gapfix`, `minerva_test_stationforms`,
   `minerva_test_smartvafix`, `minerva_test_smartvars`, `minerva_test_lmxr`,
   `minerva_test_gb8wtests`, `minerva_test_zde8`; remove agent worktrees (delete
   the integration worktree's `node_modules` / `vendor/who-va-2022/dist`
   symlinks first). Revoke the e2e test station `87253e1c-…` in GUJ026 if unwanted.

## Ranked next steps

1. `digitva-i3dl` Fable review of all Expo web screens and server paths (owner).
2. `digitva-qfh8` simplest dashboard for district offices and mentoring
   institutions: Fable design, owner approves before build.
3. `digitva-tz7b` station: five DORIS guidance routes (postcoordination offline),
   picker assets in the export, Mac app shipping .NET 10 + WHO data, SIGTERM.
4. `digitva-hs7e` ICD-11 + DORIS on the Expo Android app: NativeAOT library
   proven in-app on an emulator (12/12 parity, ~0.9 GB peak); ~2–3 weeks to
   integrate. Awaiting WHO's reply to the owner's email.
5. Staging deploy (owner's word): PII + bundle signing keys
   (`make ensure-secrets-prod`), image rebuild (now includes `smartva-rs`),
   ICD service image + `icd11_runtime` volume, Expo export, migrations in a
   maintenance window, verified dump; then `digitva-ddfx` Aadhaar sweep.
6. Older: `9ffj`, `fx2c`, `pt0s`, `jkvl`, `athy` web consent UI, `ke83.11` Hindi
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
