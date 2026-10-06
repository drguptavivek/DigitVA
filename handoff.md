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
2. **Owner decisions that unlock backend work** (policy is silent; ask one
   at a time):
   - `digitva-t6q` death_reporter role: does a reporter see or edit the
     deaths they registered, may they log contact attempts and visits, and
     does `interviewer` keep Register death? (L: enum, grid flag, migration,
     route gates, `/me/access`.)
   - `digitva-ej1` intake attachments: size and type limits, on-device
     retention, online-only first or with the encrypted offline buffer.
   - `digitva-aek` XLSForm download: source of truth (WHO reference xlsx plus
     per-extension row specs, recommended), pyxform as a check, `form_id`
     kept per project with version bumps.
   - `digitva-vjt` default roles per cadre and `digitva-5op` translation
     suggestions: both marked "not approved, policy first".
   - `digitva-r1p` Project Setup for `project_pi` (now admin-only) and an
     admin click-through of every hosted panel; `digitva-cbn` sign-off of
     the web-form visual pass screenshots (`docs/design/web-form-visual-pass`).
   - People & roles: per-row links to Access Grants are deferred (the API
     has no edit flag); the Setup home panel is admin-only, PIs use
     `/people-roles`.
3. **Expo session's halves** (not this session's files): `digitva-p6fs.4`
   coding and review workspaces (server contract done: `xl43` closed),
   `digitva-xuxk.1` Code now button, `digitva-bhpl.2`, `xpqm.2`, `bqzm.2`,
   `p6fs.27` device re-run (server regression test added), `p6fs.32`,
   vendor typecheck `digitva-i793`/`surw`, vendor flake `digitva-3jj`.
4. **External**: `digitva-fb5` five wrong-wording translations need Odia,
   Kannada, French and Malayalam readers (locales demoted meanwhile);
   `digitva-mdj` waits on WHO's reply to SwissTPH/WHO-VA#94;
   `digitva-ddv.5` report to WHO; `digitva-sn1.1.7` real-device passkey;
   Android `kmk.5`, `kfi`; production `ddv.2`.
5. **Parked proposals**: `digitva-394` training module, `digitva-roq` SSO,
   `digitva-d1x` PHMRC, `digitva-1eq` more ML coders, `digitva-zpe`
   semantic ICD search (design and quality check done,
   `docs/planning/icd-semantic-search.md`; next is the two-stage causes
   prototype).

## Deploy notes (unreleased batch)

- Migrations: `c7p3d9k2m5t8` (`va_users.job_title`, `last_signed_in_at`),
  `d8q4e1h6n3v9` (`map_case_transitions.changes`), `e9h3k6p2s8v4` (Hindi
  note drafts, data only). Earlier field-collection migrations: `d5f1b8a3c6e2`,
  `e6a2c9d4f1b7` (fails loudly if a user has two open drafts on one case:
  check first), `f7b3d9e1a5c4`, `a8c4e2f6b9d1`, `h2n5q8t1v4w7`,
  `b4k8m2r6w9x3`.
- Logs are now kept 210 days, gzipped (840 x 6 h files): check the log
  volume's free space before rollout. Sign-in IPs are wiped daily after 210
  days: restart the Celery worker so the beat row is seeded. Confirm the
  reverse proxy appends or overwrites `X-Forwarded-For`.
- Bump `STATIC_ASSET_VERSION` (coding picker, intake duplicates, People &
  roles, users panel scripts changed) and the authz global version (grant
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

## Open owner decisions

- Fold form-options and prefill-policy into `me/access` (recommended: no).
- Picking "refused" while consent is yes is refused (422).
- Prefill name split: first word given name, rest surname.
- Area dashboard: collaborators get no DM links; project cards follow final
  COD authority and can differ from table buckets.
- Daily KPI grid shows the Not analysable total only.
- The visit note (refusal with no identity) is stored in the submission
  payload only; no supervisor or DM page shows it yet.
- Duplicate hint: `previous_interviewer_name` is who started the interview
  only (the registrant may be a data manager).

## Caveats still true

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
