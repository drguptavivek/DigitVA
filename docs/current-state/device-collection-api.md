---
title: Device Collection API (Path B server side)
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-10-04
---

# Device Collection API (Path B server side)

Server side of the Android collection app (beads `digitva-kmk.1`, hardened
in `digitva-kmk.6`, offline cases in `digitva-kmk.4`, case detail, one
case list and multi-project devices for the Expo app in `digitva-p6fs.24`).
Policy:
[Field Data Collection](../policy/field-data-collection.md) (Path B). Design
and the API contract the app is built against:
`.tasks/2026-09-30-android-collection-app.md`.

## Code

- `app/services/device_auth_service.py`: enrolment codes, device enrolment,
  interviewer sessions, token rotation, bearer resolution, outstanding
  report, admin device list.
- `app/routes/api/device.py`: `/api/v1/device/*` (enrolment, sessions,
  terms, bootstrap, units, translations), CSRF-exempt, bearer only.
- `app/routes/api/intake.py`: `/api/v1/intake/*`, the one intake route set
  (cases, death register, drafts, offline uploads, supervision), either
  credential: the browser cookie (CSRF on a state change) or a device
  bearer token (no CSRF). `app/routes/api/request_helpers.py`: the request
  parsing both blueprints share. The Jinja pages (`app/routes/intake.py`)
  call it and render their CSRF token and interviewer context into the
  template; there is no bootstrap route for them.
  Removed (owner, 2026-10-04): `/intake/api/*` and the device `cases`,
  `deaths`, `submissions`, `outstanding` routes; they 404.
- `app/routes/admin_devices.py`: admin JSON API (extends the `admin`
  blueprint).
- `app/models/va_users.py::load_user_from_device_token`: the Flask-Login
  `request_loader`.
- `app/services/web_intake_service.py`: `submit_device_interview`,
  `find_device_upload`, `serialize_device_upload`; cases (shared with the
  browser): `worklist_page`, `get_case_detail`, `serialize_case_detail`;
  also: `case_prefill`, `case_row`, `get_device_case`,
  `find_device_registration`, `find_device_attempt`, `supervised_case_row`,
  `prefill_policy`.
- UI: **Devices** card in the Setup home People section
  (`admin/panels/project_setup.html`), admin only.

## Tables (migration `d7a3c9e1f5b2`)

| Table | Holds |
|---|---|
| `auth_device_enrolment_codes` | project, `code_hash` (unique), `expires_at`, `max_uses`, `use_count`, `created_by`, `revoked_at` |
| `auth_devices` | `device_id`, project, name, platform, app version, `secret_hash`, `enrolled_at`, `enrolled_via` (code id), `revoked_at`, `revoked_by`, `last_seen_at` |
| `auth_device_sessions` | one per (device, interviewer) sign-in: `access_hash` / `refresh_hash` (unique) and expiries, `previous_refresh_hash` (reuse detection), `user_session_version`, `last_seen_at`, `revoked_at` + `revoked_reason`, `outstanding_count`, `outstanding_unique_ids` (JSONB), `outstanding_reported_at` |
| `va_web_intake_drafts.client_draft_id` | the app's draft UUID, unique where not null (`uq_va_web_intake_drafts_client_draft_id`) |

Migration `e4b8d2f6a1c7` adds to `auth_device_sessions`:
`retired_refresh_hashes` (JSONB, the last 5 rotated-away refresh hashes,
newest first; GIN `jsonb_path_ops` index for the `@>` reuse lookup),
`refreshed_at` (last rotation) and `outstanding_client_draft_ids` (JSONB);
and `ix_auth_security_events_user_type_time` on `auth_security_events`
`(user_id, event_type, occurred_at)` for the lockout count.

Migration `f2c6a8d4b1e9` (`digitva-kmk.4`) adds `va_death_register.client_death_id`
(`uq_va_death_register_client_death_id`) and
`map_case_contact_attempts.client_attempt_id`
(`uq_map_case_contact_attempts_client_attempt_id`), both UUIDs unique where
not null, and `auth_device_sessions.outstanding_client_death_ids` (JSONB).

Every code, secret and token is `secrets.token_urlsafe(32)` and stored only
as its SHA-256 hex digest (a slow hash adds nothing for 256-bit random
values). The device secret is compared with `hmac.compare_digest`.

## Authentication

