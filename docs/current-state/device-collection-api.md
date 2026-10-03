---
title: Device Collection API (Path B server side)
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-10-03
---

# Device Collection API (Path B server side)

Server side of the Android collection app (beads `digitva-kmk.1`, hardened
in `digitva-kmk.6`, offline cases in `digitva-kmk.4`, case detail, history
and multi-project devices for the Expo app in `digitva-p6fs.24`). Policy:
[Field Data Collection](../policy/field-data-collection.md) (Path B). Design
and the API contract the app is built against:
`.tasks/2026-09-30-android-collection-app.md`.

## Code

- `app/services/device_auth_service.py`: enrolment codes, device enrolment,
  interviewer sessions, token rotation, bearer resolution, outstanding
  report, admin device list.
- `app/routes/api/device.py`: `/api/v1/device/*`, CSRF-exempt, bearer only.
- `app/routes/admin_devices.py`: admin JSON API (extends the `admin`
  blueprint).
- `app/models/va_users.py::load_user_from_device_token`: the Flask-Login
  `request_loader`.
- `app/services/web_intake_service.py`: `submit_device_interview`,
  `find_device_upload`, `serialize_device_upload`; offline cases:
  `device_case_filters`, `device_case_rows` / `device_case`,
  `get_device_case`, `find_device_registration`, `find_device_attempt`,
  `serialize_case_ack`; detail and history: `get_case_detail`,
  `serialize_case_detail`, `list_case_history`, `prefill_policy`.
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

- The `request_loader` accepts `Authorization: Bearer <access>` **only on
  paths under `/api/v1/device/`**; anywhere else a device token is ignored,
  so it cannot drive the browser UI or another API.
- The device blueprint's `before_request` requires the session the loader
  stamped on `g.device_session` (except `enroll`, `sessions`,
  `sessions/refresh`). A browser session cookie never satisfies it, which is
  what makes the CSRF exemption safe. Device responses set no cookie.
- The loader resolves only an unexpired, unrevoked session on an unrevoked
  device whose user is active with an unchanged `auth_session_version` (a
  password or factor reset ends device sessions too). `last_seen_at` is
  written at most once a minute.
- The interviewer grant is checked at sign-in and at every refresh, not per
  request: a withdrawn grant ends the session at the next refresh, within the
  15-minute access lifetime. The check is `interviewer_context`, so it also
  requires the project's `web_intake_mode` to be on.
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
  or device revocation and a withdrawn grant, the only code the app wipes
  on; an account change (password or factor reset, deactivation) or a closed
  project answers 401 `session_ended`, which keeps the data.

## Endpoints

As the contract, with these additions (all additive):

