# Handoff

Rewrite this file at the end of each session; do not append. Keep it under
about 150 lines. History lives in git log and closed beads (`AGENTS.md`,
"Ending a session").

## Prompt for the next session

> Read `handoff.md`, then `docs/current-state/README.md` before structural
> changes. Start the stack with `make dev` (it runs `make ensure-secrets`,
> which appends `CAPTCHA_HMAC_KEY` and `AUTH_FACTOR_ENCRYPTION_KEY` to `.env`
> when missing; plain `docker compose up` skips that and the Celery
> containers then refuse to start). Add `--profile icd11` for the WHO API,
> public DORIS service and ingress. Log in on port 8051 as the seeded admin
> in `AGENTS.md`: login is now two steps (email + background proof-of-work
> CAPTCHA, then password or passkey). The dev `testadmin` has a passkey, so
> a password sign-in asks for a second factor; sign in with the passkey or
> use its recovery codes.
> Tests: `docker compose exec -T -e TEST_DATABASE_URL=postgresql://minerva:minerva@minerva_db_service:5432/minerva_test_pii minerva_app_service uv run --no-sync python -m pytest tests --ignore=tests/migrations -q -p no:cacheprovider`
> (2494 pass, about 2.5 min; run only touched migration tests plus
> `test_schema_drift.py` and `test_no_app_imports_in_migrations.py`).
> One pytest run per test database at a time. Web form package:
> `cd vendor/who-va-2022 && npx vitest run` (779 pass); rebuild the served bundle
> with `cd tooling/who-va-2022 && node build.mjs && node check.mjs` (updates
> `manifest.json`; the page versions the bundle URL by its sha). Use `bd`;
> commit in the repo's voice and push.

## Next, ranked

1. `digitva-ddv.2` (in progress): production release on the app VM. Before
   `docker compose up -d`: confirm `.env` has
   `MAIL_BASE_URL=https://digitva.causeofdeathindia.com` (production refuses
   other hosts, and it is also the passkey RP ID: never change it after the
   first passkey is registered); run `make ensure-secrets` (or `make prod`)
   and back up `.env` (`AUTH_FACTOR_ENCRYPTION_KEY` protects TOTP secrets);
   rebuild images (new deps: webauthn, pyotp, segno); run migrations
   `c1d5e9a2f7b4` (auth factor tables) and `b1f4d8a6c9e2` (district VA
   presets). Then the ingress switch, `COMPOSE_PROFILES=icd11`,
   `DORIS_PUBLIC_COOKIE_SECURE=true` and the checks in the bead. Set
   `AUTH_FACTOR_ENFORCE_FROM` (launch + 30 days) when the owner announces the
   passkey/TOTP rollout. Login changes ship with it: two-step login,
   passkeys, TOTP, recovery codes, enrolment banner/hold, admin factor reset,
   `flask auth reset-factors` (`docs/policy/authentication-factors.md`).
2. `digitva-sn1.1.7` (P1): real-device passkey check (Windows Hello, Touch ID,
   iOS Safari, Android Chrome, phone-to-laptop, a security key). Chrome's
   virtual authenticator passes end to end on dev.
3. `digitva-vzk` worklist epic: plan and all owner decisions in
   `.tasks/2026-09-28-interviewer-worklist.md` (no assignment; team fills
   any registered case; first complete submission wins, incomplete/refused
   do not; offline in scope; supervisors = MOs at higher facilities + data
   managers; interviewers and supervisors flag duplicate/cancel, supervisors
   confirm; supervisors reopen refused). Next: policy baseline in
   `docs/policy/web-intake.md`, then build in the plan's phase order.
   Children: `vzk.1` (prefill identity/place incl. parents' names at
   registration), `vzk.2` (`interview_outcome` question: auto refused/
   completed; partially completed / respondent unavailable = incomplete, not
   coded), `vzk.3` (interviewer year of birth and sex in profile).
4. `digitva-5mu`: the web form's own UI strings stay English on a translated
   form; the date hint and "This question is required." show English on
   Hindi pages.
5. `digitva-cts`: SmartVA takes HIV/malaria from the submission's
   organization unit district setting (high on, low/very low off), else the
   form flag, else off; runs unchanged, split when mixed, options and source
   recorded (`docs/policy/smartva-generation-policy.md`). Agreed; not built.
