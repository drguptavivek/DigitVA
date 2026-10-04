---
title: API v1 Reference (me)
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-10-04
---

# API v1 Reference (me)

Policy: `docs/policy/api-v1.md`. Code: `app/routes/api/me.py`,
`app/services/access_summary_service.py`. Tests: `tests/routes/test_me_access.py`.

Both routes take either credential: the browser session cookie, or
`Authorization: Bearer <access token>` (a bearer request is authenticated by
the token alone; a bad token is 401). The terms, maintenance and factor-setup
gates apply to both. Cookie state changes need `X-CSRFToken`; bearer requests
do not.

## GET /api/v1/me/access

The signed-in user's whole access in one body. Rate limit 120 per minute.
Explicit grants only: demo-training virtual grants are never listed.

```json
{
  "user": {"user_id": "...", "name": "..."},
  "is_admin": false,
  "demo_coding": {"available": true, "project_ids": ["DEMO01"]},
  "projects": [{
    "project_id": "TST001", "project_name": "...", "has_tree": true,
    "grants": [
      {"role": "interviewer", "scope": "org_unit", "org_unit_id": "...", "unit_name": "..."},
      {"role": "coder", "scope": "project_site", "site_id": "...", "codes": false},
      {"role": "project_pi", "scope": "project"}
    ],
    "sites": [{"site_id": "...", "site_name": "...", "roles": ["coder"]}],
    "levels": [{"level_code": "phc", "level_name": "PHC", "depth": 3}],
    "units": [{"org_unit_id": "...", "unit_code": "...", "unit_name": "...",
               "level_code": "phc", "depth": 3, "parent_code": "...", "path": "D1.C1.P1",
               "is_active": true, "roles": ["interviewer"], "selectable": true,
               "can_code": false}]
  }]
}
```

- `user`: id and name only (no email or mobile).
- `is_admin`: the global admin grant. Admin gets no implicit project:
  `projects` lists only projects where the user holds an explicit grant.
- `demo_coding`: where demo coding practice is open to the user (same rule
  as the virtual grants in `resolve_grants`); `available` is true when
  `project_ids` is not empty.
- `projects[]`, sorted by `project_id`: only active projects with an active
  grant. Closed projects and inactive grants, project-sites and units never
  appear.
  - `grants`: every explicit grant in the project, for every role. `scope` is
    `project`, `project_site` (with `site_id`) or `org_unit` (with
    `org_unit_id`, `unit_name`). Grants of role `coder`, `coding_tester` and
    `reviewer` also carry `codes`: whether the grant codes under the
    project's coding scope level (a project or site grant is above any level,
    so it codes only with no level or `code_any`; a unit grant codes at or
    below the level; `coding_tester` is exempt, so always `true`).
  - `sites`: active project-sites the grants reach, with the roles that reach
    each: a project or unit grant reaches every active site of the project, a
    site grant its own site.
  - `has_tree`, `levels`, `units`: `levels` and `units` only when `has_tree`.
    Units are active and placed (unplaced units are skipped), in path order.
    Fields as the organization API's `/units`, plus `roles` and `selectable`.
- `units[].roles`: which roles reach the unit: tree reach for the picker and
  browsing (the same answer as `/organization/<project>/units?role=...`), not
  action capability; actions are still decided per request. Per role the reach
  is the whole tree for a project or project_site grant (a site grant reaches
  that site's cases in any unit, so the whole tree is shown for it); a
  `project_pi` on the project holds every role they have there on every unit
  (as `reachable_unit_ids`); otherwise the subtrees of that role's unit grants.
- `units[].can_code`: some `coder` or `coding_tester` grant covering the unit
  codes there (`codes` above, the server's coding scope rule). A client never
  offers coding where this is `false`.
- `units[].selectable`: `true` for a unit some role reaches (`roles` not
  empty). `false` with `roles: []` for an ancestor shown only as context above
  a reached unit; never a choice. The server's own scope checks never read it.

Errors: 401 `{"error": "Authentication required."}` when signed out (bad
bearer: `{"error", "code": "unauthorized"}`); 403 `terms_required`,
`maintenance`, `factor_setup_required` from the gates; 429 over the limit.

## POST /api/v1/me/terms

Body `{"accept_terms": true}`. The same view as `POST /api/v1/profile/terms`:
records the acceptance and audits `terms_accepted`; 200
`{"message": "Terms accepted.", "terms_accepted": true}`; any other body is 400
`{"error", "code": "invalid_request"}`. Exempt from the terms gate, so it works
while terms are pending; limited to 5 per minute per user, one counter shared with the
profile URL.