- Every `/api/v1/` route accepts a device bearer token beside the browser
  cookie (`authenticate_bearer` in `app/__init__.py`, bead `digitva-uzhq`);
  a bearer request is exempt from CSRF and sets no cookie. Outside
  `/api/v1/` a device token is ignored.
- The device blueprint's `before_request` requires the session the loader
  stamped on `g.device_session` (except `enroll`, `sessions`,
  `sessions/refresh`). A browser session cookie never satisfies it, which is
  what makes the CSRF exemption safe. Device responses set no cookie.
- The loader resolves only an unexpired, unrevoked session on an unrevoked
  device whose user is active with an unchanged `auth_session_version` (a
  password or factor reset ends device sessions too). `last_seen_at` is
  written at most once a minute.
- The interviewer grant is checked at sign-in and at every refresh, not per
  request: the worker needs an interviewer grant in at least one project
  (`has_interviewer_access`: `interviewer_context` non-empty, so a project
  whose `web_intake_mode` is off does not count). Losing the last one ends
  the session at the next refresh (`session_revoked`), within the 15-minute
  access lifetime. The enrolment project (`AuthDevice.project_id`) is not
  required: it is the device's admin home (listed, revoked and closed
  there) and does not limit which projects the device serves.
- Sign-in mirrors the web password step. The body's `email` field (name
  kept for the app contract) takes an email or a mobile number
  (digitva-kmoy): a value without `@` is canonicalised and matches only a
  unique sign-in number (`va_users.mobile_login`), so an unknown, shared or
  malformed number -- and a mobile-only account that never redeemed a code --
  gets the same timing-equalised `invalid_credentials` as an unknown email.
  Then: active, `sign_in_verified` (verified email or redeemed code), the
  maintenance cutoff, and a TOTP or recovery code when
  `totp_service.needs_second_factor`. Rate limits: 10/min per IP, 10/min per
  device, 20/hour per account (keyed on the canonical number for a mobile). Every refused
  sign-in is audited as `device_session_failed` with the device id and the
  reason only (`invalid_credentials`, `email_unverified`, `maintenance`, `second_factor_required`,
  `second_factor_invalid`, `second_factor_locked`, `no_interviewer_grant`).
  Other security events: `device_enrolment_code_created`, `device_enrolled`,
  `device_session_opened`, `device_session_revoked`, `device_revoked`,
  `second_factor_lockout`.
- **Pending terms do not refuse sign-in** (digitva-9an9; onboarding policy
  5.4). The session opens and the token body carries `terms_required: true`
  (refresh too); until `POST /terms` with `{"accept_terms": true}` records
  acceptance (`terms_accepted`, via `device`), every bearer call except
  `DELETE /sessions/current` and `POST /terms` answers 403 `terms_required`,
  and a refresh does not record the outstanding-work report. Contract:
  `docs/current-state/authentication-and-onboarding.md` section 6.5.
- Second-factor lockout: `second_factor_invalid` failures for the account in
  the last 15 minutes, counted from the audit trail since its last
  `device_session_opened`. The fifth records `second_factor_lockout`
  (`{device_id, channel: "device"}`); from then sign-in answers 429
  `second_factor_locked` before any code is checked, until the window
  passes. Device failures only; the web flow keeps its own per-attempt
  counter.
- Refresh presents the device id and secret (constant-time), rotates both
  tokens, and slides the refresh lifetime (`DEVICE_REFRESH_TTL_DAYS`,
  default 30, proposed C1) but never past `DEVICE_SESSION_MAX_DAYS` (default
  90) from sign-in (proposed C1 addition). Presenting any of the last 5
  retired refresh tokens revokes the session as reuse (`refresh_reused`);
  the one rotated away under 60 s ago revokes it as a lost-response race
  (409 `refresh_retry_race`). `session_revoked` is kept for administrative
  or device revocation and for a worker left with no active project (grant
  withdrawn or last project closed), the only code the app wipes on; an
  account change (password or factor reset, deactivation) answers 401
  `session_ended`, which keeps the data.

## Endpoints

As the contract, with these additions (all additive). Paths are under
`/api/v1/device`, except those starting `/intake/`, which are under `/api/v1`.

