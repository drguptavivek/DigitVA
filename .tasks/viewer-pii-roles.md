# Viewer roles: with and without PII

- Status: role + redaction built 2026-09-18; route wiring landed 2026-09-19
  for the redaction-safe surfaces only (dashboard, KPI shell, cod-bucket
  reporting page, and the submissions/filter-options/kpi JSON APIs) — see
  docs/policy/access-control-model.md, "Route wiring (2026-09-19)" under
  `collaborator_pii`, for the full reached/not-reached list. Submission
  detail rendering ("Two surfaces still unredacted" below) is still
  unreached and still needs its own change.
- Priority: high
- Created: 2026-09-18

## Goal

Split read-only access into a viewer who sees personal data and one who does
not. Operational need: a supervisor must be able to see **who did what for
which death** without every read-only account seeing the deceased's identity.

## Decision (2026-09-18, user)

Roles, not a flag on the grant. One new role only — `collaborator` already IS
the read-only role:

- `collaborator` — read-only, **no PII**. Admin panel label "Viewer".
- `collaborator_pii` — read-only, **with PII**. Label "Viewer (with PII)".

Policy baseline: `docs/policy/access-control-model.md`, sections
`collaborator`, `collaborator_pii`, and Role To Scope Rules.

The role-vs-flag tradeoff and the merged subject/staff PII set are recorded
there with their reasoning; do not re-litigate without reading it.

## Blockers — both cleared 2026-09-18

1. ~~`2e1da5fbaa0a` must land first.~~ Landed and pushed; it is the single
   head, and a new migration chains onto it.
2. ~~The `is_pii` flag set must be correct first.~~ Fixed in the working tree
   by the web-intake session: the registry applies by `field_id` across all
   active form types, the migration loops form types, `_build_pii_field_ids`
   no longer filters on `is_active` (verified), the registry no longer forces
   `is_active`, and form-type creation applies the registry so a clone is not
   born unflagged.

   The code is still uncommitted, but `b8e3d1f7a2c4` HAS since been applied
   to the dev database through alembic, and both form types now carry the
   flags (`Id10073` and `Id10010c` true on WHO_2022_VA and
   WHO_2022_VA_SOCIAL). Dev data is therefore usable for testing these roles.

   An earlier version of this note said the opposite; it was written before
   the migration ran.

## Blocker: the PII definition is currently wrong

`mas_field_display_config.is_pii` is the single definition of what
`collaborator` must not see. As of 2026-09-18 it covers only form type
`WHO_2022_VA`. `WHO_2022_VA_SOCIAL` holds ~86% of submissions (7082/8223) and
its cloned config rows still carry `is_pii = false` for the national
identification number (`Id10073`, 1129 populated values), `Id10055`,
`Id10070/71/72` and `Id10010c`.

Building the roles on that set would ship a redaction control that looks
correct and leaks the exact field it exists to hide. **A wrong redaction
control is worse than a missing one, because people then trust it.** Owned by
the web-intake session (`pii_field_registry.py`, migration `b8e3d1f7a2c4`);
raised as urgent.

Root cause worth fixing rather than patching: display-config rows are cloned
once at form-type creation and never resynced, so any per-field policy will
drift across form types. Prefer applying by `field_id` across all form types.

## Landmine to defuse before building on this table

