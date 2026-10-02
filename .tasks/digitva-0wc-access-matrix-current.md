# Access matrix as implemented today (read-only audit, 2026-10-02)

Method: static trace of the working tree (HEAD 12716c94 plus the uncommitted dm_kpi edits).
Nothing was executed; "CONFIRMED" below means the path was traced in code, not that a request was replayed.
All paths relative to /Users/vivekgupta/workspace/DigitVA. Related beads: digitva-0wc (the deep module this feeds),
digitva-blp, digitva-6zq, digitva-4in.

## 0. Vocabulary and the primitives every screen is built from

### 0.1 Layers
1. `role_required(*roles)` (app/decorators/role_required.py:96-169): role gate only, OR semantics. Predicate map at :55-73.
   `collaborator` and `collaborator_pii` both map to `is_viewer()` (:71-72). `admin` is its own predicate; there is NO general admin bypass downstream.
2. Form-level: `has_va_form_access(form, role)` (app/models/va_users.py:486-508), `is_coding_tester(form)` (:191-195),
   `has_data_manager_submission_access(project, site, org_unit)` (:431-448), `is_site_pi(form)` (:197-201).
3. Per-submission org scope (tree projects only): `submission_within_org_scope` (coding scope, app/services/org_grant_service.py:574),
   `submission_within_org_view_scope` (viewing scope, :611), list-side twin `_org_unit_scope_filter` (app/services/coder_workflow_service.py:176-233),
   `tester_covers_submission` (:309-326).
