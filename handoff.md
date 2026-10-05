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
> (3637 passed, 6 min, on 2026-10-05 with the app container at 1 GB; at the old 756 MB a full run was OOM-killed, exit 137; `test_odk_site_mappings` flakes under load; recreate `minerva_test_runner` if a run dies). Narrow tasks to Sonnet/Luna, broad
> ones to Opus/Sol (`AGENTS.md`). Dev DB head: `b4k8m2r6w9x3`. Coding goes to Sonnet code-writers (owner, 2026-10-04); code must be fast and efficient (bd memory `perf-first`). This backend
> session commits every backend file, including the Expo client API; the Expo
> session owns `mobile/` and `vendor/` only. Use `bd`; commit in the repo's
> voice and push. Ask the owner one question at a time, in plain terms.
> Code search: use semble first (`mcp__semble__search`; load it with
> ToolSearch if deferred) for "where does X happen" questions, and tell
> agents to as well; grep only for exact names or every occurrence. Owner
> wants a report on whether semble found things grep would not.
> trace-mcp is broken (binary missing at `~/.trace-mcp/bin/trace-mcp`).

## Next, ranked

1. **One `/api/v1` for every client** (epic `digitva-ntct`; policy
   `docs/policy/api-v1.md`, route reference `docs/current-state/api-v1.md`).
   Done on the backend for sign-in and intake: either credential on every
   route; `auth/*` (replies carry `access`), `me/access`, `me/terms`,
   `intake/*`, `organization/<p>/units|form-options`,
   `instruments/.../translations`; `/api/v1/device/*`,
   `/api/v1/client/bootstrap` and `/intake/api/*` are gone. The Expo app is
   on it (`digitva-ntct.1` closed). Remaining, in order:
   a. **Field collection integrity: done** (server 2026-10-04/05, app by
      the Expo session). Closed: `2bxa`, `latk`, `xz83`, `xuf9`, `6pwq`,
      `hdrv`, `w5jw`. Still open: `digitva-bhpl` until the app's revise
      screen `digitva-bhpl.2` lands (contract `expo-handoff.md` section 5);
      `digitva-jcll` (DM dashboard and KPIs count send-backs as ODK upstream
      changes; View Changes fails on a sent-back case). Added 2026-10-05:
      `digitva-xpqm` the coder gets the interviewer's last completed version
      (reverses the "phone completion wins" default; app half `xpqm.2`,
      handoff section 8) and `digitva-bqzm` a supervisor chooses between two
      interviewers' complete interviews, switch-back allowed (app half
      `bqzm.2`, section 9); follow-up `digitva-9kqk` (second own browser
      draft on a won case is a copy, not a correction). Owner: nothing is
      deployed, so no legacy fallbacks (bd memory `no-legacy-fallbacks`). Self-coding `digitva-xuxk` is done on the server
      (design `.tasks/2026-10-05-self-coding.md`; owner to confirm the
      defaults listed there; app half `digitva-xuxk.1`, contract
      `expo-handoff.md` section 10, waits on the app coding workspace
      `p6fs.4`; `xuxk` stays open until it lands). Owner confirmed three of
      the four defaults on 2026-10-05 (the fourth was replaced by `xpqm`) (recorded in `docs/policy/web-intake.md`
      and `docs/policy/interview-revisions.md`). Manual check owed: the
      browser form's stale-tab 409 (`draft_stale`) and the worklist
      other-draft badge were not driven in a browser (proof-of-work CAPTCHA).
   b. `digitva-xl43` coding and review workspace API: case content by
      category and the Step 1 / final COD steps are server HTML partials
      (`va_form.renderpartial`) today, so no app can code or review;
      unblocks `digitva-p6fs.4`.
   c. `digitva-ey38` `code` on every remaining `/api/v1` error
      (data-management, va/nqa+so, area, cod-buckets, ...) and a contract
      review of those blueprints.
   Open owner question: fold form-options and prefill-policy into
   `me/access` (recommended: no). Admin stays browser-only (`/admin/api/*`).
