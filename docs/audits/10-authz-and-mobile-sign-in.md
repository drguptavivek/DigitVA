---
title: "Security Review — Authorization Module, Callers, Mobile Sign-In"
doc_type: audit
status: active
owner: engineering
last_updated: 2026-10-03
---

# Security Review — Authorization, Callers, Mobile Sign-In

Review of `app/services/authz/` and its callers against
[Access Control Model](../policy/access-control-model.md), plus mobile sign-in
against [Mobile Sign-In](../policy/mobile-sign-in.md). 2026-10-03.

**Method.** Static review. Every `file:line` below was verified directly
against the working tree. No finding was reported from an agent's relay
without re-reading the cited code. No HTTP endpoint was executed and no
exploit was replayed; exploit paths are derived by tracing the code.

**Severity.** Critical — unauthorized access to another project's data or
privilege escalation. High — cross-site or cross-unit access, or a write the
role must not have. Medium — narrower scope escape, or a fail-open that is
hard to trigger. Low — robustness, or drift with no current exposure.

## Findings

### CRITICAL

#### 1. Renaming an org unit rewrites authorization paths in every project

`app/services/organization_service.py:843-855`

```sql
UPDATE mas_org_unit SET path = ...
WHERE path <@ CAST(:old_path AS ltree)
```

`_rewrite_subtree_paths` filters on path containment alone. `update_unit`
(`:859`) validates the unit and the new code only within the supplied project
(`:865`, `:902-908`), then calls the helper at `:929` with two bare strings.

`mas_org_unit` is unique on `(project_id, unit_code)` only
(`app/models/mas_organization.py:100-104`); paths are not unique, and
[Organization Model Policy](../policy/organization-model.md) "Unit, cadre and
worker codes are unique **within one project only**" expressly permits reuse
across projects. Ordinary valid data is therefore sufficient.

1. A PI of project A renames A's `D1` to `D2`. `D2` need not exist in A.
2. Project B has roots `D1` and `D2`. B's `D1` subtree is rewritten to `D2`.
3. `authz` subtree matching (`app/services/authz/predicates.py:93-115`)
   requires `path <@ granted.path` **and** `covered.project_id ==
   granted.project_id`. The project equality cannot repair paths already
   overwritten inside B — B's former `D1` now *is* B's `D2`.
4. The actor only needs their own existing `B/D2` grant to absorb a whole
   foreign subtree.

A PI holding no grant in B still corrupts B's authorization tree, which also
corrupts B's own authorization decisions for everyone else.

Violates: `docs/policy/access-control-model.md:445-446` (a unit grant covers
one node and
its subtree; the node's project is the grant's project) and
`organization-model.md:348-349` (PI authority is limited to own projects).

**Fix.** Pass `project_id` into `_rewrite_subtree_paths` and add
`WHERE project_id = :project_id`. `set_unit_active`
(`organization_service.py:994-1000`) already does exactly this; the correct
pattern exists 150 lines below the defect. Add a two-project regression with a
differently named sibling in the victim project.

### HIGH

