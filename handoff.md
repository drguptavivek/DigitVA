# Handoff

Rewrite this file at the end of each session; do not append. Keep it under
about 150 lines. History lives in git log and closed beads (`AGENTS.md`,
"Ending a session").

## Prompt for the next session

> Read `handoff.md`, then `docs/current-state/README.md` before structural
> changes. Start the stack with `make dev` (adds missing secrets to `.env`;
> plain `docker compose up` skips that and Celery refuses to start). Add
> `--profile icd11` for the WHO API and public DORIS. Log in on port 8051 as
> the seeded admin in `AGENTS.md`: two-step login (email or mobile + proof-of-
> work CAPTCHA, then password or passkey); dev `testadmin` asks for a second
> factor. TST001 roster logins (e.g. `test.pi@digitva.com`) are in
> `docs/current-state/test-project-tst001.md` (`flask seed test-project`).
> Tests: each agent its own DB (`CREATE DATABASE minerva_test_<name>`), drop
> it when committed; writers run targeted tests only; one full suite per
> commit batch:
> `docker compose exec -T -e TEST_DATABASE_URL=postgresql://minerva:minerva@minerva_db_service:5432/minerva_test_runner minerva_app_service uv run --no-sync python -m pytest tests --ignore=tests/migrations -q -p no:cacheprovider`
> (4025 passed, 7.5 min, 2026-10-06). Coding goes to Sonnet code-writers
> (owner, 2026-10-04); code must be fast (bd memory `perf-first`). Shared
> checkout: the Expo session owns `mobile/` and `vendor/`; this backend
> session commits every other file. Build commit lists with
> `grep -Ev '^(mobile|vendor)/'` and check the staged list; never stash. When
> one file carries two beads' hunks, stage by hunk (`git apply --cached
> --unidiff-zero`) and check the staged result reads right. Use `bd`; commit
> in the repo's voice and push. Code search: semble first. trace-mcp is
> broken (binary missing). Owner (2026-10-06): work through every actionable
> bead without stopping to report between items; ask only where policy is
> silent, one plain question.

## Next, ranked

1. **Translation drafts**: dev is at `e9h3k6p2s8v4` (429 Hindi machine
   drafts of guidance and constraint messages, `689bb139`; a Hindi reader
   accepts them in the translations editor). Other locales still need
   drafts; then `digitva-zyf` (DORIS override messages; needs a vendor
   regeneration by the Expo session).
2. **Owner decisions and checks still open**:
   - Browser check owed for web intake uploads (`c8b8edfa`, `digitva-ej1`):
     record, attach, go offline, reconnect, submit; the logout wipe; the
     7-day warning. Only server and node tests ran.
   - `digitva-0lf7` send WHO the `Id10365` birth-size constraint defect
     (`docs/kb/WHO_VA_2022_Docs/id10365-birth-size-flow.md`) with `Id10304_a`.
   - `digitva-r1p` admin click-through of every Project Setup panel (needs
     the admin's second factor); Setup stays admin-only (owner 2026-10-06).
   - 15 imported translation rows carry a red `<span>` the English lacks
     (Id10013 label in hi, kn, ml, kha, or, bn; Id10055 hint mr; hints of
     Id10002/3/4/57 in or and ar): admin edits must drop the span, since
     `update_string` now refuses markup the English lacks.
   - People & roles: per-row links to Access Grants are deferred (the API
     has no edit flag); PIs use `/people-roles`.
3. **Expo session's halves** (not this session's files): `digitva-p6fs.4.3`
   coder pick/history queues (server paging built `dfdfe624`), `p6fs.27`
   device re-run (server regression test added), `p6fs.32`, vendor
   typecheck `digitva-i793`/`surw`, vendor flake `digitva-3jj`, device
   acceptance `p6fs.5`.
   Browser coder experience (`digitva-ks4m`) has responsive browser QA;
   physical-device acceptance remains under `p6fs.5`, including real audio
   playback and touch gestures. Demo browser QA did not submit assessments,
   private notes or SmartVA runs.
4. **External**: `digitva-fb5` five wrong-wording translations need Odia,
   Kannada, French and Malayalam readers (locales demoted meanwhile);
   `digitva-mdj` waits on WHO's reply to SwissTPH/WHO-VA#94;
   `digitva-ddv.5` report to WHO; `digitva-sn1.1.7` real-device passkey;
   Android `kmk.5`, `kfi`; production `ddv.2`.
5. **Owner decisions of 2026-10-09** (below): `0wm9`, `8xbo`, `1zdi`,
   `dhmc`, `bed0`, `96a7`, `rrev`; Expo `gqtp`.
6. **Parked proposals**: `digitva-394` training module, `digitva-roq` SSO,
   `digitva-d1x` PHMRC, `digitva-1eq` more ML coders, `digitva-zpe`
   semantic ICD search (design and quality check done,
   `docs/planning/icd-semantic-search.md`; next is the two-stage causes
   prototype).

## Deploy notes (unreleased batch)

- Migrations: `c7p3d9k2m5t8` (`va_users.job_title`, `last_signed_in_at`),
  `d8q4e1h6n3v9` (`map_case_transitions.changes`), `e9h3k6p2s8v4` (Hindi
  note drafts, data only), `f2j6n9r4u1x7` (death_reporter role, grid flag,
  reporter list index), `g3k7o1s5w9a2` (grid default roles),
  `g3k7n1s5v9y2` (translation suggestions), `g4k8p2t6x1b5` (web intake
  attachments), `h5m2r8v4z1d9` (index for the daily upload purge). Dev is
  at `h5m2r8v4z1d9`. Restart the Celery worker and beat so the "Web intake
  upload purge — daily" row is seeded (30-day rule, `b29d4c59`). Earlier field-collection migrations: `d5f1b8a3c6e2`,
  `e6a2c9d4f1b7` (fails loudly if a user has two open drafts on one case:
  check first), `f7b3d9e1a5c4`, `a8c4e2f6b9d1`, `h2n5q8t1v4w7`,
  `b4k8m2r6w9x3`.
- Logs are now kept 210 days, gzipped (840 x 6 h files): check the log
  volume's free space before rollout. Sign-in IPs are wiped daily after 210
  days: restart the Celery worker so the beat row is seeded. Confirm the
  reverse proxy appends or overwrites `X-Forwarded-For`.
- Rebuild the images (`pyxform` dev dependency). Web intake uploads need
  HTTPS (WebCrypto); `sox` is already in the image.
- Bump `STATIC_ASSET_VERSION` (coding picker, intake form and attachment
  buffer, intake duplicates, People & roles, grant forms, organization grid,
  translations scripts changed) and the authz global version (grant
  cache `_FORMAT` is 3):
  `docker compose exec -T minerva_app_service uv run --no-sync python -c
  "import os,time,redis; redis.from_url(os.environ['REDIS_URL']).set('digitva_authz:gv', f'reset-{int(time.time())}')"`.
- SmartVA HIV/malaria now come from the district preset first: a project
  whose district says `low` stops running HIV even if the form flag says
  True. Tell project leads.
- The public COD scheme JSON is about 3 MB uncached: make sure the proxy
  gzips JSON.
- Recreate Redis for `volatile-lru` (drain Celery queues first); rebuild
  `app/data/who-va-2022.composed.json` after any `vendor/who-va-2022` change;
  rebuild the SmartVA image and restart worker and beat. The app build with
  `expo-handoff.md` section 1 ships with this server.
- `AUTHZ_ENFORCE_CONSULTED` is on in production: a non-public request that
  never consulted authz is refused.

## Production release notes

- Production DB is at `d3f1a7c92b64` (2026-09-17), about 80 migrations
  behind head and before org units exist; the release is one large upgrade
  (backup first).
- Every password is now server-generated; verification links sent before the
  deploy stop working (resend). Mail must work.
- Dev has a test account "Test ASHA Mobile" (mobile 9000000111, landing page
  set to coder by mistake); remove or fix.
- Review 10 behaviour changes: see closed bead `digitva-4lv4`.

## Owner decisions taken 2026-10-09 (in docs/policy, not built)

- Form-options and prefill-policy stay out of `me/access` (no code).
- Outcome "refused" with consent yes: specific 422 naming both questions,
  shown beside them: server `digitva-0wm9`, Expo `digitva-gqtp`. Today a
  valid form there is silently stored `completed`.
- Name split: last word is the surname `digitva-8xbo`.
- Area dashboard: collaborators get DM links `digitva-1zdi`; two labelled
  cards plus a Final COD column `digitva-dhmc`; visit-note count column.
- DM daily grid: Not analysable total plus optional reason columns
  `digitva-bed0`.
- Visit note shown on the area table, the DM record list and the case view,
  address redacted for non-PII viewers `digitva-96a7`.
- Duplicate hint also names who reported the death `digitva-rrev`.

## Caveats still true

- Narrative/media follow-up: real saved WebM and microphone acceptance remain with `digitva-ej1`. Newly generated project XLSForms share the typed-narrative override; existing ODK deployments require publication of the regenerated form. Help `/help/data-collection` and `docs/policy/digitva-who-form-overrides.md` document the WHO2026/ICMR/UNSW comparison; UNSW NC01 source workbook remains unavailable, and the downloadable matrix currently measures Web composition rather than independently generated XLSForms. Vendor typecheck errors at `digitva-extension.ts:738/747` and date-picker hooks lint at `web.tsx:406` remain.
- `tests/migrations` runs on its own DB, never with the main suite; give
  writers only the new migration's test plus `test_schema_drift.py` and
  `test_no_app_imports_in_migrations.py`.
- A direct start refused at consent with no identity stores a `refused`
  submission and closes its case `cancelled`; it counts under Not analysable.
- A mentor-institute member who also holds district work needs a second
  account (guard refuses mixed grants).
- Privileged (second factor) = admin or anyone holding data-manager powers,
  including In-charges and tree-project PIs.
- A TST001 built before 2026-10-01 needs the one-off level conversion in
  `docs/current-state/test-project-tst001.md`; dev is converted.
- Tests that confirm or reopen a duplicate queue a real
  `recompute_kpi_days_for_submission.delay` to the dev Redis broker.
- Test harness keeps one app context: `g` and Flask-Login's cached user
  carry over between requests (`tests/routes/test_device_api.py` uses
  `_FreshGClient`). Route tests that expect 405 can trip the shared-IP ban
  (bd memory `test-405-ban-shared-ip`).
- Emulator: `DEVICE_PUBLIC_URL=http://10.0.2.2:8051`,
  `flask devices create-enrolment-code --project <id> --actor <admin>`.
- `scripts/generate-hindi-translation.mjs` still writes an inline `ui:`
  block; re-running it would undo `languages/ui.ts`.
- `ruff format --check` fails on several committed files; only `ruff check`
  is a gate.
- "Reset from source" on `WHO_2022_VA_2026` drops the Fresh stillbirth node
  and ICD-11 rows (a snapshot is taken first); run
  `flask cod-buckets generate-icd11` again after a whole-scheme reset.
- `scheme.icd11_method` still accepts `crosswalk` though nothing uses it.
- `docs/audits/11-authz-cross-app.md` is untracked and not from this
  session; leave it to its author.
- `stash@{0}` (WIP on `a24ea0a`) is from an old incident; drop it only after
  someone confirms it holds nothing needed.
