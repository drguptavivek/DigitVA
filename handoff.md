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
> Tests: `docker compose exec -T -e TEST_DATABASE_URL=postgresql://minerva:minerva@minerva_db_service:5432/minerva_test_pii minerva_app_service uv run --no-sync python -m pytest tests/routes tests/services -q -p no:cacheprovider`
> (1766 tests, all pass; do not run the whole `tests/migrations` directory,
> it is very slow: run only the migration you touched plus
> `test_schema_drift.py` and `test_no_app_imports_in_migrations.py`), `node tests/js/doris_result_summary_check.mjs`, and
> `node --input-type=module --check < <file>` on edited JS. Use `bd`; commit
> in the repo's voice and push. Work the ranked list below.

## Next, ranked

1. `digitva-ddv.5`: owner sends WHO the CoDEdit BER-CE-9 false-warning
   report (GitHub issue 41; text in
   `docs/kb/doris-picker-who-behaviour-rules.md`, "To report to WHO").
2. `digitva-ddv.2` (in progress): production DORIS ingress release. Ingress
   code is done (forwarded headers pass through; Docker DNS re-resolve). Work
   is on the app VM only; the DMZ reverse proxy stays unchanged. In the
   untracked compose override move port 8051 from `minerva_app_service` to
   `digitva_ingress` (`8051:80`); `.env` gets `COMPOSE_PROFILES=icd11` and
   `DORIS_PUBLIC_COOKIE_SECURE=true`; `docker compose up -d`; then the image
   digest, log-privacy, five-parallel-Process and Secure-cookie checks in the
   bead. Wiring: `docs/current-state/doris-cod-workflow.md`.
3. `digitva-y0c` (P1) and `digitva-l38` (P1): the project users/units
   import (Organization panel, Export / Import) works but is CSV-only and
   UTF-8-only. The owner wants district and state managers to import files
   made in Excel: accept .xlsx (openpyxl and the advanced-import reader
   already exist) and Excel-saved CSVs (`y0c`). `l38` holds the hardening
   list from review and a browser edge-case run (NUL characters, friendly
   role errors, formula values, duplicate unit codes, PI account-status
   leak, cadre cleared on rerun, post-commit N+1, PI tests).
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
  each ~35 s to within 3 ms), `digitva-3jj` (vendored vitest under load),
  `digitva-19l` (351 of 524 vendored vitest tests fail).
- Test databases created before a model change keep old layouts
  (`create_all` never alters); drop the stale table if tests complain.
- `stash@{0}` (WIP on `a24ea0a`) is from an old incident; drop it only after
  someone confirms it holds nothing needed.
- Verification gaps: only `tests/test_role_required_validation.py` is
  mutation-tested; the intake page's JavaScript is inline in a Jinja template
  and untested; about 27 docs last updated in March were never checked
  against the code.
- `docs/kb/DORIS/` holds reference copies of WHO's DORIS/CoDEdit pages;
  `scripts/generate_codedit_messages.py` reads
  `who-codedit-report-message-identifiers.md` from there.
- Browser-only behaviour has no automated test and was verified by hand on
  2026-09-27: `window.confirmDialog` (`base.js`), the translation editor's
  inline discard prompt, and the Setup Basics re-render (the panel is emptied
  before it, because htmx settling re-hid the form).
