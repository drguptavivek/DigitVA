---
title: "Security Review — Cross-App Authorization Sweep"
doc_type: audit
status: active
owner: engineering
last_updated: 2026-10-03
---

# Security Review — Cross-App Authorization Sweep

App-wide check that every route and service makes its access decisions through
`app/services/authz/` and gives the result the policy requires. Policy is the
standard: [Access Control Model](../policy/access-control-model.md),
[Organization Model](../policy/organization-model.md),
[Web Intake](../policy/web-intake.md),
[Attachment Storage](../policy/attachment-storage.md),
[Mobile Sign-In](../policy/mobile-sign-in.md),
[Account Onboarding and Passwords](../policy/account-onboarding-and-passwords.md).
2026-10-03. Findings of
[review 10](10-authz-and-mobile-sign-in.md) (#1–#13) are not re-reported; the
status of their fixes is recorded below, and incomplete fixes are findings
here.

**Method.** Static review. Six parallel sweeps (HTML routes, JSON APIs,
device/Expo APIs, service-layer list queries, PII surfaces, grant writes and
tasks) produced candidates; every candidate below was re-verified directly
against the working tree, with fresh `file:line` quotes. Scout-only claims
that failed re-reading (three did — see "Checked and clean") are recorded so
the next review does not repeat them. No HTTP endpoint was executed; paths are
derived by tracing code.

**Cross-verification (2026-10-03).** A second, independent read-only pass
re-traced every finding. It confirmed #1, #2, #7, #8 and #12; narrowed
findings #3 and #4 (who can reach them) and downgraded #4 to Low; corrected the proposed fixes
for #2 and #3, which were wrong as first written; added a missed caller to #1
and #11 and a missed PII case to #3; and withdrew #9 as stale. Corrections are
folded into the findings below and marked *(cross-check)*. Line numbers drift
while the tree is being edited; the function names are the stable anchor.

**Severity.** Critical — another project's data, or privilege escalation.
High — cross-site or cross-unit access, or a write the role must not have.
Medium — narrower escape, or a fail-open that is hard to trigger. Low — drift
with no current exposure.

## Status of review-10 fixes

Verified fixed in the working tree: **#1** (`organization_service.py:843-862`,
`_rewrite_subtree_paths` filters `WHERE project_id = :project_id`);
**#2** (`viewer_pii_service.py`, `_PII_GRANTING_ROLES`, an explicit allowlist
excluding `collaborator` and `interview_supervisor`); **#3**
(`viewer_pii_service.py:55-74`, redaction resolves through
`authz.resolve_grants`, so closed projects and deactivated units/pairs cannot
hold it open); **#4** (routes `coding.py:247-263`, `reviewing.py:212-227`,
`api/coding.py:63-97` and service `coder_workflow_service.py:627-643`,
`:787-788`, `:803` re-derive scope on every resume and existing-allocation
branch); **#5** (`va_users.py:497-498` applies the active-pair predicate to
`coding_tester` too; `predicates.py:210-228` tester lenses carry
`active_pair=True`); **#8** (`predicates.py:458-461` admin `SYNC_FORM` = form
exists, matching the list bypass); **#9**
(`project_user_import_service.py:181-221` asks `authz.can_grant` before unit
and cadre validation, one refusal for non-admins); **#13**
(`dm_kpi_scope.py:55-66` `GRANT_PROJECT_SQL` resolves a unit grant's project
through its active row; NULL is never a wildcard — the active-coders count
`dm_kpi_coders.py:88-97` reads through `scope.sql()`, language gap
`dm_kpi_language.py:107-121` through `GRANT_PROJECT_SQL = ANY(:project_ids)`).

**#6** is fixed: the leak is closed and the policy roster sentence was amended
in commit 65019606 to admit a unit manager's coders on units in its subtree
(owner decision 2026-10-03, digitva-4b3e), matching `grant_in_scope_sql`.
**#7** is fixed for history (`coder_dashboard_service.py:186-239` applies
`scope_filter(user, Action.VIEW)`) but the sibling count path was missed
(finding 5). **#12** is half-done: demo sessions got provenance
(`mark_demo_started`), coding-tester artifacts did not (finding 6).

## Findings

### HIGH

#### 1. NQA and Social Autopsy saves authorize by allocation ownership only

`app/utils/va_permission/va_permission_11_require_coding_access.py:30-40`

