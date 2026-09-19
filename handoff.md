# Handoff

Updated 2026-09-19 (later session). The PII fail-closed fix landed on top of
`648dce3`; `origin/main` is at the commit that updated this file, working tree
clean.

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
| `4b0e308` | PII set fails closed per form type; PII cache versioned on `mas_field_display_config` `(count, max(updated_at))`. No migration. |
| `711710e` | Policy: what a second form type must pass before it goes live |
| (this session) | `tests/test_route_auth_coverage.py`: every `url_map` endpoint must carry `role_required` or `login_required`, or sit on an explicit allowlist |

Migration chain is linear: `f1c6a9d3e7b5 -> a40c38e73af4 -> c5f2a8d1e9b3 ->
b8e3d1f7a2c4`. Verified by an empty-database `flask db upgrade` replay of the
whole chain, which reaches head and yields 2,489 selectable ICD-10 codes and
four COD bucket schemes.

Verified: full suite 1,409 passed after the public-route decisions (1,402 after the route-coverage test, 1,391 after the PII change, 1,381 on the rebased tree before all three).

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

Ranked across every session's input. Done since the previous ranking: the
PII set failing open, the PII cache never invalidating, and the route
decorator guarantee (see the two sections below). The six routes that were
pending a decision are settled: help and WHO documents public, `/` requires
login.

1. **The `form-options` endpoint** (`docs/policy/va-web-form-options.md`). It
   unblocks removing the hardcoded `locale = "en"` at
   `va_intake_form.html:168` and the never-set `instrument` property. The form
   falls back to the bundled WHO 2022 instrument, which works only while
   exactly one form type is live.

2. **Closed-project grant revocation.** `.tasks/closed-project-grant-revocation.md`.
   A project-scoped grant on a closed project still resolves, in two
   independent mechanisms. Fixing one alone leaves them disagreeing, so it needs
   a decision about what a closed project means for every grant scope.

3. **Migrations importing live app code.** `.tasks/migrations-importing-app-code.md`.
   15 migration files import from `app.*`; the `mas_org_unit` break came from
   exactly this. A lint on `app.services` imports under `migrations/versions`
   plus the empty-database upgrade replay closes it.

Then: attachments phase 2, the validator sidecar (written, unwired, decision
W1), ICD-11 coding screen phases 3-6.

## Route decorator guarantee (landed this session)

`role_required` now stamps its wrapper with `__digitva_roles__`, and
`tests/test_route_auth_coverage.py` walks `app.url_map` at runtime, follows
each view's `__wrapped__` chain, and fails on any endpoint that carries
neither that marker nor Flask-Login's `login_required` (detected by code
object, because `functools.wraps` rewrites `__module__` and `__qualname__`
and a name check finds nothing). `hasattr(f, "__wrapped__")` was rejected
as the signal: any `wraps`-based decorator sets it, and the test keeps one
assertion proving unguarded-but-wrapped endpoints still exist so that
rationale stays falsifiable. Positive control registers an unguarded view on
a bare `flask.Flask` and asserts it is reported.

One allowlist, `PUBLIC_BY_DESIGN`, checked for stale entries and for
entries that later became guarded. It holds fourteen endpoints: static,
health, the seven `va_auth` account-access flows (login, logout, maintenance
banner, forgot password, reset link, resend verification, verify email), the
WHO reference documents, and the four help pages. Decided 2026-09-19: help
and WHO documents are public so a prospective user can read them before
logging in; `help.page` keeps its in-body role filter for role-restricted
pages. `va_main.va_index` (`/`, `/index`, `/vaindex`) now carries
`login_required`; an anonymous visitor is redirected to the login page.
`tests/routes/test_public_route_access.py` asserts the anonymous behaviour
of each class at runtime.

`API_PATH_PREFIXES` is now a constant on `role_required`, and a test asserts
every `/api/`-shaped rule matches one of its prefixes, closing item 2 of
`.tasks/auth-decorator-followups.md`. Item 3 (`project_pi` is the only
predicate that queries) is still open.

## PII set confirmation (landed this session)

A form type's PII set is **confirmed** when at least one `is_pii` row sits on
a field the form actually owns (`subcategory_code IS NOT NULL OR odk_label IS
NOT NULL OR is_custom = false`). "Zero `is_pii` rows" was never a usable
check: `apply_pii_field_registry` creates three redaction-only rows for every
form type, WHO-shaped or not. Derived from data, so no migration and no
confirm button: an admin confirms a PHMRC form by flagging one of its real
fields in the field-mapping panel.

Unconfirmed fails closed: a plain `collaborator` gets no payload at all on
the submission page, and the submissions CSV export writes the payload
columns empty for every role (it was already PII-filtered for every role).
The admin form-type list, `get_form_type_stats`, the field-mapping panel and
`flask form-types` all show the status.

**One exemption, deliberate:** the SmartVA input export still only strips
flagged fields on an unconfirmed form type, logged as
`pii set unconfirmed | <code> | smartva input export not withheld`. It is a
processing feed reachable only by data managers and admins, and withholding
there would make SmartVA unusable on any new questionnaire. The remaining
fail-open on that path is unchanged from before: a form whose form type
cannot be resolved exports its payload with only the hardcoded omit list
applied. Recorded in `docs/policy/access-control-model.md`.

The PII status cache is keyed on `(count(*), max(updated_at))` of
`mas_field_display_config` for the form type, so an admin edit or Celery-run
sync reaches every worker on its next call. The other mapping caches
(fieldsitepi, choices, labels) are still process-level and cleared only by
`clear_cache()` — a test that mutates a mapping row and renders must clear
them on cleanup, or later tests in the same process render the mutated
build after the savepoint has rolled the row back.

Test database for this tree: `minerva_test_pii` (created this session).

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
