# Handoff

Updated 2026-09-19. Five sessions worked one shared checkout and landed 16
commits; `origin/main` is at `98b9816`, working tree clean.

## What landed

| Commit | What |
| --- | --- |
| `3a17d8c` | Viewer roles wired to routes; two scope leaks closed; per-unit coding gates; migration `a40c38e73af4` |
| `b8d05ef` | WHO 2026 annex ICD-10 ranges as the `WHO_2022_VA_2026` scheme; migration `c5f2a8d1e9b3` |
| `926c212` | Web intake configurability, organization-API ancestors, PII field registry; migration `b8e3d1f7a2c4` |
| `e16ea30` | `role_required` raises at decoration time on an unknown role name |
| `6ea5420` | `R10` selectable, bucketed to `VAs-06.01` |
| `b247950`, `ae6d6fa`, `5c5473a`, `8f0f672`, `98b9816` | Policy and task records (below) |
| `455eb34`, `d08fce7`, `63a3dcb`, `479b698`, `44ffbeb` | Tooling hygiene: Dolt log and backup pointer untracked, beads prefix fixed, droppings ignored |

Migration chain is linear: `f1c6a9d3e7b5 -> a40c38e73af4 -> c5f2a8d1e9b3 ->
b8e3d1f7a2c4`. Verified by an empty-database `flask db upgrade` replay of the
whole chain, which reaches head and yields 2,489 selectable ICD-10 codes and
four COD bucket schemes.

Verified: full suite 1,381 passed on the rebased tree.

## The access model, as it now stands

`collaborator` and `collaborator_pii` reach **five** read-only routes:
`/data-management/`, `/data-management/dashboard`, and the `submissions`,
`filter-options` and `kpi` APIs. Nothing else, no writes.

Two things worth knowing before extending it:

- **`dm_scope_filter` is wider than the grant and fails open.** An `org_unit`
  grant is bridged to the unit's whole project, because a unit does not name a
  site. Callers that enumerate submissions must AND in
  `dm_submission_org_unit_condition`. Two callers were not doing that and were
  serving a project's whole site roster to a viewer granted one leaf unit;
  both now narrow themselves. If you add a caller, apply the condition or write
  down why the coarse answer is right.
- **`/data-management/cod-buckets` is deliberately NOT viewer-reachable.** The
  page is a shell and all three endpoints behind it are `data_manager`/`admin`,
  so granting the page alone gives a screen that 403s on every fetch. Opening
  that API is a separate widening: `export.csv` emits staff identity.

## Start here

Ranked across every session's input. The first two are new and both fail open.

1. **The PII set fails open for any non-WHO questionnaire.**
   `.tasks/pii-registry-fails-open-for-non-who-forms.md`. `PII_FIELDS` is keyed
   on WHO field ids and applied to every active form type without checking the
   form contains them. A PHMRC or Ballabgarh form type gets no flags on its own
   name and national-ID fields, and exports them in the clear. `is_pii` is now
   the single source of truth behind the viewer split and five redaction
   surfaces, so an empty set reads as "nothing here is personal data". Fail
   closed.

2. **The PII set is cached per process with no invalidation.** Same task file.
   `get_pii_field_ids()` memoizes; nothing in the repo calls `cache_clear`. An
   admin edit or a Celery-run sync does not reach a web worker until restart.

3. **Nothing guarantees a route has a decorator at all.**
   `.tasks/auth-decorator-followups.md`. A mistyped role now fails at import; a
   *missing* decorator fails open, and three unguarded routes have been found by
   audit rather than by a check. A test walking `app.url_map` and failing on any
   unguarded, non-allowlisted endpoint closes it. Use the runtime map, not an
   AST sweep — only `url_map` sees dynamically registered blueprints.

4. **The `form-options` endpoint** (`docs/policy/va-web-form-options.md`). It
   unblocks removing the hardcoded `locale = "en"` at
   `va_intake_form.html:168` and the never-set `instrument` property. The form
   falls back to the bundled WHO 2022 instrument, which works only while
   exactly one form type is live.

5. **Closed-project grant revocation.** `.tasks/closed-project-grant-revocation.md`.
   A project-scoped grant on a closed project still resolves, in two
   independent mechanisms. Fixing one alone leaves them disagreeing, so it needs
   a decision about what a closed project means for every grant scope.

Then: attachments phase 2, the validator sidecar (written, unwired, decision
W1), ICD-11 coding screen phases 3-6.

## Open and unexplained

- **The dev DB stamp moved backwards two revisions** with the later migrations'
  data still present. Fixed by re-running `flask db upgrade`; cause unknown.
  A stamp regressing without a downgrade is a data-integrity signal. Likely
  contributor: `boot.sh` retries `flask db upgrade` forever against a DB
  stamped at a revision the tree lacks, hanging silently instead of failing.
  `.tasks/dev-db-stamp-regression-and-infra.md`.
- **Dev and a fresh clone have diverged**: dev's `WHO_2022_VA` carries 2,414
  mappings against a fresh clone's 2,380. That is how a test passes here and
  fails everywhere else.
- **`test_odk_site_mappings`** failed once in a full run with its POST and GET
  each taking 35,118ms to within 3ms. Not reproduced, not explained. The
  identical timings are the fingerprint if it recurs.
- **15 migration files import from `app.*`**, unswept. The `mas_org_unit` break
  came from exactly this.
- **`stash@{0}`** is still present from the incident earlier this week.

## How to work in this repo now

- **One test database per tree.** `TestConfig` honours `TEST_DATABASE_URL`
  above everything. `drop_all` cannot order a table its metadata has never
  seen, so a tree lacking another tree's uncommitted model cannot tear down a
  schema containing it — persistently, not as a race. See
  `docs/policy/test-harness.md`.
- **Shared checkout discipline.** Git read-only unless you are the session that
  owns landing commits; never `stash` (one swept 37 files across four sessions
  this week). Build file lists from `git diff`, never from memory of your own
  edits — in a shared tree the diff is the only source of truth about what a
  commit will contain.
- **Six vacuity rules** are in `docs/policy/test-harness.md`, each from a check
  that passed today while proving nothing: assert the subject is present before
  asserting it is absent; patch the module object, not a dotted path through a
  package that re-exports it; a missing fixture can make an authorization test
  vacuous; defeat the bytecode cache when mutation testing; treat an errored
  `setUpClass` as the whole class unverified; the dual-table FK trap.
- **Migrations chain onto committed revisions only**, verified in `git log`. An
  `origin/main` was broken this week by a revision naming a parent that existed
  only in a working tree. Three migrations named one parent today; each
  re-chained as it landed.

## Known gaps in what was verified

No suite has been mutation-tested except `tests/test_role_required_validation.py`.
The two new ICD CLI commands and migration `c5f2a8d1e9b3` have no automated
test. The intake page's JavaScript is inline in a Jinja template and
structurally untestable — which is why the optional-level reachability bug
lived there undetected. About 27 docs were last updated in March and have never
been checked against the code.