```python
alloc = db.session.scalar(
    sa.select(VaAllocations.va_sid).where(
        VaAllocations.va_allocated_to == current_user.user_id,
        VaAllocations.va_allocation_for == VaAllocation.coding,
        VaAllocations.va_allocation_status == VaStatuses.active,
        VaAllocations.va_sid == va_sid,
    )
)
```

The coder/coding_tester branch of `POST /api/v1/va/<sid>/narrative-qa`
(`app/routes/api/nqa.py:75`) and `POST /api/v1/va/<sid>/social-autopsy`
(`app/routes/api/so.py:73`) delegates here and nothing more; the routes carry
only `role_required`, and the helper checks only the demo gate and the
allocation row. The reviewer branch in the same routes does it right:

```python
# REVIEW scope as well as the allocation: an allocation that outlived
# a re-routing or a narrowed grant does not carry the save.
if not can(current_user, Action.REVIEW, va_sid):        # nqa.py:62, so.py:60
```

The branch is chosen by the client's `va_actiontype`; any value other than
`vastartreviewing` lands in the unscoped coder branch.

An allocation is ownership, not scope, and it outlives both: rerouting the
submission (`route_submission`, `pin_submission_org_unit` set `org_unit_id`
only), revoking the coder grant, or closing the project does not release the
row. `release_stale_coding_allocations` releases only allocations older than
one hour; it runs inside the allocation entry points
(`coder_workflow_service.py:655`, `:708`) and from an hourly beat task
(`sync_tasks.py:2348-2363`) *(cross-check: the audit first said entry points
only)*. The exposure window is therefore up to about two hours. The codebase
already states the rule — `coder_workflow_service.py:630-641`, "Holding an
allocation is ownership, not scope" — and enforces it for resume; the save
paths are the ones that do not.

Path: a coder is allocated submission S while granted on unit U; a data
manager re-routes S to unit V outside their subtree; the coder POSTs an NQA
or Social Autopsy payload for S — the write succeeds and lands an active
artifact on a submission they may no longer even `VIEW`.

*(cross-check)* A third caller shares the gap: `app/routes/api/icd10.py:110`,
`_require_coding_or_reviewing_access`, guarding the ICD search routes
(read-only, lower impact). Fixing the two routes alone would leave it open.

Violates: `access-control-model.md`, "Authorization Rule" —
"Workflow-specific constraints … **do not replace role and scope checks**" —
and "Every other per-submission surface … checks the submission's own unit,
not only form access."

**Fix.** Inside `require_coding_access` — the one choke point for NQA, Social
Autopsy and ICD search — after the allocation check, add
`authz.can(current_user, Action.CODE, va_sid)` and return the JSON 403 the
helper already uses. Prefer `can` to `_require_coder_access`, which raises
`AllocationError` and would need translating. Demo coders still pass (demo
virtual grants cover CODE, `authz/grants.py:239-286`); admin demo returns
before the allocation check; CODE and RECODE share a lens
(`authz/actions.py:80-81`), so recode allocations are unaffected.

**Test.** Coder with an active allocation; reroute the submission's unit out
of the coder's subtree; `POST …/narrative-qa`, `…/social-autopsy` and an ICD
search → 403, and no `va_narrative_assessments` row. Positive control: the
same requests before the reroute → 200/201.

#### 2. Intake drafts are authorized by ownership only after creation

`app/services/web_intake_service.py:1065-1074`

```python
draft = db.session.get(VaWebIntakeDraft, uuid.UUID(str(draft_id)))
…
if draft is None or draft.user_id != user.user_id:
    raise WebIntakeError("Draft not found.", 404)
```

`start_draft` runs `_require_scope` (`:1010`) and `get_death` re-checks it
(`:605-610`), but reading, saving, discarding and submitting a draft never do:
`GET /intake/form/<draft_id>` (`app/routes/intake.py:66-72`),
`GET /intake/api/drafts/<id>` (`:307-321`),
`PATCH /intake/api/drafts/<id>` (`:323-341`), discard (`:343-350`) and
`POST /intake/api/drafts/<id>/submit` (`:355-362`) all pass through
`get_draft`, and `submit_draft` (`web_intake_service.py:1409-1432`) checks
only `_require_live_org_unit` — the unit's liveness, never the caller's grant.
The route gate `@role_required("interviewer")` is `u.is_interviewer()`
(`app/decorators/role_required.py:63`) and passes whenever the user holds
*any* interviewer grant anywhere. A user who loses every interviewer grant is
blocked; the exploit needs one remaining grant elsewhere.