6. DORIS prefill (`digitva-hln`, built 2026-09-29) follow-ups, all owner
   steps: deploy the ODK rows in
   `docs/kb/WHO_VA_2022_Docs/odk-doris-support-rows.xlsx` (A1-A3 agreed;
   A4-A10 proposed; test the `dob_*` constraints in Collect first); send
   WHO `docs/kb/DORIS/who-va-2022-doris-consistency-proposal.md` (strip the
   internal header line; GitHub issue on SwissTPH/WHO-VA or email); site
   training on `docs/kb/WHO_VA_2022_Docs/odk-training-date-of-birth.md` and
   on Id10366 no longer accepting 0 (answer `Id10366_check` = no).
   `digitva-zyf`: the Id10366 override message is not translatable yet.
   The extension is always on for every web project; ODK rows are generated
   from it (`npm run build:odk-doris-rows` in `tooling/who-va-2022`, then
   `tooling/who-va-2022/build_odk_doris_rows.py` in the app container).
7. `digitva-ej1`: web attachment upload (audio narration, document images);
   owner allows offline on-device storage, encrypted, deleted after upload.
8. `digitva-ddv.5`: owner sends WHO the CoDEdit BER-CE-9 report.
   `digitva-fb5` (P1): translation label fixes need a speaker.

## Waiting on the owner

- Merge [drguptavivek/WHO-va-2022#1](https://github.com/drguptavivek/WHO-va-2022/pull/1)
  (our vendored package pushed upstream). `aashieshsingh/WHO-va-2022` has
  separate commits to 25 Sep (date calendar, field controls); not merged.
- `digitva-712.6` (12 ICD-11 crosswalk disagreements), `digitva-dus.3`
  (ICD-11 selectable/sex/age draft), `digitva-mdj` (WHO #94 unanswered).

## Approved, not started

- `digitva-r1p`: Project Setup home phases 2-4. `digitva-yds.3`: COD bucket
  schemes in Help. `digitva-e5j`: explain empty coding-search results.
- `digitva-aek`: download a project's ODK XLSForm built from its enabled
  modules (ODK form becomes a project output). After `digitva-hln`.
- `digitva-d1x` (P3, after the WHO form is stable): PHMRC shortened form
  (`docs/kb/PHMRC`) as a web form with its label images and audio; capture
  only, downstream pipeline later.

Epics: `digitva-dus` (V3), `digitva-roq` (per-project SSO; the email login
step is where it hooks in), `digitva-sn1` (passkeys/TOTP, build done),
`digitva-vzk` (worklist), `digitva-1eq` (more ML coders), `digitva-zpe`
(semantic ICD search).

## Caveats still true

- Dev has a `test.coder.nc01@gmail.com` account (password as in `AGENTS.md`)
  created for the DORIS browser check; its SADEMO coder grant is set to
  `deactive`. The other four test coders are not in this dev database.

- Web form: speed is the priority; round-3 measures (4x CPU throttle) are in
  `docs/design/web-form-visual-pass/README.md` (tap on the 164-question
  section 18/26 ms p50/p95). The bundle is 19 KB over the pre-round-3 size.
- Web drafts: reopening now restores answers and blocks saves until restore
  settles (`digitva-ybz`, fixed). Dev draft `eca5d80d` had its
  `meta.createdAt` moved to 2026-09-29 by a pre-fix open (answers intact).
- Dev passkeys need `WEBAUTHN_RP_ID=localhost` / `WEBAUTHN_ORIGIN`, pinned in
  `docker-compose.override.yml`; dev `.env` carries the production
  `MAIL_BASE_URL`.
- Admin panels opened directly by URL (not through the admin shell) lack
  Bootstrap JS, so their offcanvas buttons fail; use the shell.
- "Reset from source" on `WHO_2022_VA_2026` drops the Fresh stillbirth node
  and ICD-11 rows; a snapshot is taken first (`digitva-tet`).
- Dev's `WHO_2022_VA` has 2,414 mappings against a fresh clone's 2,380.
- The dev DB stamp once moved back two revisions
  (`.tasks/dev-db-stamp-regression-and-infra.md`).
- Flaky: `digitva-ssi` (`test_odk_site_mappings`, passes on rerun),
  `digitva-3jj`, `digitva-19l`.
- `stash@{0}` (WIP on `a24ea0a`) is from an old incident; drop it only after
  someone confirms it holds nothing needed.
- ODK connection credentials still use Fernet (TOTP secrets moved to
  AES-256-GCM); separate subsystem.
- Browser-only behaviour verified by hand, not automated: `confirmDialog`,
  the admin panel swap fix (`2c98f2a`), the project form layout, the passkey
  ceremony (Playwright script lived in the session scratchpad only).
