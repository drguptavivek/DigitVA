# Handoff

Rewrite this file at the end of each session; do not append. Keep it under
about 150 lines. History lives in git log and closed beads (`AGENTS.md`,
"Ending a session").

## Prompt for the next session

> Read `handoff.md`, then `docs/current-state/README.md` before structural
> changes. Start the stack with `make dev` (adds missing secrets to `.env`).
> Add `--profile icd11` for the WHO API (`127.0.0.1:8382`; every `/icd/...`
> call needs the header `API-Version: v2`; Coding Tool `/ct`, Browser
> `/browse`). Log in on port 8051 as the seeded admin in `AGENTS.md`
> (two-step login: email, then password or passkey). `make test-projects`
> seeds TST001 and the test accounts (password in
> `docs/current-state/test-project-tst001.md`); **`test.all@digitva.com`**
> codes, reviews, reports deaths and supervises: TST001 (organization,
> pick-and-choose) plus SADEMO (classical, random). Rebuild the app with
> `npm run export:web` in `mobile/digitva-collect` (Flask serves `dist/` at
> `/app/_expo/` without a restart; a new top-level screen file needs its name in
> `_SPA_ROUTE_ROOTS`, `app/routes/expo_client.py`, guarded by
> `tests/test_expo_client_routes.py`).
> Tests: each agent its own DB (`CREATE DATABASE minerva_test_<name>`), drop it
> when done; writers run targeted tests; one full suite per commit batch:
> `docker compose exec -T -e TEST_DATABASE_URL=postgresql://minerva:minerva@minerva_db_service:5432/<db> minerva_app_service uv run --no-sync python -m pytest tests --ignore=tests/migrations -q -p no:cacheprovider`
> (about 25 min). Mobile: `npx tsc --noEmit` and `npx jest` in
> `mobile/digitva-collect` (90 suites, 1215 tests, 2026-10-12); node checks
> `NODE_PATH=mobile/digitva-collect/node_modules node tests/js/{doris_rules,doris_fields,icd11_picker}_check.mjs`.
> Coding goes to code-writer subagents; reviewers are read-only; shared
> checkout: never stash, build commit lists from `git diff`. Use `bd`; commit in
> the repo's voice and push. Code search: semble first. Owner (2026-10-06): work
> through every actionable bead without stopping to report between items; ask
> only where policy is silent, one plain question.

## Landed this session (2026-10-12): DORIS editor, app shell, test data

- **Rules** in `docs/policy/doris-certificate-rules.md` (V1-V12): fetal card under 1 year,
  hours survived under 7 days, pregnancy card for Female, surgery/autopsy/injury follow-ups by answer, interval and date
  warnings (never block). Server `drop_inapplicable_sections` and Expo `rules.ts` and Flask `doris_rules.js` agree; EstimatedAge is always prefilled.
- **Both editors** use the WHO wording and A-E lines, calendar dates (DOB, injury, surgery have a Date/Year-Month/Year dropdown; death is plain), a clear X per
  question, 3-character auto-search, shadcn-zinc tokens (`docs/current-state/doris-ui-tokens.md`), NQA-style choice rows. Shared picker page
  `app/static/doris_picker_host.html` (iframe on web, WebView on native, theme and query by message).
- **Expo shell**: one `ui` token source (`docs/current-state/ui-consistency-audit.md`), shared theme store without flicker, shared `AppHeader` with
  nav tabs, a phone bottom tab bar, the account menu, a sticky sections bar (`48 y · Female · Raisen, Madhya Pradesh` from `case.survey_district/_state`),
  queue redesign, section and scroll kept on reload, saves keep the open section. `migrations/env.py` no longer mutes loggers (13 old log-test failures).
- **Decided**: no Astryx or UI library (native components, shadcn tokens); district and state are not PII (read through the same visibility as the tables).

## Next, ranked

1. **New beads from this session**: `digitva-bhzx` left rail flashes after clicking Coding (not fixed; capture frames at 375px);
   `digitva-o9xc` native iOS/Android check (WebView picker, date picker, shell); `digitva-x928` server session resurrected by in-flight GETs;
   `digitva-by4y` Flask editor on a real logged-in page (htmx Save, light mode); `digitva-fb3a` real-click checks (header More, drawer,
   picker in a case); `digitva-ff8s` seed ready TST001 cases for pick-and-choose; `digitva-b4qs` open DORIS owner decisions (Not stated rows, year
   warning, age band, small Expo/Flask rule drifts); `digitva-1i5v` transparent logo; `digitva-d3vn` in-app Help; `digitva-4czp` account menu email and roles;
   `digitva-avun` native queue params; `digitva-6vad` seed test gaps.