Path: an interviewer holds interviewer grants on (A, S1) and (B, S2) and
starts a draft for A:S1. The A grant is revoked (or project A is closed). The
user still passes the role gate through B, then reads the draft's stored
answers, saves sections, and submits — creating a `va_submissions` row and
moving a case inside a project, site or unit they no longer hold.

*(cross-check)* `list_drafts` (`:1058`) filters by `user_id` only, so the
revoked draft also keeps appearing in the user's list. Minor, and outside the
`get_draft` choke point.

Violates: `web-intake.md`, "Role gate vs scope" — "Which project, site and
unit a questionnaire may actually be filled for is decided separately, by
`web_intake_service.interviewer_context()` and `_require_scope()`. **The role
gate never widens scope**" — and `access-control-model.md` rule 3 (the target
record must fall inside one of the user's explicit grants).

**Fix.** Re-check the grant in `get_draft`, after the ownership check — one
choke point for page, GET, PATCH, discard and submit — and answer a grant
failure with the same "Draft not found." 404 `get_death` uses, so an id is
never an existence oracle.

*(cross-check: the fix as first written was wrong.)* Do not call
`_require_scope(user, draft.project_id, draft.site_id, draft.org_unit_id)`
unguarded. Besides the grant 403, it raises 400s for unit state: "That
organization unit is not active in this project" (`:366-367`) and "Choose the
organization unit for this entry" (`:343-348`, `:353`, for a null-unit draft
in a project with units). Raised from `get_draft`, those would:

- block discard of a draft whose unit was deactivated after it was started,
  leaving the case `in_progress` with no way out;
- pre-empt the deliberate 409 in `_require_live_org_unit` (`:1314-1335`) at
  submit;
- refuse null-unit drafts that `submit_draft` accepts today.

Translate only the grant failure into the 404 and let unit-state checks stay
where they are (the live-unit check still guards submit) — either by catching
only the 403 from `_require_scope`, or by checking reach directly through
`interviewer_context` and `_reachable_unit_ids`. Filter `list_drafts` by the
same reach.

**Test.** Two-project interviewer; revoke project A's grant; GET, PATCH,
discard and submit of the A draft → 404, no submission row, no case-state
change, and the draft is absent from `list_drafts`. Positive control: all
succeed before the revocation. Regression: deactivate the draft's unit with
the grant intact → discard still succeeds and submit still answers the 409.

### MEDIUM

#### 3. Cached data-manager exports are re-served without a fresh scope check

`app/routes/api/data_management.py:183-222` (`_serve_cached_export_csv`)

```python
ref = export_store.export_cache_lookup(
    export_kind=export_kind,
    user_id=current_user.user_id,
    filters=filters,
    ttl_seconds=ttl_seconds,
)
if ref is not None:
    response = _deliver_export(ref, filename, cache_status="HIT")
```

The cache identity is export kind + user id + filter set only
(`export_store_service.py:128-139`, `filter_hash(export_kind, user_id,
filters)`); TTL is 900 s (`data_management.py:74`, overridable by
`DM_EXPORT_CACHE_TTL_SECONDS`). On a hit, `export_fn` — where the scope query
(`_dm_submission_query_parts`) and `should_redact_pii` run — is skipped, and
`_deliver_export` sends the stored CSV or a 302 to its presigned URL with no
authorization call. All five DM CSV exports go through this helper —
submissions, smartva_input, smartva_results, smartva_likelihoods and the
coded-COD snapshot, which carries `narrative_text` (`:263-313`).

*(cross-check: reach narrowed.)* Full revocation is not exploitable: the route
gate `role_required("data_manager")` resolves live grants through
`effective_roles` and runs before the cache lookup, so a user with no
DM-capable grant left gets 403. The exposure is a user who still holds some
DM-capable grant (data_manager, or a site_pi/project_pi grant that implies
it) while their scope narrows or their cases move.

Paths:

- **Narrowing.** A DM with two grants exports the submissions CSV; one grant
  is revoked; they re-request the same URL and receive the wider file for up
  to 15 minutes.
- **Re-routing.** Cases are re-routed out of a unit DM's subtree; the cached
  file still holds them.
