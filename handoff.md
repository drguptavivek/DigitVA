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
> CAPTCHA, then password or passkey); dev `testadmin` has no passkey.
> Test project: `flask seed test-project` builds `TST001` (DH > CHC > 2
> PHC-AAM > 6 SC-AAM, 24 users in every role, password `Aiims@123`; roster in
> `docs/current-state/test-project-tst001.md`). It is idempotent and
> dev/staging only.
> Tests: `docker compose exec -T -e TEST_DATABASE_URL=postgresql://minerva:minerva@minerva_db_service:5432/minerva_test_pii minerva_app_service uv run --no-sync python -m pytest tests --ignore=tests/migrations -q -p no:cacheprovider`
> (2842 passed on 2026-10-01; `test_spelling_fold.py` can fail in a full run and passes alone). One pytest run per test database at a time.
> Web form package: `cd vendor/who-va-2022 && npx vitest run` (791 pass);
> rebuild the served bundle with `cd tooling/who-va-2022 && node build.mjs &&
> node check.mjs`. Android app: `mobile/digitva-collect/README.md`
> (`npx jest`: 66 pass). Dev DB head: `c4a9e7d2b6f1`. Use `bd`; commit in the
> repo's voice and push. Owner wants second opinions from a read-only Fable
> agent (`bd memories advisor`). Ask the owner one question at a time, in
> plain terms.

## Next, ranked

1. `digitva-eiw` + `digitva-djd` mentor institutes and unit-scoped roles.
   Owner design is final (full text in both beads' notes). Stage 1 landed:
   `mas_mentor_institute`, `map_mentor_institute_org_unit` (to depth-1
   district units), `map_mentor_institute_user`, `flask mentor-institute ...`,
   grant guard `check_mentor_grant` (member: org_unit grant inside an attached
   district's subtree, roles coder/reviewer/coding_tester/collaborator_pii
   only), `site_pi` refused at org_unit (CHECK + validator; classical projects
   keep it at project_site), policy baselines written. Next, give each to a
   fresh code-writer with its whole scope:
   - **Stage 1b** (with these review fixes): a district `data_manager` may
     give grants to staff of institutes attached to their district (still
     inside the guard); new `mentor_institute` admin creates/removes only
     their institute's staff accounts, never grants (an institute cannot
     widen its own access); platform admin creates institutes and attaches
     districts. Fixes: `add_member` warning undercounts active mentor-role
     grants outside the attached subtree; `DEFAULT_TYPICAL_ROLES[("district",
     "CS")]` in `organization_service.py:136` still lists `site_pi`; guard runs
     before the permission check in admin grant create (info leak); CLI passes
     no actor (audit `actor=-`); add tests for the import path, the data
     manager create route and the warning count. No admin UI yet.
   - **Stage 2**: `data_manager` and `coding_tester` at unit scope cover the
     grant's subtree on every surface, incl. KPI/analytics, unrouted queue and
     sync (owner: no hidden pages). Plan from the 2026-10-01 Plan agent:
     per-submission predicate on `VaSubmissions.org_unit_id`; unit-only DM in
     `is_data_manager` and `has_data_manager_submission_access(org_unit_id=)`;
     DM grid via `scope_unit_ids_for_roles`; coding-tester bypass at
     `coder_workflow_service.py:~719` and `_within_coding_org_scope` must
     become unit-scoped; one `_coding_waivers` helper replacing four copies of
     the PI/tester waiver; `_get_granted_va_forms` is project-wide for unit
     grants (fail-open). Follow-ups `digitva-d5s` (waivers key on site_id
     only) and `digitva-6qy` (query cost).
   - Mentors are excluded from district staff headcounts and listed apart
     (rule in `docs/policy/people-and-roles-page.md`; `mentors_for_unit`
     exists, no UI).
2. `digitva-6zq` verify: an active demo-training project may make
   `is_coder`/`is_reviewer`/`is_coding_tester` true for every user
   (`_get_granted_va_forms` unions demo forms). Policy opens demo projects
   for coding only. Write the test first.
3. `digitva-ci8` record every web sign-in: `signed_in` security event with
   method and client IP (trusted proxy header only), IP wiped after 210
   days by a beat task, plus `va_users.last_signed_in_at` (additive
   migration) set on web sign-in and device session open.
4. `digitva-nk1` People & roles page, also the access audit page. Policy is
   complete with owner decisions: `docs/policy/people-and-roles-page.md`
   (status proposed; mark active when building). Blocked by `ci8` for the
   audit columns; also make every grant write set `created_by_user_id`.
5. `digitva-dea` keep log files 210 days (now 14; `va_logger.py`
   `LOG_BACKUP_COUNT`). Dev is ~1.5 GB per 14 days: compress rotated files,
   check production disk first. Database audit records stay permanent.
6. `digitva-t6q` `death_reporter` role (ANM, MPW, ASHA register deaths,
   never interview): policy text for the owner, then code.
7. **Owner browser checks**: org page "District reference model" card and
   "Populate district defaults" (`/admin/panels/organization?project_id=TST001`),
   `/help/user-roles`, Setup home panels (`digitva-r1p`), People > Devices,
   `/intake/supervision` (as `test.mo.phc01`), duplicate hint on `/intake/`.
   TST001 now supplies supervisor, DM and CHO accounts.
8. `digitva-kfi` Android rewrite, all owner-decided 2026-10-01: policy text
   first (`docs/policy/field-data-collection.md`, then mark Path B accepted),
   then the app. 6-digit PIN; timed lock after 5 wrong, no wrong-PIN wipe;
   wipe only on `session_revoked`; server issues one data key per scope
   (district) at sign-in, kept in the Keystore, so the PIN is only the unlock
   gate and a PIN reset (after password + second factor) keeps the interviews;
   one shared store per scope (interviewers in a scope see each other's
   interviews, unsynced included); data managers at any unit level create
   enrolment codes for staff under their unit (depends on `djd`); 30-day
   sliding refresh with 90-day cap; self-signed release key held and backed up
   by the owner (C4 accepted).
   `digitva-35x` duplicate hint, owner-decided: show name, date of death,
   village, age, sex, respondent name and previous worker only for cases in
   the viewer's own scope, never the ID or anything of an out-of-scope case;
   supervisors at CHC/PHC/DH deactivate or reactivate an interview with a
   logged reason. Policy baseline first.
9. `digitva-kmk.5` Android release (signing now decided, see `kfi`; real device biometric, QR
   scan, 5-minute lock); debug builds only until then.
10. `digitva-ej1` attachments for web intake, then on the phone.
11. `digitva-4in` DM KPI dashboard shell vs data_manager-only APIs (PII
    review).
12. Carried over: `digitva-ddv.2` production release (every migration from
    `c4e8a2f6b9d3` to `b8d2e5f1a7c3`, `DEVICE_PUBLIC_URL` if devices are
    used), `digitva-sn1.1.7`, `digitva-cts`, `digitva-hln`, `digitva-ddv.5`,
    `digitva-fb5` (and `hi.json` needs a Hindi speaker's review).

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
- Data managers cannot give unit grants (refused by design) until stage 1b,
  which allows only mentor-institute grants; CHO interviewer grants come from
  an admin or project PI. A mentor-institute member who also holds district
  work needs a second account (guard refuses mixed grants).
- A TST001 built before 2026-10-01 (level codes `dh`/`sc`) needs the one-off
  level conversion in `docs/current-state/test-project-tst001.md` before the
  seed reruns; dev is converted.
- ANM/MPW in TST001 have no grant and fall through to `/coding/` (no
  `death_reporter` yet).
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
