---
title: Authorization module design (digitva-0wc)
doc_type: task
status: active
owner: engineering
last_updated: 2026-10-02
---

# digitva-0wc: authorization deep module — design

Read-only design pass, 2026-10-02, against HEAD `4fcd984e` (working tree clean). Every `file:line` below was read in this pass; anything not read is marked **unverified**. Paths are repo-relative.

## 0. Summary of the shape

One package, `app/services/authz/`, with four public calls and no other entry points:

```python
can(user, action, target) -> Decision          # one object; 1 SQL query
require(user, action, target) -> None          # raises AuthzError(403/404) for routes/services
scope_filter(user, action) -> ColumnElement    # SQL predicate on VaSubmissions, for lists
can_grant(actor, role, target) -> Decision     # who may write which grant where
```

plus two small helpers the rest of the app already needs: `effective_roles(user)` (what opens a role gate) and `coding_gate_waivers(user)` (gates, not scope). Everything is derived from one per-request `ResolvedGrants` object (one or two queries) and one rule table (`RULES`). `can()` is defined as `EXISTS(... va_sid = :sid AND scope_filter(user, action))`, so a list can never offer what `can` refuses: they are the same predicate.

Three decisions that cascade through everything else:

1. **One `view` action is the union of every viewing scope** (coder view, reviewer view, tester cover, data-manager shape, the viewer roles, site PI, project PI, admin). Attachments and workflow events are part of viewing a submission and alias to it. This one lever closes F2, F3/blp, F4, F5, F7, F8, F11, F12 and F13.
2. **Project kind is "has an active org level"** (`org_grant_service.projects_with_org_tree`, org_grant_service.py:496-503), not `project_structure_mode`: organization-model.md:186-187 says the mode gates editing only. Edge: an `organization`-mode project with no levels is a site project to authz; recorded as an open question (§9).
3. **The predicate is uniform across project kinds.** Project and pair grants reach every submission of their project/pair; unit grants reach submissions whose `org_unit_id` is in the subtree. On a site project nothing is routed, so the unit branch is simply empty. The `has_tree` special case in `_submission_within` (org_grant_service.py:547-558) and `_org_unit_scope_filter` (coder_workflow_service.py:207-221) disappears; the only tree-dependent rule left is the coding scope level, which can only be set on a tree project.

## 1. Interface

### 1.1 Files

```
app/services/authz/
  __init__.py      re-exports: Action, Decision, Reason, AuthzError, can, require,
                   scope_filter, can_grant, grant_list_filter, effective_roles,
                   coding_gate_waivers, resolve_grants, invalidate, redacts_pii
  actions.py       Action enum, Lens enum, RULES table, GRANT_RULES table
  grants.py        Grant, ProjectSettings, ResolvedGrants, resolve_grants(), memo
  predicates.py    scope_filter(), can(), require(), _lens_predicate(), _subtree_select()
  grant_writes.py  can_grant(), grant_list_filter()
  waivers.py       CodingWaivers, coding_gate_waivers()   (moved from coder_workflow_service)
```

`redacts_pii` is `viewer_pii_service.should_redact_pii` re-exported unchanged (its docstring says the per-user rule is decided; not reopened, see §9).

### 1.2 Types

```python
class Action(enum.Enum):
    # target = va_sid
    VIEW = "view"                    # open read-only: shell, every read partial, attachments, events
    CODE = "code"                    # start / pick / random pool / resume / coder saves
    RECODE = "recode"                # same scope as CODE; ownership + 24h window are workflow (§4)
    REVIEW = "review"                # reviewer start / resume / Step 1 / final
    TRIAGE = "triage"                # DM not-codeable, screening pass/reject, upstream accept/reject, ODK edit URL
    SYNC_SUBMISSION = "sync_submission"
    ROUTE_PIN = "route_pin"          # pin / clear pin (target unit checked separately, §2.4)
    # target = form_id
    SYNC_FORM = "sync_form"          # whole-form sync, preview, run history
    # target = project_id
    LIST_UNROUTED = "list_unrouted"
    # target = ("pair", project_id, site_id) | ("unit", org_unit_id)
    SITE_PI_REPORT = "site_pi_report"
    # target = VaDeathRegister
    SUPERVISE_INTAKE = "supervise_intake"
    # no target: scope_filter only (DM grid, KPI panels, exports, filter options)
    LIST_DATA = "list_data"

READ_ATTACHMENTS = Action.VIEW   # aliases, so call sites read naturally
READ_EVENTS = Action.VIEW

class Reason(enum.Enum):
    ALLOWED, NOT_FOUND, NO_ROLE, PROJECT_CLOSED, OUT_OF_SCOPE, VIEW_ONLY, UNROUTED

@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: Reason
    message: str                 # operator-facing, the same strings the routes flash today
    def __bool__(self): return self.allowed

class AuthzError(Exception):
    status_code: int             # 403, or 404 when the target does not exist
    message: str
```

`test_code` is not an action: a coding tester performs `CODE`; what differs is the gate waiver, which is a separate function (§1.4). `read_kpi` is `LIST_DATA`. `view_pii` is not an action: redaction is a per-user property today (`should_redact_pii`, viewer_pii_service.py:42-94) and stays one.

### 1.3 Grant resolution (grants.py)

```python
@dataclass(frozen=True)
class Grant:
    role: VaAccessRoles
    scope_type: VaAccessScopeTypes
    project_id: str                  # resolved for every scope (pair -> project, unit -> project)
    site_id: str | None              # project_site scope only
    org_unit_id: uuid.UUID | None    # org_unit scope only
    unit_depth: int | None           # the unit's level depth
    virtual: bool = False            # demo-training grant, see §2.6

@dataclass(frozen=True)
class ProjectSettings:
    project_id: str
    has_tree: bool
    scope_depth: int | None          # depth of coding_scope_level_id, None = no coding scope
    above_mode: str                  # 'code_any' | 'view_only'
    demo_training: bool

@dataclass(frozen=True)
class ResolvedGrants:
    user_id: uuid.UUID
    is_admin: bool
    grants: tuple[Grant, ...]        # active grants on active projects only
    projects: dict[str, ProjectSettings]

    # pure functions, no SQL:
    def wide_projects(self, roles, *, coding: bool) -> frozenset[str]
    def wide_pairs(self, roles, *, coding: bool) -> frozenset[tuple[str, str]]
    def unit_grant_ids(self, roles, *, coding: bool) -> frozenset[uuid.UUID]
    def dm_projects(self) -> frozenset[str]          # any DM-capable grant's project (unrouted queue)
    def holds(self, role, scope_type=None) -> bool
```

