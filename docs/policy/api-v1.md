---
title: One Client API (/api/v1)
doc_type: policy
status: active
owner: engineering
last_updated: 2026-11-27
---

# One Client API (`/api/v1`)

Owner decisions, 2026-10-04 (`digitva-339w`). Baseline for every frontend:
the Jinja Flask pages' scripts, the Expo app in a browser, and the Expo app
on Android and iOS. Built; "State" below records what shipped.

## Rules

1. **One route set, either credential.** Every client route lives under
   `/api/v1/` and accepts either the browser session cookie (state changes
   need `X-CSRFToken`) or a device bearer token. Same route, same body,
   whichever credential arrives. No per-client copies of a route.
2. **The server decides, always.** Each request is authorised from the
   signed-in user's grants in `app/services/authz`, whatever the client
   sends. Nothing a client receives (the access summary included) grants
   anything; it only tells the client what to show. Production refuses any
   route that never consulted authz (`AUTHZ_ENFORCE_CONSULTED`).
3. **One shape for the same thing.** One user object (`user_id`, `name`),
   one error body `{"error": "<message>", "code": "<machine code>"}` on
   every 4xx/5xx, one unit-tree shape. The error rule has one exception
   (owner, 2026-10-05, `digitva-ey38`): `/api/v1/doris-clinical/*` keeps, for
   its own refusals, its nested `{"schema_version": 1, "error": {"code", "message"}}` because that
   shape is tied to the DORIS editor UI and the WHO DORIS clinical model it
   serialises. Since 2026-11-25 (`digitva-r8nh.39`) that body also carries
   a top-level `code`, the same value as `error.code`; status, nested code and
   message are unchanged, and DORIS clients keep reading the nested body.
   Everything else, whatever the blueprint, answers the flat body;
   an error with no domain code takes the code of its HTTP status.
4. **Everything about the user in one call.** The sign-in confirmation
   carries the access summary; `GET /api/v1/me/access` returns the identical
   body whenever the client wants it again (after a 403, a grant change, an
   app resume). One builder, built from `resolve_grants`.
5. **Cross-site requests cannot act as the user** (owner 2026-11-25,
   `digitva-r8nh.39`).
   - **CSRF exemptions are named one view at a time**, never a whole
     blueprint, so a new route is CSRF-checked unless someone adds it on
     purpose. Exempt today: the sign-in views in `CSRF_EXEMPT_VIEWS`
     (`app/routes/api/auth.py`), which take their credential from the body or a
     bearer and never sign the browser in; and the WHO ICD-11 proxy, which the
     coding tool calls without a token and which only reads from the
     configured ICD service. Outside `/api/v1/`, the ICD-11 client API views
     (`app/routes/icd11_client_api.py`) are exempt one by one too: they read
     only their own bearer token, never a cookie (icd11-client-api.md).
   - **Sign-in cookies are same-site.** The session and remember cookies are
     `SameSite=Lax` (or `Strict`): the exemptions above rely on the browser
     withholding the cookie from another site's POST. Any other value from the
     environment is logged as an error and replaced with `Lax` at startup; it
     never stops the app from starting.
   - **No CORS.** No route sends `Access-Control-Allow-*` headers, so another
     site's page cannot send a JSON request with the user's cookie or read a
     reply. The phone app and the Expo web build are same-origin or use a
     bearer and need none.

## By design (owner 2026-11-25, `digitva-r8nh.39`)

Found by the route auth matrix (`tests/fixtures/route_auth_matrix.json`) and
kept as they are:

- **A device token carries device roles only.** On a bearer request an
  account keeps just its `NATIVE_DEVICE_ROLES` grants and `is_admin` is false
  (`_device_projection`, `app/services/authz/grants.py`), so an admin's phone
  acts as an interviewer (or supervisor, where granted) on every `/api/v1`
  route. Admin work is browser-only.
- **Decommissioning a device the account does not have answers 200.**
  `DELETE /api/v1/me/devices/<id>` is idempotent: it ends this account's
  sessions on that device and reports `sessions_ended` (0 when there were
  none).
- **The account deletion request needs no body.**
  `POST /api/v1/me/deletion-request` is identified by the signed-in session
  ([Public Privacy and Data Requests](public-privacy-and-data-requests.md));
  an empty `{}` is a complete request.