- **Lost PII grant** *(cross-check: missed)*. A user loses the grant that
  entitles them to unredacted PII but keeps the DM role; the cached unredacted
  CSV — narratives included — is still served. This is the more sensitive
  case.

Violates: `attachment-storage.md`'s matrix principle — "The decision is never
cached, never inferred from a token, and never moved into templates" — and
`access-control-model.md` "Every access goes through authz": the request is
answered without consulting authz at all.

**Fix.** *(cross-check: the fix as first written was wrong.)* The first draft
named `dm_grant_scope(current_user)` and `DmScope.digest` "in
`dm_kpi_scope.py`". `dm_grant_scope()` (`data_management_service.py:374`)
returns `DmGrantScope`, which has no digest; `DmScope.digest()` is a method
in `app/routes/api/dm_kpi/dm_kpi_scope.py:217-225`, reached through
`dm_scope()`. More importantly, that digest hashes only active pairs and unit
grant ids: it misses re-routing (the grant set is unchanged while
`s.org_unit_id` changes), redaction state, and project-to-pair grant swaps
that expand to the same pairs. A `scope_filter(LIST_DATA)` re-check on a hit
misses redaction too. Workable options:

- key the cache on a fingerprint of scope **and** `should_redact_pii(user)`,
  and accept that re-routing stays a data change bounded by a short TTL; or
- drop the export cache for scoped exports, or cut the TTL to a value the
  owner accepts as the re-routing window.

**Test.** Use a two-grant DM, not a full revocation (which 403s at the gate
regardless of the cache): export; revoke one grant; re-request → cache miss
and a narrower file. Second case: revoke the PII-entitling grant, keep DM →
re-request yields a redacted file. Positive control: unchanged grants →
`X-Export-Cache: HIT`.

**Severity.** Medium, at the low end: it needs a still-valid DM role, a
concurrent narrowing, and the TTL window, and the user previously held
legitimate access to the data; the PII case keeps it above Low.

### LOW

#### 4. The site-PI pair report serves a deactivated (project, site) pair to the project PI

*(cross-check: downgraded from Medium; the site_pi path in the first draft is
not reachable.)*

`app/services/sitepi_reporting_service.py:224-246`

```python
return _dashboard_data(
    "f.project_id = :project_id AND f.site_id = :site_id",
    """g.scope_type = :project_site_scope
     AND g.project_site_id IN (
         SELECT ps.project_site_id
         FROM va_project_sites ps
         WHERE ps.project_id = :project_id
           AND ps.site_id = :site_id
           AND ps.project_site_status = :active_status
     )""",
```

The first argument is the submission filter — no active-pair predicate — and
it is reused in the work and error subqueries, so KPIs, rows and per-coder
counts all cover the inactive pair. The second argument constrains only the
coder roster. The project-wide variant (`:188-203`) and the unit variant
(`:249-267`) both exclude inactive pairs; the pair variant alone does not.
The object check agrees with the gap: `_can_site_pi_report`'s pair branch
(`predicates.py:516-537`) admits an admin, a project_pi of the project, or a
matching pair-scoped site_pi grant, without looking at `project_site_status`.

Who can reach it. A **site_pi** cannot: grant loading (`authz/grants.py:185-216`)
outer-joins the pair on `project_site_status = active`, so a pair grant on a
deactivated pair either drops out or carries `site_id = None`, and the
predicate's `x.site_id == site_id` never matches. A **project_pi** of the
project can: the predicate admits any `site_id` for a project in
`pi_projects`. `_report` (`sitepi.py:105-142`) accepts any `project:site`
string from `?siteSelect=`; the options list offers only active pairs, but a
hand-typed or stale selection for deactivated pair (A, S) renders the full
report for forms still keyed to (A, S). The same branch admits nonexistent
sites (an empty report, harmless).

Why Low: the user is a PI of the same project with legitimate project-wide
reach; nothing crosses projects. It is drift from the app-wide rule —
"Data-management and viewer reach stops at a deactivated (project, site) pair"
(`predicates.py:255-258`) — not a leak.

**Fix.** Add the same `EXISTS (… ps.project_site_status = 'active')` predicate
to the pair path's submission filter, copying `:197-201`; in
`_can_site_pi_report`'s pair branch require an existing active pair for the
project_pi path, so list and object stay identical.

