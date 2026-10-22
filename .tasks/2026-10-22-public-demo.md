# Public demo mode

Status: design approved by the owner 2026-10-22; not started (phase 1, this record and the policy, is digitva-77v5.1)
Priority: P1
Created: 2026-10-22
Epic: digitva-77v5. Children: .1 policy and design, .2 backend core, .3 report and download, .4 dashboard, .5 Expo web link and Android path, .6 purge, .7 deployment.

## Goal

Anyone can sign up with a username and password, collect VAs (web and
digitva-collect) into a public demo project, code and review their own
submissions, see a cause-of-death report, download their own responses, and
see a public aggregate dashboard. Policy: `docs/policy/public-demo.md`.

## Context

- Separate deployment, same image, own Redis and Postgres, shared ICD-11/DORIS
  container (`docker-compose.yml`, `icd_api_service`). Host under
  `causeofdeathindia.com` so `mobile/digitva-collect/src/enrolment.ts`
  (`ENROLMENT_DOMAIN`) accepts it.
- One flag, `PUBLIC_DEMO_ENABLED`, default off. Off means: blueprint routes
  not registered (404), no demo enrolment endpoint, purge task a no-op,
  grant guard inert, `flask public-demo` commands refuse.
- Real VA data never lives on the demo database.

## Facts relied on (checked 2026-10-22)

- `va_users` has `CheckConstraint("email IS NOT NULL OR mobile_login IS NOT NULL", name="email_or_mobile")`, `app/models/va_users.py:19-21`.
- Sign-in step 1 (`app/routes/va_auth.py`, `va_login`) treats a value with `@` as email and anything else as a mobile number. A username must therefore start with a letter and be routed to its own branch before the mobile branch.
- `creation_other(via, ...)` already lists `self_signup`, `app/services/user_account_service.py:211`.
- Web submit refuses pending attachment uploads (409 `attachments_pending`) and queues SmartVA after commit, `app/services/web_intake_service.py` about lines 2455-2523 (`smartva_service.queue_smartva_after_commit(va_sid, "web_intake_submit")`).
- Self-coding: `allocate_own_case`, `app/services/coder_workflow_service.py:868`, only for the user who owns the submitted draft.
- No own-review guard: `start_reviewer_coding`, `app/services/reviewer_coding_service.py:372`.
- Consent: `save_settings`, `seed_notice_versions`, `approve_notice_version` in `app/services/consent_service.py` (lines 561, 706, 727).
- Demo virtual grants: `DEMO_VIRTUAL_ROLES` in `app/services/authz/actions.py:116`, applied in `_resolve`, `app/services/authz/grants.py` about lines 383-395.
- `ENROLMENT_MAX_USES = 200`, `app/services/device_auth_service.py:96`; `enrol_device` at line 300.
- The Celery worker runs with `--concurrency=1` (`docker-compose.yml:200`).
- Setup model: `app/services/training_demo_service.py` (`setup_training_project`), CLI in `app/commands/training_demo.py`.
- Proof-of-work CAPTCHA: `app/services/pow_captcha_service.py` (`verify_challenge`).
- Breach check: `password_breach_error_message` as used in `app/services/mobile_sign_in_service.py`; policy `docs/policy/password-breach-checks.md`.

## Phases

### digitva-77v5.2 Backend core

- Config: `PUBLIC_DEMO_ENABLED` and the limit settings (policy section 8).
- Migration: add a nullable `username` column to `va_users` (stored lower-case, unique index on it), a public-demo marker (column or `other` key; prefer a column so queries and the purge guard can index it), and widen `email_or_mobile` to `email IS NOT NULL OR mobile_login IS NOT NULL OR username IS NOT NULL`. Additive and reversible; run `flask db heads` before and after.
- Login: a username branch in step 1 and the password step. The identifier is a username when it has no `@`, matches the username pattern and is not a canonical mobile number; the same answer for known and unknown identifiers is kept (`authentication-factors.md` section 1). Existing mobile and email branches unchanged.
- Sign-up route (only when the flag is on): username and password rules, breach check, PoW CAPTCHA, notice acceptance, global cap of active accounts, per-IP limits, `created_via = self_signup`, grants of interviewer, coder and reviewer on the demo project in the same transaction. No session is issued before the existing sign-in flow runs, or sign-in follows sign-up (decide while building; either is fine).
- `flask public-demo setup`: idempotent, modelled on `setup_training_project` (organization mode, `web_intake_mode` both, self-coding, ICD-11 + DORIS, masked CoD off, NQA and social autopsy off, medical records and death summary on, narration `english` and `hindi`, consent required with the seeded en+hi notice approved, recode window 5 minutes, per-project attachment limits). Refuses unless the flag is on.
- Confinement: one server-side guard in the grant write path. The exact choke point has to be found first (grant writers include `app/services/org_grant_service.py` validators and the data-manager and admin grant routes); if there is more than one writer, add the guard where they converge or to each. The guard refuses any grant, for a public-demo account, other than the three roles on the demo project. Also exclude public-demo accounts from the virtual grants in `_resolve`.
- Own-case filters: on the demo project, coder allocation (pick-and-choose queue, `allocate_pick_form`, `allocate_own_case` paths) and the reviewer queue filter on submitter = current user. This must be a predicate in the shared queue and allocation queries, not only in list views. Check every path that can allocate or open a case by id (coder, reviewer, case grids, data-manager views) so a guessed `va_sid` is refused.
- Limits: sign-ups per IP, active-account cap, submissions per day and in total, open drafts, attachment size and count, enforced server-side at the point of write.