| Call | Notes |
|---|---|
| `POST /enroll` | 10/min per IP. Code consumed atomically (`use_count < max_uses`). |
| `POST /sessions` | Extra refusals: 401 `device_invalid` (unknown device or wrong secret), 401 `invalid_credentials`, 403 `email_unverified`, `maintenance` (pending terms no longer refuse: see above). A closed project answers 403 `device_revoked`. |
| `POST /sessions/refresh` | Needs `device_id` + `device_secret` (else 401 `device_invalid`, nothing revoked). 401 `refresh_reused` / 409 `refresh_retry_race` (reuse, session revoked); 401 `session_revoked` (device or admin revoke, grant withdrawn, signed out); 401 `session_ended` (account changed or project closed; keeps data); 401 `session_expired` and 401 `refresh_invalid` revoke nothing. Optional `count`/`unique_ids`/`client_draft_ids`. |
| `DELETE /sessions/current` | `login_required`, not the interviewer role, so a withdrawn interviewer can still sign out. |
| `GET /bootstrap` | `user`, `context` (the intake context filtered to the device's project), `form_options` (the `/api/v1/organization/<project>/form-options` body), `instrument_version` (the served bundle's manifest sha, `who_va_bundle_version`), all for the enrolment project as before; plus `default_project_id` and `projects` (multi-project, below). No CSRF fields. |
| `POST /submissions` | Accepts an optional `completion: {valid, issues}` beside `draft`; see below. |
| `GET /units` | `units_payload` from `app/routes/api/organization.py` over `authz.reachable_unit_ids(user, project, {interviewer})`: the web picker's body. 403 when nothing is reachable. |
| `GET /instruments/<code>/translations/<locale>` | `translations_response` from `app/routes/api/instruments.py`, only for `served_instrument_locales(project)` (the default form type's instrument, `available_locales`); else 404 `not_found`. |
| `POST /outstanding` | Stores count, sorted unique ids and sorted, normalised `client_draft_ids` and `client_death_ids` (UUIDs) on the session; the admin device list returns all three (`outstanding_client_death_ids` added in `digitva-kmk.4`). |
| `GET /cases` | Offline cases, below. 120/min. Optional `project_id`. |
| `GET /cases/<death_id>` | Case detail with full contacts, below. 120/min. |
| `GET /history` | Case history, below. 120/min. |
| `POST /deaths` | Offline registration, below. |
| `POST /cases/<death_id>/attempts`, `/visit` | Offline attempts and visits, below. |
| Admin `POST .../device-enrolments` | Also returns `qr_svg` (segno) and `max_uses`; `Cache-Control: no-store`. The QR server URL is `DEVICE_PUBLIC_URL` (default: scheme and host of `MAIL_BASE_URL`; set `http://10.0.2.2:8051` for an emulator). Outside debug/testing a plain-http URL other than localhost, 127.0.0.1 or 10.0.2.2 refuses the code (503, logged); checked when a code is issued, not at startup, so a bad value cannot stop the server. |
| CLI `flask devices create-enrolment-code --project <id> --actor <admin email> [--minutes N] [--uses N]` | `app/commands/devices.py`: same `create_enrolment_code` service, bounds and `device_enrolment_code_created` event; the named active global admin is the recorded actor (`created_by` is not null). Prints the QR payload JSON only. For the emulator run it with `-e DEVICE_PUBLIC_URL=http://10.0.2.2:8051`. |

Every error body is `{"error", "code"}`; the role gate's 401/403 bodies carry
`error` only.

Body caps (`_body_limit` in the device blueprint, applied before the first
read, including the rate limiter's key functions, which read the body in an
app-level hook): 2 MB for `/submissions`, 256 KB for `/outstanding` and
`/sessions/refresh`, 16 KB otherwise; over it -> 413 `payload_too_large`.

The app wipes an interviewer's store only on `session_revoked`. A refresh
whose response was lost and is retried with the old token answers 409
`refresh_retry_race`, and theft-style reuse 401 `refresh_reused`; both
revoke the session but the app keeps the data and asks the interviewer to
sign in again.

## Uploads

`submit_device_interview` runs the web path in the device's project only:
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
- Scope: a site outside the interviewer's context in the device's project is
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

## Offline cases (`digitva-kmk.4`)

- **Download.** `GET /cases` is `list_worklist` with `extra_filters` =
  `device_case_filters`: the device's project, states `registered`,
  `scheduled`, `not_reachable`, `paused`, `refused` (`DEVICE_CASE_STATES`),
  or `in_progress` started by the caller. Same scope as the web worklist
  (unit grants their subtrees; "details pending" never listed), same
  keyset paging, `limit` clamped to 1..200. Rows are
  `serialize_worklist_row` plus `prefill` from `_prefill_from_death`, the
  object the web form page receives for the case; `device_case_rows`
  resolves the page's unit presets and org path names in three queries
  (`_unit_prefill_parts`), whatever the page size. `Cache-Control:
  no-store`.
- **Data minimisation.** Phones are masked in the row (`******1234`) and
  never in the prefill: the app needs no full number offline, though the web
  case page shows it. The prefill does carry the informant's and parents'
  names, the address and ABHA, because they are the questionnaire's
  prefilled answers; on the phone they live only in the interviewer's
  SQLCipher store and are dropped when the case leaves the list.
- **Registration.** `POST /deaths` looks up `client_death_id` first (the
  registrant's own -> 200 with the case, current state; another user's ->
  409; out of scope now -> 404), then `register_death(...,
  client_death_id=...)`. A concurrent resend that loses the unique index is
  answered 200 the same way. `register_death`'s content refusals (400) are
  answered 422 `invalid_registration`; a list or object in a field is 422 too.
  The fields are the web register form's, including optional
  `date_of_birth_partial` (`YYYY-MM` or `YYYY`, never with `date_of_birth`);
  the case row's `prefill` maps it to `Id10020` = no and the WHO
  `dob_precision` fields.
- **Attempts.** `find_device_attempt` first (same user and case -> 200, even
  after the case has moved on; otherwise 409), then `log_contact_attempt(...,
  client_attempt_id=...)`; 422 `invalid_attempt` for a bad outcome or date.
- **Visits.** `set_visit` stores no row, so no client id: a resend sets the
  same date again. 422 `invalid_visit` for a bad date.
- A case outside the caller's scope or the device's project is 404
  (`get_device_case`) on attempts and visits.
- Ordering: a case registered offline gets its `death_id` from `/deaths`;
  the app sends registrations, then attempts and visits, then interviews
  (with `death_id`), so `/submissions` always names a case that exists.
- Known gap: an attempt's `attempted_at` (and the case's `last_contact_at`)
  is the sync time, not when it happened offline.