`resolve_grants(user)` runs **one query**: `va_user_access_grants` (active) LEFT JOIN `va_project_sites` (active, gives project_id/site_id) LEFT JOIN `mas_org_unit` (active) JOIN `mas_org_level` (depth) with `active_project_condition` on the resolved project id (the shared predicate, org_grant_service.py:154-177, as policy requires), plus one query for the settings of the projects involved (`va_project_master.coding_scope_level_id` -> `mas_org_level.depth`, `above_scope_coding_mode`, `demo_training_enabled`, and `EXISTS mas_org_level active` for `has_tree`; this generalises `_project_scope_settings`, org_grant_service.py:306-325). Demo-training projects are added as virtual grants (§2.6).

`coding=True` applies the coding scope rule: a wide grant survives only if `scope_depth is None or above_mode == 'code_any'` (today `wide_grant_scope`, org_grant_service.py:506-533); a unit grant survives if `scope_depth is None or unit_depth >= scope_depth or above_mode == 'code_any'` (today `codeable_unit_ids`, :328-384). `coding=False` keeps everything (today `viewable_unit_ids`, :602-608).

**Memo.** Stored in `request.environ["digitva.authz"]` keyed by `user_id`, the pattern and reason already written at dm_kpi_scope.py:139-157 (`flask.g` can outlive a request). Outside a request (Celery, CLI, direct service tests) it resolves fresh. `invalidate(user_id)` is called by every grant write (admin.py create/toggle, data_management.py create/toggle, project_user_import_service, mentor_institute_service.remove_staff) so a grant written and used in one request is seen.

### 1.4 Predicates (predicates.py)

```python
def scope_filter(user, action: Action) -> sa.ColumnElement:
    g = resolve_grants(user)
    if g.is_admin and action in ADMIN_BYPASS: return sa.true()
    clauses = [p for lens in RULES[action] if (p := _lens_predicate(g, lens)) is not None]
    return sa.or_(*clauses) if clauses else sa.false()
```

**Predicate hygiene (load-bearing).** The returned expression references `VaSubmissions` columns only; `VaForms` is reached through uncorrelated subqueries with `.correlate(None)`. The reviewing dashboard joins `VaForms` itself and the coder pool does not; a correlated `EXISTS` on `VaForms` silently adds a cartesian product in one of them. This is exactly why `_org_unit_scope_filter` is written the way it is (coder_workflow_service.py:204-206, 231-235) and why `scope_unit_ids_select` carries `.correlate(None)` (org_grant_service.py:281-282). Keep that comment in the module.

Building blocks:

```python
def _forms_in(g, projects, pairs, *, require_active_pair: bool):
    # VaSubmissions.va_form_id IN (SELECT form_id FROM va_forms WHERE form_status='active'
    #   AND (project_id IN :projects OR (project_id, site_id) IN :pairs)
    #   [AND EXISTS active va_project_sites row for (project_id, site_id)])
    # require_active_pair=True for the coder role only (today va_users.py:602-603)

def _subtree_select(unit_ids):
    # SELECT covered.org_unit_id FROM mas_org_unit covered
    #   JOIN mas_org_unit granted ON covered.project_id = granted.project_id
    #                            AND covered.path <@ granted.path          -- GiST, ix_mas_org_unit_path
    #   WHERE granted.org_unit_id IN :unit_ids AND covered.is_active
    # anchored on the already-resolved grant units (a handful of ids), never on the grants table,
    # and never materialised: a district subtree stays in Postgres.

def _routed_into(unit_ids):   # VaSubmissions.org_unit_id.in_(_subtree_select(unit_ids))
```

`_lens_predicate(g, lens)` for each Lens (§2.1): wide grants via `_forms_in`, unit grants via `_routed_into`. Unrouted submissions (`org_unit_id IS NULL`) are reached by wide grants only, by construction; the one exception (`LIST_UNROUTED`, `ROUTE_PIN` on an unrouted case) is its own lens.

```python
def can(user, action: Action, target) -> Decision:
    # submission-targeted actions:
    #   exists = db.session.scalar(select(exists().where(VaSubmissions.va_sid == sid, scope_filter(user, action))))
    #   if exists: return Decision(True, ALLOWED, "")
    #   row = one SELECT of (project_id, site_id, org_unit_id, project_status) for the sid -> NOT_FOUND / reason
    # reason on denial, from ResolvedGrants + that row, no further SQL:
    #   no grant of any lens role            -> NO_ROLE
    #   project not active                   -> PROJECT_CLOSED
    #   routed and (role holds it in VIEW lens but not CODE lens) -> VIEW_ONLY
    #   unrouted and only unit grants there  -> UNROUTED
    #   else                                 -> OUT_OF_SCOPE
    # form / project / pair / unit / case targets: a small per-action resolver (§2.3), same ResolvedGrants.

def require(user, action, target) -> None:
    d = can(user, action, target)
    if not d: raise AuthzError(404 if d.reason is Reason.NOT_FOUND else 403, d.message)
```

Routes translate `AuthzError` to `va_permission_abortwithflash` / JSON, exactly as they translate `AllocationError` today (coding.py:46-47).

### 1.5 Gate waivers (waivers.py)

`coding_gate_waivers(user) -> CodingWaivers` is `_CodingWaivers` / `_coding_waivers` moved verbatim (coder_workflow_service.py:268-309) and fed from `ResolvedGrants` instead of five `get_*` calls. Gates are separate from scope by policy (access-control-model.md:380-384, organization-model.md:652-655), so this is deliberately **not** inside `scope_filter`. `tester_covers_submission` (coder_workflow_service.py:312-329) becomes unnecessary: a tester's reach is just the `CODE` lens with the tester role included.

### 1.6 Effective roles