### Review findings to build into .2 (Fable review, 2026-10-22)

- **B1 sign-in gate.** `sign_in_verified` (`app/models/va_users.py:123-127`) is `email_verified OR mobile_verified_at`, so a username account is refused on the web (`app/routes/va_auth.py:320`) and on devices (`is_mobile_only` = `email is None`, `app/models/va_users.py:117`; `app/services/device_auth_service.py:487-489`). Add a third disjunct (username set); make `is_mobile_only` mean `email is None and mobile_login is not None` (unchanged for every existing account, which has one of the two) and check its other callers (`app/routes/admin.py`, `app/routes/data_management.py`, `app/routes/admin_mentor_institute.py`, `app/routes/api/profile.py`). No fake verification stamps.
- **B2 one identifier resolver.** Device sign-in (`app/services/device_auth_service.py:433-443`) has its own email/mobile branch. One shared resolver (email, mobile, username) used by `va_auth._preauth_user`/`_set_preauth` (`app/routes/va_auth.py:100-131`) and `_sign_in_user`.
- **B3 grant guard.** No single grant writer exists (14 constructor sites and 10 reactivation sites; `authz.can_grant` checks the actor, not the grantee). Guard with a `Session.before_flush` listener beside `app/services/grant_cache.py:279` that raises for a new or reactivated `VaUserAccessGrants` row of a public-demo user unless it is interviewer, coder or reviewer at project scope on the demo project.
- **B4 isolation in `scope_filter`.** `VaSubmissions` has no submitter column; the submitter is `VaWebIntakeDraft.user_id` with `status='submitted'` and `va_sid` set (`app/models/va_web_intake.py:432-453`; device uploads write the same draft rows). A coder grant's VIEW lenses reach the whole project (`app/services/authz/actions.py:72-78`), so the filter goes in `scope_filter` / `_lens_predicate` / `reaches` (`app/services/authz/predicates.py:306-336,407-431`) for public-demo users: `va_sid IN (select va_sid from va_web_intake_drafts where user_id = :me and status = 'submitted')`, index-backed (add an index if none covers it). Test VIEW, attachments, random and pick allocation, `allocate_own_case`, reviewer queue, case list.
- **M1 reviewer-eligible sweep.** It runs inside `release_stale_coding_allocations_task`, hourly (`app/tasks/sync_tasks.py:2605-2624`). Make the interval a setting; the demo deployment sets a few minutes.
- **M2 account creation.** Use `create_invited_user` (`app/services/user_account_service.py:244-256`) with languages english + hindi, then `accept_terms` (`:283-292`), so `vacode_language`, `permission`, `landing_page` are set and the device API does not answer `terms_required`.
- **M4 one unit.** `_require_scope` (`app/services/web_intake_service.py:516-539`) needs a unit when the project has levels; setup seeds one unit and demo drafts default to it.
- **M6 guessed death id.** `start_draft` (`app/services/web_intake_service.py:1639-1660`) does not check who registered the death; for public-demo users require `registered_by == me`.
- Setup sets `demo_training_enabled = False` explicitly.