- **Three JSON routes are public**: `GET /api/v1/app/version` (server
  compatibility and build), `GET /api/v1/ui-strings` (published UI
  languages, needed before sign-in) and `GET /api/v1/public/totals.json`
  (the home page's aggregate figures, [Public Home Stats](public-home-stats.md)).
  None carries user data. Each sits, with its reason, on `PUBLIC_ENDPOINTS`
  in `app/services/authz/consulted.py`.

## Access summary

For every user type on the platform (admin, project and site PI, data
manager, coder, reviewer, interviewer, interview supervisor, collaborator,
mentor-institute member, coding tester):

- `user`, and `is_admin`. An admin is reflected back as admin from browser
  and API sign-in alike; the summary does not enumerate every project for
  them. Server-side checks apply to admins on every request as to anyone.
- `projects`: each project the user holds a grant in, with the user's
  grants there (role, scope, site or unit), its sites, and for a project
  with an organization tree the user's unit tree: every unit below their
  granted units plus the units they report up to (context, not
  selectable), each unit tagged with the roles that reach it. Not the full
  project tree, except where the user's reach is the full tree: a project
  or site grant, a project PI, or an admin.
- The access body is the complete statement of a user's access (owner,
  2026-10-05, digitva-ntct.3): a client needs no other route to learn what
  the user may do or where. Every value is the output of the predicate the
  server enforces (`role_flags`, the lens rules in `RULES`,
  `interviewer_context`, the factor and PII services), never a second copy
  of a rule. `grants[]` lists every resolved grant with `active` (its gate
  opens) and `source`; every other list (`roles`, `sites[].roles`,
  `units[].roles`, `actions`) counts active grants only. Explicit grants
  only: demo-training practice is reported under `demo_coding` and never
  appears in `roles` or `actions`. `actions` is reach, not a decision: where
  the user's grants reach each action; whether the action is allowed on one
  case is still decided per request. Additive: a field is never renamed,
  retyped or removed (clients ignore unknown keys).
- Checked against the code (2026-10-04): no role acts on or picks units
  outside that set. Units outside it reach a client only as names on rows
  it is already shown (the person lookup's posts, a case's own unit);
  unrouted cases have no unit. A picker for one action filters the tree by
  the role tags: the pin and reroute picker offers only units reached
  through a data manager, In-charge or project PI grant, since the server
  refuses a pin through a coder grant.

## State (2026-10-04)

Done:

- One credential layer: a device token or the browser cookie on every
  `/api/v1` route (account security stays browser-only).
- One intake route set, `/api/v1/intake/*`, either credential. The
  `/intake/api/*` routes and the device intake copies are gone.
- One error body `{"error", "code"}` on `/api/` paths: the role gate, the
  login gate, CSRF (`csrf_failed`), rate limits (`rate_limited`) and, under
  `/api/v1/`, every other HTTPException (404, 405, ...) carries a `code`;
  analytics, area, coding, data management, ICD, workflow and the rest answer
  it too (digitva-ey38), the doris-clinical exception aside.
- Content refusals (deaths, attempts, visits) are always 422 with a specific
  code; single-case actions reply `{"case": <detail>}` (supervisor actions:
  the supervisor list's row shape under the same key). The case detail
  carries `prefill` only for a caller who may start or resume the interview.

Remaining: nothing (digitva-ad02). The device-only routes
(`/api/v1/device/*`, `/api/v1/client/bootstrap`) are removed; sign-in is
`/api/v1/auth/*`, a user's access is `GET /api/v1/me/access` (also in the
sign-in and refresh replies), and the unit picker, form options, prefill
policy and translations are the shared routes. Route reference:
`docs/current-state/api-v1.md`. The one `user` object is `{user_id, name}`
(`email` is added only in the sign-in reply's own `user`).

Form options and prefill policy stay separate routes, not part of
`me/access` (owner, 2026-10-09): `me/access` is read on every browser
reload and answers who the user is and what they may reach; per-project form
configuration is read only by a client that works in that project.

No legacy mobile app exists (owner, 2026-10-04): device-only routes are
removed as their replacements land, not kept alongside them. The Jinja pages
are the only legacy client and move onto the same routes.

Deploy note: bump `STATIC_ASSET_VERSION` with this release; cached old intake
scripts call the removed `/intake/api/*` routes and read the old reply shapes.
