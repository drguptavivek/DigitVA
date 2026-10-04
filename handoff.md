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
> work CAPTCHA, then password or passkey); dev `testadmin` has no passkey.
> Test project: `flask seed test-project` builds `TST001` (roster in
> `docs/current-state/test-project-tst001.md`; dev/staging only).
> Tests: each agent its own DB (`CREATE DATABASE minerva_test_<name>`), drop
> it when committed; writers run targeted tests only, one dedicated Sonnet
> runner does one full suite per commit:
> `docker compose exec -T -e TEST_DATABASE_URL=postgresql://minerva:minerva@minerva_db_service:5432/minerva_test_<name> minerva_app_service uv run --no-sync python -m pytest tests --ignore=tests/migrations -q -p no:cacheprovider`
> (3334 passed, 5 min, on 2026-10-04). Narrow tasks to Sonnet/Luna, broad
> ones to Opus/Sol (`AGENTS.md`). Dev DB head: `c4e8a1f7d2b3`. This backend
> session commits every backend file, including the Expo client API; the Expo
> session owns `mobile/` and `vendor/` only. Use `bd`; commit in the repo's
> voice and push. Ask the owner one question at a time, in plain terms.

## Next, ranked

1. **Deploy notes for `digitva-5hmc`** (landed): production refuses (403 +
   log) any non-public request that never consulted authz
   (`AUTHZ_ENFORCE_CONSULTED`, off in dev/test). Grants are cached in Redis
   (`digitva_authz:` keys, 5-min TTL). After any migration, restore or raw
   SQL data fix that changes grants, projects, sites, pairs, forms or units,
   bump the global version (every cached entry becomes unreachable):
   `docker compose exec -T minerva_app_service uv run --no-sync python -c
   "import os,time,redis; redis.from_url(os.environ['REDIS_URL']).set('digitva_authz:gv', f'reset-{int(time.time())}')"`
   (or wait 5 minutes). Redis runs allkeys-lru;
   versions are random tokens so eviction never revives an old entry.
2. **Deploy order** `digitva-p6fs.25` (Expo session): the app's terms screen
   and `terms_required` handling must ship before or with the 9an9 backend;
   a current app build shows `terms_required` as an error.
3. Run `tests/migrations` on its own DB, never in the same run as the main
   suite (it breaks setup there).
4. `digitva-04u4` job title per person (shown in the DM exact lookup when it
   exists). `digitva-ci8` record every web sign-in.
5. `digitva-v1sq` coding workflow follow-ups (recode list RECODE scope,
   `ready_for_coding` source, area overview EXPLAIN, open-submission repair
   gate, KPI cache vs pair status). Intake now has its own grant-only
   `web_intake_service.reachable_unit_ids` (yw11); `project_wide_grant_exists`
   is gone.
6. Expo (`digitva-p6fs`): auth contract for the app is
   `docs/current-state/authentication-and-onboarding.md`. Device sign-in
   takes email or mobile; `user.email` may be null. `p6fs.4` coding/review
   workspaces, `p6fs.5` device acceptance. Device case contract (p6fs.24,
   on main): `docs/current-state/device-collection-api.md` -- bootstrap
   `projects`, `project_id` required, `/cases` = browser list per project,
   `/cases/<id>` detail with full contacts; the Expo app must adopt it
   (p6fs.22/.23). Device `/units` takes no site, so with a site grant on any
   site of the project it offers the whole tree and the create at another
   site may refuse the unit (403); an optional `site_id` there would need
   the owner (the browser picker already sends one, `digitva-yw11`).
7. Older queue: `digitva-nk1` People & roles page, `digitva-dea` log
   retention, `digitva-t6q` death_reporter role, `digitva-kfi` Android
   rewrite, `digitva-35x` duplicate hint, `digitva-kmk.5` Android release,
   `digitva-ej1` intake attachments, `digitva-ddv.2` production release,
   `digitva-sn1.1.7`, `digitva-cts`, `digitva-hln`, `digitva-ddv.5`,
   `digitva-fb5`.

## Production release notes (this session)

- Production DB is at `d3f1a7c92b64` (2026-09-17), about 77 migrations
  behind head and before org units exist; the release is one large upgrade.
- Migrations to run (backup first): `c4e8a1f7d2b3` (tester output flag, after the others), `e2b7c4d9a1f3` (In-charge = site_pi at
  a unit), `f3a8c1d6e2b9` (mobile sign-in, codes table, email nullable),
  `b7d4e9f2a6c1` (partial date of birth).
