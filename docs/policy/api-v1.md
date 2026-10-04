---
title: One Client API (/api/v1)
doc_type: policy
status: active
owner: engineering
last_updated: 2026-10-04
---

# One Client API (`/api/v1`)

Owner decisions, 2026-10-04 (`digitva-339w`). Baseline for every frontend:
the Jinja Flask pages' scripts, the Expo app in a browser, and the Expo app
on Android and iOS. Not yet built; the current routes are listed under
"Today" so the migration can be tracked.

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
   every 4xx/5xx, one unit-tree shape.
4. **Everything about the user in one call.** The sign-in confirmation
   carries the access summary; `GET /api/v1/me/access` returns the identical
   body whenever the client wants it again (after a 403, a grant change, an
   app resume). One builder, built from `resolve_grants`.

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
- Checked against the code (2026-10-04): no role acts on or picks units
  outside that set. Units outside it reach a client only as names on rows
  it is already shown (the person lookup's posts, a case's own unit);
  unrouted cases have no unit. A picker for one action filters the tree by
  the role tags: the pin and reroute picker offers only units reached
  through a data manager, In-charge or project PI grant, since the server
  refuses a pin through a coder grant.

## Today (to converge)

| Same thing | Current routes |
| --- | --- |
| Bootstrap | `/api/v1/device/bootstrap`, `/intake/api/bootstrap`, `/api/v1/client/bootstrap` |
| Unit list | `/api/v1/device/units`, `/api/v1/organization/<project>/units` |
| Cases | `/api/v1/device/cases*`, `/intake/api/cases*` |
| Error body | device `{error, code}`; `/intake/api/*` `{error}` only |
| User object | `user_id` in most; `id` in `/api/v1/client/bootstrap` |

A device token is accepted only under `/api/v1/device/` today
([Expo Web Client Boundary](expo-client.md)); rule 1 replaces that fence
with per-route authorisation. Old routes stay until every client has moved
(backward compatibility), then go.
