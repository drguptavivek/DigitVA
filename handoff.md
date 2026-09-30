# Handoff

Rewrite this file at the end of each session; do not append. Keep it under
about 150 lines. History lives in git log and closed beads (`AGENTS.md`,
"Ending a session").

## Prompt for the next session

> Read `handoff.md`, then `docs/current-state/README.md` before structural
> changes. Start the stack with `make dev` (adds missing secrets to `.env`;
> plain `docker compose up` skips that and Celery refuses to start). Add
> `--profile icd11` for the WHO API and public DORIS. Log in on port 8051 as
> the seeded admin in `AGENTS.md`: two-step login (email + proof-of-work
> CAPTCHA, then password or passkey); the dev `testadmin` has a passkey, so a
> password sign-in asks for a second factor.
> Tests: `docker compose exec -T -e TEST_DATABASE_URL=postgresql://minerva:minerva@minerva_db_service:5432/minerva_test_pii minerva_app_service uv run --no-sync python -m pytest tests --ignore=tests/migrations -q -p no:cacheprovider`
> (2569 passed before the 2026-09-30 night; not rerun in full since, see
> item 1). One pytest run per test database at a time. Web form package:
> `cd vendor/who-va-2022 && npx vitest run` (786 pass); rebuild the served
> bundle with `cd tooling/who-va-2022 && node build.mjs && node check.mjs`.
> Android app: `mobile/digitva-collect/README.md` (`npx jest`: 66 pass).
> Dev DB head: `b8d2e5f1a7c3`. Use `bd`; commit in the repo's voice and push.

## Next, ranked

1. **Run the full test suite** (command above) and fix anything it finds.
   The overnight session (21 commits, `962f247`..`d059b711`) verified each
   change on targeted runs of up to 390 tests; a full run was refused by
   the permission check after the first commit and was not retried.
2. **Owner browser checks** that needed an admin or supervisor login
   (granting admin to a test account was refused):
   - Setup home (`digitva-r1p`, phases 2-4 built): each hosted panel inside
     the admin shell (Organization tree, Coding scope block, Project Sites
     toggles, Project Forms mapping editor, ODK Connections narrowing,
     Access Grants and Project PIs with the pinned project, Attachments,
     Activity) and People > Devices (create code, QR, list, revoke).
   - `/intake/supervision` as an `interview_supervisor` and as a data manager.
   - Duplicate hint banner and badge on `/intake/` and the form.
3. **Owner decisions** (below), especially `digitva-vzk.12`: a refusal on a
   direct-start interview can never be submitted, web or phone, because the
   minimum identity is asked after consent.
4. `digitva-kmk.5` Android release: signing and distribution (C4), a real
   device for biometric enforcement, QR camera scan, the 5-minute lock with
   the form open. Until then debug builds only, non-production server.
5. `digitva-ej1` attachments (audio, document images) for web intake, then
   on the phone as BLOBs in the encrypted store.
6. `digitva-4in`: DM KPI dashboard shell admits admin/collaborators but its
   APIs are data_manager-only; needs a PII review before opening.
7. Carried over: `digitva-ddv.2` production release (now also every
   migration from `c4e8a2f6b9d3` to `b8d2e5f1a7c3`, and `DEVICE_PUBLIC_URL`
   if devices are used), `digitva-sn1.1.7` real-device passkeys,
   `digitva-cts`, `digitva-hln` owner steps, `digitva-ddv.5`, `digitva-fb5`
   (also: the app's `hi.json` needs a Hindi speaker's review).

## What landed 2026-09-30 (for orientation; details in git log)

- Area dashboard `/area/` for every granted user, project cards at the
  root, staff breakdown behind `should_redact_pii` (`docs/policy/area-dashboard.md`).
- Worklist: the death register is the case; states, audited locked
  transitions, one team worklist page, visits, contact attempts, pause,
  structured address and masked phones, prefill from case and interviewer
  profile, `interview_outcome`, possible-duplicate hint,
  `interview_supervisor` role and supervision page, confirmed duplicates
  excluded from every coding reader (`docs/policy/web-intake.md`,
  `docs/policy/coding-workflow-state-machine.md`).
- Setup home phases 2-4 (panels hosted in locked-project mode).
- Android Path B: device API (`docs/current-state/device-collection-api.md`),
  Expo app with SQLCipher per interviewer, PIN, biometric, auto-lock,
  offline cases; end-to-end run on the emulator passed.
- Web form UI strings follow the locale (`digitva-5mu`).

## Open owner decisions

- `vzk.12` refusal before identity (see item 3).
- Incomplete interview outcomes (partially completed, respondent
  unavailable) route to the existing `consent_refused` workflow state, so DM
  KPIs count them as consent refusals. Alternatives: a new state, or no
  submission row.
- Picking "refused" while consent is yes is refused (422).
- Prefill name split: first word given name, rest surname.
- Possible-duplicate hint shows the other case's id only (per policy).
- Coder personal history keeps confirmed duplicates; DM grid has no "show
  duplicates" toggle.
- Area dashboard: collaborators get no DM links; project cards follow final
  COD authority and can differ from table buckets.
- Android (`docs/policy/field-data-collection.md`, "Path B design",
  proposed): C1 30-day sliding refresh with a 90-day cap, C4 signing,
  package id `org.digitva.collect`, enrolment codes admin-only, PIN 6-16
  digits with a wipe at 5 wrong, wipe only on `session_revoked` (password
  reset, deactivation and a closed project keep the data).
- Setup home stays admin-only.

## Caveats still true

- Tests that confirm or reopen a duplicate now queue a real
  `recompute_kpi_days_for_submission.delay` to the dev Redis broker (the dev
  worker finds no such sid and does nothing); consider eager Celery in tests.
- Test harness keeps one app context: `g` and Flask-Login's cached user
  carry over between requests in a test (`tests/routes/test_device_api.py`
  uses `_FreshGClient`).
- Dev data made overnight: cases SDH-000008 (direct, details pending),
  SDH-000009 (Test Case Alpha, cancel flag pending), SDH-000010 (Test Case
  Beta), one partially completed device upload on HP2026; all HP2026 test
  devices revoked; `test.coder.nc01` grants noted "TEMP area-dashboard
  browser check 2026-09-30" are `deactive`.
- For the emulator: `DEVICE_PUBLIC_URL=http://10.0.2.2:8051` on the exec,
  `flask devices create-enrolment-code --project HP2026 --actor <admin>`;
  the dev AVD is arm64 (`-PreactNativeArchitectures=arm64-v8a`). After a
  vendor change run `npm run vendor:build` in the app.
- `scripts/generate-hindi-translation.mjs` in the vendor package still
  writes an inline `ui:` block; re-running it would undo `languages/ui.ts`.
- ICD-11 signed off 2026-09-29; production still needs its migrations and
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