**Test.** Deactivate pair (A, S); a project_pi of A requests
`?siteSelect=A:S` → 404; the project-wide report is unchanged. Positive
control: an active pair renders as before.

#### Policy and implementation drift

| # | Finding | Where | Note |
|---|---------|-------|------|
| 5 | Coder authored-output counts ignore current scope and confirmed duplicates. `get_coder_output_summary` filters only `va_finassess_by`, active status and non-demo; `get_coder_completed_count` and `get_coder_not_codeable_count` discard the `accessible_form_ids` their callers (`coding.py:81`, `api/coding.py:231`) pass. The history query beside them applies `scope_filter(user, Action.VIEW)`; the counts do not, so a rerouted-out final is still counted. *(cross-check)* Neither counts nor history apply `not_confirmed_duplicate_condition` (its only use in the file is the recode query, `:390`); the first draft wrongly said history did. | `coder_dashboard_service.py:110-177`; history contrast `:186-239`; policy: "checks the submission's own unit, not only form access", and `coding-workflow-state-machine.md:51` duplicate exclusion covering "coder and reviewer dashboard counts" | Accept `user`; add `scope_filter(VIEW)` to the counts and the duplicate predicate to both counts and history. The summary is cached through `_cached_dashboard_project_value`: the key or invalidation must reflect scope. Test: reroute a finalized case out of the coder's unit → count drops; confirm a duplicate → count and history drop; positive control: in-scope final counted. |
| 6 | Review-10 #12 fix incomplete: coding-tester artifacts remain unmarked and counted. `by_role="vacoder"` is hard-coded for every coding session, tester or not (`coder_workflow_service.py:696`, `:764`; the `else admin_actor` branch at `:591` is effectively dead); `demo_session` provenance exists only for demo (`:592`, `mark_demo_started`). DM C-12/C-24 (`dm_kpi_coders.py:148-172`) count every active `va_final_assessments` row with no role filter, and the recode-window sweep `mark_reviewer_eligible_after_recode_window_submissions` (`:914-950`) advances tester-finalized submissions to reviewer-eligible. | `coder_workflow_service.py:591-596`, `:696`, `:764`, `:914-950`; `dm_kpi_coders.py:148-172`; policy `access-control-model.md:381-382`, `auth-decorator-rbac.md:57`: "its coding does not count toward results or real workflow counts" | Persist tester provenance on the final/review rows; exclude it from production counts and the sweep (schema-touching). *(cross-check)* Arguably Medium: through the sweep, tester output reaches real reviewer queues. Not an authz leak. Test: tester finalizes → C-12 unchanged and the submission not reviewer-eligible; positive control: coder final counted. |
| 7 | The coded-COD snapshot export's only PII guard is its route gate. `narrative_text` ships as a base column (`:1664`, `:1746`); `should_redact_pii` (`:1622`) is computed but cannot cover it. The route is `data_manager`-only today and data managers are on the PII allowlist, so nothing is exposed — but the policy blocker that `narrative_text` must be resolved before any widening is still unresolved, and the guard is one `role_required` edit away from failing open. | `data_management_service.py:1622-1746`, route `api/data_management.py:305-313`; policy `access-control-model.md:315-335`: "Do not grant `collaborator` the coded-COD snapshot export until `narrative_text` is resolved … it is the column that carries the deceased's name" | Resolve the `is_pii` decision across both exports, or refuse redacting viewers at the route (`should_redact_pii` → 403). Test: redacting viewer → 403; positive control: data manager → 200. |
| 8 | The policy's Redis grant cache ("Redis cache for grant lookups", owner 2026-10-03: per-user version, global version, 5-minute TTL, DB fallback) is not implemented. `resolve_grants` memoizes per request only ("No cross-request cache") and `invalidate` clears that memo; admin/CLI writes that skip `authz.invalidate` are therefore inert today — and become stale-window bugs the day the cache lands. Safe direction: a revoked grant bites on the next request. | `authz/grants.py:297-325`; policy `access-control-model.md:821` "Redis cache for grant lookups" | Implement the cache per policy, or amend the policy to request-local resolution. Test (when implemented): a grant write bumps the per-user version; control: revocation visible on the next request. |
| 9 | **Withdrawn** *(cross-check: stale)*. The first draft said the policy still restricts the DM coder roster to project and site grants. That text is from review 10 (`10-authz-and-mobile-sign-in.md:178`); the policy was amended in commit 65019606 (`access-control-model.md:505-509`, owner decision 2026-10-03, digitva-4b3e) to admit a unit manager's coders on units in its subtree, and `grant_in_scope_sql` (`dm_kpi_scope.py:142-160`, `dm_kpi_coders.py:250-268`) matches it. | — | No action. |
| 10 | `GET /site-maintenance-status` is public and not named in the policy's reviewed public list. It exposes only the maintenance flag and message (it feeds the sign-in banner). *(cross-check)* The code side is already reviewed: `tests/test_route_auth_coverage.py:99-100` lists `va_auth.site_maintenance_status` in `PUBLIC_BY_DESIGN` with a reason. | `va_auth.py:569-572`; policy `access-control-model.md:806-812` exception list | Policy text only: name it in the list with the why. No code or test change. |
| 11 | Authenticated endpoints that decide without authz: `/api/v1/instruments/<code>/translations/<locale>` gates on `login_required` only (reference translation strings; also served to devices); the profile self-service routes (`profile.py` view and `force_password_change`, `:13-37`) and *(cross-check: missed)* every route in `api/profile.py` gate on `login_required` only. No submission, person or grant data is reachable; this is the SSOT letter, not a leak. | `api/instruments.py:28-31`; `profile.py:13-37`; `api/profile.py`; policy: "A non-public endpoint that completes without consulting authz is a defect" | An `effective_roles`-based gate accepting any signed-in role, or named reviewed exceptions. *(cross-check)* The probe-all-routes test accepts a bare `login_required` as a guard (`tests/test_route_auth_coverage.py:232`), so the fix needs a test-policy change — e.g. a reviewed "any signed-in user" tier — before the test can enforce it. |
| 12 | NQA/Social-Autopsy completion KPI misattributes the feature flag on shared sites: the project join is `COALESCE((SELECT ps.project_id FROM va_project_sites ps WHERE ps.site_id = f.site_id … LIMIT 1), f.project_id)`, so a submission's flag comes from whichever active pair for the shared site sorts first. The form's own `f.project_id` is authoritative and available. Metric drift only — `scope.sql()` still bounds every row to the caller's scope. | `dm_kpi_exclusions.py:455-467` | `ON pm.project_id = f.project_id`. Test: two projects sharing a site with differing flags → each counted under its own flag; positive control: single-project site unchanged. |

