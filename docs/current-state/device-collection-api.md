---
title: Device Collection API (Path B server side)
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-09-30
---

# Device Collection API (Path B server side)

Server side of the Android collection app (bead `digitva-kmk.1`). Policy:
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
  `find_device_upload`, `serialize_device_upload`.
- UI: **Devices** card in the Setup home People section
  (`admin/panels/project_setup.html`), admin only.

## Tables (migration `d7a3c9e1f5b2`)

| Table | Holds |
|---|---|
| `auth_device_enrolment_codes` | project, `code_hash` (unique), `expires_at`, `max_uses`, `use_count`, `created_by`, `revoked_at` |
| `auth_devices` | `device_id`, project, name, platform, app version, `secret_hash`, `enrolled_at`, `enrolled_via` (code id), `revoked_at`, `revoked_by`, `last_seen_at` |
| `auth_device_sessions` | one per (device, interviewer) sign-in: `access_hash` / `refresh_hash` (unique) and expiries, `previous_refresh_hash` (reuse detection), `user_session_version`, `last_seen_at`, `revoked_at` + `revoked_reason`, `outstanding_count`, `outstanding_unique_ids` (JSONB), `outstanding_reported_at` |
| `va_web_intake_drafts.client_draft_id` | the app's draft UUID, unique where not null (`uq_va_web_intake_drafts_client_draft_id`) |

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
- Sign-in mirrors the web password step: timing-equalised unknown email,
  active, verified email, forced password change, maintenance cutoff, and a
  TOTP or recovery code when `totp_service.needs_second_factor`. Rate limits:
  10/min per IP, 10/min per device, 20/hour per account. Refused sign-ins are
  audited as `device_session_failed` (device id and reason only). Other
  security events: `device_enrolment_code_created`, `device_enrolled`,
  `device_session_opened`, `device_session_revoked`, `device_revoked`.
- Refresh rotates both tokens; the refresh lifetime slides
  (`DEVICE_REFRESH_TTL_DAYS`, default 30, proposed C1). Presenting the
  refresh token a session last rotated away from revokes the session.

## Endpoints

As the contract, with these additions (all additive):

| Call | Notes |
|---|---|
| `POST /enroll` | 10/min per IP. Code consumed atomically (`use_count < max_uses`). |
| `POST /sessions` | Extra refusals: 401 `device_invalid` (unknown device or wrong secret), 401 `invalid_credentials`, 403 `email_unverified`, `password_change_required`, `maintenance`. A closed project answers 403 `device_revoked`. |
| `POST /sessions/refresh` | 401 `session_revoked` (reuse, revoked, grant withdrawn, device revoked, account changed); 401 `session_expired` and 401 `refresh_invalid` (unknown token) revoke nothing. Optional `count`/`unique_ids`. |
| `DELETE /sessions/current` | `login_required`, not the interviewer role, so a withdrawn interviewer can still sign out. |
| `GET /bootstrap` | `user`, `context` (the intake context filtered to the device's project), `form_options` (the `/api/v1/organization/<project>/form-options` body), `instrument_version` (the served bundle's manifest sha, `who_va_bundle_version`). No CSRF fields. |
| `POST /submissions` | Accepts an optional `completion: {valid, issues}` beside `draft`; see below. |
| `POST /outstanding` | Stores count and sorted unique ids on the session. |
| Admin `POST .../device-enrolments` | Also returns `qr_svg` (segno) and `max_uses`; `Cache-Control: no-store`. The QR server URL is `DEVICE_PUBLIC_URL` (default: scheme and host of `MAIL_BASE_URL`; set `http://10.0.2.2:8051` for an emulator). |

Every error body is `{"error", "code"}`; the role gate's 401/403 bodies carry
`error` only.

The app should wipe an interviewer's store only on `session_revoked`, never
on `session_expired` or `refresh_invalid`. Even so, a refresh whose response
is lost, retried with the old token, is reuse and revokes the session: an
open owner risk (data loss on a flaky network) until the contract separates
reuse from administrative revocation.

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

## Not built

- Admin UI for per-session revocation (device revoke ends all its sessions).
- Offline worklist download and attachments (phase 3).
- A supervisor view of superseded copies and telling the interviewer in the
  web list.
