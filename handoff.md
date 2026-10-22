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

## State (2026-10-22, late evening)

`main` = `origin/main` = the Training & demo commit on top of `cac5d57a7`
(area dashboard `digitva-qfh8`, client CSRF fixes `ww5u`/`0trb`, one active
allocation per user `igq7`). Migration chain head: `c5e8a1f4b2d9 →
e2b7d4a9c6f1 → a7c3e9f1d5b2 → e3b7d1a9c4f2` (training tables). Dev is at
`a7c3e9f1d5b2`: upgrade it to `e3b7d1a9c4f2` (additive, three empty tables).

Training & demo project `digitva-vd0g` (policy
`docs/policy/training-demo-project.md`): project `TRN01` (WHO 2022 web, English
form, English + Hindi narration, ICD-11 + DORIS, NQA and social autopsy off).
Each training is a retained session: 200 consented `UNSW01NC0101` cases from the
owner's frozen random list (`app/services/training_corpus/UNSW01NC0101.txt`),
pseudonymised (names, addresses, phones, identifiers incl. inside the
narrative; attachments kept original), 20 coder slots of 10. Trainees use their
real accounts; admin adds them (one or several roles, single or bulk "accounts
I created") in Admin > Training sessions; coders need Hindi. First sign-in shows
a role checklist; public `/demo` page; trainer report at
`/data-management/training/<code>` (progress, agreement with the source cause
at WHO VA cause level, CSV); graduation CSV for the main project's users import.
Not live until `DIGITVA_TRAINING_PROJECT_ID=TRN01` is set and `flask
training-demo setup` runs. Rehearsed on a clone of dev: 200 copies, 20x10,
source untouched; only 28 of 228 attachments copied because dev holds only
those files. `flask training-demo check-source` (read-only, counts only) found
no residual original values in the 200.

Drop after this commit: `minerva_test_vd0g`, `minerva_test_vd0g_ui`, the
worktree `.claude/worktrees/demo-training` (branch `feat/demo-training`);
`minerva_test_area`, `minerva_test_alloc` if still present.

## Ranked next steps

1. Training go-live (owner's word): dev upgrade + `DIGITVA_TRAINING_PROJECT_ID=TRN01`
   in `.env`, `flask training-demo setup`, `create-session`; on staging after the
   deploy (step 6), check the session's `attachments_copied` /
   `attachments_not_stored` counts.
2. `digitva-54in` (P1): no self-review guard anywhere in reviewing, though the
   coder help says self-review is impossible. Owner decides: enforce (exempt
   `TRN01`, where the owner allows it) or fix the help text. Build on `igq7`.
3. Remaining Fable review findings: `digitva-owqc` (N+1 in the allocation
   sweep), `digitva-en2g` (admin NQA/SA without scope), `digitva-2s6p` (station
   sign-out, duplicate React key, UTC dates, non-object JSON 500). Review
   gotchas worth deciding: allocation timeout counts from start not last
   activity; coding queue shows the data collector's name; hard-coded English
   in workspace/queue/DORIS.
4. `digitva-tz7b` station: five DORIS guidance routes (postcoordination offline),
   picker assets in the export, Mac app shipping .NET 10 + WHO data, SIGTERM.
5. `digitva-hs7e` ICD-11 + DORIS on the Expo Android app: NativeAOT library
   proven in-app on an emulator (12/12 parity, ~0.9 GB peak); ~2–3 weeks to
   integrate. Awaiting WHO's reply to the owner's email.
6. Staging deploy (owner's word): PII + bundle signing keys
   (`make ensure-secrets-prod`), image rebuild (now includes `smartva-rs`),
   ICD service image + `icd11_runtime` volume, Expo export, migrations in a
   maintenance window, verified dump; then `digitva-ddfx` Aadhaar sweep.
7. Older: `9ffj`, `fx2c`, `pt0s`, `jkvl`, `athy` web consent UI, `ke83.11` Hindi
   for ~100 station strings (English copies in `hi.json`), Tauri app, Android
   release signing and per-ABI APK split, `ke83.9` SmartVA whitepaper fixes.

## Open owner decisions

- `digitva-54in` self-review: enforce outside `TRN01`, or correct the help text.
- Keep `admin_create_user` writing `other.created_by_user_id` (needed for the
  training bulk picker's "accounts I created")? Landed; revert if not wanted.

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