2. **Deploy notes.** This field-collection release: migrations
   `d5f1b8a3c6e2`, `e6a2c9d4f1b7` (fails loudly if a user has two open
   drafts on one case: check first), `f7b3d9e1a5c4`, `a8c4e2f6b9d1`,
   `h2n5q8t1v4w7`. Recreate Redis to pick up `volatile-lru` (drain the
   Celery queues first; `CONFIG GET maxmemory-policy`). Restart the Celery
   worker so the notification purge beat row is seeded. Rebuild
   `app/data/who-va-2022.composed.json` (`cd tooling/who-va-2022 && npm run
   build:composed-instrument`) after any `vendor/who-va-2022` change.
   Self-coding: migration `b4k8m2r6w9x3`; bump `STATIC_ASSET_VERSION`
   (intake form, worklist and coder dashboard scripts changed) and the authz
   global version below (grant cache `_FORMAT` is now 2).
   SmartVA (`0ba9833b`): rebuild the image (font cache prebuilt, smaller
   context), restart the Celery worker and beat (beat seeds the 30 s
   `sweep_smartva_pending`); `SMARTVA_CHARTS=1` only for debugging. Web and
   app interviews already sitting in `smartva_pending` are picked up by the
   first sweep. Docker Desktop's disk was at 91% on 2026-10-05; a build
   filled it once and stopped dev Postgres (build cache prune recovered it). The
   app build with `expo-handoff.md` section 1 must ship with this server.
   Earlier notes: Bump `STATIC_ASSET_VERSION` with the API release (cached
   old intake scripts call removed routes). `digitva-5hmc`: production
   refuses any non-public request that never consulted authz
   (`AUTHZ_ENFORCE_CONSULTED`); grants are cached in Redis
   (`digitva_authz:` keys, 5-min TTL); after any migration, restore or raw
   SQL fix that changes grants, projects, sites, pairs, forms or units, bump
   the global version:
   `docker compose exec -T minerva_app_service uv run --no-sync python -c
   "import os,time,redis; redis.from_url(os.environ['REDIS_URL']).set('digitva_authz:gv', f'reset-{int(time.time())}')"`.
   `digitva-p6fs.25`: the app's terms screen ships before or with the 9an9
   backend.
3. Run `tests/migrations` on its own DB, never in the same run as the main
   suite (it breaks setup there).
4. `digitva-04u4` job title per person (shown in the DM exact lookup when it
   exists). `digitva-ci8` record every web sign-in.
5. `digitva-v1sq` coding workflow follow-ups (recode list RECODE scope,
   `ready_for_coding` source, area overview EXPLAIN, open-submission repair
   gate, KPI cache vs pair status).
6. Expo (`digitva-p6fs`): `p6fs.4` coding/review workspaces, `p6fs.5` device
   acceptance; both use the one `/api/v1` contract (`ad02` is landed). A
   signed-in worker's unit tree, not the site, is the scope
   (`docs/policy/web-intake.md`).
7. Older queue: `digitva-nk1` People & roles page, `digitva-dea` log
   retention, `digitva-t6q` death_reporter role, `digitva-kfi` Android
   rewrite, `digitva-35x` duplicate hint, `digitva-kmk.5` Android release,
   `digitva-ej1` intake attachments, `digitva-ddv.2` production release,
   `digitva-sn1.1.7`, `digitva-cts`, `digitva-hln`, `digitva-ddv.5`,
   `digitva-fb5`, flaky `test_odk_site_mappings`.

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
- `minerva_test_runner` is the full-suite DB; drop `minerva_test_fix` and any
  `minerva_test_<bead>` left after its commit.
- Review 10 behaviour changes: see closed bead `digitva-4lv4`.

## Proposals parked (plan only, need owner discussion)

`digitva-394` training module (`/training/`, `trn_*` tables, trainer role,
certification gates intake), `digitva-vjt` default roles per cadre,
`digitva-5op` district team suggests translation changes.

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