`effective_roles(user) -> frozenset[str]` returns the keys of `role_required._ROLE_METHODS` the user satisfies. It is the single place that says: `site_pi@org_unit` and `project_pi` on a tree project count as `data_manager` and `interview_supervisor`; a demo-training project counts as `coder` (§2.6). `VaUsers.is_data_manager()`, `is_site_pi()`, `is_coder()` etc. (va_users.py:152-259) become one-line wrappers over it at stage 7, so navbar, `landing_url` (va_users.py:92-117) and the decorator all agree. `_ROLE_METHODS` stays a literal dict (auth-decorator-rbac.md:348-367 and `tests/test_role_required_validation.py` assert it); only the lambdas' bodies change.

## 2. The rule table

### 2.1 Lenses

A **lens** is one way a grant resolves to submissions. `RULES[action]` is a tuple of lenses; the predicate is their OR.

| Lens | Roles counted | Wide grants (project / pair) | Unit grants | Unrouted reached by |
|---|---|---|---|---|
| `CODE_CODER` | coder, coding_tester, (virtual demo coder) | coder: active pair required, coding-scope rule; tester: no scope rule | coder: coding-scope rule; tester: whole subtree, scope-level exempt | wide only |
| `CODE_REVIEWER` | reviewer, (virtual demo reviewer) | coding-scope rule | coding-scope rule | wide only |
| `VIEW_CODER` | coder, coding_tester | whole project / pair whatever the scope level | whole subtree | wide only |
| `VIEW_REVIEWER` | reviewer | same | same | wide only |
| `DM` | data_manager (any scope); site_pi **@org_unit**; project_pi **on a tree project** | whole project / pair | whole subtree | wide only |
| `VIEWER` | collaborator, collaborator_pii | whole project / pair | whole subtree | wide only |
| `SITE_PI_PAIR` | site_pi @project_site | whole pair | n/a | yes (pair) |
| `PROJECT_PI_SITE` | project_pi on a site project | whole project | n/a | yes |
| `DM_PROJECT_UNROUTED` | every `DM`-lens grant, any scope | `org_unit_id IS NULL AND form's project IN dm_projects()` | | the queue itself |
| `DM_DIRECT` | data_manager @project / @pair; project_pi on a tree project | whole project / pair | **none** (a form spans units) | yes |

### 2.2 Action → lenses