## Checked and clean

Recorded so the next review does not re-cover them.

- **Coding track, object and list agree.** Pool counts use
  `_available_submission_filters(..., user=...)`, which appends
  `scope_filter(user, Action.CODE)` (`coder_workflow_service.py:171-188`);
  pick, random and recode re-check `_require_coder_access` (an `authz.can`
  wrapper) on every branch including existing allocations (`:549-563`,
  `:652-654`, `:711-716`, `:787-788`, `:803`); resume routes re-derive scope
  (`coding.py:247-263`, `reviewing.py:212-227`); the allocation API GET
  scope-checks before returning masked identifiers (`api/coding.py:63-97`).
  Area overview filters the list with `scope_filter(Action.VIEW)` and opens
  each row with `require(Action.VIEW)` (`coding.py:321-423`).
- **Reviewer track.** Reviewer saves re-check `can(REVIEW)` beside the
  allocation (`nqa.py:58-71`, `so.py:58-71`); reviewer resume re-asks REVIEW
  (`reviewing.py:212-227`).
- **Attachments.** Both routes resolve the record first and authorize with
  `authz.can(READ_ATTACHMENTS, va_sid)` fresh on every request; local delivery
  enforces realpath containment (`va_form.py:2149-2250`,
  `attachment_store.py:109-143`).
- **Device and Expo APIs.** The device blueprint rides a bearer session (CSRF
  exempt by contract) and every case/draft read re-checks project, site, unit
  and interviewer reach in `web_intake_service` (`interviewer_context`,
  `_require_scope`, out-of-scope ids read as 404, `:598-617`); Expo static
  serving is contained to configured assets (`expo_client.py:1-105`).
- **Intake supervision.** One predicate (`authz/supervision.py`) decides both
  the worklist and each object action; the supervisor API is behind
  `role_required` plus `can(SUPERVISE_INTAKE)` (`intake.py:399-500`); the
  duplicate mark reads both cases' scope.
