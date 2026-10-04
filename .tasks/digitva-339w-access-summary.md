# Access summary and one /api/v1 credential layer

- Status: design, awaiting owner review
- Priority: P1
- Created: 2026-10-04
- Beads: `digitva-339w` (this), epic `digitva-ntct`
- Policy: `docs/policy/api-v1.md`

## Goal

As soon as any user signs in, the backend sends everything about their
access in one body; the same body is available again from
`GET /api/v1/me/access`. Every client (Jinja scripts, Expo web, Expo native)
uses that one route with either credential.

## Stage 0: either credential on /api/v1 (security-sensitive, `digitva-uzhq`)

Mechanism notes: Flask-Login's session `user_loader` runs before the
`request_loader`, so widening the prefix alone lets a cookie win; a
pre-step must drop the session identity when `Authorization: Bearer` is
present. CSRFProtect enforces in its own early hook, so a later hook cannot
skip it: exempt bearer requests through CSRFProtect itself (or
`WTF_CSRF_CHECK_DEFAULT=False` + explicit `csrf.protect()` for cookie
requests). `generate_csrf()` and `session[...]` writes in `/api/v1` routes
(e.g. `client.py` bootstrap) must not run for bearer requests.

Today `load_user_from_device_token` (`app/models/va_users.py:598`) accepts a
bearer token only under `/api/v1/device/`.

- Accept `Authorization: Bearer` on every `/api/v1/` path. A request that
  carries a bearer header is authenticated by the bearer only: a cookie on
  the same request is ignored, and a bad token is 401, never a fallback to
  the cookie (no mixed identity).
- CSRF: a bearer request is exempt (no ambient credential); a cookie request
  keeps `X-CSRFToken` on state changes. One `before_request` decides this,
  not per-blueprint `csrf.exempt`.
