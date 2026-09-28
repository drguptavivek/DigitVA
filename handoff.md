# Handoff

Rewrite this file at the end of each session; do not append. Keep it under
about 150 lines. History lives in git log and closed beads (`AGENTS.md`,
"Ending a session").

## Prompt for the next session

> Read `handoff.md`, then `docs/current-state/README.md` before structural
> changes. `docker compose up -d` (add `--profile icd11` for the WHO API,
> public DORIS service and ingress). Log in on port 8051 as the seeded admin
> in `AGENTS.md`; the ingress (clinical app plus public DORIS demo) is on
> 8052, e.g. `http://localhost:8052/help/doris-demo`. SADEMO is the DORIS dev
> project: ICD-11, masked (coder and reviewer both use DORIS in Step 1),
> Demo/Training, 30-minute retention.
> Tests: `docker compose exec -T -e TEST_DATABASE_URL=postgresql://minerva:minerva@minerva_db_service:5432/minerva_test_pii minerva_app_service uv run --no-sync python -m pytest tests --ignore=tests/migrations -q -p no:cacheprovider`
> (2337 tests, all pass, about 2 min 10 s; do not run the whole
> `tests/migrations` directory, it is very slow: run only the migration you
> touched plus `test_schema_drift.py` and
> `test_no_app_imports_in_migrations.py`). One pytest run per test database
> at a time: killing `docker compose exec` does not kill pytest inside the
> container, and a second run on the same database hangs. Also
> `node tests/js/doris_result_summary_check.mjs`, and
> `node --input-type=module --check < <file>` on edited JS. Use `bd`; commit
> in the repo's voice and push. Work the ranked list below.

## Next, ranked

1. `digitva-ddv.2` (in progress): production DORIS ingress release, on the
   app VM only; the DMZ reverse proxy stays unchanged. **First** confirm
   production `.env` has `MAIL_BASE_URL=https://digitva.causeofdeathindia.com`:
   production now refuses every host but that one (plus localhost for the
   healthcheck) and will not start without it (`trusted_hosts_for` in
   `config.py`; dev is exempt via `FLASK_ENV=development`). Then in the
   untracked compose override move port 8051 from `minerva_app_service` to
   `digitva_ingress` (`8051:80`); `.env` gets `COMPOSE_PROFILES=icd11` and
   `DORIS_PUBLIC_COOKIE_SECURE=true`; `docker compose up -d`; then the image
   digest, log-privacy, five-parallel-Process and Secure-cookie checks in the
   bead. Wiring: `docs/current-state/doris-cod-workflow.md`. This deploy also
   ships the 2026-09-28 login fixes: password-reset links sent before it
   stop working (one-hour links, now single-use).
2. `digitva-sn1.1` (P1): passkeys and TOTP. All owner decisions are made and
   recorded in `.tasks/2026-09-28-passkey-login.md`; next step is the policy
   baseline in `docs/policy`, then one additive migration and the build.
   Decisions in short: same second page (passkey or password) for every
   email; local proof-of-work CAPTCHA, no third-party service; passkey or TOTP
   mandatory for admins and data managers only, coders may use password
   alone; 30-day enrolment window, then a forced setup page (no lock-out);
   any admin resets another user's factors (never their own), audited;
   break-glass `flask auth reset-factors` emails a single-use magic link into
   onboarding. WebAuthn RP ID comes from `MAIL_BASE_URL`. Coordinate the
   email step with per-project SSO (`digitva-roq`,
   `.tasks/2026-09-26-project-sso-oauth2.md`).
3. `digitva-ddv.5`: owner sends WHO the CoDEdit BER-CE-9 false-warning
   report (GitHub issue 41; text in
   `docs/kb/doris-picker-who-behaviour-rules.md`, "To report to WHO").
4. `digitva-fb5` (P1): code-prefix typos are fixed at render time; what is
   left needs a speaker (Odia and Kannada labels carrying another
   question's wording, three unit cases in fr/ml). The KA01 ODK workbook
   maintainer should be told about its shifted Marathi `units_5`.

DORIS final causes already feed VA cause reporting: the COD MV buckets an
ICD-11 value by its first stem through the native `WHO_2022_VA_2026` scheme.
`digitva-712` has only owner reviews left.

## Waiting on the owner


- `digitva-712.6`: 12 ICD-11 crosswalk disagreements with specific causes on
  both sides.
- `digitva-dus.3` (in progress): review the ICD-11 selectable/sex/age draft
  (`docs/policy/who-2022-icd11-coding-allowability.md`). It is now the only
  hard check on a DORIS final cause (first stem only). Rule 4 made every
  disease-chapter category selectable (`digitva-ddv.6`); dev took it through
  `flask icd11 policy-import`, not a migration, so another database needs
  the same import until the draft is signed off.
- `digitva-mdj`: WHO answered #95 only; #94 (Id10304_a relevance) unanswered.
- `docs/manuscript/DigitVA_Architecture_and_Workflow  -  Repaired.pptx`
  (untracked) is PowerPoint's auto-repaired copy of the committed deck: keep
  it as the replacement or delete it.

## Approved, not started

- `digitva-r1p`: Project Setup home phases 2-4 (phase 1 done).
- `digitva-yds.3`: COD bucket schemes read-only in Help.
- `digitva-e5j`: explain empty coding-search results caused by age/sex
  policy.

Epics: `digitva-dus` (V3 umbrella), `digitva-roq` (per-project SSO; also
unblocks a WebView shell for the ICD-11 picker), `digitva-sn1`
(passkeys/TOTP), `digitva-1eq` (more ML coders), `digitva-zpe` (semantic
ICD search, in progress).

## Caveats still true

- "Reset from source" on `WHO_2022_VA_2026` drops the Fresh stillbirth node
  and all ICD-11 rows (the source workbook predates them); a snapshot is taken
  first (`digitva-tet`), so restore from it.
- The floating VA definition panel and its Quill save round-trip were never
  exercised on a live coding page with a real allocation.
- Dev's `WHO_2022_VA` has 2,414 mappings against a fresh clone's 2,380, so a
  test can pass here and fail elsewhere.
- The dev DB stamp once moved back two revisions with later data present;
  cause unknown (`.tasks/dev-db-stamp-regression-and-infra.md`).
- Flaky or unexplained: `digitva-ssi` (`test_odk_site_mappings`, POST and GET
  each ~35 s to within 3 ms; failed once in a full run on 2026-09-28, passed
  on rerun), `digitva-3jj` (vendored vitest under load),
  `digitva-19l` (351 of 524 vendored vitest tests fail).
- Test databases created before a model change keep old layouts
  (`create_all` never alters); drop the stale table if tests complain.
- `stash@{0}` (WIP on `a24ea0a`) is from an old incident; drop it only after
  someone confirms it holds nothing needed.
- Verification gaps: only `tests/test_role_required_validation.py` is
  mutation-tested; the intake page's JavaScript is inline in a Jinja template
  and untested; about 27 docs last updated in March were never checked
  against the code.
- WHO ICD-11 zip bundles in `docs/kb` are git-ignored; the unzipped folders
  are tracked and their sources are in `docs/kb/icd-11-who-downloads.md`.
- `docs/kb/DORIS/` holds reference copies of WHO's DORIS/CoDEdit pages;
  `scripts/generate_codedit_messages.py` reads
  `who-codedit-report-message-identifiers.md` from there.
- Browser-only behaviour has no automated test and was verified by hand on
  2026-09-27: `window.confirmDialog` (`base.js`), the translation editor's
  inline discard prompt, and the Setup Basics re-render (the panel is emptied
  before it, because htmx settling re-hid the form).