- Every password is now server-generated; verification links sent before the
  deploy stop working (resend). Mail must work: verification, reset and
  profile generate need it; `MAIL_DEBUG` is pinned off.
- Demo coding/reviewing is open only to admins and people with an active
  coder, reviewer or coding_tester grant.
- Dev has a test account "Test ASHA Mobile" (mobile 9000000111, landing page
  set to coder by mistake); remove or fix.
- Drop finished test DBs: `minerva_test_runner`, `minerva_test_fix`.
- Review 10 (`digitva-4lv4`): a coder or reviewer whose allocation leaves
  their scope is refused (403, API returns null), not released; the row
  clears with the 1-hour stale release. Coder history cache can show a
  rerouted case for up to 300 s. Admin may now sync a form on a deactivated
  pair. A site data manager's coder roster now shows only its own pairs'
  coders.

## Proposals parked (plan only, need owner discussion)

- `digitva-394` training module: separate `/training/` blueprint, same
  user DB, practice interviews in `trn_*` tables only, trainer role on a
  mentor unit, certification gates real intake. Cases: the 6 cause-chain
  examples in the 2026 PCVA manual plus WHO ICD-11 mortality training
  material (owner has WHO permission to adapt). Depends on the mentor-institute stages above.
- `digitva-vjt` default roles per cadre, pre-ticked at grant time.
- `digitva-5op` district team views translations and suggests changes.

## Open owner decisions

- Picking "refused" while consent is yes is refused (422).
- Prefill name split: first word given name, rest surname.
- Coder personal history keeps confirmed duplicates; DM grid has no "show
  duplicates" toggle.
- Area dashboard: collaborators get no DM links; project cards follow final
  COD authority and can differ from table buckets.
- Daily KPI grid shows the Not analysable total only; a per-day reason split
  would need a stored column and migration.
- The visit note (refusal with no identity) is stored in the submission
  payload only; no supervisor or DM page shows it yet.

## Caveats still true

- A direct start refused at consent with no identity stores a `refused` submission
  and closes its case `cancelled` (the identity constraint allows no other
  closed state without one); it counts under Not analysable in DM KPIs.
- A mentor-institute member who also holds district work needs a second
  account (guard refuses mixed grants).
- Privileged (second factor) = admin or anyone holding data-manager powers,
  which includes In-charges and tree-project PIs (`digitva-9an9` item 3).
- Deploy: bump `STATIC_ASSET_VERSION` with `74c114e1`; `reviewing.start` is
  now POST with CSRF, and a cached old reviewer dashboard script gets 405.
- A TST001 built before 2026-10-01 (level codes `dh`/`sc`) needs the one-off
  level conversion in `docs/current-state/test-project-tst001.md` before the
  seed reruns; dev is converted.
- `access_grants.html` `ROLE_LABEL` has no `interviewer` entry.
- Tests that confirm or reopen a duplicate queue a real
  `recompute_kpi_days_for_submission.delay` to the dev Redis broker.
- Test harness keeps one app context: `g` and Flask-Login's cached user
  carry over between requests (`tests/routes/test_device_api.py` uses
  `_FreshGClient`).
- Emulator: `DEVICE_PUBLIC_URL=http://10.0.2.2:8051` on the exec,
  `flask devices create-enrolment-code --project <id> --actor <admin>`; the
  dev AVD is arm64. After a vendor change run `npm run vendor:build`.
- `scripts/generate-hindi-translation.mjs` still writes an inline `ui:`
  block; re-running it would undo `languages/ui.ts`.
- ICD-11 production still needs its migrations and
  `flask analytics refresh-submission-mv`.
- Dev passkeys need `WEBAUTHN_RP_ID=localhost` / `WEBAUTHN_ORIGIN` pinned in
  `docker-compose.override.yml`; dev `.env` carries the production
  `MAIL_BASE_URL`.
- `ruff format --check` fails on several committed files; only `ruff check`
  is a gate. Admin panels opened by URL lack Bootstrap JS; use the shell.
- "Reset from source" on `WHO_2022_VA_2026` drops the Fresh stillbirth node
  and ICD-11 rows; a snapshot is taken first (`digitva-tet`).
- Flaky: `digitva-ssi`, `digitva-3jj`, `digitva-19l`.
- `stash@{0}` (WIP on `a24ea0a`) is from an old incident; drop it only after
  someone confirms it holds nothing needed.
