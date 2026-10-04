---
title: API v1 Reference
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-10-04
---

# API v1 Reference

The one route reference for every client (the Jinja pages, Expo web, the
native collection app). Policy: `docs/policy/api-v1.md`. Code:
`app/routes/api/` (`auth.py`, `me.py`, `intake.py`, `organization.py`,
`instruments.py`, `profile.py`), `app/services/access_summary_service.py`,
`app/services/device_auth_service.py`. Tests: `tests/routes/test_device_api.py`
(sign-in, tokens, intake), `tests/routes/test_me_access.py`,
`tests/routes/test_client_api.py`, `tests/routes/test_api_v1_credentials.py`.
Design of the device side (tables, sessions, uploads, cases):
[Device Collection API](device-collection-api.md).

## Credentials

Every `/api/v1` route takes either credential: the browser session cookie, or
`Authorization: Bearer <access token>` from a device sign-in (a bearer request
is authenticated by the token alone, the cookie on the same request is
ignored, and a bad token is 401 `unauthorized`). Bodies are identical for
both. Account security routes (`/api/v1/profile/*` passkeys, TOTP, password)
stay cookie-only (403 `cookie_session_required` for a bearer). The terms,
maintenance and factor-setup gates apply to both (JSON 403 `terms_required`,
`maintenance`, `factor_setup_required`); sign-in, refresh, sign-out and
accepting terms stay open under them as stated below.

CSRF: a cookie request that changes state sends `X-CSRFToken`; a bearer
request sends none and never gets one, and sets no cookie. The browser client
reads its token from the `X-CSRFToken` response header of
`GET /api/v1/me/access` (set for a cookie request only) and sends it back on
every `POST`, `PUT`, `PATCH` and `DELETE`, JSON included.
While terms are pending, `me/access` answers 403 `terms_required`; that
refusal carries the same `X-CSRFToken` header (cookie only), so the client
can `POST /api/v1/me/terms` straight away.

