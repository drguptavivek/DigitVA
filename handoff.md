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
> (2569 passed at the start of 2026-09-30; not rerun in full since, see
> caveats). One pytest run per test database at a time. Web form package:
> `cd vendor/who-va-2022 && npx vitest run` (782 pass); rebuild the served
> bundle with `cd tooling/who-va-2022 && node build.mjs && node check.mjs`.
> Android app: `mobile/digitva-collect/README.md`. Use `bd`; commit in the
> repo's voice and push.

## Next, ranked

1. **Run the full test suite** (command above). The 2026-09-30 overnight
   session landed 16 commits on targeted runs only; its full-suite run was
   blocked by a permission check after the first commit.
2. **Owner browser checks** the overnight session could not do without an
   admin or supervisor login (granting admin to a test account was refused):
   - Setup home (`digitva-r1p`): every hosted panel inside the admin shell
     (Structure/Organization tree, Coding scope block, Project Sites toggles,
     Project Forms mapping editor, ODK Connections narrowing, Access Grants
     and Project PIs with the pinned project, Attachments, Activity), and the
     People > Devices card (create code, QR, revoke).
   - Supervision page `/intake/supervision` as an `interview_supervisor`
     and as a data manager.
3. `digitva-kmk` Android app (design and API contract in
   `.tasks/2026-09-30-android-collection-app.md`; policy baseline in
   `docs/policy/field-data-collection.md`, "Path B design", marked
   proposed). Built: server device API (`kmk.1`), app phase 2a (`kmk.2`).
   Next: `kmk.6` hardening (may be in the tree or landed; check git log),
   then `kmk.3` phase 2b security (SQLCipher per interviewer, PIN,
   biometric, auto-lock, FLAG_SECURE, wipes), `kmk.4` offline cases and
   attachments, `kmk.5` release. **No real interviews before 2b.**
4. `digitva-vzk` worklist: phases 2-5 and 7 built, supervisor role built,
   prefill and interview outcome built. Left: `vzk.11` automatic duplicate
   check (phase 6), `vzk.10` duplicate-exclusion follow-ups (stored daily KPI
   rows not recomputed on confirm/reopen; coverage guard's regex misses
   `VaSubmissionWorkflowEvent`; missing indexes for the area staff view).
5. `digitva-4in`: DM KPI dashboard shell admits admin/collaborators but its
   APIs are data_manager-only (empty data); needs a PII review to open.
6. Carried over: `digitva-ddv.2` production release (now also needs every
   migration from `c4e8a2f6b9d3` to `d7a3c9e1f5b2` and later, plus
   `DEVICE_PUBLIC_URL` if devices are used), `digitva-sn1.1.7` real-device
   passkeys, `digitva-5mu`, `digitva-cts`, `digitva-hln` owner steps,
   `digitva-ej1`, `digitva-ddv.5`, `digitva-fb5`.

## Open owner decisions (from 2026-09-30)

- **Interview outcome routing** (`vzk.2`): partially completed and
  respondent unavailable submissions route to the existing `consent_refused`
  workflow state (the only non-coding state that also blocks SmartVA), so DM
  KPIs count them as consent refusals. Alternatives: a new state, or no
  submission row for incomplete interviews. The browser page cannot submit
  an incomplete interview yet; the device API can.
- Interviewer picking "refused" while consent is yes is refused (422).
- Name split for prefill: first word given name, rest surname.
- Area dashboard: collaborators get no links to the DM dashboard; project
  cards follow final-COD authority and can differ from the table buckets.
- Coder personal history keeps confirmed duplicates; DM grid has no "show
  duplicates" toggle.
- Android: C1 (30-day sliding refresh, 90-day cap proposed), C4 signing and
  distribution, package id `org.digitva.collect`, who may create enrolment
  codes (admin only now), PIN length/wipe threshold (6 digits / 5).
- Setup home stays admin-only; opening it to project PIs is undecided.

## Caveats still true

- ICD-11 signed off 2026-09-29 (migrations `d3a9c5e1f7b2`, `a7c3e9f1b5d2`);
  production still needs them and `flask analytics refresh-submission-mv`.
- Dev test data created overnight: cases SDH-000008 (direct, details
  pending), SDH-000009 (Test Case Alpha, in progress, cancel flag pending),
  SDH-000010 (Test Case Beta, not reachable); `test.coder.nc01` holds
  temporary grants noted "TEMP area-dashboard browser check 2026-09-30"
  (collaborator on unit SDH and on UNSW01, interviewer on DH01), set to
  `deactive` at the end of the session.
- Dev passkeys need `WEBAUTHN_RP_ID=localhost` / `WEBAUTHN_ORIGIN` pinned
  in `docker-compose.override.yml`; dev `.env` carries the production
  `MAIL_BASE_URL`. For the emulator set `DEVICE_PUBLIC_URL=http://10.0.2.2:8051`.
- `ruff format --check` fails on several committed files; only `ruff check`
  is a gate.
- Admin panels opened directly by URL lack Bootstrap JS; use the shell.
- "Reset from source" on `WHO_2022_VA_2026` drops the Fresh stillbirth node
  and ICD-11 rows; a snapshot is taken first (`digitva-tet`).
- Flaky: `digitva-ssi`, `digitva-3jj`, `digitva-19l`.
- `stash@{0}` (WIP on `a24ea0a`) is from an old incident; drop it only after
  someone confirms it holds nothing needed.
- Test harness: the suite keeps one app context, so `g` and Flask-Login's
  cached user carry over between requests in one test
  (`tests/routes/test_device_api.py` uses a `_FreshGClient` for this).