2. **Role home on the Expo web app** (design `.tasks/2026-10-11-home-jump-page.md`). Committed: role login to `/app/` (`digitva-umc4`), area deaths (`b3pt`), `/app/`
   role router with last-visit resume (`k6i9`), supervision screen (`xqta`), cases for ODK-only VAs in tree projects (`l8y3`; backfill `flask web-intake
   backfill-odk-cases --dry-run` first). Close after a dev check: `test.cho.sc01` -> Collection, `test.mo.phc01` -> Coding with Supervision, `test.cs.dh01` ->
   Supervision, `test.dpm.dh01` -> `/area/`, last-visit resume, a death reporter's new-death page; KPI strip (`qu7x`), My organization (`e7sz`), UI-string
   editor (`fsjz`). Next: `digitva-dt1e` Expo overlay of corrections, `digitva-1g1h` eight more UI languages. DM Expo screen deferred (`digitva-qirs`).
3. **Translation drafts**: dev at `e9h3k6p2s8v4` (429 Hindi drafts; a Hindi reader accepts them in the editor). Other locales need drafts;
   then `digitva-zyf` (DORIS override messages; needs a vendor regeneration).
4. **Owner decisions and checks open**: browser check of web intake uploads (`c8b8edfa`, `digitva-ej1`: record, attach, offline, reconnect, submit,
   logout wipe, 7-day warning); `digitva-0lf7` send WHO the `Id10365` defect (`docs/kb/WHO_VA_2022_Docs/id10365-birth-size-flow.md`) with `Id10304_a`;
   `digitva-r1p` admin click-through of Project Setup (admin-only, owner 2026-10-06); 15 imported translation rows carry a red `<span>` the English
   lacks (Id10013 label hi/kn/ml/kha/or/bn; Id10055 hint mr; hints Id10002/3/4/57 or/ar): admin edits must drop it; per-row links to Access Grants deferred.
5. **Expo session's halves**: `digitva-p6fs.4.3` coder pick/history queues (server paging `dfdfe624`), `p6fs.27`, `p6fs.32`, vendor typecheck
   `digitva-i793`/`surw`, vendor flake `digitva-3jj`, device acceptance `p6fs.5` (audio, touch). `digitva-r0fa` coder component audit
   (`docs/current-state/coder-component-inventory.md`); `digitva-uoe5` final questionnaire/rail visual check; `digitva-ks4m` browser coder experience;
   sign-out repair `digitva-rcte` (client now aborts requests and hard-redirects).
6. **External**: `digitva-fb5` five wrong-wording translations (Odia, Kannada, French, Malayalam readers); `digitva-mdj` WHO reply on SwissTPH/WHO-VA#94;
   `digitva-ddv.5` report to WHO; `digitva-sn1.1.7` real-device passkey; Android `kmk.5`, `kfi`; production `ddv.2`.
7. **Open smaller**: `digitva-4ufj` collaborator Data page toasts "data_manager access is required"; Expo `digitva-gqtp` intake 422 message beside `fields`.
8. **Parked**: `digitva-394` training module, `digitva-roq` SSO, `digitva-d1x` PHMRC, `digitva-1eq` more ML coders, `digitva-zpe` semantic ICD
   search (`docs/planning/icd-semantic-search.md`).

## Deploy notes (unreleased batch)

- No new migration this session. Migrations pending vs production: `c7p3d9k2m5t8`, `d8q4e1h6n3v9`, `e9h3k6p2s8v4` (Hindi drafts), `f2j6n9r4u1x7`
  (death_reporter role, grid flag), `g3k7o1s5w9a2`, `g3k7n1s5v9y2`, `g4k8p2t6x1b5`, `h5m2r8v4z1d9`, `j7n3q9w5y2e8`, `k8p4r2w6y3f1` (ODK-only cases), `m4v8r2t6q1w9`
  (UI string corrections; dev is here); earlier field collection: `d5f1b8a3c6e2`, `e6a2c9d4f1b7` (fails loudly if a user has two open drafts on one case),
  `f7b3d9e1a5c4`, `a8c4e2f6b9d1`, `h2n5q8t1v4w7`, `b4k8m2r6w9x3`. Production DB is at `d3f1a7c92b64`, about 80 behind head.