- A bearer request never writes the session cookie.
- Gates apply to both credentials alike: terms (`terms_required`),
  maintenance, password change, factor setup (today
  `enforce_factor_setup` skips `/api/v1/device/` by path; switch to "skip
  when bearer-authenticated").
- Not widened: `/admin/api/*`, Jinja pages, `/intake/api/*` stay cookie
  only. `/api/v1/device/*` keeps working unchanged until clients move.
- Errors on `/api/v1/*`: `{"error", "code"}` for both credentials.
- Tests: bearer reaches a non-device `/api/v1` GET; bearer + cookie of
  another user resolves to the bearer user; bad bearer + good cookie is
  401; bearer POST needs no CSRF, cookie POST still does; revoked device or
  session is 401; bearer never sets `Set-Cookie`; bearer cannot reach
  `/admin/api/*` or a Jinja page; terms gate holds for bearer.

## Stage 1: the access summary

Builder: one function in a new `app/services/access_summary_service.py`,
built from `resolve_grants(user)` (memoised, Redis-cached) plus one tree
query per project. It calls `mark_consulted()`.

```json
{
  "user": {"user_id": "…", "name": "…"},
  "is_admin": false,
  "projects": [{
    "project_id": "TST001", "project_name": "…", "has_tree": true,
    "grants": [
      {"role": "interviewer", "scope": "org_unit", "org_unit_id": "…"},
      {"role": "coder", "scope": "project_site", "site_id": "…"},
      {"role": "project_pi", "scope": "project"}
    ],
    "sites": [{"site_id": "…", "site_name": "…", "roles": ["coder"]}],
    "levels": [{"level_code": "phc", "level_name": "PHC", "depth": 3}],
    "units": [{"org_unit_id": "…", "unit_code": "…", "unit_name": "…",
               "level_code": "phc", "parent_code": "…", "path": "…",
               "roles": ["interviewer"], "selectable": true}]
  }]
}
```

- `grants`: every active, non-virtual grant in the project, for every role.
- `units` (tree projects only): per role, the reach is the whole tree for a
  project or site grant and for `project_pi`, else the subtrees of that
  role's unit grants. Each unit carries the roles whose reach includes it;
  ancestors of reached units come as `roles: []`, `selectable: false`.
  Same unit fields as `units_payload` (`app/routes/api/organization.py`).
- `sites`: the project-sites the user's grants reach, with the roles that
  reach each, derived as `interviewer_context` does today: a project or
  unit grant reaches every active site of its project, a site grant its own
  site. Case creation names `(project, site, unit)`, so a unit-only
  interviewer must still get sites.
- Admin: `is_admin: true` (owner decision: admin is reflected back from
  browser and API alike). Proposed, not yet decided: `projects` lists only
  projects where the admin holds an explicit grant.
- Explicit grants only (owner 2026-10-04: "all grants are explicit, no
  implicit grants"). Demo-training virtual grants are not listed; demo
  coding keeps working server-side as today.
- `demo_coding: {"available": bool, "project_ids": [...]}` (top level):
  where demo coding is open to the user, from the same rule
  `resolve_grants` uses for the virtual demo grants (owner 2026-10-04).
  Kept out of `grants` so grants stay explicit.
- Size: ponytail ceiling is a large tree under a project grant; measure on
  the biggest dev tree before adding paging.

Where it is returned:
- `GET /api/v1/me/access`, either credential.
- `POST /api/v1/device/sessions` and `/sessions/refresh` add `access`
  (additive; old app builds ignore it).
- Browser sign-in is an HTML form; the browser's first call after it is
  `GET /api/v1/me/access` (Expo web) or the page bootstrap (Jinja).

Tests: one per shape (unit grant subtree + ancestors, project grant whole
tree, site grant in a tree project, two roles on overlapping units tagged
both, unit grant in project Q not in P, inactive grant/closed project
absent, admin flag), and that the body equals across credentials.

## Stage 2: one route set (owner 2026-10-04: build it all now)

No legacy mobile app exists, so device-only routes are removed, not kept.
Only the Jinja pages are legacy; their intake scripts move to the new
routes and `/intake/api/*` is deleted. Handlers stay thin over
`web_intake_service`; one error body `{error, code}`.

| Area | Route under `/api/v1/` | Replaces |
| --- | --- | --- |
| Device sign-in | `POST auth/enroll`, `POST auth/sessions` (+ `access`), `POST auth/sessions/refresh` (+ `access`), `DELETE auth/sessions/current` | `device/enroll`, `device/sessions*` |
| Me | `GET me/access`, `POST me/terms` | `device/bootstrap`, `device/units`, `client/bootstrap`, `device/terms`, `intake/api/bootstrap` |
| Reference | `GET organization/<p>/form-options`, `GET instruments/<code>/translations/<locale>` (served-locale rule kept), `GET intake/projects/<p>/prefill-policy` | `device/instruments/...`, bootstrap `form_options`/`prefill_policy` |
| Cases | `GET intake/cases`, `GET intake/cases/<id>`, `GET intake/cases/<id>/possible-duplicates`, `POST intake/cases/<id>/flags`, `.../visit`, `.../attempts`, `.../pause`, `GET intake/deaths`, `POST intake/deaths` | `device/cases*`, `device/deaths`, `intake/api/cases*`, `intake/api/deaths` |
| Drafts | `GET/POST intake/drafts`, `GET/PATCH intake/drafts/<id>`, `POST intake/drafts/<id>/discard`, `POST intake/drafts/<id>/submit` | `intake/api/drafts*` |
| Offline upload | `POST intake/submissions`, `POST intake/outstanding` | `device/submissions`, `device/outstanding` |
| Supervision | `GET intake/supervision/cases`, `POST intake/supervision/cases/<id>/resolve-flag`, `.../cancel`, `.../reopen`, `.../duplicate` | `intake/api/supervision/*` |
| Coding, reviewing | existing `coding/*`, `reviewing/*` | (bearer works after stage 0) |

Where a device and a browser route differ today (device requires
`project_id` on lists; device detail adds `prefill` and `links`), the one
route takes the richer behaviour: `project_id` optional filter, detail
always carries `prefill` and `links`. Rate limits: keep the stricter of the
two per route. Docs: `docs/current-state/device-collection-api.md` becomes
the one API reference (rename to `api-v1.md` under current-state).

## Open owner questions

1. Demo grants: settled, explicit grants only in the summary.
2. Device token on coding and reviewing: taken as intended (owner: the
   app serves every user type, all routes needed for API access).