`pii_field_registry.py:170-172` forces `row.is_active = True` on the update
path (and the migration's `DO UPDATE` mirrors it). `field_mapping_service.py`
(`_build_fieldsitepi`) renders a field iff `is_active` AND
`subcategory_code IS NOT NULL`, so forcing it true would resurrect a
deliberately hidden mapped field onto the coding screen.

Inert **today**: no code path anywhere sets `is_active = False` on that table
(the admin field-edit handler hides a field by nulling the category codes
instead). It becomes live the moment anyone adds an is_active toggle — which
this work plausibly would. Fix defensively first: do not force `is_active`
on update, leave it at whatever it was.

## Contract this work depends on (being fixed by the web-intake session)

`_build_pii_field_ids` (`field_mapping_service.py:325-333`) currently filters
on `is_active = True` in the SAME query as `is_pii = True`. So **deactivating
a PII-flagged field drops it OUT of redaction and it gets exported.** Hiding a
field un-redacts it — failing in the direction nobody notices, because the
field disappears from the UI (looking like the intended effect) while
continuing to appear in the CSV.

This is live-relevant to this task specifically: a with-PII/without-PII
feature is exactly the kind of work that adds an is_active toggle, and doing
so on the current query would reproduce the leak the roles exist to prevent.

The fix decouples them: `is_active` governs DISPLAY only, `is_pii` governs
REDACTION only, and the redaction query stops filtering on `is_active`.

Root cause of the coverage gap, also being fixed: `form_type_service` copies
`is_pii` from the source form type when it clones field rows — at the clone,
export and import paths — taking the flag AS IT STOOD AT CREATION TIME.
WHO_2022_VA_SOCIAL was cloned before WHO_2022_VA was flagged, and nothing
resyncs. Applying by `field_id` fixes every form type that exists today; form
type creation now also applies the registry immediately, so a type created
tomorrow from an unflagged source does not start wrong. This matters to these
roles because a redaction set that silently excludes a whole form type is the
failure mode the roles cannot survive.

**Do not wire up any is_active toggle until that has landed.** Treat the
decoupling as the contract these roles rest on: once `is_pii = True`, a field
stays redacted regardless of display state. A regression test should assert
exactly that — a field flagged PII and deactivated is still redacted.

## Expected scope

- enum values + migration (`ALTER TYPE ... ADD VALUE` in an
  `autocommit_block()`, as the org_unit scope migration did)
- add `collaborator_pii` to `ROLES_ALLOWING_ORG_UNIT`
- **one redaction helper taking the viewer's role.** Never a per-screen
  condition — a screen that forgets fails open
- enforcement at every surface, not just the obvious one:
  - submission payload rendering (detail view, coding screen)
  - exports: the payload via `_filter_export_payload` **and base columns**,
    which bypass it entirely (see organization-model.md, "Unit columns in
    submission exports")
  - `va_submissions.va_data_collector` is a base export column today while
    the payload's `SubmitterName` is deliberately stripped — the same name,
    published and redacted at once. Close that inconsistency
  - **search**, not only display: `data_management_service.py:222` filters on
    `va_data_collector.ilike(...)`, so a no-PII viewer could confirm a
    collector's name by searching for it even if it is never rendered
  - API responses and the analytics MV
- admin UI: role picker, and the labels above
- tests: a plain `collaborator` sees redacted payload, redacted staff
  identity, redacted export (payload AND base columns) and cannot confirm a
  name via search; `collaborator_pii` sees all of it; existing roles
  unchanged

## Rollout

Making plain `collaborator` no-PII **removes** visibility from every existing
grant. That is deliberate and is the safe direction, but the migration must
NOT auto-upgrade anyone. Existing collaborators needing PII are re-granted as
`collaborator_pii` by an admin or PI, per person. Someone must work through
the current collaborator list — flag this to the user before release.

## Corrected 2026-09-18: a finding that was wrong

An audit reported that `/api/v1/organization/<project_id>/units` wrongly 403'd
global-scoped non-admin grants. It was accepted and "fixed", and a test was
written asserting a global `data_manager` reaches the whole tree.

It was wrong. `ck_va_user_access_grants_role_scope` permits `scope_type =
'global'` only for `role = 'admin'`, so such a grant cannot exist. The fix was
dead code and the test asserted an impossible state; both are reverted.

A follow-up proposed widening the constraint so the test would pass. **Do not.**
`global` means every project, present and future — a global `data_manager` or
`collaborator` would be one row granting all projects forever, which is what
`admin` is for.

Note also that "above-scope" in commit 497ae07 means a grant at a unit above
the project's `coding_scope_level_id`, entirely within one project's tree. It
does not mean global scope and needs no change to that constraint.

Rule taken from this: verify a finding's premise before acting, and hold
findings that propose RELAXING a constraint to a higher bar than those that
propose tightening one. A wrong tightening is an inconvenience; a wrong
relaxation is a vulnerability.

## Working-tree migration state (2026-09-18)

Two uncommitted migrations both chain onto the committed head
`2e1da5fbaa0a`: `b8e3d1f7a2c4` (PII flags, web-intake session) and
`f1c6a9d3e7b5` (collaborator_pii role, this work). That is the correct shape
for two independent changes, but it means a plain `flask db upgrade` in this
tree fails with multiple heads.

Use `flask db upgrade heads`, or name the revision. **Do not "fix" it by
chaining one onto the other while both are untracked** — chaining onto an
uncommitted revision is what broke `origin/main` earlier today (see
`8eae9f9`). Whoever commits second re-chains onto whatever is then the head.

## Every path that creates a field-config row must apply the PII registry

These roles treat `mas_field_display_config.is_pii` as the single source of
truth for what a no-PII viewer may not see. The consequence: **any code path
that creates a row on that table without applying the registry silently
widens what a "Viewer" can see.** The row arrives with `is_pii` at its
`False` default and the export leaks the field again.

Three such doors were found and closed on 2026-09-18, all by the web-intake
session:

1. form-type **clone** (`form_type_service`) — copied `is_pii` as it stood at
   creation time, which is how WHO_2022_VA_SOCIAL was born unflagged
2. form-type **import** — same copy
3. **ODK schema sync** (`odk_schema_sync_service.sync_selected` and
   `_register_new_field`) — created rows at the default and never applied the
   registry. Reachable from the admin field-mapping panel: register a form
   type, run ODK schema sync, and `Id10073` lands unflagged. Nothing corrects
   it but a manual `flask seed run`, which `boot.sh` never does.

A fourth was filed as a LOW follow-up on 2026-09-18: a standalone migration
entry point that does not call the registry. That it keeps happening is the
argument for the durable fix below, not for a fourth patch.

**If this work adds another way to create rows on that table, it must call
the registry too.** Check before adding one.

Worth revisiting once these roles land: the durable fix is a default applied
at row creation rather than a call remembered at each site, since the failure
mode is silent and the list of sites is only known by searching. Deliberately
not attempted during the fix of the three known doors.

## Field counts: do not record a bare count

The count of PII fields that are coder-mapped drifted twice in opposite
directions in one afternoon (12 -> 11 -> 12) because a count cannot be
checked without redoing the work. The correct figure is 12 mapped, 3
unmapped, the unmapped being `Id10073`, `abha_number`, `abha_address`.

Record the explicit field list, never the count.


## Built, and the gap that stops it working (2026-09-18)

Done and tested (14 tests, verified non-vacuous by the test runner):

- `collaborator_pii` exists and is grantable (`c04662c`)
- `should_redact_pii(user)` in `app/services/viewer_pii_service.py` — the one
  helper; redact only when the user holds no active grant with a role other
  than plain `collaborator`
- staff identity blanked on dashboard rows and in the unrouted-submissions
  API; the search path drops the collector, coder and reviewer name clauses
  so a name cannot be confirmed by searching for it

**THE GAP — the roles do not work yet.** A plain `collaborator` has no wired
route access at all: there is no `collaborator` entry in
`app/decorators/role_required.py`'s `_ROLE_METHODS`, no route calls
`role_required("collaborator")`, and `dm_scope_filter` resolves visible
project/site pairs from `data_manager` grants only.

So the redaction is correct and unreachable. It takes effect the moment
somebody grants collaborators access to these routes — which is an
access-WIDENING change and deliberately out of scope here. **Do not describe
the viewer roles as delivered until that is done.**

## Two surfaces still unredacted (update 2026-09-19: one closed, one open)

1. **Submission detail rendering** — `app/routes/data_management.py`
   `view_submission` -> `render_va_coding_page` -> the ~1300-line
   `renderpartial` route in `app/routes/va_form.py`. This is where subject PII
   actually renders to a viewer. Still not touched: too large and coupled to
   change safely without dedicated review. `role_required` on
   `view_submission` deliberately keeps `collaborator`/`collaborator_pii` out
   (route wiring, 2026-09-19) precisely so this stays unreachable until it
   is.

2. ~~**`dm_coded_cod_snapshot_export_csv`**~~ — closed 2026-09-19, together
   with two more of the same shape found while closing it:

   - `dm_coded_cod_snapshot_export_csv` — `coder_name`, `reviewer_name`,
     `nqa_name`, `social_autopsy_name`, `active_coder_assigned_name`,
     `active_reviewer_assigned_name`
   - `dm_submissions_export_csv` — the `*_by` user ids: `dm_review_by`,
     `initial_assess_by`, `coder_review_by`, `reviewer_review_by`,
     `final_assess_by`, `reviewer_final_assess_by`
   - `dm_coder_daily_statistics` — every row is a named coder and their
     throughput, so a redacted viewer gets **no rows**. Blanking the name
     would leave `coder_id` as a stable per-person key across days, which is
     the same disclosure by another route

   All three route through `should_redact_pii`; the columns are emptied, not
   dropped, because the submissions export documents that downstream
   consumers depend on its column offsets.

   The three SmartVA exports (`input`, `results`, `likelihoods`) were checked
   at the same time and have no gap: they emit no staff-identity column, and
   the input export's payload already passes through `_filter_export_payload`.

   **`narrative_text` is a BLOCKER on wiring the snapshot export to viewers,
   not a leftover.** Do not grant `collaborator` that export until it is
   resolved. It is the free-text death narrative and routinely carries the
   names of the deceased, the respondent and the attending clinician, in
   prose, where no field-level flag reaches them.

   It is deliberately NOT in `COD_SNAPSHOT_STAFF_IDENTITY_HEADERS`: it is
   subject personal data governed by `is_pii` on the payload field, not staff
   identity, and filing it under a staff-identity name would hand the next
   reader a category error. It is also unredacted everywhere else —
   `dm_submissions_export_csv` ships the same narrative to every role today —
   so redacting it on one export alone is an inconsistent half-change.

   The failure this wording exists to prevent: the staff columns now look
   handled, so the export reads as safe to widen, and a plain viewer gets the
   deceased's name in free text on the first row. Recorded as a blocker
   rather than an open item because an open item reads as deferrable
   tidy-up.

Surface 1 is still open and still gated on the wiring event. Whoever wires
collaborator access owns closing it at the same time, or the wiring itself
creates the leak.