## Case detail, history and multi-project devices (`digitva-p6fs.24`)

Policy: [Field Data Collection](../policy/field-data-collection.md)
("Offline contact details", "Multi-project devices") and
[Web Intake](../policy/web-intake.md) ("Contact data and attempts"). No
migration: no table or column changed.

- **Project of a request.** `GET` calls take an optional `project_id` query
  parameter, `POST` calls a `project_id` body field (`_requested_project_id`
  / `_request_project` in the blueprint). Named: it must be a project of the
  worker's `interviewer_context`, else 403 `project_forbidden` (alike for an
  unknown and an ungranted project). Absent: the device's enrolment project
  (`AuthDevice.project_id`), unchecked as before, so an older app is
  unaffected. Applies to `/units`, `/cases`, `/history`, `/deaths`,
  `/submissions`, `/cases/<id>/attempts`, `/cases/<id>/visit` and
  `/instruments/<code>/translations/<locale>` (locales of that project).
  Mutations still run `_require_scope` (site and unit of that project): a
  site of another project is 403 `forbidden`. `/submissions` with a
  `death_id` of another project than the resolved one is 404, as are
  attempts and visits on such a case (`get_device_case`).
- **Bootstrap `projects`.** One entry per authorized project: `project_id`,
  `project_name`, `web_intake_mode`, `sites` (that project's context
  entries), `form_options` (`form_options_payload`: `config_version`,
  `enabled_extensions`, `languages`, `translation_versions`, ...) and
  `prefill_policy` (`web_intake_service.prefill_policy`): `direct` (the
  prefill a direct start with no unit gets: interviewer and its locked
  questions), `units` (`{org_unit_id: {answers, lockedQuestionNames}}`, the
  area answers and locked presets a direct start in that unit adds, for every
  unit the worker may pick), `answer_fields` (`PREFILL_ANSWER_FIELDS`, WHO
  question -> register column) and `locked_fields` (`PREFILL_LOCKED_FIELDS`).
  All derived from `_prefill_from_death`, which uses the same constants and
  stays the authority: locked answers are recomputed on upload. Not
  described: name, sex, dates and age (sent as `prefill.deceased` and mapped
  by the package), the age and partial-birth-date brackets and the
  place-of-death keyword match (conditional; see the builder).
  `default_project_id` is the enrolment project. When the worker no longer
  holds an interviewer grant there (a `multi_project` session outlives it),
  top-level `context` is `[]`, `form_options` and `default_project_id` are
  `null`, and `projects` still lists the remaining projects;
  `/instruments/<code>/translations/<locale>` without `project_id` then
  answers 403 `project_forbidden`. An older app never sees this: its session
  is revoked with that grant.
