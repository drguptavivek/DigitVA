---
title: Device Collection API (Path B server side)
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-10-03
---

# Device Collection API (Path B server side)

Server side of the Android collection app (beads `digitva-kmk.1`, hardened
in `digitva-kmk.6`, offline cases in `digitva-kmk.4`). Policy:
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
  `serialize_case_ack`.
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
  terms gate (`pw_reset_t_and_c`, code `password_change_required`), the
  maintenance cutoff, and a TOTP or recovery code when
  `totp_service.needs_second_factor`. Rate limits: 10/min per IP, 10/min per
  device, 20/hour per account (keyed on the canonical number for a mobile). Every refused
  sign-in is audited as `device_session_failed` with the device id and the
  reason only (`invalid_credentials`, `email_unverified`,
  `password_change_required`, `maintenance`, `second_factor_required`,
  `second_factor_invalid`, `second_factor_locked`, `no_interviewer_grant`).
  Other security events: `device_enrolment_code_created`, `device_enrolled`,
  `device_session_opened`, `device_session_revoked`, `device_revoked`,
  `second_factor_lockout`.
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
| `POST /sessions` | Extra refusals: 401 `device_invalid` (unknown device or wrong secret), 401 `invalid_credentials`, 403 `email_unverified`, `password_change_required`, `maintenance`. A closed project answers 403 `device_revoked`. |
| `POST /sessions/refresh` | Needs `device_id` + `device_secret` (else 401 `device_invalid`, nothing revoked). 401 `refresh_reused` / 409 `refresh_retry_race` (reuse, session revoked); 401 `session_revoked` (device or admin revoke, grant withdrawn, signed out); 401 `session_ended` (account changed or project closed; keeps data); 401 `session_expired` and 401 `refresh_invalid` revoke nothing. Optional `count`/`unique_ids`/`client_draft_ids`. |
| `DELETE /sessions/current` | `login_required`, not the interviewer role, so a withdrawn interviewer can still sign out. |
| `GET /bootstrap` | `user`, `context` (the intake context filtered to the device's project), `form_options` (the `/api/v1/organization/<project>/form-options` body), `instrument_version` (the served bundle's manifest sha, `who_va_bundle_version`). No CSRF fields. |
| `POST /submissions` | Accepts an optional `completion: {valid, issues}` beside `draft`; see below. |
| `GET /units` | `units_payload` from `app/routes/api/organization.py` over `authz.reachable_unit_ids(user, project, {interviewer})`: the web picker's body. 403 when nothing is reachable. |
| `GET /instruments/<code>/translations/<locale>` | `translations_response` from `app/routes/api/instruments.py`, only for `served_instrument_locales(project)` (the default form type's instrument, `available_locales`); else 404 `not_found`. |
| `POST /outstanding` | Stores count, sorted unique ids and sorted, normalised `client_draft_ids` and `client_death_ids` (UUIDs) on the session; the admin device list returns all three (`outstanding_client_death_ids` added in `digitva-kmk.4`). |
| `GET /cases` | Offline cases, below. 120/min. |
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

## Not built

- Admin UI for per-session revocation (device revoke ends all its sessions).
- Attachments (phase 3, deferred).
- The admin Devices card shows the unsent count only, not the registration
  ids (they are in the JSON).
- A supervisor view of superseded copies and telling the interviewer in the
  web list.

Login, onboarding and device sign-in endpoints: [Authentication, Login and Onboarding](authentication-and-onboarding.md).
