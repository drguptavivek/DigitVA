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
> (3055 passed on 2026-10-03, one flaky admin test `digitva-bgyr`; `test_spelling_fold.py` can fail in a full run and passes alone). One pytest run per test database at a time.
> Web form package: `cd vendor/who-va-2022 && npx vitest run` (791 pass);
> rebuild the served bundle with `cd tooling/who-va-2022 && node build.mjs &&
> node check.mjs`. Android app: `mobile/digitva-collect/README.md`
> (`npx jest`: 66 pass). Dev DB head: `e2b7c4d9a1f3`. Use `bd`; commit in the
> repo's voice and push. Owner wants second opinions from a read-only Fable
> agent (`bd memories advisor`). Ask the owner one question at a time, in
> plain terms.

## Next, ranked

1. `digitva-0wc` **authorization module** (owner priority). One module with a
   small interface, `can(user, action, submission)` and `scope_filter(user,
   action)` (SQL predicate for lists), over the existing grants (RBAC with
   scoped grants; no schema change except the In-charge CHECK below). Every
   screen, partial, attachment and API calls it. Input: the audit of how each
   screen decides access today, `.tasks/digitva-0wc-access-matrix-current.md`
   (F1, F6, F9 fixed in `74c114e1`; F2-F5, F7, F8, F10-F19 open). Progress:
   policy written (`4fcd984e`); **design done**:
   `.tasks/digitva-0wc-design.md` (package `app/services/authz/`: `can`,
   `require`, `scope_filter`, `can_grant`; stages 0-7). **Stage 0
   committed** (module, 236-row matrix, single-source and shadow tests, lh1h
   fix; no callers yet). **Stage 1 (coding)
   committed**. **Stage 2
   committed** (viewing, attachments, events, partials, viewers open a case,
   area view = blp; plain viewers get no attachments, no DORIS prefill, a
   certificate without AdministrativeData; read-only partial allowlist).
   **Stage 3 committed**
   (DM pages, APIs, KPIs, analytics, COD buckets, unrouted queue for every
   DM of a tree project, pin, project_pi as DM on tree projects, admin DM
   view, 38lp, 4in; DM and viewer reach stops at a deactivated
   project-site). **Stage 4 (reviewing)
   committed** (reviewer dashboard, start, allocation, saves, NQA/SO/ICD/DORIS
   reviewer checks on REVIEW; view wider than review, F7; reviewer
   rendering by reviewer reach; area link). **Stage 5 committed**
   (migration `e2b7c4d9a1f3`, applied to dev: site_pi at org_unit = the
   In-charge, with every DM power, intake supervision and the unit site PI
   report; project_pi supervises tree projects). **Stage 6 implemented, in
   verification** (grant writes through can_grant/grant_list_filter; DMs,
   in-charges and project_pi create grants per the district rule; unit
   writers see managed people without contact details). Open from stage 6:
   `digitva-i0zb` (owner: how a unit DM adds an existing account),
   `digitva-xd1q` (400-before-403 oracle). Dev DB head: `e2b7c4d9a1f3`.
   A parallel Expo-client session (`digitva-p6fs`) has uncommitted work
   in this checkout (client API/static host, mobile/, app/__init__.py,
   additive draft locale fields and tests): commit only stage files by name.
   Expo preview `/app/`: English/Hindi UI, shared dark/light form theme,
   left sidebar/phone rail, login handoff and server collection drafts; coding/review still link to existing workspaces (.4).
   Expo: 78 Jest tests, TypeScript and separate web/Android JS exports pass.
   Browser synthetic TST001 registration, Hindi save/resume and theme checked;
   left rail tested at 391px without overflow, drawer Escape/focus return checked.
   Focused backend: 73 passed, 20 subtests; latest broad run: 3068 passed,
   33 failures confined to unfinished stage-6 grant-write tests. Device/APK
   and full browser submission acceptance remain `digitva-p6fs.5`. `digitva-bibk`: reference model still
   suggests interview_supervisor for in-charges. `digitva-8126`: stale migration
   test. `digitva-26pg`: unit DM
   KPI/analytics/COD counts still include deactivated-pair forms. Known: through the widened DM gate, project_pi on a tree
   project reaches the stage-6 grant pages, which read old helpers (empty,
   writes refused) until stage 6. Carry into later
   stages: admin unrouted queue = tree projects only (stage 3); TR01 cutoff
   and language in pick validators; Recode list should also apply RECODE
   scope; remove `ready_for_coding` source in `mark_coder_step1_saved`; EXPLAIN the
   area overview ORDER BY for project-wide grants; gate the open-submission
   repair job on SYNC_SUBMISSION (stage 2).
   Demo projects stay open to coding and reviewing (owner). Update this line as each stage
   lands. Owner decisions 2026-10-02 (all in the bead notes, written into
   `docs/policy/access-control-model.md` / `organization-model.md`, marked
   "Implementation tracked in digitva-0wc"):
   - **In-charge** at every level of a district project (District = CMO or
     Civil Surgeon, Block = SMO, PHC = MO): the `site_pi` role allowed at
     `org_unit` (migration lifting the `role_scope` CHECK; mentors still
     refused). All data manager powers in their area, plus field-work
     supervision, every screen with PII, and creating data managers at their
     own level and below.
   - **project_pi in district projects**: every screen, acts as data manager
     and supervisor across the project; codes/reviews only with a grant.
   - **Data manager grants, district projects only**: create DMs strictly
     below their level; create interviewer, coder, reviewer, coding_tester,
     viewers anywhere in their subtree. Site projects keep today's rule.
   - **Viewers** (`collaborator`, `collaborator_pii`, so mentors) open one
     submission read-only in scope; plain viewer redacted.
   - **Unrouted queue**: every DM of the project sees it, routes only into
     their own subtree (owner accepted the cross-district visibility).
   - Absorbs `digitva-blp` (area view partials refuse coders/reviewers;
     confirmed in the browser), `digitva-lh1h` (DM KPI and DM scope match
     bare site ids across projects), `digitva-38lp`, `digitva-h67s`.
   - Plain-language guide: `docs/policy/roles-explained.md` with the D2
     diagram `docs/policy/diagrams/district-roles.d2` (render:
     `d2 --layout elk <d2> <svg>`; d2 installed via Homebrew). Rewrite
     `/help/user-roles` from it when the module lands.
2. `digitva-6zq` verify: an active demo-training project may make
   `is_coder`/`is_reviewer`/`is_coding_tester` true for every user
   (`_get_granted_va_forms` unions demo forms). Policy opens demo projects
   for coding only. Write the test first.
3. `digitva-ci8` record every web sign-in: `signed_in` security event with
   method and client IP (trusted proxy header only), IP wiped after 210
   days by a beat task, plus `va_users.last_signed_in_at` (additive
   migration) set on web sign-in and device session open.
3b. `digitva-04u4` job title per person: free text, display only, public
   (not personal data, visible to every role), distinct from cadre; additive
   column on `va_users`. Policy line first.
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
- Built today (until `digitva-0wc`): data managers give unit grants only to
  mentor-institute staff (inside the mentor guard); CHO interviewer grants
  come from an admin or project PI. Policy now states the wider 2026-10-02
  rules. A
  mentor-institute member who also holds district work needs a second
  account (guard refuses mixed grants).
- Deploy: bump `STATIC_ASSET_VERSION` with `74c114e1`; `reviewing.start` is
  now POST with CSRF, and a cached old reviewer dashboard script gets 405.
- Unit-only DMs now count as privileged: second-factor enforcement applies to
  them (TST001 DPM/BPM) once `AUTH_FACTOR_ENFORCE_FROM` is set.
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