Signed out: 401 `{"error": "Authentication required.", "code": "unauthorized"}`
on any `/api/v1` route. That is the cue to send the browser to the sign-in
page, `/vaauth/valogin?next=<path>`; sign out is `/vaauth/valogout` (the
browser's own pages). No route returns these URLs.

Errors: every body is `{"error", "code"}` (the role gate's 401
`unauthorized` and 403 `forbidden`, CSRF 400 `csrf_failed`, 429
`rate_limited`, and on `/api/v1/` 404 `not_found`, 405 `method_not_allowed`).
Blueprints outside the client contract (analytics, coding, data management,
...) still answer some bodies without `code`.

## Sign-in (`/api/v1/auth`, `app/routes/api/auth.py`)

CSRF-exempt: they authenticate with a device credential (an enrolment code,
the device secret, a refresh token), never the cookie. Request bodies are
capped before anything reads them (256 KB for refresh, 16 KB otherwise; over
it 413 `payload_too_large`). Flows, audit events, lockout and the error codes:
[Authentication and Onboarding](authentication-and-onboarding.md) section 6.

| Call | Notes |
|---|---|
| `POST /auth/enroll` | Body `code`, `device_name`, `platform`, `app_version`. 201 `{device_id, device_secret, project, server_time}`. 10/min per IP. Code consumed atomically (`use_count < max_uses`). |
| `POST /auth/sessions` | Body `device_id`, `device_secret`, `email` (an email or a mobile number), `password`, optional `otp`. 201 `{access_token, access_expires_at, refresh_token, refresh_expires_at, user {user_id, name, email}, terms_required, access}`. `access` is the `GET /me/access` body for that user, shown even while terms are pending (it is display only; the terms gate is on requests). Refusals: 401 `device_invalid` (unknown device or wrong secret), 401 `invalid_credentials`, 401/403 `second_factor_required`, 429 `second_factor_locked`, 403 `email_unverified`, `maintenance`, `device_revoked`, `no_interviewer_grant` (no active project). Limits: 10/min per IP, 10/min per device, 20/hour per account. |
| `POST /auth/sessions/refresh` | Body `refresh_token`, `device_id`, `device_secret` (else 401 `device_invalid`, nothing revoked); optional outstanding-work report `count`, `unique_ids`, `client_draft_ids`, `client_death_ids` (not recorded while terms are pending). 200, the same body as sign-in, `access` included. 401 `refresh_reused` / 409 `refresh_retry_race` (reuse; session revoked); 401 `session_revoked` (device or admin revoke, no active project left, signed out); 401 `session_ended` (account changed; keeps data); 401 `session_expired` and `refresh_invalid` revoke nothing. 30/min per IP. |
| `DELETE /auth/sessions/current` | Bearer only (a cookie: 401 `unauthorized`). 204. `login_required`, not the interviewer role, so a withdrawn interviewer can still sign out; open while terms are pending. |

## Me and reference

| Call | Notes |
|---|---|
| `GET /me/access` | The whole access body, below. Sets `X-CSRFToken` for a cookie request. |
| `POST /me/terms` | Below. Also `POST /profile/terms` (the same view). |
| `GET /organization/<project>/units?role=interviewer` | The unit picker: `web_intake_service.reachable_unit_ids` (grant-based; a project grant or any site grant of the project reaches the whole tree). 403 when nothing is reachable. Other `role` values and none are the browsing views. |
| `GET /organization/<project>/form-options` | `form_options_payload`: `config_version`, `enabled_extensions`, `form_types`, `intake_note`, `default_locale`, `available_locales`, `translation_versions`, `narration_languages`, `show_guidance`, `web_intake_mode` (which capture paths are open), `instrument_version` (the served form bundle's manifest sha, `who_va_bundle_version`). Any grant reaching the project. |
| `GET /intake/projects/<project>/prefill-policy` | `web_intake_service.prefill_policy`; the project must be one of the caller's interviewer projects (403 `project_forbidden`). |
| `GET /instruments/<code>/translations/<locale>[?project_id=]` | `translations_response` (weak ETag, 304). Without `project_id`: any servable (active or `in_review`) locale to any signed-in user. With it: also needs a grant reaching the project (403 `forbidden`; unknown or inactive project 404 `not_found`) and serves only that project's instrument and `available_locales`, else 404 `not_found` (the offline app passes it). 120/min. |

A client starts from `GET /me/access` (or the sign-in reply's `access`), then
reads `form-options` and `prefill-policy` per interviewer project it works in
and the `units` picker per project that has a tree.

## Intake (`/api/v1/intake`, `app/routes/api/intake.py`)

Paths are under `/api/v1`. Either credential; the caller needs the
interviewer role (supervision: `interview_supervisor` or `data_manager`).

| Call | Notes |
|---|---|
| `POST /intake/submissions` | Body `client_draft_id` (UUID), `project_id`, `site_id`, `draft` (envelope: meta keys only, `draft.data` is not read; optional `startedAt`, `completedAt`, `deviceClockAt`, each ISO 8601 with a UTC offset), `answers_json` (string: the exact JSON text of the answers object) and `answers_sha256` (64 hex, SHA-256 of that text's UTF-8 bytes), optional `completion: {valid, issues}`, `death_id`, `org_unit_id`. The server hashes `answers_json` as received, then parses. 422 `answers_hash_required` (a field missing, not a string, or a malformed hash), 422 `answers_hash_invalid` (hash differs; nothing stored), 422 `invalid_interview` (not a JSON object, over 1 MB, nested deeper than 6, or one of the three times present but unparsable or offset-less). 201 on a new upload, 200 on a resend with the same hash, 409 `hash_mismatch` on a resend with another hash or of an upload stored before hashing, body `{error, code, stored}` where `stored` is the first result. Result: `{va_sid, case, outcome, superseded, answers_sha256}`, the stored hash echoed. A cookie request stores no `meta.deviceId`. Detail: [Device Collection API](device-collection-api.md) "Uploads". |
| `POST /intake/outstanding` | Device session only (a cookie: 403 `device_session_required`). Stores count, sorted unique ids and sorted, normalised `client_draft_ids` and `client_death_ids` (UUIDs) on the session; the admin device list returns all three (`outstanding_client_death_ids` added in `digitva-kmk.4`). |
| `GET /intake/cases?project_id=&mine=&state=&limit=&cursor=` | The case list, below. 120/min. `project_id` optional. |
| `GET /intake/cases/<death_id>` | Case detail with full contacts, links and (when the caller may start or resume it) prefill, below. 120/min. |
| `GET /intake/cases/<death_id>/possible-duplicates`, `POST /intake/cases/<death_id>/flags`, `/pause` | The browser worklist's calls, now for every client. Each replies `{"case": <detail>}`, the body of `GET /intake/cases/<id>` (below). |
| `GET/POST /intake/deaths` | List (`project_id`, `site_id` required) and register (`project_id` required; `client_death_id` optional, idempotent), below. |
| `POST /intake/cases/<death_id>/attempts`, `/visit` | Attempts (`client_attempt_id` optional, idempotent) and visits, keyed by the case (no `project_id`), below. |
| `GET/POST /intake/drafts`, `GET/PATCH /intake/drafts/<id>`, `POST /intake/drafts/<id>/discard`, `/submit` | The web draft store. Draft saves and submits take no body cap beyond the service's answer checks. |
| `GET /intake/supervision/cases`, `POST /intake/supervision/cases/<id>/resolve-flag`, `/cancel`, `/reopen`, `/duplicate` | Supervisor list and actions (`interview_supervisor` or `data_manager`). Each action replies `{"case": <row>}`, the case in the supervisor list's row shape (`serialize_supervised_row`: who registered and started it, no contact details, no prefill), not the interviewer's detail: a supervisor need not hold an interviewer grant. |
| Admin `POST .../device-enrolments` | Also returns `qr_svg` (segno) and `max_uses`; `Cache-Control: no-store`. The QR server URL is `DEVICE_PUBLIC_URL` (default: scheme and host of `MAIL_BASE_URL`; set `http://10.0.2.2:8051` for an emulator). Outside debug/testing a plain-http URL other than localhost, 127.0.0.1 or 10.0.2.2 refuses the code (503, logged); checked when a code is issued, not at startup, so a bad value cannot stop the server. |
| CLI `flask devices create-enrolment-code --project <id> --actor <admin email> [--minutes N] [--uses N]` | `app/commands/devices.py`: same `create_enrolment_code` service, bounds and `device_enrolment_code_created` event; the named active global admin is the recorded actor (`created_by` is not null). Prints the QR payload JSON only. For the emulator run it with `-e DEVICE_PUBLIC_URL=http://10.0.2.2:8051`. |

Content refusals of a death, an
attempt or a visit are always 422 with a specific code (`invalid_registration`,
`invalid_attempt`, `invalid_visit`), with or without a client id; a malformed
request (a bad UUID, a missing `project_id`) is 400 `invalid_request`.

**`project_id`** (`request_project_id` in `request_helpers.py`): a query
parameter on `GET`, a body field on `POST`, required on `/intake/deaths` and
`/intake/submissions` (missing: 400 `invalid_request`); an optional filter
on `GET /intake/cases`. It must be one of the worker's projects
(`interviewer_context`, the interviewer projects of `/me/access`), else 403
`project_forbidden`, alike for an unknown and an ungranted project. The
enrolment project is never a default. Case-keyed calls (`/cases/<id>`,
`/attempts`, `/visit`) take none: the case's own project must be one of the
worker's, which the scope already enforces (404 otherwise).

Body caps (`_body_limit` in the intake blueprint, applied before the first read,
including the rate limiter's key functions, which read the body in an
app-level hook): 2 MB for `/intake/submissions`, 256 KB for
`/intake/outstanding`, 16 KB otherwise
(draft saves and submits excepted); over it -> 413 `payload_too_large`.

The app wipes an interviewer's store only on `session_revoked`. A refresh
whose response was lost and is retried with the old token answers 409
`refresh_retry_race`, and theft-style reuse 401 `refresh_reused`; both
revoke the session but the app keeps the data and asks the interviewer to
sign in again.

## GET /api/v1/me/access (body)

The signed-in user's whole access in one body. Rate limit 120 per minute; `Cache-Control: no-store`.
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

Errors: 401 `unauthorized` when signed out or on a bad bearer; 403
`terms_required`, `maintenance`, `factor_setup_required` from the gates (the
same codes for every `/api/v1` route; the old browser bootstrap's
`password_change_required` and `redirect_url` are gone: terms are
`terms_required`, factor setup goes to `/profile/#passkeys-card`); 429 over
the limit. Response header (cookie request only): `X-CSRFToken`.

## POST /api/v1/me/terms (body)

Body `{"accept_terms": true}`. The same view as `POST /api/v1/profile/terms`:
records the acceptance and audits `terms_accepted`; 200
`{"message": "Terms accepted.", "terms_accepted": true}`; any other body is 400
`{"error", "code": "invalid_request"}`. Exempt from the terms gate, so it works
while terms are pending; limited to 5 per minute per user, one counter shared with the
profile URL.