4. Workflow/ownership: `va_validate_permissions` validators (app/decorators/va_validate_permissions.py), allocation checks (app/utils/va_permission/*), service-layer state checks.

### 0.2 Role predicates (what opens the role gate)
| Role | Predicate | Source |
|---|---|---|
| coder | form-resolved grants (project, project_site w/ ACTIVE project-site, org_unit via forms in subtree) OR any live unit grant OR demo union | va_users.py:152-156, 350-351, 510-607 (active-site rule :602-603, demo union :605-606) |
| coding_tester | same resolver, role coding_tester (no active-site rule) | va_users.py:191-195, 353-354 |
| reviewer | same resolver, role reviewer | va_users.py:203-207, 369-370 |
| site_pi | form resolver only (`site_pi` is project_site scope only, never org_unit) | va_users.py:197-201, 362-363 |
| project_pi | EXISTS project-scope project_pi grant on an active project | va_users.py:277-299 |
| data_manager | direct (project/project_site) OR unit grant | va_users.py:221-245 |
| collaborator / collaborator_pii | project, project_site, or org_unit viewer grant | va_users.py:381-421 |
| admin | global grant | va_users.py:261-275 |

Closed projects: every resolver ANDs `active_project_condition` (org_grant_service.py:154-177), so a closed project resolves no non-admin grant.

### 0.3 Org-based vs conventional
- A project is "org-based" when it has an active `mas_org_level` row (`_submission_within`, org_grant_service.py:536-572; `projects_with_org_tree` :496; list twin `project_has_tree` coder_workflow_service.py:204-212).
- On a conventional project every org-scope function returns True / is a no-op (org_grant_service.py:555-556 "if not has_tree: return True"; coder_workflow_service.py:218 `sa.not_(project_has_tree)`).
  So conventional = form-level check only.
- Coding scope (org-based): `codeable_unit_ids` (org_grant_service.py:328-384) keeps a unit grant when scope level is unset, OR grant depth >= scope depth, OR `above_scope_coding_mode == code_any`; then expands to subtree.
  `wide_grant_scope(coding=True)` (:506-533) keeps a project / project_site grant only when scope level is unset or mode is `code_any`.
  Viewing scope: `viewable_unit_ids` = whole subtree of every unit grant (:602-608); `coding=False` keeps all project / project_site grants.
- Unrouted submissions (org_unit_id NULL) on a tree: reached only by project / project_site grants (:565-566), never by unit grants.

Grant-scope behaviour on a TREE project for coder / reviewer (the rule every coder/reviewer screen is supposed to follow):
| Grant | no scope level | scope level + code_any | scope level + view_only |
|---|---|---|---|
| project | codes + views whole project incl. unrouted | same | views whole project, codes nothing |
| project_site | codes + views that (project,site) pair incl. unrouted | same | views pair, codes nothing |
| org_unit at/below scope depth | codes + views subtree | codes + views subtree | codes + views subtree |
| org_unit above scope depth | codes + views subtree | codes + views subtree | views subtree, codes nothing |
(org_grant_service.py:328-384, 506-533, 536-572, 602-618). coding_tester is exempt from scope level (coder_workflow_service.py:213-215 adds `scope_unit_ids(coding_tester)`; policy organization-model.md "coding_tester is exempt").
Conventional: project / project_site grants only; unit grants cannot exist in a project with no tree in practice, and org filters are no-ops.

## 1. Coding surfaces (app/routes/coding.py, app/routes/api/coding.py)

| Screen / API | Role gate | Form-level check | Per-submission check | Conventional | Org-based (project / project_site) | Org-based (org_unit; view_only vs code_any) |
|---|---|---|---|---|---|---|
| GET /coding/ dashboard (coding.py:49-220) | coder, coding_tester, admin (:50) | forms = coder forms U tester forms (:52); active project-site rule only for coder (va_users.py:602) | counts filtered by `_org_unit_scope_filter` (:66-68) | counts for granted forms | project/pair grant counts incl. unrouted only if codes (scope level unset or code_any); under view_only count 0 | counts only codeable units (+ tester subtree); view_only above-scope grant shows 0 and `has_org_unit_area` link (:219,223-231) |
| POST /coding/start random (:234-245; service coder_workflow_service.py:699-773) | coder, tester, admin | `get_coder_va_forms | get_coding_tester_va_forms` (:713) | pool via `_available_submission_filters` (:236-262): state, ODK, dup, language, org filter, TR01; site gates (:725-741), unit gates (:745-747) | allowed | filter above | filter above; view_only never yields work |
| GET /coding/resume (:248-260) | coder, tester, admin | none (reads own active allocation) | none at shell; partial validator `varesumecoding` re-checks coding scope (va_validate_permissions.py:131-134,146-153) | ok | ok | ok |
| POST /coding/pick/<sid> (:263-271; service :776-845) | coder, tester | `has_va_form_access(coder) or is_coding_tester` (:795) | `tester_covers_submission or submission_within_org_scope(coder)` (:802-807); state, retired, dup (:813-820); site gate (:822-826); unit gate (:828-834); NO language filter, NO TR01 filter | allowed | project/pair grant must code (scope level rule) | codeable set only, so view_only -> 403 "outside your coding scope" |
| Pick list `get_pick_available_forms` (:1117-1149) via /coding/ and /api/v1/coding/available | same | same | `_available_submission_filters` (language, org, TR01) but NOT site/unit coding gates | lists | lists | lists codeable only |
| POST /coding/recode/<sid> and POST /api/v1/coding/recode/<sid> (coding.py:274-281; api/coding.py:168-176; service :848-930) | coder, tester | NONE | NONE: no form check, no org scope check, no ownership check (only: no live allocation, retired, dup, state `coder_finalized`, 24h window) | any coder reaches any site | same | same (F1) |
| GET /coding/view/<sid> shell (coding.py:296-313) | coder, tester, admin | `has_va_form_access(coder) or tester_covers` (:304) | `tester_covers or submission_within_org_view_scope(coder)` (:308-312) | form check only | wide grant views regardless of scope level | viewable subtree |
| ... its content partials (`action=vacode&actiontype=vaview`, `_validate_vacode` :213-218 + :126-129) | via login_required + validator | `_has_coding_form_access` (:105-111) | `_within_viewing_org_scope` = view scope for role coder ONLY, no tester shortcut (:95-102) + `va_permission_ensureviewable` = user's OWN active final or coder-review (va_permission_06_ensureviewable.py) | own coded only | same | same (shell opens for any in-scope submission; partials only for the user's own; F4, F5) |
| GET /coding/area overview (coding.py:329-401) | coder, tester, reviewer, admin | none | rows = submissions routed to `viewable_unit_ids(role)` ONLY (org_unit grants), inner join to unit (:374-377); `is_codeable` flag (:391) | empty page (no tree, no unit grants) | EMPTY: project / project_site grants are not in `viewable_unit_ids` (F2) | lists viewable subtree, marks codeable vs "view only" |
| GET /coding/area/<sid> shell (:417-443) | coder, tester, reviewer, admin | `is_admin or has_va_form_access(role) or tester_covers` (:431-435) | `submission_within_org_view_scope(role)` (:437), no tester shortcut | conventional: shell opens (no-op) | wide grant ok | viewable subtree ok; renders `render_va_coding_page(..., "vadata", "vaview", "coder")` (:443) |
| ... its content partials (`action=vadata`) | validator `_validate_vadata` (va_validate_permissions.py:307-331) | `has_data_manager_submission_access` ONLY | n/a | 403 for non-DMs | 403 | 403 (F3, bead digitva-blp) |
| GET /api/v1/coding/allocation, /stats, /history, /projects, /available (api/coding.py:63,204,218,234,254) | coder, tester, admin | forms from coder U tester | /stats and /available through `_available_submission_filters`; /history by own outcomes | | | |
| POST /api/v1/coding/allocation (api/coding.py:110-161) | coder, tester, admin | `allocate_pick_form` / `allocate_random_form` | as the HTML twins (demo requires admin :121) | | | |
| /coding/demo (coding.py:284) | admin only | n/a | n/a | demo projects only | | |
| POST /api/v1/coding/admin-override-recode (api/coding.py:179) | admin | n/a | n/a | | | |

Coder content partials and saves (renderpartial, va_form.py:590-593, `action`/`actiontype` read from request.values :604-605, same source as the validator, va_validate_permissions.py:36-37):
| actiontype | Validator checks (`_validate_vacode`) | Notes |
|---|---|---|
| vastartcoding (:135-145) | coding org scope (:131-134), `_has_coding_role`, 200-form yearly cap (:140), allocation on partials | |
| varesumecoding (:146-153) | coding org scope, role, any allocation, allocation on this sid on partials | form access NOT re-checked: a recode allocation (F1) carries a coder through |
| varecode (:154-163) | form access (:155), no active allocation, `validaterecodelimits` = own prior outcome within 24h | the route /coding/recode never uses this actiontype (F1) |
| vapickcoding (:164-199) | form access, 200 cap, pick intake mode, ready-pool state, retired, dup | allocation on partials |
| vademo_start_coding (:200-212) | admin returns early; else coder/tester role + demo submission + allocation | |
| vaview (:213-218) | see section above | |
Saves: final COD requires an active coding allocation in-handler (va_form.py:1654-1666). Step-1 save (`vainitialasses` POST, :1261-1370) has no in-handler allocation check; it relies on the validator and `mark_coder_step1_saved` state guard (F9). NQA / Social Autopsy / ICD search / DORIS APIs require an active allocation for the sid (va_permission_11_require_coding_access.py; api/nqa.py:71-74; api/so.py:69-72; api/icd10.py:107-129; api/doris_clinical.py:72-105), so allocation is the entitlement there.

## 2. Reviewing surfaces (app/routes/reviewing.py, app/routes/api/reviewing.py)

| Screen / API | Role gate | Form-level | Per-submission | Conventional | Org-based project / project_site | Org-based org_unit |
|---|---|---|---|---|---|---|
| GET /reviewing/ dashboard (reviewing.py:38-203) | reviewer | `get_reviewer_va_forms` (:41) + active project-site join (:62-67) | `_org_unit_scope_filter(role="reviewer")` (:44,75,160) = CODING scope; language `in_(vacode_language)` exact match; lists every submission of the form regardless of workflow state (no state filter) | lists | like coder | codeable only; view_only lists nothing |
| GET /reviewing/start/<sid> (:206-215) | reviewer | `start_reviewer_coding` (reviewer_coding_service.py:245-311): form access (:253), language (:255), dup, state must be `reviewer_eligible`, no existing final, retired | NONE: no org scope check anywhere in the service | allowed | allocates + commits state change (F6) | same (F6) |
| POST /api/v1/reviewing/allocation/<sid> (api/reviewing.py:46-52) | reviewer | same service | none (F6) | | | |
| POST /api/v1/reviewing/finalize/<sid>, /initial/<sid> (api/reviewing.py:56,118; service :314-360) | reviewer | `has_va_form_access(reviewer)` (service :342) | allocation + state; NO org scope | | | out-of-scope submit possible once allocated (F6) |
| GET /reviewing/resume (:218-224) | reviewer | allocation | partial validator re-checks reviewing scope (va_validate_permissions.py:251-254) | | | |
| GET /reviewing/view/<sid> shell (:227-240) | reviewer | `has_va_form_access(reviewer)` | `submission_within_org_scope(reviewer)` = CODING scope (:236) | form only | like coder coding rule | view_only reviewer refused (F7) |
| ... partials (`action=vareview&actiontype=vaview`, `_validate_vareview` :280-284) | validator | `has_va_form_access(reviewer)` | `_within_reviewing_org_scope` = coding scope (:251) ; no ownership, no workflow-state check | any in-form submission | | |
| partials start/resume (:255-279) | | form access, language, retired, `ensurenotreviewed`; allocation on partials | reviewing org scope (:251) | | | |
| NQA / SO / ICD / DORIS reviewer saves | | `has_va_form_access(reviewer)` | active reviewing allocation | | | |
| `vareviewform` POST partial (va_form.py:1117-1204) | validator only | | no allocation check in handler (F10) | | | |

## 3. Site PI, project PI, area, collaborator

| Screen / API | Role gate | Form/scope check | Per-submission | Behaviour |
|---|---|---|---|---|
| GET /sitepi/ (sitepi.py:20-35), /sitepi/data (:38-56) | site_pi | `get_site_pi_project_site_pairs()`; /data re-checks pair against the user's grants (:47) | aggregates only | conventional only (site_pi cannot be a unit grant; organization-model/access-control policy). project_pi has NO site PI dashboard |
| Site PI submission view | `action=vasitepi` partials only; there is NO shell route that renders `vasitepi` (grep: only validator, template hint vademographicdetails.html:108, category_rendering_service.py:37) | `has_va_form_access(form,"sitepi")` (va_validate_permissions.py:293) | none: any submission of the form; `varecode` needs coded, `varereview` needs reviewer_finalized (:297-300) | reachable only by hand-built URL |
| project_pi data screens | NONE: `project_pi` appears in role_required only on serve_attachment (va_form.py:2052) and admin/org panels | n/a | n/a | no submission view, no attachments (F8) |
| GET /area/ (routes/area.py:14-17), /api/v1/area/* (api/area.py) | login_required (no role) | `candidate_projects` / `resolve_area_scope` (area_dashboard_service.py:128-225) | counts only | tree: whole tree for admin, project_pi, or any project/project_site grant of an org-unit-capable role, else union of unit subtrees (`reachable_unit_ids`, org_grant_service.py:464-493); sites-mode: all sites for project grant, else granted sites (area_dashboard_service.py:154-189). Outside area = 404 |
| Collaborator / collaborator_pii: GET /data-management/ and /dashboard (data_management.py:307-361), /api/v1/data-management/submissions, /kpi, /filter-options (api/data_management.py:217,309,358) | collaborator, collaborator_pii (+data_manager; admin on the two page shells only) | `get_dm_view_projects`, `get_dm_view_project_sites`, `dm_org_unit_ids` (data_management_service.py:345-380); org_unit grants bridged to whole project then narrowed per submission by `dm_submission_org_unit_condition` (:414-441) | rows redacted by `should_redact_pii` | No submission detail, no attachments, no workflow events, no coding/reviewing, no navbar link (no `is_viewer` in any template; landing_url va_users.py:92-119 has no viewer case; DM navbar links va_navbar.html:78,87 need is_data_manager) |

## 4. Data manager surfaces (app/routes/data_management.py, app/routes/api/data_management.py)

| Screen / API | Role gate | Form-level | Per-submission | Notes |
|---|---|---|---|---|
| /data-management/ and /dashboard shells (:307-361) | data_manager, admin, collaborator, collaborator_pii | any dm-view scope | n/a | admin passes the gate but has no DM scope, so counts/lists are empty; the dm-kpi APIs behind /dashboard are data_manager only (bead digitva-4in) |
| /data-management/view/<sid> (:402-429) | data_manager, admin | | `has_data_manager_submission_access(project, site, org_unit)` (:415); admin has no bypass here | renders `vadata`; audit read written |
| vadata partials (`_validate_vadata`, va_validate_permissions.py:307-331) | validator | | same method; only `vaview` accepted | admin 403; coder/reviewer 403 (F3) |
| POST sync / screening / upstream-change / odk-edit etc. | data_manager (+admin on upstream/screening/odk-edit pages) | | `has_data_manager_submission_access`; the service-layer `_dm_submission_scope_check` DOES bypass for admin (data_management_service.py:2508-2524) | admin can accept upstream change but not view the submission (F11) |
| Unit-grant DM: whole-form ops need direct scope (api/data_management.py:392-396, 415-421, 514-520) | | `dm_form_in_scope` direct only | | single-submission refresh covers subtree (:624-640) |
| /data-management/cod-buckets, exports, coder-daily-stats, dm_kpi/* | data_manager (cod-buckets API also admin) | | | collaborators excluded by design (access-control-model.md "Route wiring"); dm_kpi unit-grant coverage is mid-edit in the working tree (HEAD: unit-only DMs see an empty panel; policy text still says so) |

## 5. Attachments, workflow events (per-submission side channels)

| Screen / API | Role gate | Check | Result |
|---|---|---|---|
| GET /vaform/attachment/<token>, /vaform/media/<form>/<file> (va_form.py:2051-2146) | attachment: coder, reviewer, data_manager, site_pi, project_pi, admin; media: login_required only | `can_access_submission_attachment` (attachment_service.py:274-310), fresh each time | admin always; DM via `has_data_manager_submission_access`; site_pi by form only; reviewer by form + `submission_within_org_scope` (CODING scope); coder/tester ONLY if `_user_holds_submission` (allocation OR own active outcome) AND (`tester_covers` or view scope); legacy `permission` dict last. No branch for project_pi, collaborator, or a role-less coding_tester (F8, F12) |
| GET /api/v1/workflow/events/<sid> (api/workflow.py:14-86) | login_required | `_may_read_events`: DM submission access; coder or reviewer = form access + VIEW scope for that role; site_pi by form; legacy dict | no admin branch, no tester branch, no project_pi branch; coder reads events of ANY in-scope submission, not only own (F13) |
| `workflow_history` partial (va_form.py:1221-1231) | validator only | no extra | follows the action's validator |

## 6. Findings (inconsistencies)

Severity: H = authorization bypass or data write across scope; M = screen/partial disagreement or policy contradiction users hit; L = hygiene.

F1 [H, CONFIRMED; no test covers it: tests/ has only the same-sid reuse test, tests/services/test_coding_allocation_service.py:858, and nothing asserts a non-owner or out-of-scope recode is refused] Recode start has no form, scope, or ownership check.
`POST /coding/recode/<sid>` (coding.py:274-281) and `POST /api/v1/coding/recode/<sid>` (api/coding.py:168-176) call `start_recode_allocation` (coder_workflow_service.py:848-930). That function checks only: no other live allocation (:855-871), retired/dup (:873-876), state == coder_finalized and an authoritative final within 24h (:878-895). It never checks that the caller coded it, holds the form, or is inside org scope. The UI list (`get_coder_recodeable_sids`, coder_dashboard_service.py:309-348) and the `varecode` validator (va_validate_permissions.py:154-163, `va_permission_validaterecodelimits`) enforce ownership, but neither route uses them. Result: any coder or tester with any grant can create a coding allocation, a recode episode and a workflow transition on another coder's / another site's recently finalized submission by sid. The follow-up `/coding/resume` partials pass: `varesumecoding` checks role, allocation and (tree only) org scope, never form access (:146-153). Conventional projects have no org check at all, so cross-site takeover is open there.

F2 [M, CONFIRMED] Area overview lists a different set than the area view opens, and than the policy says.
Overview rows come only from `viewable_unit_ids` (org_unit grants; coding.py:337,377). Policy (organization-model.md "Viewing scope"; access-control-model.md Role To Scope Rules) says a project / project_site coder or reviewer views every submission of the project/pair, routed or unrouted. `area_view_submission` honours that via `submission_within_org_view_scope` (:437, wide grants at org_grant_service.py:565) but the list and the navbar-ish link `_has_org_unit_area` (coding.py:223-231) do not: a project-scope coder on a tree project sees an empty overview and no link, yet could open a sid by URL. Unrouted submissions are excluded even from unit viewers (inner join on `MasOrgUnit`, :374). The Area dashboard (`reachable_unit_ids`, org_grant_service.py:464-493) answers the same "what do I oversee" question including wide grants and the project PI, so two screens disagree.

F3 [M, CONFIRMED] Area view shell opens; every content partial 403s (digitva-blp). `area_view_submission` renders action `vadata` (coding.py:443); `_validate_vadata` (va_validate_permissions.py:322-327) allows only `has_data_manager_submission_access`. Coder/reviewer/tester get the shell with "Loading..." and 403 partials; the shell also ships DM hints because `back_dashboard_role="coder"` but `va_action="vadata"` selects the DM category set (category_rendering_service.py:38). Additional blockers that survive a validator-only fix: attachments (F12: `_user_holds_submission` refuses a viewer who did not code or hold the case) and `workflow_history`. `render_va_coding_page` also queues `run_open_submission_repair` on every `vadata` shell open (coding_service.py:91-103): a read-only viewer triggers a repair job.

F4 [M, CONFIRMED] `/coding/view/<sid>` shell vs partials disagree on coding_tester. Shell lets `tester_covers_submission` bypass the unit check (coding.py:303-312); the partial validator for `vaview` calls only `_within_viewing_org_scope` (va_validate_permissions.py:126-129), which has no tester shortcut (:95-102) and resolves view scope for role `coder` only. A project / site / unit tester with no coder grant on a tree project gets 403 "outside your area" on every partial of a submission they coded. Same absence of the tester shortcut in `area_view_submission` (:437). Attachments do honour the tester (attachment_service.py:301-304), so three screens, three answers.

F5 [M, CONFIRMED] `/coding/view/<sid>` shell opens for any in-scope submission; partials require the user's OWN active final/review (`va_permission_ensureviewable`, va_permission_06_ensureviewable.py) and attachments the allocation/own outcome (attachment_service.py:236-259). The shell checks neither (coding.py:296-313). Reachable only by URL guess today (coder history links are own cases), so low traffic, but it is the same shell-then-403 pattern as F3.

F6 [H, CONFIRMED; no test covers it: tests/test_coding_scope_enforcement.py:456-463 only checks that a reviewer grant gives no CODING scope; tests/routes/test_reviewing_routes.py and tests/services/test_reviewer_coding_service.py use project_site grants and never an out-of-unit reviewer start] Reviewer unit-scope bypass on allocation and API submit.
`reviewing.start` (reviewing.py:206-215), `POST /api/v1/reviewing/allocation/<sid>` (api/reviewing.py:46-52) and the service `start_reviewer_coding` (reviewer_coding_service.py:245-311) check form access, language, state; no `submission_within_org_scope`. The scope gate lives only in `_validate_vareview` (va_validate_permissions.py:251), i.e. only on `renderpartial`. Consequences on a tree project: (a) a reviewer outside the unit, or a view_only reviewer, who knows or guesses an eligible sid allocates it, flips it to reviewer_coding_in_progress and holds it for the 1h timeout; the HTML shell then renders with 403 partials. (b) Via the JSON API there is no partial at all: `POST /api/v1/reviewing/finalize/<sid>` and `/initial/<sid>` (api/reviewing.py:56,118; service form check :342) require only reviewer form access + allocation, so the whole review can be completed out of scope. Compare coder pick, where the service checks scope (coder_workflow_service.py:798-807). It also bypasses the "reviewing list" filter (reviewing.py:44).
Also `GET /reviewing/start/<sid>` is a state-changing GET (allocation + workflow transition + commit), so there is no CSRF protection on it despite the CSRF-on-state-change rule in CLAUDE.md. [CONFIRMED]

F7 [M, CONFIRMED behaviour; policy wording ambiguous] Reviewer viewing scope is the coding scope, against the Viewing-scope bullet "The same rule governs the reviewer track, using reviewer grants" (organization-model.md). tests/test_project_grant_org_scope.py:188-196 asserts reviewer ATTACHMENTS deliberately follow coding scope, so this part looks intended; the contradiction is internal: the reviewer events API uses view scope (api/workflow.py:75-79). Coder `vaview` uses viewing scope (va_validate_permissions.py:126-129, coding.py:308-312). Reviewer `vaview` uses `submission_within_org_scope` (coding scope: va_validate_permissions.py:223-230,251; reviewing.py:236; attachments attachment_service.py:290-292). A reviewer above the scope level under view_only can open nothing: not the shell, not partials, not attachments; their only read path is `/coding/area/<sid>` with `?role=reviewer`, which is F3. Reviewer events API does use view scope (api/workflow.py:75-79), so a view_only reviewer reads the event history but nothing else. The reviewer dashboard also has no link to the area overview (reviewer-only users cannot reach /coding/area from any nav: `has_org_unit_area` is on the coder dashboard only, va_code.html:262-273; navbar shows VA Coding only for `can_access_coding_dashboard`, va_navbar.html:51).

F8 [M, CONFIRMED] project_pi has role gate access but no data access, contradicting access-control-model.md ("project_pi: view data across all assigned sites"). `serve_attachment` lists project_pi (va_form.py:2052) but `can_access_submission_attachment` has no project_pi branch (attachment_service.py:274-310) so it always 403s (unless a legacy permission-dict entry exists). No validator (vacode/vareview/vasitepi/vadata) and no events branch accept project_pi. There is no project-PI submission view or site-PI-style dashboard at all (sitepi.py:21,39 are `site_pi` only). project_pi's reach is: org panel and admin project management, area dashboard counts.

F9 [H, CONFIRMED by static trace; not replayed] A non-coder can save a coder Step-1 and pull an uncoded submission out of the pool.
`renderpartial` rewrites `vainitialasses` to `vafinalasses` only for UNMASKED projects (va_form.py:606); `masked_cod_required` defaults to true (app/models/va_project_master.py:120-122, cod_entry_mode.project_mode), so on default projects the Step-1 branch (va_form.py:1232-1386) is live. Its POST path has no allocation check and no role/action check: it deactivates the caller's prior initial rows, inserts a `VaInitialAssessments` row, audits as `vacoder`, and calls `mark_coder_step1_saved` (:1352-1370), whose allowed_from includes `ready_for_coding` (app/services/workflow/transitions.py:469-487). `coder_step1_saved` is not in `CODER_READY_POOL_STATES` (= {ready_for_coding}, workflow/definition.py:64), so the case leaves the pool. The only gate is the validator for the caller's chosen `action`/`actiontype`: `action=vareview&actiontype=vaview` needs just reviewer form access + reviewing scope (va_validate_permissions.py:251,280-284); `action=vasitepi&actiontype=vaview` needs site-PI form access only (:293,301-302); `action=vadata&actiontype=vaview` needs DM scope (:322-331). None requires an allocation or a workflow state. `is_category_enabled` (va_form.py:618) does not intercept because `vainitialasses` is not a nav category (to be confirmed per form type). Needs a valid CSRF token and a valid ICD value, and this audit did not execute it. Recovery of such a stuck case is not traced: stale-release is allocation-driven (coding_allocation_service.py:158-, :537) and there is no allocation. Settle by a test: as a reviewer on a masked project POST `/vaform/<sid>/vainitialasses?action=vareview&actiontype=vaview` for a ready_for_coding sid and assert 403. The same missing allocation check applies to `vacoderreview` POST (va_form.py:1946-2045, which then dereferences a None allocation at :1985 and 500s before committing, so it is a robustness bug, not a write).

F10 [L, PLAUSIBLE] `vareviewform` POST (va_form.py:1117-1204) writes the caller's `VaReviewerReview` row with no allocation or state check; `action=vareview&actiontype=vaview` passes `_validate_vareview` with just form access + reviewing scope (va_validate_permissions.py:280-284). Template reference exists (vareviewform.html:1) but no navigation reaches it; settle by checking whether any shipped screen renders it.

F11 [M, CONFIRMED] Admin passes role gates but fails per-submission checks. `role_required("data_manager","admin")` on `/data-management/view/<sid>` (data_management.py:403) then `has_data_manager_submission_access` (:415, grants only; va_users.py:431-448) -> 403 for an admin with no DM grant; same in `_validate_vadata` (:322-327) and `dm_odk_edit_url` (data_management_service.py:635). `/coding/view/<sid>` likewise (coding.py:297-305, no admin shortcut) while `/coding/area/<sid>` has an admin shortcut (:432) that then fails view scope on tree projects. No validator has an admin bypass (auth-decorator-rbac.md says admin bypasses ABAC "via va_hasrole", but `va_hasrole` is only used for dashboard-role checks at va_validate_permissions.py:40-45). Meanwhile the service layer does bypass for admin (`_dm_submission_scope_check`, data_management_service.py:2520). Net: admin can accept an upstream change but cannot open the submission it is about. Also the DM API list endpoints exclude admin (api/data_management.py:218,310,359) while the page shells include admin (data_management.py:308,338).

F12 [M, CONFIRMED] Attachment role gate vs service disagree. `serve_attachment` omits `coding_tester` (va_form.py:2052) although the service has a tester branch (attachment_service.py:294-304); a tester-only user fails at the role gate (their `is_coder()` is False, va_users.py:152-156) unless a demo project makes everyone a coder (F14). `serve_media` has no role gate at all (va_form.py:2086, `login_required` only) and relies on the service. Coder/tester attachments additionally require allocation or own outcome, which is stricter than the coder view shell and the events API.

F13 [L, CONFIRMED] `GET /api/v1/workflow/events/<sid>` is wider/narrower than the page it serves: any coder/reviewer with form access and view scope reads the event history of any in-scope submission, not only their own (coder `vaview` partials need own outcome); no admin, tester, or project_pi branch (api/workflow.py:55-86). Events carry actor_role not names, so exposure is low.

F14 [M, CONFIRMED mechanism, intent PLAUSIBLE; bead digitva-6zq] `_get_granted_va_forms` unions all demo-training project forms into the result for coder, coding_tester, data_manager AND reviewer for every user (va_users.py:605-606). So while a demo project has an active form, `is_coder()`, `is_reviewer()` and `is_coding_tester()` are True for every signed-in user, `reviewing.dashboard` and all `role_required("reviewer")` routes open, and `has_va_form_access(demo_form, "reviewer")` is True. Policy (coding-workflow-state-machine.md:251) says only that demo projects are open for CODING.

F15 [M, CONFIRMED] Coding tester on a tree project at project or project_site scope sees an empty pool. `_org_unit_scope_filter` (coder_workflow_service.py:213-233) adds tester units only for unit grants (`scope_unit_ids(coding_tester)`, :215) and wide grants only for the `coder` role (`wide_grant_scope(user, coder)`, :221). So dashboard counts, random allocation and the pick list exclude every tree-project submission for a project/site tester with no coder grant, while pick (`tester_covers_submission`, :802), view (coding.py:303) and `_within_coding_org_scope` (va_validate_permissions.py:90) accept them. `_CodingWaivers` and `tester_covers_submission` (:265-326) treat project/pair testers as covering every submission, which is the documented intent.

F16 [L, CONFIRMED] `allocate_pick_form` skips filters its own list applies: narration language (`_narration_language_filter`, :84-88) and the TR01 cutoff (:91-98) are in `_available_submission_filters` (:236-262) but not in the pick path (:776-845). The pick list also omits the site/unit coding gates that pick then enforces (:822-834), so the list can offer rows pick refuses. A coder can POST /coding/pick/<sid> for a submission in a language outside their profile. The validator `vapickcoding` (va_validate_permissions.py:164-199) does not check language either.

F17 [L, CONFIRMED] Area overview mixed-role links drop `role`: the overview for a user with coder and reviewer unit grants can be rendered with `?role=reviewer`, but the View link (va_area_overview.html:79) carries no role, and `area_view_submission` re-derives it (coding.py:428; `_prefers_reviewer_area` :404-414), defaulting to coder when any coder viewable units exist, so reviewer-only rows return 403. Also `coding_tester` is admitted to both area routes (coding.py:330,418) but `viewable_unit_ids` is evaluated for coder/reviewer only, so a tester-only user gets an empty overview.

F18 [L, CONFIRMED] Doc contradiction: access-control-model.md ends the "Route wiring" section with "Inherited ... neither `_expand_project_ids_to_active_pairs` nor `get_data_manager_projects()`/`get_viewer_projects()` checks the project's own status", but `_get_granted_project_ids` now applies `active_project_condition` (va_users.py:643-668) and the "Closed Projects" section of the same file says the opposite. Same file also says dm-kpi panels leave unit grants out while the working tree is changing that.

F19 [L, CONFIRMED] Reviewer dashboard lists every submission of the reviewer's forms regardless of workflow state or whether reviewing is open (reviewing.py:154-177 only filters language, org scope, dup, retirement), and `view` opens any of them (no ownership/state, unlike coder `ensureviewable`). Whether that is intended oversight or leakage of pre-coding data to a reviewer is a policy question; coding-workflow-state-machine.md says reviewer coding opens only after the recode window.

## 7. Per-role summary of what each can reach today

- coder: dashboard/start/pick/resume/recode (F1); view shell (any in-scope), partials (own only); area overview (unit grants only, F2) + area shell (partials 403, F3); attachments (allocation or own); events (any in-scope).
- coding_tester: as coder, minus scope-level restriction; pool empty for project/site testers on tree projects (F15); partials on tree 403 (F4); attachments blocked at role gate if no coder grant (F12).
- reviewer: dashboard, start (no scope check, F6), resume, view (coding scope, F7); area routes; attachments by coding scope; events by view scope.
- site_pi: dashboard + data (pairs); hand-built `vasitepi` partials for any submission of the form; attachments by form; events by form.
- project_pi: no submission screens; area dashboard; org/admin panels (F8).
- collaborator / collaborator_pii: DM dashboard shell, submissions list, KPI cards, filter options; area dashboard; nothing else; no nav entry.
- data_manager: DM pages, view (read-only `vadata`), triage, sync, grant management, KPI, attachments, events; unit-DM narrower for whole-form ops.
- admin: coding dashboard/start/resume/demo; DM shells and upstream/screening actions; cannot open any submission via the validators (F11); attachments yes; events no.

## 8. Legacy `va_users.permission` JSONB fall-through (not role/scope based)
`has_va_form_access(form, role)` for any role string other than coder/reviewer/sitepi reads the dict (va_users.py:493-494, 503-507); `can_access_submission_attachment` (attachment_service.py:305-309) and `_may_read_events` (api/workflow.py:82-86) accept any form listed under a legacy key other than coder/reviewer/sitepi, with no org scope and no grant, status or closed-project check. Writers: `va_user_create`/`va_user_update` (app/services/va_user/va_user_01_create.py:57, 02_update.py:87) reached from `va_db_initialise_04_vausers.py` seeding, and app/commands/seed.py:250 (`{"coder": [...]}`, which the coder path ignores). Every application user-creation path writes `{}` (user_account_service.py:73, project_user_import_service.py:218, commands/users.py:217). So it is effectively dead for new users but remains a live, undocumented, scope-free fall-through for any user whose dict was populated.

## 9. Not traced (boundary of this audit)
app/routes/api/analytics.py and the MV helpers behind it; internals of app/routes/api/cod_buckets.py (role gate only: data_manager/admin, :82,:99); app/routes/api/organization.py (picker; only the shared `reachable_unit_ids` was read); the uncommitted app/routes/api/dm_kpi/* edits (only role gates and the HEAD scope docstring read); web intake (app/routes/intake.py) and interviewer/supervisor grants; app/routes/api/device.py, instruments.py, profile.py, va_definitions.py (role gates only, from grep); admin panel routes beyond `_current_user_can_manage_project`; whether `vainitialasses` is a nav category for any form type; whether `vareviewform` is ever rendered; no request was replayed and no test was run.