| Action | Lenses | Admin |
|---|---|---|
| VIEW (+attachments, events) | VIEW_CODER, VIEW_REVIEWER, DM, VIEWER, SITE_PI_PAIR, PROJECT_PI_SITE | bypass |
| CODE, RECODE | CODE_CODER | no bypass (admin codes demo only, today's `vademo_start_coding` path) |
| REVIEW | CODE_REVIEWER | no bypass |
| TRIAGE, SYNC_SUBMISSION | DM | bypass (today `_dm_submission_scope_check` bypasses, data_management_service.py:2520; the validators do not, F11) |
| ROUTE_PIN | DM, DM_PROJECT_UNROUTED | bypass |
| LIST_DATA | DM, VIEWER | bypass (today admin passes the shell and sees nothing, bead 4in) |
| LIST_UNROUTED (project) | DM_PROJECT_UNROUTED | bypass |
| SYNC_FORM (form) | DM_DIRECT | bypass |
| SITE_PI_REPORT (pair) | site_pi@pair on that pair; project_pi on that project (both kinds; "view reporting for an assigned project", access-control-model.md:72) | bypass |
| SITE_PI_REPORT (unit) | site_pi@org_unit whose subtree holds the unit; project_pi on that tree project | bypass |
| SUPERVISE_INTAKE (case) | interview_supervisor@unit, data_manager any scope, site_pi@org_unit, project_pi on a tree project | **no bypass** (intake has none today, case_transition_service.py:244-252; keep) |

### 2.3 Role × scope × project kind, as the writer will read it

Columns: what the holder may do in a **site project** (no tree) / in a **tree (district) project**. "scope" = the grant's project, pair or subtree. PII column per §2.7.

| Role @ scope | Site project | Tree project | PII |
|---|---|---|---|
| admin @global | everything, every project, closed included | same | yes |
| project_pi @project | VIEW every submission of the project (+attachments, events); SITE_PI_REPORT for every site of the project; can_grant per §2.8; waives coding gates; no CODE/REVIEW/TRIAGE | all of the site column **plus** acts as DM over the whole project: TRIAGE, SYNC_SUBMISSION, SYNC_FORM, ROUTE_PIN anywhere, LIST_UNROUTED, LIST_DATA, SUPERVISE_INTAKE; still no CODE/REVIEW | yes |
| site_pi @pair | VIEW every submission of the pair; SITE_PI_REPORT(pair); waives gates for the pair; nothing else | same (a pair on a tree project is the auto site; rare) | yes |
| site_pi @org_unit (**In-charge**) | not grantable (validator) | every DM power in the subtree (TRIAGE, SYNC_SUBMISSION, ROUTE_PIN into own subtree, LIST_UNROUTED of the project, LIST_DATA), SUPERVISE_INTAKE in the subtree, VIEW in the subtree, SITE_PI_REPORT(unit) for units in the subtree, can_grant per §2.8; **not** SYNC_FORM (§9); no CODE/REVIEW | yes |
| data_manager @project / @pair | VIEW, TRIAGE, SYNC_SUBMISSION, SYNC_FORM, LIST_DATA in scope; ROUTE_PIN n/a (no tree); can_grant site rule | same in scope, plus ROUTE_PIN anywhere in the project / pair, LIST_UNROUTED; can_grant district rule | yes |
| data_manager @org_unit | n/a | VIEW, TRIAGE, SYNC_SUBMISSION, LIST_DATA for submissions routed into the subtree; LIST_UNROUTED of the whole project; ROUTE_PIN of an unrouted or in-subtree case **into own subtree only**; **not** SYNC_FORM; can_grant district rule | yes |
| coder @project / @pair | CODE + VIEW every submission of scope (active pair required) | VIEW every submission of scope, routed or unrouted; CODE them if no coding scope level or `code_any`; under `view_only` codes nothing (VIEW_ONLY reason) | yes |
| coder @org_unit | n/a | VIEW the whole subtree; CODE the subtree if unit depth >= scope depth or `code_any`, else nothing; never an unrouted case | yes |
| coding_tester @project / @pair | CODE + VIEW every submission of scope; gates waived for the pair/project; no scope-level rule | same, scope-level exempt (F15 closed: project/pair testers get the pool) | yes |
| coding_tester @org_unit | n/a | CODE + VIEW the subtree, scope-level exempt; gates waived per submission inside the subtree only | yes |
| reviewer @project / @pair | REVIEW + VIEW scope | VIEW scope routed or not; REVIEW under the same coding-scope rule as coder (F7 closed: viewing is the wider right, reviewing the narrower) | yes |
| reviewer @org_unit | n/a | VIEW subtree; REVIEW subtree under the scope rule; never unrouted | yes |
| collaborator @any | VIEW (single submission, read-only), LIST_DATA; no writes | same, unit = subtree | **redacted** |
| collaborator_pii @any | same as collaborator | same | yes |
| interviewer @any | nothing here (web intake has its own grant-only scope, web_intake_service; untouched) | same | yes |
| interview_supervisor @org_unit | n/a | SUPERVISE_INTAKE in subtree; nothing on coding/DM screens | yes (supervision views, web-intake.md item 14) |
| mentor (institute member) | may only hold coder / reviewer / coding_tester / collaborator_pii @org_unit (guard); then exactly the rows above | same | yes |

Exceptions and precedences, in prose:

- **Closed projects.** `resolve_grants` ANDs `active_project_condition` once, so a grant on a non-active project is absent from `ResolvedGrants`; every lens is therefore empty for it. Admin is `global` and bypasses. This is the same rule as today, written once instead of in each resolver (access-control-model.md:598-604).
- **Unrouted.** A submission with `org_unit_id IS NULL` is reached by wide grants of any lens and by nothing else, except the queue (`DM_PROJECT_UNROUTED`): every DM-capable grant of the project sees it (owner decision, access-control-model.md:476-483) and may pin it into its own subtree. Today's queue filter admits only fallback-routed cases inside a unit subtree (api/data_management.py:773-796); the new rule is wider on purpose.
- **Pin target.** `ROUTE_PIN` on the submission plus a second check on the target unit: wide DM grant on the project -> any unit of the project; unit DM / In-charge -> target in own subtree; clearing a pin needs only the submission check. The `reaches_whole_site` shortcut (api/data_management.py:912-921) goes.
- **Coding scope level only exists with a tree**, and `pick_and_choose` is forced with it (organization-model.md:681-683); nothing else is tree-dependent.
- **Project and pair grants are the top of the tree** on a tree project (organization-model.md:623-631): the `_forms_in` branch is the same expression for both kinds; keyed on `(project_id, site_id)` tuples, never bare `site_id` (fixes lh1h in `DmScope`).
- **Tester and PI waivers** lift gates, never scope (§1.5). A unit tester's waiver is per submission (allocate_random_form, coder_workflow_service.py:760-767) and stays where it is.
- **Mentor guard** is a write-time guard only (organization-model.md:466-479); `can()` never consults institute membership.
- **Language, workflow state, allocation, 24h window, 200-form cap, retired, duplicate, gates**: workflow, outside `can` (§4).

### 2.4 Decisions on points the audit left open

- F5 (coder `/coding/view` shell vs own-only partials): `VIEW` is "in viewing scope". The own-outcome check `va_permission_ensureviewable` (va_permission_06_ensureviewable.py) stays as a workflow constraint on the **coder-record rendering** (`action=vacode&actiontype=vaview` shows the coder's own assessment); the area/read-only rendering (`vadata`/`vaview`) needs `VIEW` only. The coder dashboard history links keep using the coder rendering, so nothing visible changes for coders.
- F12 (coder attachments require holding the case): dropped. A coder in viewing scope sees the area rendering, which counts and serves attachments (coding_service.py:118), so attachments must follow `VIEW`. digitva-ck9's concern (an old allocation outliving re-routing) is covered because `VIEW` is evaluated against the current `org_unit_id`.
- F13 (events wider than the page): events = `VIEW`; same answer as the page.
- F19 (reviewer dashboard lists every state): unchanged; open question (§9).
- F16 (pick skips language/TR01, list skips gates): workflow, not scope; stage 1 adds the language filter to `allocate_pick_form` and the gate exclusion to `get_pick_available_forms` so list and pick agree, using `coding_gate_waivers`.
- vadmtriage POST (va_form.py:656-659) checks `is_data_manager()` with no scope: becomes `require(user, TRIAGE, sid)`. Rule for `renderpartial`: **read partials need `VIEW`; write partials call `require(<write action>)` in the handler** (access-control-model.md:631-634 already demands this). Widening `vadata` to viewers without this would expose the triage POST to a plain collaborator.
- `render_va_coding_page` queues `run_open_submission_repair` on every `vacode`/`vadata` open (coding_service.py:91-103): gate on `can(user, SYNC_SUBMISSION, sid)` so a read-only viewer does not trigger a repair job (F3's side note).

### 2.5 Grant management (`can_grant`)

```python
@dataclass(frozen=True)
class GrantTarget:
    role: VaAccessRoles
    scope_type: VaAccessScopeTypes
    project_id: str | None = None          # project scope
    project_site_id: uuid.UUID | None = None
    org_unit_id: uuid.UUID | None = None

def can_grant(actor, target: GrantTarget, *, grantee_id=None) -> Decision
def grant_list_filter(actor) -> sa.ColumnElement   # over VaUserAccessGrants: the grants the actor may manage
```

`GRANT_RULES`, derived from access-control-model.md:526-577 and dm-user-grant-management.md:60-130:

| Actor's grant | Project kind | May create / reactivate / revoke |
|---|---|---|
| admin | any | any role, any scope |
| project_pi @project | any | any role except admin, project_pi, at any scope inside the project (project, pair, unit); today's rule admin.py:2523-2527 |
| site_pi @org_unit (In-charge) | tree | data_manager on own unit or any descendant; plus the DM district list below, anywhere in own subtree; never site_pi, project_pi, admin, interview_supervisor |
| data_manager @project | site | coder, coding_tester, data_manager at project or pair in that project (today `_dm_can_manage_scope`, data_management.py:115-149) |
| data_manager @pair | site | coder, coding_tester, data_manager on that pair only |
| data_manager @project | tree | data_manager strictly below: any pair or any unit of the project, never project scope; interviewer, coder, reviewer, coding_tester, collaborator, collaborator_pii at project, pair or any unit |
| data_manager @pair | tree | no data_manager (nothing lies below a pair); the six roles on that pair |
| data_manager @org_unit | tree | data_manager on strict descendants only; the six roles on own unit or descendants |
| anyone | any | never admin, project_pi, site_pi (either scope), interview_supervisor unless admin / project_pi |

After `can_grant` passes, the existing write-time checks run unchanged: `validate_org_unit_grant` (cadre rules, org_grant_service.py:90-151) and `check_mentor_grant` (mentor_institute_service.py:638-659). Toggle uses the same table on the stored grant's (role, scope); a DM still may not revoke their own data_manager grant (dm-user-grant-management.md:152-154). The mentor exception today (`_dm_can_manage_unit_grant`, data_management.py:76-92: a district DM may write mentor-role unit grants) is subsumed: under the district rule a DM writes coder/reviewer/tester/collaborator_pii unit grants inside their subtree anyway, and the guard narrows it for members. `grant_list_filter` lists exactly what `can_grant` allows (dm-user-grant-management.md:178-195), replacing `_dm_grant_filter` + `_dm_listed_grant_condition` (data_management.py:152-202).

### 2.6 Demo-training projects (digitva-6zq)

Today `_get_granted_va_forms` unions every demo-training form for coder, coding_tester, data_manager and reviewer for every user (va_users.py:605-606). Policy says demo projects are open for coding (coding-workflow-state-machine.md:251-253). But `tests/routes/test_demo_training_project.py:363-371` (`test_plain_user_can_start_reviewing_demo_case_without_grant`) asserts reviewer access without a grant, so the reviewer half is tested, deliberate behaviour, not an accident. The module reproduces it: `resolve_grants` appends virtual project-scope grants of **coder, coding_tester and reviewer** for every active demo-training project; **not** data_manager (that union is already dead: the only DM form path passes `include_demo=False`, va_users.py:473-477). Whether reviewer demo access should survive is an owner question (§9); the constant `DEMO_VIRTUAL_ROLES` in actions.py is the one place to change it.

### 2.7 PII

Every role sees personal data except plain `collaborator`; decided per user by `should_redact_pii` (viewer_pii_service.py:42-94), which already applies `active_project_condition`. Job title (digitva-04u4) is public and never redacted. The viewer detail render (stage 4) must call `redacts_pii` and the unconfirmed-PII-set withholding (access-control-model.md:254-270) exactly as the DM grid does; the module does not re-implement redaction.

## 3. Single source

`can` is defined through `scope_filter`; there is no second Python implementation of the rules. The things that can still drift are (a) a reason computed wrongly on denial (harmless: it only changes the message), and (b) a later author adding a Python-only branch to `can`. Two tests pin it:

- `tests/authz/test_single_source.py`: for every fixture user and every submission-targeted action, `{sid for sid in ALL_SIDS if can(user, action, sid)} == set(select va_sid where scope_filter(user, action))`. Also asserts the SQL of `scope_filter` compiles with `VaSubmissions` as the only free table (`sa.select(VaSubmissions.va_sid).where(pred)` executes without a FROM error), which is the hygiene rule of §1.4.
- `tests/authz/test_matrix.py` (§8) checks the expected outcomes.

## 4. Workflow constraints compose outside `can`

Policy separates role, scope and workflow (access-control-model.md:609-634, 767-773). The module answers only "may this person act on this object"; services keep everything else and call `require` first:

```python
def allocate_pick_form(user, va_sid):
    release_stale_coding_allocations(timeout_hours=1)
    require(user, Action.CODE, va_sid)                 # replaces _require_coder_access (coder_workflow_service.py:641-662)
    ... 200-cap, existing allocation, intake mode, ready-pool state, retired, duplicate, language, gates ...

def start_recode_allocation(user, va_sid):
    require(user, Action.RECODE, va_sid)
    ... coder_finalized, authoritative final by this user, recode_limit_error, 24h cutoff ... (unchanged, :892-919)

def start_reviewer_coding(user, va_sid):
    require(user, Action.REVIEW, va_sid)               # replaces _require_reviewer_access (reviewer_coding_service.py:237-251)
    ... language, duplicate, reviewer_eligible, no existing final, allocation, retired ...
```

Lists: `scope_filter(user, CODE)` AND the pool filters (`CODER_READY_POOL_STATES`, `submission_is_in_odk`, duplicates, language, TR01) AND the gate exclusions. The partial validators (`va_validate_permissions.py`) keep their allocation / state checks and replace every `_within_*_org_scope` + `has_va_form_access` pair with one `require`. `va_permission_ensureviewable`, `ensureallocation`, `validaterecodelimits` stay as they are. Rule for a writer: if a check reads an allocation, a workflow state, a timestamp or the user's language profile, it is workflow and does not belong in authz.

## 5. The In-charge: `site_pi` at `org_unit`

**Migration** (new revision chained on the dev head; handoff.md says `d7e3a1c9b5f2`, **unverified** here, run `flask db heads` first). Upgrade: `DROP CONSTRAINT ck_va_user_access_grants_role_scope`, recreate with `(role = 'site_pi' AND scope_type IN ('project_site', 'org_unit'))`. That string already exists as `ROLE_SCOPE_BEFORE` in `migrations/versions/c4a9e7d2b6f1_add_mentor_institutes_and_site_pi_scope.py:33-35`; this migration is its inverse. Additive: it only loosens a CHECK; existing `project_site` site_pi rows are untouched. Downgrade mirrors c4a9e7d2b6f1's upgrade (:125-131): set `grant_status = inactive` with a `notes` line on every `site_pi` / `org_unit` row, then reinstate the tight CHECK; no row is deleted (AGENTS.md: reversible, never destructive).

**Validator.** Remove the refusal at org_grant_service.py:103-107; add `VaAccessRoles.site_pi` to `ROLES_ALLOWING_ORG_UNIT` (:44-55). Cadre: `site_pi` is not in `CADRE_FLAG_BY_ROLE` (:65-68), so a cadre is optional and, if given, validated by the descriptive path (:143-149), which is what "cadre validation applies as for any unit grant" means. **Mentor guard**: `MENTOR_ROLES` (mentor_institute_service.py:51-57) does not contain `site_pi`, so `check_mentor_grant` already refuses it; add a test. Display name "In-charge" when `scope_type == org_unit` (admin panel `ROLE_LABEL` in `access_grants.html`, the DM users page, `/help/user-roles`; template work, **unverified** which files render labels).

**Powers.** `Grant(role=site_pi, scope_type=org_unit)` is counted by the `DM` lens, the `DM_PROJECT_UNROUTED` lens, the `SUPERVISE_INTAKE` role set and `SITE_PI_REPORT(unit)`; `effective_roles` returns `data_manager`, `interview_supervisor` and `site_pi` for it. So every DM page, the unrouted queue, pin, triage, single-submission sync and the supervision page open with no route changes beyond the `is_*` wrappers. `SYNC_FORM` stays direct-grant only (§9).

**Site PI report for a unit.** `get_sitepi_dashboard_data(project_id, site_id)` (sitepi_reporting_service.py:206) builds every query on `va_submissions s JOIN va_forms f` (:67-68, :248-249, :260-261, :290-291) with a `scope_sql` fragment (`_workflow_kpis(scope_sql, params)`, :54). Add a sibling `get_sitepi_unit_dashboard_data(org_unit_id)` whose fragment is `s.org_unit_id = ANY(:unit_ids)` with `unit_ids` from `_subtree_select`, and whose coder roster (:237-238 reads `va_user_access_grants`) lists unit grants in the subtree. `sitepi.py` offers each site_pi pair as today and each held unit as a second option group; `/sitepi/data` validates the selection through `can(user, SITE_PI_REPORT, target)` instead of the pair set at sitepi.py:47. `project_pi` gets the same page for their project's sites and units (F8). **Unverified**: whether every one of the ten SQL blocks in that service references `s`; the writer must read :206-330 before changing the signature.

**Supervision.** `case_transition_service._covering_grants` (:120-205) imports `SUPERVISING_ROLES` from authz, adds `site_pi` to the unit branch and a `project_pi`-on-tree-project branch alongside the project-scope `data_manager` one. The narrowest-grant audit rule (`supervising_grant`, :244-248) is unchanged; a `site_pi` unit grant ranks with `interview_supervisor` at equal depth.

## 6. Performance

- Per request: one grant query + one project-settings query (both small, indexed on `ix_va_user_access_grants_user_status`, va_user_access_grants.py:52-56), memoised in `request.environ`. Then each `can` is one `EXISTS` and each list embeds the predicate. Today a single coder pick runs `has_va_form_access` (one query), `is_coding_tester` (one), `tester_covers_submission` (two), `submission_within_org_scope` (four or five): it becomes one.
- Subtrees are never materialised into Python: `_subtree_select` is an `IN (subquery)` anchored on the grant units, served by `ix_mas_org_unit_path` (GiST, migrations/versions/c8d2e4f6a1b3:76) and `ix_va_submissions_org_unit_id` (c1d4e7f9a3b6:78). This replaces the `sorted(unit_ids)` IN-lists at coder_workflow_service.py:223, coding.py:376, data_management_service.py:441 and the `uuid[]` array in `DmScope.sql` (dm_kpi_scope.py:106-124).
- Wide grants are tiny lists (`project_id IN`, `(project_id, site_id) IN`), fine as bind parameters.
- No new index is needed. `va_forms (project_id, site_id)` has no composite index that I could see (**unverified**; `va_forms` is a few hundred rows, so a scan of it inside the subquery is cheap).
- The KPI cache key (dm_kpi_scope.py:164-169) must digest the resolved grants, not `site_ids|unit_ids`, once `DmScope` is built from authz; `ResolvedGrants.digest()` (sha1 of the sorted grant tuples) does that.
- No cross-request caching of grants: a revoked grant must bite on the next request.

## 7. Staged migration

Ordered by risk and value. Reorders against the brief's list are explained inline. Each stage ships alone with its tests; the old helpers keep working beside the module until stage 8.

**Stage 0 — module + tests + hot-fix lh1h.** Files: `app/services/authz/*`, `tests/authz/*`; and `app/routes/api/dm_kpi/dm_kpi_scope.py:57-77` (`dm_site_ids` -> pairs) with `dm_kpi_grid`, `dm_kpi_burndown`, `dm_kpi_pipeline` filtering on `(f.project_id, f.site_id)`. lh1h is a live cross-project leak with a one-line pattern already at submission_analytics_mv.py:1203; it does not wait for stage 3. Shadow comparison: a **test**, not runtime, that seeds the TST001 roster (`flask seed test-project`, 24 users) and asserts old helpers and `scope_filter` agree for coder/reviewer/DM viewing; it is deleted at stage 8. Closes: lh1h. Risk: none to production (nothing calls the module yet).

**Stage 1 — coding.** Files: `coder_workflow_service.py` (`_require_coder_access` -> `require(CODE)`, `_org_unit_scope_filter` -> `scope_filter(CODE)`, `_available_submission_filters`, `allocate_pick_form` language filter, `get_pick_available_forms` gate exclusion, `_CodingWaivers` moved), `coding.py` (`dashboard` counts, `view_submission` -> `require(VIEW)`, `area_overview` rows = `scope_filter(VIEW)` for coder|reviewer|tester with `is_codeable` from `scope_filter(CODE)`, `area_view_submission` -> `require(VIEW)`, `_has_org_unit_area`/`_prefers_reviewer_area` from `ResolvedGrants`), `va_validate_permissions.py::_validate_vacode` (scope lines :126-134, :155, :165, :214 -> `require`), `api/coding.py`, `coder_dashboard_service.get_coder_recodeable_sids` (+ `recode_limit_error`, h67s). Closes: F2, F4, F5, F15, F16, F17, h67s. Risk: medium (highest-traffic screens; behaviour change for project/pair testers who gain the pool and for area overview which now lists wide grants). Tests: matrix rows for coder/tester; existing `tests/test_coding_scope_enforcement.py`, `test_project_grant_org_scope.py`, `test_org_unit_coding_gates.py` must stay green.

**Stage 2 — attachments, events, partials, viewers, area (blp).** Moved ahead of reviewing and DM because blp is browser-confirmed breakage and the viewer decision is an owner priority. Files: `attachment_service.can_access_submission_attachment` (:274-310 -> `can(VIEW)`; `_user_holds_submission` deleted), `va_form.py::serve_attachment` role list gains `coding_tester`, `collaborator`, `collaborator_pii` (:2052) and `serve_media` gets the same gate (:2086), `api/workflow.py::_may_read_events` (-> `can(VIEW)`), `va_validate_permissions.py::_validate_vadata` (-> `require(VIEW)` for `vaview`), the vadmtriage POST (va_form.py:656-659 -> `require(TRIAGE)`), `coding_service.render_va_coding_page` repair gating, a viewer-reachable `vadata` rendering with `redacts_pii` applied and area-specific hints instead of DM hints (category_rendering_service.py:34-45 maps action -> role; add an `area` action or pass the back role), a submission link from the DM grid for viewers, navbar entry for viewers (va_navbar.html, va_users.landing_url). Closes: F3/blp, F8 (project_pi attachments and events), F11 (admin view), F12, F13, owner decision "viewers open one submission". Risk: medium-high on PII: the new viewer render must be tested with a plain collaborator against an unconfirmed-PII form type (withheld) and a confirmed one (redacted). Tests: matrix rows for VIEW; `tests/routes/test_serve_attachment.py`, `test_va_form_pii_redaction.py`, `test_collaborator_viewer_access.py` extended.

**Stage 3 — DM pages, APIs, KPIs, unrouted queue, pin, project_pi-as-DM.** Files: `data_management_service.py` (`dm_scope_filter`, `dm_direct_scope_pairs`, `dm_org_unit_ids`, `_dm_scope_pairs`, `dm_submission_org_unit_condition`, `dm_form_in_scope`, `_dm_submission_scope_check` -> `scope_filter(LIST_DATA)` / `require(TRIAGE|SYNC_SUBMISSION)` / `can(SYNC_FORM)`), `api/data_management.py` (every `has_data_manager_submission_access` call; `_dm_submission_scope_filter` + `unrouted_submissions` -> `scope_filter(LIST_UNROUTED)`; `set_submission_org_unit` -> `require(ROUTE_PIN)` + target-unit check; `sync_form`/`sync_preview`/`sync_runs` -> `SYNC_FORM`; 38lp: `dm_kpi_sync /status`, `/attachment-health`, `/smartva-failure-rate` gated on `DM_DIRECT`, `/refresh` under `limiter.limit`), `dm_kpi_scope.DmScope` built from `ResolvedGrants` (`sql()` becomes the authz predicate rendered via `str(compile)` or, simpler, the KPI raw-SQL fragments keep their shape but take pairs + the subtree subquery text), `api/analytics.py::_dm_scope_filter` and `submission_analytics_mv._mv_scope_filter` (unit part as subquery), `data_management.py` shells admit `project_pi`, `site_pi` via `effective_roles`; the dm-kpi APIs admit the same roles as the shell (4in). `VaUsers.is_data_manager` -> `effective_roles` (so navbar and `landing_url` follow). Closes: F11 (service/validator agreement), 38lp, 4in, unrouted-queue decision, project_pi-in-tree-project decision. Risk: high (largest surface, raw SQL in dm_kpi; KPI cache keys). Tests: matrix rows for DM / viewer / project_pi; `tests/routes/test_dm_kpi_unit_scope.py`, `test_data_manager_dashboard.py`, `tests/services/test_dm_scope_collaborator.py`, `test_unit_scoped_dm_tester.py`.

**Stage 4 — reviewing.** Files: `reviewer_coding_service._require_reviewer_access` (-> `require(REVIEW)`), `reviewing.py` (`dashboard` uses `scope_filter(REVIEW)`; `view_submission` -> `require(VIEW)`, F7), `va_validate_permissions._validate_vareview` (:251, :257, :281 -> `require`), `api/reviewing.py`. Closes: F7. Risk: low (small surface, F6 already fixed). The reviewer dashboard gains the area link (F7 note) once `_has_org_unit_area` is role-agnostic.

**Stage 5 — In-charge, site PI, project_pi screens, supervision.** Files: the migration (§5), `org_grant_service.validate_org_unit_grant` + `ROLES_ALLOWING_ORG_UNIT`, `mentor_institute_service` (test only), `case_transition_service._covering_grants` + `_SUPERVISING_ROLES`, `intake.py` supervision routes admit `site_pi`, `project_pi` through `effective_roles`, `sitepi.py` + `sitepi_reporting_service` (unit variant), `VaUsers.is_site_pi`/`is_interview_supervisor` -> `effective_roles`, admin panel + `access_grants.html` labels, `project_user_import_service` accepting `site_pi` with a unit code, `/help/user-roles` text. Closes: the In-charge decision, F8 (site PI report for project_pi), `vasitepi` partials (reachable only by hand-built URL today, audit §3) replaced by the `VIEW` rendering. Risk: medium (schema change, new role placement; in-charges work via `interview_supervisor` today so nothing breaks if it slips). Tests: migration round trip in `tests/migrations`, matrix rows for site_pi@unit, supervision predicate tests.

**Stage 6 — grant writes.** Files: `data_management.py` (`_dm_can_manage_scope`, `_dm_can_manage_unit_grant`, `_dm_grant_filter`, `_dm_listed_grant_condition`, `require_dm_scope` -> `can_grant` / `grant_list_filter`; the DM users page gains unit and cadre pickers for tree projects), `admin.py::admin_create_access_grant` / `admin_toggle_access_grant` (project_pi branch :2523-2527 -> `can_grant`), `project_user_import_service.prepare` (`is_admin` flag -> `can_grant` per row), `mentor_institute_service.dm_covers_mentor_unit` (subsumed), every write calls `invalidate`. Closes: the district DM grant decision; dm-user-grant-management.md status draft -> active. Risk: medium (write path; wrong table = wrong people get grants). Tests: `tests/authz/test_can_grant.py` from §2.5's table, both project kinds; `tests/test_auth_grants.py`, `test_org_unit_grants.py`.

**Stage 7 — delete the old helpers and the legacy fall-through.** Remove `submission_within_org_scope`, `submission_within_org_view_scope`, `_submission_within`, `wide_grant_scope`, `codeable_unit_ids`, `viewable_unit_ids`, `has_view_only_scope`, `project_wide_grant_exists`, `reachable_unit_ids` (area dashboard and the units picker move to `ResolvedGrants`), `_org_unit_scope_filter`, `tester_covers_submission`, `has_va_form_access` role branches, `has_data_manager_submission_access`, `has_data_manager_form_access`, `va_hasrole`, the `permission` JSONB fall-throughs (va_users.py:493-507, attachment_service.py:305-309, api/workflow.py:82-86; audit §8 shows every creation path writes `{}`; **count non-empty rows in production before deleting**, and keep the column), the stage-0 shadow test, `_dm_scope_pairs` bridging. `VaUsers.is_*` and `get_*` become wrappers or go. Update `docs/current-state/workflow-and-permissions.md`, `auth-decorator-rbac.md` §4 table, access-control-model.md "Implementation tracked in digitva-0wc" markers, F18's stale paragraph. Risk: low if stages 1-6 kept their tests.

## 8. Testing strategy

- **Matrix test** `tests/authz/test_matrix.py` + `tests/authz/matrix.py`. The expected outcomes are a **hand-written literal** derived from §2.3, never from `RULES` (otherwise the test is a tautology). Fixtures, built once per class on `tests/base.py` (`BaseTestCase`, class transaction + per-test savepoint, base.py:1-60): one tree project with `coding_scope_level_id` at PHC and `view_only`, one with `code_any`, one site project, one closed project, one demo-training project; units District > CHC > PHC > Sub-centre; submissions routed at district, PHC, sub-centre, unrouted, another site's form, closed project's form; users one per (role, scope type) plus a mentor and a mixed coder+collaborator. The literal is a list of `(user_key, action, sid_key, expected: bool | Reason)`, about 150 rows grouped by rule, each row's comment citing the policy line. The test iterates it through `can` and, for list actions, through `scope_filter`.
- **Single-source test** (§3).
- **can_grant test** from §2.5, both kinds, plus mentor and cadre refusals still raised after a `True` decision.
- **Fail-closed route probe** `tests/authz/test_fail_closed_routes.py`: a decorator marker only proves decorator-level checks and `require` lives in services, so instead: a fixture user with **no grants** hits every `url_map` rule whose arguments include `va_sid` (plus `form_id` sync routes and every `va_partial` name from the category config) as GET and, where the rule allows, POST with CSRF headers (`_csrf_headers`, base.py:536); assert never 200, and, with `authz.can` wrapped by a spy, assert it was invoked for each endpoint (not-invoked = a route that decided on its own). Extend `tests/test_route_auth_coverage.py`'s allowlist idea: endpoints that legitimately skip `can` (dashboards with no object) are listed with a reason.
- **Harness caveats**: one pushed app context for the whole session (base.py:29-33), so the `request.environ` memo is per test-client request and `resolve_grants` outside a request must not cache; `db.session.commit()` inside routes only releases a savepoint, so grant writes in tests are visible to the same test; one pytest run per test database (AGENTS.md). Reuse `base_admin_user`, `base_project_pi_user`, `base_coder_user`, `BASE_PROJECT_ID/BASE_SITE_ID` and the `CodingScopeFixtureMixin` pattern (tests/test_coding_scope_enforcement.py:33-90).

## 9. Not doing, and open questions

Not doing: no external engine; no new In-charge role (owner chose `site_pi@org_unit`); no schema change beyond the CHECK; no cross-request grant cache; no runtime shadow mode; `_ROLE_METHODS` stays a literal; no per-submission PII (viewer_pii_service docstring records that as decided); no change to web-intake interviewer scope (`web_intake_service._reachable_unit_ids`, grant-only by design); not widening route decorators per route (effective roles instead); not removing the `permission` column.

Open questions, genuinely undecided by policy:

1. **project_pi in a site project viewing submissions.** access-control-model.md:71 ("view data across all assigned sites") is read here as `VIEW` + attachments + events + the site PI report, no DM actions. Confirm.
2. **Reviewer demo access without a grant** (6zq): policy says coding only; `tests/routes/test_demo_training_project.py:363` says reviewing too. Module reproduces the test; one constant to change.
3. **In-charge and `SYNC_FORM`**: "every power of a data_manager in that subtree" (ACM:120-122) versus "whole-form operations need a project or site grant" (ACM:495-499). Applied the unit rule (single-submission sync only).
4. **Reviewer dashboard lists every state** (F19); unchanged.
5. **Coder `vaview` own-only** on the coder rendering (§2.4): kept; confirm it is intended.
6. **`organization`-mode project with no active level** is a site project to authz; confirm, or switch the kind test to the mode.
7. **Legacy `permission` JSONB**: delete the fall-through at stage 7 after a production count.
8. **Unit site-PI report contents**: which KPIs make sense per unit (coder roster, site gates do not apply).
9. **Supervision admin bypass**: none today; kept.

### Critical Files for Implementation
- /Users/vivekgupta/workspace/DigitVA/app/services/org_grant_service.py (the resolvers being replaced; `scope_unit_ids_select`, `active_project_condition`, `_project_scope_settings`, `validate_org_unit_grant`)
- /Users/vivekgupta/workspace/DigitVA/app/services/coder_workflow_service.py (`_org_unit_scope_filter`, `_CodingWaivers`, `_require_coder_access`, `allocate_pick_form`, `start_recode_allocation`)
- /Users/vivekgupta/workspace/DigitVA/app/decorators/va_validate_permissions.py (every partial validator)
- /Users/vivekgupta/workspace/DigitVA/app/models/va_users.py (`is_*`, `_get_granted_va_forms`, `has_*_access`)
- /Users/vivekgupta/workspace/DigitVA/app/routes/data_management.py and /Users/vivekgupta/workspace/DigitVA/app/routes/api/data_management.py (grant writes, unrouted queue, pin)
- /Users/vivekgupta/workspace/DigitVA/migrations/versions/c4a9e7d2b6f1_add_mentor_institutes_and_site_pi_scope.py (template for the In-charge CHECK migration)