#### 2. `_PII_GRANTING_ROLES = frozenset(VaAccessRoles) - {VaAccessRoles.collaborator}
```

`interview_supervisor` is therefore treated as a PII-unlocking role, against
[Web Intake Policy](../policy/web-intake.md): "an `interview_supervisor`
grant does not lift redaction anywhere else."

Path: a user holds `collaborator` on district D2 and `interview_supervisor`
on D1. `can(VIEW)` on a D2 submission succeeds through the collaborator lens;
`should_redact_pii` then returns `False` solely because of the unrelated D1
grant, and the viewer receives unredacted subject and staff identifiers on a
plain-viewer screen.

This is the failure direction the policy warns about: the role list is where
new roles silently land.

**Fix.** Replace the complement with an explicit allowlist excluding
`interview_supervisor` as well as `collaborator`; keep intake-specific
identifier access separate. Test: mixed collaborator + supervisor holds
`VIEW` while `should_redact_pii` stays `True`, with a qualifying
`collaborator_pii` grant as the positive control.

#### 3. Dormant grants on deactivated units still suppress redaction

`app/services/viewer_pii_service.py:68-90`

`should_redact_pii` resolves each grant's project through its own
subqueries, which test identifier equality only — never `unit.is_active` or
`project_site_status`. Compare `app/services/authz/grants.py:199-215`, which
applies both.

Deactivating a unit deliberately leaves the grant row active
(`organization-model.md:407-409`). So a user whose `collaborator_pii` unit
grant was deactivated resolves **no** access through it (correct), yet
`should_redact_pii` still finds it and stops redacting their remaining plain
`collaborator` screens.

This is not the documented per-user mixed-role PII rule: the grant used to
defeat redaction no longer resolves to access at all.

**Fix.** Resolve redaction from the same grant relation the access resolvers
use, or add the active-pair and active-unit predicates to the helper's
target-resolution subqueries. Cover deactivate/reactivate for both unit and
pair scope, with `grant_status` active throughout.

#### 4. Resume and allocation paths trust a stale allocation

`app/routes/coding.py:246-258` — `role_required` plus allocation ownership,
then render. Same shape at `app/routes/reviewing.py:212-218` and
`GET /api/v1/coding/allocation` (`app/routes/api/coding.py:63-97`), which also
returns masked SID, age,
gender and collector.

Service-side, `app/services/coder_workflow_service.py:637-639` and `:693-697`
return an existing allocation **before** any scope check. Verified:
`allocate_pick_form` calls `_require_coder_access` at `:699`, but only on the
new-allocation path.

A coder whose grant is narrowed, or whose submission is rerouted outside the
unit, keeps both the page and the allocation JSON.

Violates: `access-control-model.md:506-508` (coder and reviewer views check
the submission's own unit, not only form access) and
[Attachment Storage](../policy/attachment-storage.md) ("an old allocation or coder outcome grants
nothing after reroute").

**Fix.** Call the current authz action for the track (CODE/RECODE for coder,
REVIEW for reviewer) before rendering or returning any active allocation, in
both the routes and the service's existing-allocation branches. Allocation
ownership must not substitute for current scope.

#### 5. `coding_tester` can allocate on deactivated project-site mappings

`app/models/va_users.py:513-515` applies `active_project_site_exists` only
when `role == 'coder'`. The tester authorization lane deliberately runs with
`active_pair=False` (`predicates.py:213-220`), and the pool gate helper finds
no active mapping and continues without excluding the pair
(`coder_workflow_service.py:248-257`, `:280-299`).

Result: a tester with a project- or unit-scoped `coding_tester` grant can
allocate and write coding artifacts for a retired (project, site) pair.

Violates: `access-control-model.md:348-354` (coder-visible forms must resolve
to an active `va_project_sites` mapping) and `:386-390` (a tester waives
coding gates "but **never** scope").

**Fix.** Apply the active-mapping predicate to non-virtual
`coding_tester` form resolution and to CODE pool filtering. Keep the waivers
for `coding_enabled`, date and daily limits only.

#### 6. DM coder roster leaks coder identities across projects

`app/routes/api/dm_kpi/dm_kpi_coders.py:255-268`

```sql
WHERE g.project_id = ANY(:project_ids) OR g.project_id IS NULL
```

`org_unit` grants store `project_id` NULL, so every active unit-scoped coder
grant in **every** project satisfies the predicate. The result includes name,
email and languages, and `active_allocations` is counted without a scope
predicate.

`access-control-model.md:498-501` is explicit: coder *counts* keyed by grant
project may include a unit grant's project, but "the coder roster, which names
coders, stays on project and site grants only."

**Fix.** Drop the NULL-project fallback. Restrict named rows to
project/project_site grants resolving into the direct roster scope; scope any
retained allocation totals to those same projects.

### MEDIUM

#### 7. Coder workflow history filters by form, not the submission's current unit

`app/services/coder_dashboard_service.py:180-230` and `:309-380` constrain
only `VaSubmissions.va_form_id.in_(accessible_form_ids)`, with no per-SID
scope predicate. The unit-scoped form getter includes a form whenever *any*
submission on it sits in the unit subtree, so the form-level filter is wider
than the current routed submission scope.

A unit coder whose form stays reachable through a sibling submission sees an
out-of-unit submission's masked identifier, age, gender and date in history, and may be told it is recodeable.

`access-control-model.md:506-508` requires workflow history to check the
submission's own unit.

**Fix.** Pass the user into the history and recodeable queries and add the
same per-submission authz predicate the coding and view paths use.

### LOW — policy and implementation drift

| # | Finding | Where | Note |
|---|---------|-------|------|
| 8 | `SYNC_FORM` admin bypass differs between list and object checks. The list bypass returns true unconditionally; the single-form branch still requires an active pair for admins. Fail-closed, so no exposure, but administering a retained form after its mapping is deactivated is refused. The parity sweep only walks `SUBMISSION_ACTIONS`, so nothing compares them. | `predicates.py:349-350`, `:450-464`; `tests/authz/test_single_source.py:23-34` | Make the admin branch require only that the form exists; add an admin case for a form on an inactive pair. |
| 9 | Project-user import validates unit state and cadre **before** `can_grant`, emitting "unit code is unknown or inactive" and cadre errors first. Existence oracle, and the opposite of the required ordering. Reachability from a subtree-limited actor was not verified. | `project_user_import_service.py:185-211` then `:212-221`; `access-control-model.md:550-557`; digitva-xd1q | Authorize the requested target first; normalize missing and unauthorized units to one refusal for non-admins. |
| 10 | A `project_site` grant counts as `is_wide` (`grants.py:62-65`), so `_can_pin_to` (`predicates.py:491-506`) lets a `(P, site A)` manager target any unit in P. The normative policy says routing stays inside the manager's own subtree and a pair has no units below it. | `access-control-model.md:480-486`, `:559-564`; design doc `.tasks/digitva-0wc-design.md:261` allows it | Documented in the design record, so this is drift between the normative policy and the design, not an undocumented fail-open. Reconcile one side. **Owner decision 2026-10-03: the code is right** (a project-site manager may pin to any unit of the project); policy updated. |
| 11 | Mentor grants lost the district-issuer rule. `can_grant` has no grantee identity, and `check_mentor_grant` takes no actor, so a CHC/PHC data manager can issue `collaborator_pii` to an institute member. The recipient guard itself is correct. | `grant_writes.py:140-152`, `:173-181`; `mentor_institute_service.py:581-604`; `organization-model.md:482-489` | The design doc (`:307`) deliberately subsumed it; the normative policy still says district-or-above. Same reconciliation task as #10. **Owner decision 2026-10-03: the code is right** (a CHC/PHC data manager may issue mentor grants, `collaborator_pii` included); policy updated. |
| 12 | `coding_tester` artifacts are indistinguishable from real coder output: same rows, same `by_role='vacoder'`, no provenance marker. Tester coding lands in real dashboard totals, DM coder-output and burndown counts, and the 24-hour sweep advances those submissions to reviewer-eligible. | `coder_workflow_service.py:684-691`, `:751-756`, `:913-939`; `coder_dashboard_service.py:111-155`; `dm_kpi_coders.py:155-172`; `dm_kpi_burndown.py:179-190`; `access-control-model.md:373-390` | Metric and workflow-state pollution, not a read leak. Persist tester/demo provenance and exclude those rows from production counts and transitions. |
| 13 | Utilization and language-gap SQL mishandle unit-grant project identity: utilization treats NULL `project_id` as a wildcard and overcounts; language-gap omits unit-grant coders and reports a false gap. | `dm_kpi_coders.py:64-86`; `dm_kpi_language.py:96-109`; `access-control-model.md:498-500` | Resolve the unit grant's project through `mas_org_unit`; never use NULL as a wildcard. |

## Checked and clean

Recorded so the next review does not re-cover them.

- **Attachments.** `app/services/attachment_service.py` resolves the record
  before authorizing, authorizes with `authz.can(READ_ATTACHMENTS, va_sid)`
  freshly, and denies redacted viewers. Neither the opaque-token route nor the
  deprecated filename route treats a client path or token as a capability, and
  delivery only ever receives an already-authorized record.
- **Data management pages and APIs.** `app/routes/data_management.py`,
  `app/routes/api/data_management.py` and
  `app/services/data_management_service.py` gate correctly. Sync status is
  intentionally system-level and explicitly refuses unit-only scope, matching
  the policy that whole-form operations need a project or site grant.
- **Site PI report.** `app/routes/sitepi.py:105-134` re-authorizes every
  selected pair and unit with `authz.can(SITE_PI_REPORT)`; selection values are never
  treated as authorization.
- **Unrouted routing destination.** The subtree bound on the *destination* unit
  is correct; a unit manager cannot route outside their own subtree.
- **Mentoring institute recipient guard.** Correctly restricts a member to
  `org_unit` grants of coder, reviewer, coding_tester or collaborator_pii
  inside an attached district.
- **Closed projects.** Grants are never deleted or deactivated; resolution is by
  project status and admin reach is unchanged.
- **Legacy `vasitepi` action.** Removed 2026-10-03 (digitva-a00o);
  `_ACTION_VALIDATORS` in `app/decorators/va_validate_permissions.py:242-247`
  contains only `vacode`, `vareview`, `vadata`, `vaarea`, all of which route
  through `authz.require`. No residual bypass.

## Mobile sign-in — no findings

`app/services/mobile_sign_in_service.py` and migration `f3a8c1d6e2b9`, checked
against `docs/policy/mobile-sign-in.md`. This is the strongest code reviewed.

- **The credential is per-person, not per-app.** Codes are stored as
  `keyed_hash(f"{user_id}:{code}")` (`:98-100`), so one code value never hashes
  alike for two people, and there is no shared app secret anywhere in the flow.
- **Constant-time comparison.** `hmac.compare_digest` at `:236`.
- **No timing oracle.** `_NO_ROW` (`:52`) makes the unknown-identifier and
  wrong-code paths execute identical statements (`:218-234`), so a live code
  and a bogus one are indistinguishable by timing.
- **Brute force is bounded.** The `FOR UPDATE` lock at `:226-234` serializes
  guesses and the fifth failure voids the code (`:238-254`), so a code is
  compared at most `MAX_CODE_FAILURES` times in total. Redemption is further
  rate-limited at the route (10 per minute per IP, 10 per hour per identifier).
- **Issuance is properly gated.** `may_issue_code` (`:103-137`) requires the
  actor to manage **every** active grant the target holds, none of them
  privileged or global-scoped, and the target to have **no** verified email —
  which closes the takeover where a manager redeems their own code against a
  peer's address. The refund side is rate-limited to 20 per hour per caller.
- **Migration is additive and reversible.** `email` becomes nullable with the
  unique constraint intact; the backfill fills `mobile_login` only where the
  canonical number is unambiguous; `downgrade()` refuses while any account has
  no email rather than leaving one with no way to sign in; the one-live-code
  invariant is a partial unique index, so the **database** enforces it rather
  than application code.

Residual, non-security observation: a 6-digit code with a 72-hour TTL is a
1-in-a-million secret per person, protected only by the 5-attempt void and
route-level rate limiting. That matches the spec as written; flagging it as
worth a periodic re-read if the TTL or attempt budget ever changes.

## Suggested order of work

1. **#1** — one-line `project_id` predicate, copying `set_unit_active`.
2. **#2 and #3** — one piece of work: both are fail-open PII in
   `viewer_pii_service`, and the fix is the same explicit allowlist plus the
   active-target predicates.
3. **#4 and #5** — scope escape on the coding track.
4. **#6 and #7** — read scope, coder track and DM analytics.
5. **#10 and #11** — decide which side is authoritative, then reconcile the
   other. These need an owner decision, not a patch.
6. **#8, #9, #12, #13** — hygiene.

Findings #8 through #13 were confirmed statically but not exercised against a
running instance; #9 and #11 in particular depend on current HTTP reach, which this review
did not establish.