- Mobile: new dependencies `react-native-webview` and `@react-native-community/datetimepicker` need a native rebuild (prebuild) and the web export
  (`npm run export:web`, never plain `expo export`). Static assets use `?v=` suffixes (DORIS CSS 14, picker JS 4); bump `STATIC_ASSET_VERSION` and the authz
  version (grant cache `_FORMAT` 3): `docker compose exec -T minerva_app_service uv run --no-sync python -c "import os,time,redis; redis.from_url(os.environ['REDIS_URL']).set('digitva_authz:gv', f'reset-{int(time.time())}')"`.
- Restart Celery worker and beat (upload purge daily row; sign-in IP wipe after 210 days). Logs kept 210 days gzipped: check log volume space. Confirm
  the proxy appends `X-Forwarded-For`. Rebuild images (`pyxform`); uploads need HTTPS (WebCrypto); gzip JSON (public COD scheme about 3 MB).
- SmartVA HIV/malaria come from the district preset first (a `low` district stops HIV even if the form flag is True): tell project leads.
- Recreate Redis for `volatile-lru` (drain Celery first); rebuild `app/data/who-va-2022.composed.json` after any `vendor/who-va-2022` change; rebuild the SmartVA image.
- Stored KPI grid days counted Not analysable and Not codeable as a running stock (`digitva-9uqn`): after deploy back up, then `flask kpi
  recount-day-events --dry-run` and without; never `flask kpi backfill` for this.
- Org template (2026-10-12): ASHA loses Fill VA, ANM and MPW gain it for projects populated after that date; HP2026 keeps ASHA ticked until its admin unticks it.
- `AUTHZ_ENFORCE_CONSULTED` is on in production: a non-public request that never consulted authz is refused.

## Owner decisions (recorded in docs/policy)

- Form-options and prefill-policy stay out of `me/access`. DM daily grid keeps one Not analysable total (`bed0` closed; days are a running stock, `9uqn`).
- Visit note on the area table, DM record list and case view, address redacted for non-PII viewers (`96a7`); duplicate hint names who reported (`rrev`).
- Landed earlier: consent/outcome 422, last-word surname (`ddeaa449`); area cards and collaborator links (`663cba6a`); stored grid days (`1569719c`).

## Caveats still true

- `tests/migrations` runs on its own DB, never with the main suite; writers get only the new migration's test plus `test_schema_drift.py` and
  `test_no_app_imports_in_migrations.py`. `make test-projects` seeds through the user import; the SADEMO grant for `test.all` is written directly (the import is organization-only).
- A direct start refused at consent with no identity stores a `refused` submission and closes its case `cancelled` (counts under Not analysable).
- A mentor-institute member who also holds district work needs a second account (guard refuses mixed grants). Admin/DM privileges include In-charges and tree-project PIs.
- Authentication (`digitva-74ni`): web password or passkey for every role, no TOTP; native password then local PIN/biometrics, device tokens carry worker grants only;
  native passkeys deferred (`digitva-uwbg`).
- Narrative/media: real WebM and microphone acceptance remain with `digitva-ej1`; existing ODK deployments need the regenerated XLSForm published. Vendor
  typecheck errors at `digitva-extension.ts:738/747` and date-picker hooks lint at `web.tsx:406` remain.
- A TST001 built before 2026-10-01 needs the one-off level conversion in `docs/current-state/test-project-tst001.md`; dev is converted.
- Tests that confirm or reopen a duplicate queue a real `recompute_kpi_days_for_submission.delay` to the dev Redis broker. The harness keeps one app
  context (`g` and Flask-Login's user carry over; `tests/routes/test_device_api.py` uses `_FreshGClient`); route tests expecting 405 can trip the shared-IP ban
  (bd memory `test-405-ban-shared-ip`).
- Emulator: `DEVICE_PUBLIC_URL=http://10.0.2.2:8051`, `flask devices create-enrolment-code --project <id> --actor <admin>`.
- `scripts/generate-hindi-translation.mjs` writes an inline `ui:` block; re-running it undoes `languages/ui.ts`. `ruff format --check` fails on several
  committed files; only `ruff check` is a gate. "Reset from source" on `WHO_2022_VA_2026` drops the Fresh stillbirth node and ICD-11 rows (snapshot first); rerun
  `flask cod-buckets generate-icd11`. `scheme.icd11_method` still accepts `crosswalk`.
- The WHO choice control hard-codes a 48px row and an 8px gap, and its native build has no theming hook (dark rows are web-only). Browser pane: tool clicks
  and screenshot coordinates differ in scale (CSS px vs screenshot px); overlays mount a moment after a click.
- `stash@{0}` (WIP on `a24ea0a`) is from an old incident; drop it only after someone confirms it holds nothing needed.