| Call | Notes |
|---|---|
| `POST /enroll` | 10/min per IP. Code consumed atomically (`use_count < max_uses`). |
| `POST /sessions` | Extra refusals: 401 `device_invalid` (unknown device or wrong secret), 401 `invalid_credentials`, 403 `email_unverified`, `maintenance` (pending terms no longer refuse: see above), 403 `device_revoked` (revoked device), 403 `no_interviewer_grant` (no active project). |
| `POST /sessions/refresh` | Needs `device_id` + `device_secret` (else 401 `device_invalid`, nothing revoked). 401 `refresh_reused` / 409 `refresh_retry_race` (reuse, session revoked); 401 `session_revoked` (device or admin revoke, no active project left, signed out); 401 `session_ended` (account changed; keeps data); 401 `session_expired` and 401 `refresh_invalid` revoke nothing. Optional `count`/`unique_ids`/`client_draft_ids`. |
| `DELETE /sessions/current` | `login_required`, not the interviewer role, so a withdrawn interviewer can still sign out. |
| `GET /bootstrap` | `{user, instrument_version, projects}`: `user {user_id, name}`, `instrument_version` (the served bundle's manifest sha, `who_va_bundle_version`), `projects` (below). No CSRF fields. |
| `POST /intake/submissions` | Body `project_id` (required) and an optional `completion: {valid, issues}` beside `draft`; see below. A cookie request stores no `meta.deviceId`. |
| `GET /units?project_id=` | `units_payload` from `app/routes/api/organization.py` over `web_intake_service.reachable_unit_ids(user, project)` (grant-based, the create-time check's rule without a site: a project grant or any site grant of the project reaches the whole tree): the web picker's body. 403 when nothing is reachable. |
| `GET /instruments/<code>/translations/<locale>?project_id=` | `translations_response` from `app/routes/api/instruments.py`, only for `served_instrument_locales(project)` (the default form type's instrument, `available_locales`); else 404 `not_found`. |
| `POST /intake/outstanding` | Device session only (a cookie: 403 `device_session_required`). Stores count, sorted unique ids and sorted, normalised `client_draft_ids` and `client_death_ids` (UUIDs) on the session; the admin device list returns all three (`outstanding_client_death_ids` added in `digitva-kmk.4`). |
| `GET /intake/cases?project_id=&mine=&state=&limit=&cursor=` | The case list, below. 120/min. `project_id` optional. |
| `GET /intake/cases/<death_id>` | Case detail with full contacts, links and (when the caller may start or resume it) prefill, below. 120/min. |
| `GET /intake/cases/<death_id>/possible-duplicates`, `POST /intake/cases/<death_id>/flags`, `/pause` | The browser worklist's calls, now for every client. Each replies `{"case": <detail>}`, the body of `GET /intake/cases/<id>` (below). |
| `GET/POST /intake/deaths` | List (`project_id`, `site_id` required) and register (`project_id` required; `client_death_id` optional, idempotent), below. |
| `POST /intake/cases/<death_id>/attempts`, `/visit` | Attempts (`client_attempt_id` optional, idempotent) and visits, keyed by the case (no `project_id`), below. |
| `GET/POST /intake/drafts`, `GET/PATCH /intake/drafts/<id>`, `POST /intake/drafts/<id>/discard`, `/submit` | The web draft store. Draft saves and submits take no body cap beyond the service's answer checks. |
| `GET /intake/supervision/cases`, `POST /intake/supervision/cases/<id>/resolve-flag`, `/cancel`, `/reopen`, `/duplicate` | Supervisor list and actions (`interview_supervisor` or `data_manager`). Each action replies `{"case": <row>}`, the case in the supervisor list's row shape (`serialize_supervised_row`: who registered and started it, no contact details, no prefill), not the interviewer's detail: a supervisor need not hold an interviewer grant. |
| `GET /intake/projects/<project_id>/prefill-policy` | `web_intake_service.prefill_policy`; the project must be one of the caller's (403 `project_forbidden`). |
| Admin `POST .../device-enrolments` | Also returns `qr_svg` (segno) and `max_uses`; `Cache-Control: no-store`. The QR server URL is `DEVICE_PUBLIC_URL` (default: scheme and host of `MAIL_BASE_URL`; set `http://10.0.2.2:8051` for an emulator). Outside debug/testing a plain-http URL other than localhost, 127.0.0.1 or 10.0.2.2 refuses the code (503, logged); checked when a code is issued, not at startup, so a bad value cannot stop the server. |
| CLI `flask devices create-enrolment-code --project <id> --actor <admin email> [--minutes N] [--uses N]` | `app/commands/devices.py`: same `create_enrolment_code` service, bounds and `device_enrolment_code_created` event; the named active global admin is the recorded actor (`created_by` is not null). Prints the QR payload JSON only. For the emulator run it with `-e DEVICE_PUBLIC_URL=http://10.0.2.2:8051`. |

Every error body is `{"error", "code"}`, the role gate's 401 (`unauthorized`)
and 403 (`forbidden`) included, and the generic handlers' on `/api/` paths:
CSRF 400 `csrf_failed`, 429 `rate_limited`, and on `/api/v1/` 404
`not_found` and 405 `method_not_allowed`. Content refusals of a death, an
attempt or a visit are always 422 with a specific code (`invalid_registration`,
`invalid_attempt`, `invalid_visit`), with or without a client id; a malformed
request (a bad UUID, a missing `project_id`) is 400 `invalid_request`.
Blueprints outside the client contract (analytics, coding, data management,
...) still answer some bodies without `code`.

**`project_id`** (`request_project_id` in `request_helpers.py`): a query
parameter on `GET`, a body field on `POST`, required on `/device/units`,
`/device/instruments/<code>/translations/<locale>`, `/intake/deaths` and
`/intake/submissions` (missing: 400 `invalid_request`); an optional filter
on `GET /intake/cases`. It must be one of the worker's projects
(`interviewer_context`, as bootstrap `projects` lists them), else 403
`project_forbidden`, alike for an unknown and an ungranted project. The
enrolment project is never a default. Case-keyed calls (`/cases/<id>`,
`/attempts`, `/visit`) take none: the case's own project must be one of the
worker's, which the scope already enforces (404 otherwise).

Body caps (`_body_limit` in each blueprint, applied before the first read,
including the rate limiter's key functions, which read the body in an
app-level hook): 2 MB for `/intake/submissions`, 256 KB for
`/intake/outstanding` and `/device/sessions/refresh`, 16 KB otherwise
(draft saves and submits excepted); over it -> 413 `payload_too_large`.

The app wipes an interviewer's store only on `session_revoked`. A refresh
whose response was lost and is retried with the old token answers 409
`refresh_retry_race`, and theft-style reuse 401 `refresh_reused`; both
revoke the session but the app keeps the data and asks the interviewer to
sign in again.

## Uploads

`submit_device_interview` runs the web path in the named project only:
`start_draft` (scope, case, prefill) with `own_copy=True`, so an active web
draft on the case is never reused or merged; the envelope's `data` saved as
one section named `device`; then `submit_draft` with `intake_source =
"device"` (payload `DeviceID` `digitva-device`). The draft records
`meta.deviceId` and `meta.interviewOutcome`.

- **Validity.** `submit_draft` treats a questionnaire as complete only when
  the client's form engine says `valid: true`. The contract's envelope has no
  such field, so the app must send `completion.valid` (or a `valid` member on
  `draft`); without it a complete interview is refused 422 unless it picks an
  incomplete `interview_outcome`.
- **Idempotency.** A resend of the same `client_draft_id` returns the stored
  result with 200 (current case status). A concurrent resend that loses the
  unique index is answered the same way. Another interviewer's id is 409.
- **Superseded copy.** When the named case is already `submitted`,
  `duplicate` or `cancelled`, the upload is stored as a draft with status
  `superseded`: its answers kept under the case, no submission, no routing,
  and the case (identity included) untouched. Response `va_sid: null`,
  `superseded: true`. Supervisors cannot yet list these copies.
- Scope: a site outside the interviewer's context in the named project is
  403; a case outside it, or in another project, is 404.
- **Locked answers.** The draft's server-computed prefill decides which
  answers are locked (interviewer identity, area presets, ABHA); their
  values overwrite whatever the upload carries, in the stored section and
  the submission payload, and in a superseded copy (whose draft now stores
  that prefill). A tampered value is never persisted; nothing is refused
  for it (docs/policy/web-intake.md, "Locked prefill").
- **Bounds.** `draft.data` nested deeper than 6 levels or over 1 MB
  serialized is 422 before anything is stored, on the superseded path too
  (`_check_device_answers`).

## Cases (`digitva-kmk.4`, simplified in `digitva-p6fs.24`)

Policy: [Field Data Collection](../policy/field-data-collection.md)
("Offline contact details", "Multi-project devices") and
[Web Intake](../policy/web-intake.md) ("Contact data and attempts", "Who
sees which cases"). No migration.

One route set, `/api/v1/intake`, serves the browser (cookie and CSRF) and
the device (bearer); where the two once differed it takes the richer
behaviour.

- **List.** `GET /intake/cases` is the worklist, `worklist_page`. Query:
  `project_id` (optional filter), `mine`
  (true/false), `state` (comma-separated `CASE_STATES`), `limit` (default
  50, clamped to 1..200), `cursor` (from `next_cursor`, opaque); malformed:
  400 `invalid_request`. Body `{cases, counts, next_cursor}`: each row is
  `serialize_worklist_row` (`death_id`, `unique_id`, `project_id`,
  `site_id`, `org_unit_id`, `unit_name`, `source`, `state`,
  `details_pending`, `deceased_name`, `deceased_sex`, `age_years`,
  `date_of_death`, `pending_flag`, `next_visit_at`, `last_contact_at`,
  `informant_phone_masked`, `informant_phone_2_masked`, `registered_by_me`,
  `started_by_me`, `my_draft_id`, `va_sid`, `created_at`, `updated_at`)
  plus `possible_duplicates` (`[{death_id, unique_id}]`, up to three, from
  the whole scope); `counts` per state cover the scope, the project and
  `mine` but not `state`. Every state in scope is listed; the app picks its
  active download with `state=`. Order: next visit soonest first (undated
  last), then `updated_at` newest first, then `death_id`; keyset-paged on
  those three, looking one row ahead (a last page of exactly `limit` rows
  already has `next_cursor` null). Phones masked (`******1234`), no
  informant name, address or prefill. `Cache-Control: no-store`.
- **`va_sid`** (the submission id) in a list row and in the detail only
  when the caller started the case (`started_by_me`), else null: interview
  forms are their interviewer's own. The supervision list keeps it for
  every case.
- **Detail.** `GET /intake/cases/<death_id>` returns `{"case": ...}` built by
  `get_case_detail` (one query over `_worklist_select` with
  `_worklist_scope`, every project of the worker's) and
  `serialize_case_detail`: visible exactly when the worklist would list it,
  any state, else (or a malformed id) 404. Fields: `death_id`, `unique_id`,
  `project_id`, `site_id`, `org_unit_id`, `unit_name`, `source`, `state`,
  `details_pending`, `pending_flag`, `deceased {name, sex, age_years,
  date_of_birth, date_of_birth_partial, date_of_death, place_of_death}`,
  `household_address {address, house_street, village_ward, landmark}`,
  `informant {name, phone, phone_2}` in full, `remarks`, `next_visit_at`,
  `last_contact_at`, `registered_by_me`, `started_by_me`, `my_draft_id`,
  `va_sid`, `created_at`, `updated_at`. No ABHA, parents' names, other
  users' ids, client ids or duplicate ids. `no-store`. With `prefill`
  (`case_prefill`, the object the web form page receives for the case, so an
  interview started offline opens prefilled; it carries the questionnaire's
  own answers, ABHA and parents' names included, never a phone) only when the
  caller may start or resume the interview: they hold the case's active draft,
  or the case is open (not submitted, duplicate or cancelled) and no other
  interviewer's draft holds it. Otherwise the key is absent. The same body,
  prefill rule included, is the reply of every interviewer single-case action
  (`POST /intake/deaths`, `/cases/<id>/flags`, `/visit`, `/attempts`, `/pause`).
  `links`: `{self, attempts, visit, start_interview}` plus `form`
  (the Jinja questionnaire page) when `my_draft_id` is set.
- **Offline download.** The app reads the list with its active states
  (`state=registered,scheduled,not_reachable,paused,refused,in_progress`,
  every page) per project, then the detail of each listed case, and keeps
  contact details only for cases in active states, purging them when a case
  leaves those states, on logout and on `session_revoked`.
- **Scope (`_worklist_scope`)**, shared by the list and the detail: per
  project-site of the intake context, no unit filter when a project grant or
  a site grant on that site exists, else the subtrees of the worker's unit
  grants in that project (a sub-select per project over
  `authz.subtree_select`; grants from the request-memoised
  `authz.resolve_grants`); "details pending" only for its starter. A wider
  grant beside a unit grant sees the whole site. The intake
  blueprint computes `interviewer_context` once per request
  (`interviewer_context`, request environ) and passes it to the service.
- **Registration.** `POST /intake/deaths` (body `project_id`, `site_id`,
  `org_unit_id`, optional `client_death_id` and the web register form's
  fields) looks up `client_death_id` first, when sent (the registrant's own -> 200 with the
  case, current state; another user's -> 409; out of scope or another
  project now -> 404, `get_device_case`), then `register_death(...,
  client_death_id=...)`. A concurrent resend that loses the unique index is
  answered 200 the same way. The reply is `{"case": <detail>}` (`case_row`, no
  second scope query), the registrant's own new case, so its prefill is
  present. `register_death`'s content refusals (400), and a list or object in a
  field, are always 422 `invalid_registration`, with or without a
  `client_death_id`. `date_of_birth_partial` (`YYYY-MM` or `YYYY`,
  never with `date_of_birth`) maps in the prefill to `Id10020` = no and the
  WHO `dob_precision` fields.
- **Attempts.** `POST /intake/cases/<id>/attempts`: with a
  `client_attempt_id`, `find_device_attempt` first (same user and case -> 200,
  even after the case has moved on; otherwise 409), then `log_contact_attempt(...,
  client_attempt_id=...)`; 422 `invalid_attempt` for a bad outcome or date,
  with or without a client id. Replies `{"case": <detail>}`, 201 (200 on a
  resend).
- **Visits.** `set_visit` stores no row, so no client id: a resend sets the
  same date again. A bad date is 422 `invalid_visit`. Replies `{"case": <detail>}`.
- Attempts and visits run the browser's service calls, which scope the case
  (`get_death`): a case outside the worker's scope is 404, whatever its
  project.
- Ordering: a case registered offline gets its `death_id` from `/intake/deaths`;
  the app sends registrations, then attempts and visits, then interviews
  (with `death_id`), so `/intake/submissions` always names a case that exists.
- Known gap: an attempt's `attempted_at` (and the case's `last_contact_at`)
  is the sync time, not when it happened offline.

## Multi-project devices (`digitva-p6fs.24`)

- A device works in every project the signed-in worker is an interviewer in
  (bootstrap `projects`), with no admin step; every project-scoped call
  names its `project_id`. The session lasts while at least one remains.
- **Bootstrap `projects`.** One entry per authorized project: `project_id`,
  `project_name`, `web_intake_mode`, `sites` (that project's intake context
  entries), `form_options` (`form_options_payload`, the
  `/api/v1/organization/<project>/form-options` body: `config_version`,
  `enabled_extensions`, `languages`, `translation_versions`, ...) and
  `prefill_policy` (`web_intake_service.prefill_policy`): `direct` (the
  prefill a direct start with no unit gets: interviewer and its locked
  questions), `units` (`{org_unit_id: {answers, lockedQuestionNames}}`, the
  area answers and locked presets a direct start in that unit adds, for every
  unit the worker may pick; presets and org paths resolved in three queries,
  `_unit_prefill_parts`), `answer_fields` (`PREFILL_ANSWER_FIELDS`, WHO
  question -> register column) and `locked_fields` (`PREFILL_LOCKED_FIELDS`).
  All derived from `_prefill_from_death`, which stays the authority: locked
  answers are recomputed on upload. Not described: name, sex, dates and age
  (sent as `prefill.deceased` and mapped by the package), the age and
  partial-birth-date brackets and the place-of-death keyword match
  (conditional; see the builder).
- The app drops a project's local data (drafts, cases, contact details) when
  the project leaves bootstrap `projects`, and everything on
  `session_revoked`.
- The enrolment project does not bound the device: closing it ends nothing
  while the worker has another active project. Only an admin revoke (lost
  phone) ends the device; a worker with no active project left gets
  `session_revoked` and the app wipes.

## Not built

- Admin UI for per-session revocation (device revoke ends all its sessions).
- Attachments (phase 3, deferred).
- The admin Devices card shows the unsent count only, not the registration
  ids (they are in the JSON).
- A supervisor view of superseded copies and telling the interviewer in the
  web list.

Login, onboarding and device sign-in endpoints: [Authentication, Login and Onboarding](authentication-and-onboarding.md).