- **Grant writes.** The admin panel asks `can_grant` before the scope, cadre
  and unit validation (digitva-xd1q ordering, `admin.py:2596-2650`, target
  extraction `:1283-1303`), runs the mentor guard after the permission check so
  a 400 never discloses institute membership, and lists grants through
  `grant_list_filter` (`:1334-1340`); the DM page create/toggle path goes
  through `require_dm_scope`/`can_grant` and reactivating a unit grant
  re-states its cadre (`:2696-2702`); the project-user import authorizes each
  distinct target before unit and cadre validation
  (`project_user_import_service.py:181-221`).
- **DM KPI scope SQL.** Grant project resolution joins the active pair and
  active unit rows and COALESCEs; NULL `project_id` on unit grants is never a
  wildcard (`dm_kpi_scope.py:55-66`). Site-keyed aggregate rows are read only
  through `aggregate_site_ids`, the sites whose every project the DM holds
  (`:70-95`; readers `dm_kpi_grid.py:86-90`, `dm_kpi_burndown.py:120-124`,
  `:300-304`, `:380-384`, `dm_kpi_pipeline.py:628-646`).
- **Celery tasks acting for users.** Single-form, backfill and single-submission
  sync re-authorize inside the worker (`sync_tasks.py:236-256`, `:1103`,
  `:1261`, `:2056`); the whole-run `run_odk_sync` is triggered by an
  admin-only route (`admin.py:6353-6376`); attachment S3 upload, quarantine
  and SmartVA archive are admin-panel/shell operations over blobs, not user
  scopes.
- **CSRF.** Global CSRFProtect; the documented exemptions are the bearer device
  blueprint and the read-only WHO proxy (`api/icd11.py:86-89`); page and JSON
  clients get `X-CSRFToken` from the bootstrap endpoints (`intake.py:86-98`,
  `admin.py:1367-1387`).
- **Closed projects and grant liveness.** Grant loading applies the active
  pair/unit/project predicates and resolves nothing for a closed project
  (`authz/grants.py:180-221`); redaction rides the same relation (review-10
  #3 fix).
- **Site-PI object checks.** `_report` authorizes every selection with
  `can(SITE_PI_REPORT)` and out-of-scope units 404 (`sitepi.py:101-124`); the
  unit path stops at deactivated pairs (`sitepi_reporting_service.py:258-266`).
  The pair-path gap is finding 4.
- **Area rollups.** Candidate units come from `authz.reachable_unit_ids` and
  each row counts only its own subtree; submissions keep their attribution to
  deactivated units by decision 2026-09-18, so a deactivated descendant folding
  into its ancestor's total is the policy's "counts over a closed unit stay
  correct", not a leak (`area_dashboard_service.py:209-227`, `:368-409`).
- **Public surface.** Landing, help and catalogue pages serve curated public
  data; WHO document delivery uses a fixed allowlist (`va_main.py:89-100`);
  mobile code issuance is gated by the may-issue rules on the DM page and
  admin-only elsewhere.

## Not verified

- Readers of `va_daily_kpi_aggregates` outside this app (BI/dashboards): every
  in-app reader is gated by `aggregate_site_ids`; nothing outside `app/` was
  auditable statically.
- Every `flask users …` / `flask mentor-institute …` subcommand was
  spot-checked (actor recorded, shell-level authority), not traced line by
  line.
- No HTTP endpoint was executed; all paths are static traces, as in review 10.

## Suggested order of work

1. **#1** — one `can(CODE)` call inside `require_coding_access`, copying the
   reviewer branch beside it; covers NQA, Social Autopsy and ICD search.
2. **#2** — a grant-only re-check in `get_draft` (404 on grant failure, unit
   state left to `_require_live_org_unit`), plus the same reach on
   `list_drafts`.
3. **#3** — scope-and-redaction fingerprint in the export cache key, or a
   shorter TTL; owner to choose the re-routing window.
4. **#5 and #12** — small query corrections with ready positive controls.
5. **#4** — one EXISTS clause in the pair report's filter, and the matching
   object check.
6. **#7** — the `narrative_text` `is_pii` decision, then the route guard.
7. **#6** — tester provenance (schema-touching; batch with the next migration).
8. **#8, #10, #11** — policy/code reconciliation; none is a patch-first item.
   #10 is a policy line only; #11 needs the route-coverage test tier first.