Moved to later phases: **M3** purge (.6): most `va_sid` foreign keys have no `ondelete`; the purge deletes in explicit order and also covers `va_death_register`, consent records and `map_consent_audit`, case transitions and contact attempts, notifications, device sessions, `va_submissions_auditlog` rows of the purged cases; policy section 9 to list them once the order is built. **M5** devices (.5): `AuthDevice` has no user column; cap devices by counting distinct devices in `auth_device_sessions`; the demo enrolment sets `project_id` to the demo project and relies on `interviewer_context` (needs the project's active forms). Own-data download (.3) reads register PII through `register_pii_accessor`.

### digitva-77v5.3 Report and download

- Per-submission report page, submitter only; reads SmartVA result, final ICD-11 cause and reviewer verdict from existing stores, derives the pipeline state from workflow state. Print stylesheet; no PDF library.
- Download of own submissions as CSV and JSON; rate limit 10/hour, audit event (count only), submitter filter in the query. CSV cells that start with `=`, `+`, `-` or `@` are escaped.

### digitva-77v5.4 Dashboard

- Public page and JSON, no login. Aggregate queries only over the demo project (accounts, submissions, coded, reviewed; cause fractions for SmartVA and coder; age band and sex counts). Cached 5 minutes. No case rows, free text or usernames. Fixed number of aggregate queries.

### digitva-77v5.5 Expo web link and Android path

- Expo web: a link to the sign-up page on the demo deployment only.
- Android: "Try the demo" screen. Sign up or sign in with username and password, then enrol through a demo enrolment endpoint that exists only when the flag is on and issues a device for the signed-in demo account without a code. Max 3 devices per account. Release builds already accept `*.causeofdeathindia.com`.
- Native sign-up and the CAPTCHA: superseded 2026-10-22. Mobile users sit behind carrier-grade NAT, so per-IP limits cannot carry the load; the app's JSON sign-up requires the same proof of work as the web (policy section 8), fetched from a flag-gated challenge endpoint. Account cap 500 with eviction of the least-recently-signed-in account idle at least 7 days (built with the purge, .6).
- `make check-web` applies (Expo app change).

### digitva-77v5.6 Purge

- Daily Celery beat task plus `flask public-demo purge --dry-run`. Selects accounts with the public-demo marker and last sign-in (or creation, if never signed in) older than 30 days. Hard guard: flag on and marker set, checked in the query and again before each delete. Deletes, per account in its own transaction: drafts, submissions, payload versions, attachment rows and stored files, SmartVA results and runs, coding and reviews, grants, sessions, devices, and the user. Stored-file removal after commit. One audit event per run with counts. Needs a full list of tables keyed by `va_sid` or user id; derive it from foreign keys and test that no row of a purged account remains.

### digitva-77v5.7 Deployment

- Compose overlay or separate project for the demo: app, Celery worker, Celery beat, own Redis (own password), own Postgres database, existing ICD container reached over a shared network. Env: `PUBLIC_DEMO_ENABLED=1`, own `SECRET_KEY` and database URL. Reverse proxy on `demo.causeofdeathindia.com`, TLS, real client IP forwarded (the per-IP limits depend on it). Nightly backup of the demo database (owner 2026-10-22), with a tested restore; the purge (.6) runs only once the backup is in place.
- Worker concurrency: see risks.

## Risks

- **Confinement bug.** A demo account gaining any wider grant, or seeing another person's case, is the main risk. Mitigate with the guard at the grant write path, the exclusion from virtual grants, the predicate in shared queries, and tests that try every role and a guessed `va_sid` against another user's case.
- **SmartVA throughput.** The worker runs with concurrency 1; many sign-ups and submissions queue SmartVA behind each other, so the report shows "waiting for SmartVA" for a long time. Per-account daily limits bound it; raise concurrency on the demo worker if the queue grows, and watch queue length.
- **Redis isolation.** The demo must not share a Redis (broker, result backend, rate limit and cache keys) with the main deployment, or a flood on the demo can starve or leak into the main one. Own Redis, own password, verified in .7.
- **Upload abuse.** Public uploads (10 MB, 6 per draft) can fill disk. Per-account limits, 30-day purge, and a disk-usage alert; consider a global storage ceiling.
- **Rate limits behind a proxy.** Wrong client-IP handling makes per-IP limits useless or locks everyone out. Test with the proxy headers.
- **ICD API terms.** WHO ICD-11 API terms for anonymous public use must be checked by the owner before launch. Not decided; blocks launch, not development.
- **Real data entered despite the notice.** Mitigated by the notice, the 30-day deletion and the separate database; not eliminated.

## Verification (tests to add)

- .2: username rules (length, charset, leading letter, case-insensitive uniqueness, a digit string refused); password rules (length, breach hit, equals username); flag off gives 404 and creates no account; login branch (username, email and mobile still work; unknown username gives the same answer); migration up and down and the widened constraint; setup is idempotent and refuses when the flag is off; confinement (every other role and project refused, virtual grants not applied); own-case filters (user A cannot allocate, open or review user B's case, including by `va_sid`); each limit.
- .3: report shows each pipeline state; another user gets 403/404; download returns only own rows, is rate limited and audited; CSV formula escaping.
- .4: no usernames or free text in the response; counts match fixtures; cache honoured; works logged out.
- .5: `make check-web`; Jest for the Try the demo screen; demo enrolment endpoint absent when the flag is off, device cap enforced.
- .6: dry run deletes nothing; purges only marked accounts older than 30 days; refuses when the flag is off; main-style accounts untouched; no orphan rows or files after a purge.
- .7: manual: the demo stack starts with its own Redis and database; a sign-up, submit, SmartVA, code, review pass end to end; the main stack is unaffected.
- Run targeted tests per phase; the main session runs one full suite before each commit.

## References

- `docs/policy/public-demo.md`, `docs/policy/account-onboarding-and-passwords.md`, `docs/policy/web-intake.md`, `docs/policy/authentication-factors.md`, `docs/policy/mobile-sign-in.md`, `docs/policy/password-breach-checks.md`, `docs/policy/training-demo-project.md`
- `.tasks/2026-09-30-android-collection-app.md`

## Expected Scope

One migration, a new blueprint and service for public demo, changes to login, the grant write path, the allocation and reviewer queues, digitva-collect, compose files and docs in `docs/current-state` (authentication, runtime). Update `docs/current-state` in each phase that ships.