- **`multi_project` flag.** `POST /sessions` and `POST /sessions/refresh`
  accept `"multi_project": true`. With it the grant check (sign-in and every
  refresh, `_session_access`) needs an interviewer grant in any project;
  without it, the enrolment project as before, so losing that grant answers
  `session_revoked` even when another project's grant remains. The flag is
  per request, nothing is stored: a multi-project app sends it on every
  refresh. The closed-enrolment-project check (`session_ended`) is
  unchanged for both. A multi-project app drops a project's local data when
  the project leaves bootstrap `projects`.
- **Case detail.** `GET /cases/<death_id>` (`get_case_detail`, one query
  over `_worklist_select` with `_worklist_scope`): visible exactly when the
  worklist would list it (project-site from the intake context, unit grants
  their subtrees with no-unit cases excluded, `draft_identity` for its
  starter only), any state; with `project_id` also that project. Otherwise,
  or a malformed id, 404 `not_found`. Body `{"case": ...}`:
  `serialize_case_detail` (`death_id`, `unique_id`, `project_id`, `site_id`,
  `org_unit_id`, `unit_name`, `source`, `state`, `details_pending`,
  `pending_flag`, `deceased {name, sex, age_years, date_of_birth,
  date_of_birth_partial, date_of_death, place_of_death}`,
  `household_address {address, house_street, village_ward, landmark}`,
  `informant {name, phone, phone_2}` in full, `remarks`, `next_visit_at`,
  `last_contact_at`, `registered_by_me`, `started_by_me`, `my_draft_id`,
  `va_sid` (null unless `started_by_me`), `created_at`, `updated_at`) plus `prefill` (as on `/cases`
  rows) and `links {self, attempts, visit}`. No ABHA, parents' names, other
  users' ids, client ids or duplicate ids. `Cache-Control: no-store`. The
  browser twin is `GET /intake/api/cases/<death_id>` (cookie, interviewer):
  the same body without `prefill`, links `self`, `attempts`, `visit`,
  `start_interview` (`POST /intake/api/drafts`) and `form` when
  `my_draft_id` is set.
- **History.** `GET /history?project_id=&cursor=&limit=&state=`
  (`list_case_history`): every case of the project in the worklist scope,
  any state, `created_at` then `death_id` newest first, keyset cursor
  (opaque), `limit` default 50 clamped to 1..200 (not a number: 400), `state`
  comma-separated `CASE_STATES` (unknown: 400). Rows are
  `serialize_history_row`: the worklist row (phones masked, no prefill) with
  `va_sid` null unless `started_by_me`. `no-store`. Paging looks one row
  ahead, so a last page of exactly `limit` rows already has `next_cursor`
  null; ties on `created_at` are ordered by `death_id`. No index serves this
  sort yet; the project filter bounds it. Follow-up (no migration in this
  change): an index on `va_death_register (project_id, created_at,
  death_id)`.
- **Scope (`_worklist_scope`)**, shared by `/cases`, `/history`, the detail
  and the web worklist: per project-site of the intake context, no unit
  filter when a project grant or a site grant on that site exists, else the
  subtrees of the worker's unit grants in that project (a sub-select per
  project over `authz.subtree_select`; grants from the request-memoised
  `authz.resolve_grants`). A wider grant beside a unit grant therefore sees
  the whole site; before this change the unit grant narrowed it. The
  blueprint computes `interviewer_context` once per request
  (`_interviewer_context`, request environ) and passes it to the service.
- **Expo integration.** Read bootstrap `projects`; send `project_id` on
  every call for a project other than the default (always, to be safe);
  send `multi_project: true` on sign-in and every refresh; keep the
  `/cases` download per project and fetch `/cases/<id>` for each listed
  case to hold its contacts offline, deleting a case's detail when it
  leaves `/cases`, on logout and on `session_revoked`; show `/history`
  online only; drop a project's local data when it leaves `projects`.

## Not built

- Admin UI for per-session revocation (device revoke ends all its sessions).
- Attachments (phase 3, deferred).
- The admin Devices card shows the unsent count only, not the registration
  ids (they are in the JSON).
- A supervisor view of superseded copies and telling the interviewer in the
  web list.

Login, onboarding and device sign-in endpoints: [Authentication, Login and Onboarding](authentication-and-onboarding.md).
