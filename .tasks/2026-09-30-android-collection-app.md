# Android collection app (Path B)

Status: design draft, 2026-09-30, revised after design review the same day. Phase 1 (server) built 2026-09-30 (`digitva-kmk.1`, `docs/current-state/device-collection-api.md`), with the contract additions listed there; the upload needs `completion.valid` from the app. Hardened the same day (`digitva-kmk.6`): body caps, absolute session cap, device-bound refresh, reuse codes separate from revocation, second-factor lockout, device units and translations; the contract below is current. Owner asked (2026-09-30) for an Android app
for data collection with QR-code device provisioning, biometric lock with an
app-PIN fallback, encryption, server URL set from the QR, and a multilingual
UI, **after** the web form and dashboard work lands. Policy it must satisfy:
`docs/policy/field-data-collection.md` (Path B). Epic: see bead in the
handoff.

## Stack

- Expo (SDK 57) React Native app at `mobile/digitva-collect/`, built from the
  vendored package's own Expo demo (`vendor/who-va-2022/examples/expo-demo`),
  which already renders `WhoVaForm` from `@drguptavivek/who-2022-va/native`
  with an injected `draftStore` and platform adapters. The form engine, its
  validation and its languages are the same code the web page runs.
- Dependency on the vendored package by `file:` path; no fork.
- Android only for now. Local debug builds with the Android SDK on the dev
  machine (`expo prebuild` + Gradle); no EAS, no signing until C4.

## Provisioning by QR

1. An admin (later a project PI) opens **Devices** in the project's Setup
   home and creates an enrolment code: project, expiry (default 1 h: the admin is standing there), maximum
   uses (default 1; a batch for a training day may use more). The same page
   lists enrolled devices with a revoke button. The server
   stores only a hash of the code.
2. The page shows a QR holding JSON only:
   `{"v":1,"server":"https://digitva.causeofdeathindia.com","enroll":"<code>","project":"UNSW01"}`.
   No personal data, no credential beyond the one-time code.
3. The app scans it (camera), checks the server URL against a host allowlist
   compiled into the build (release: the production host only, so a forged QR
   cannot point the phone at a server that would collect the interviewer's
   password; debug: also `http://10.0.2.2:8051` and `http://localhost:8051`),
   and calls
   `POST /api/v1/device/enroll` with the code, a device name and app version.
   The server returns `device_id` and a random `device_secret` (stored hashed
   server-side; on the phone in Android Keystore-backed SecureStore). The
   device secret is sent only to `/device/sessions`, never on later calls.
4. The server URL comes from the QR and is fixed for that enrolment; changing
   it means re-enrolling (wipes nothing but requires a new QR). A manual URL
   field exists only in debug builds.

## Interviewer sign-in on the device

- `POST /api/v1/device/sessions`, authenticated as the device, with email and
  password, plus a TOTP or recovery code when the account has factors
  (`docs/policy/authentication-factors.md`). The browser CAPTCHA step is
  replaced by the device credential and a per-device rate limit.
- Every account keeps a password path (`authentication-factors.md`), so no
  passkey-on-device or QR sign-in is needed. Reuse `totp_service`
  (`needs_second_factor`, `verify`, `verify_recovery_code`). Rate limits per
  device and per account, matching the web login limits.
- Bearer tokens reach existing handlers through a Flask-Login
  `request_loader`, so `role_required("interviewer")` and the intake services
  work unchanged; the device blueprint is CSRF-exempt (no cookies).
- The session requires an active `interviewer` grant (any scope) in the
  enrolled project. Tokens: opaque random access token (15 min) and refresh
  token bound to (device, user), both stored hashed; the refresh token rotates
  on every use, is presented with the device id and secret, and reuse of any
  of the last five retired ones revokes the session (as `refresh_reused`,
  which the app does not wipe on).
- **Proposed C1**: refresh lifetime 30 days, sliding, capped at 90 days from
  sign-in (`DEVICE_SESSION_MAX_DAYS`, proposed addition). Expiry never loses
  data: the store is keyed by the interviewer's PIN, not the token, so unsent
  work waits until the interviewer signs in again.
- Revocation: admin revokes a device or a session; withdrawing the
  interviewer's grant revokes it at the next refresh (checked on every
  refresh, no trigger needed); the server then answers `session_revoked` and
  the app wipes **that interviewer's store only**, as policy requires. No
  other code wipes.

## On-device storage and unlock

- One encrypted store per interviewer (decision C2): its own SQLCipher
  database file (`expo-sqlite` with `useSQLCipher`, verified in the SDK).
  Attachments, when they come, are BLOBs inside that database, not separate
  files, so no second cipher is needed.
- The database passphrase is a random per-store secret held in Keystore-backed
  SecureStore joined with the PIN; SQLCipher's own PBKDF2 (256k iterations)
  derives the key. A copy of the app's files alone cannot be brute-forced.
  No scrypt/HKDF module: none ships in Expo without custom native code, and
  it would not change the threat model.
- **Biometric**: a second SecureStore entry with `requireAuthentication`
  (Keystore key usable only after a strong biometric) holds the PIN-derived
  passphrase part. Adding a new fingerprint invalidates it and the app falls
  back to the PIN. Emulators do not enforce this; it needs a real device.
- The failed-PIN counter lives in SecureStore beside the store secret (it
  must be readable while locked).
- The PIN (6 digits minimum) is set at first sign-in on the device and is
  always the fallback. After 5 wrong PINs in a row that interviewer's store is
  wiped (only theirs), after a warning at 3.
- Auto-lock after 5 minutes idle and when the app has been in the background
  over 1 minute; the data key is dropped from memory on lock.
- Screens are marked secure (no screenshots, blank in the recent-apps view).
- The home screen lists the accounts on the device by display name only; it
  never shows another account's case count or contents.
- Push and purge: a submission is deleted locally once the server
  acknowledges it. No history is kept on the device.
- Sign-out wipes that interviewer's database, secrets and cached keys
  (policy "wipe on logout"); unsent interviews are warned about first.
- No personal data in device logs: log submission ids, draft ids and unit
  codes only.

## Sync protocol

- `GET /api/v1/device/bootstrap`: project, forms, locales, enabled
  extensions, district presets, the interviewer's reachable org units: the
  same data the web intake bootstrap gives, cached on the device.
- `POST /api/v1/device/submissions`: one completed interview with a client
  draft UUID. The server stores it in a new unique `client_draft_id` on
  `va_web_intake_drafts`, calls `start_draft` then `submit_draft` (the same
  validation and `route_synced_submission` path as web submit, with
  `intake_source` = `device`), and a resend of the same UUID returns the
  existing `va_sid` instead of a 409.
- A device interview for a case a teammate already submitted is uploaded as
  a superseded copy (`web-intake.md`, first-valid-form rule), never left
  stuck on the phone; today `start_draft`/`submit_draft` refuse a submitted
  case with 409, so this path is new server work.
- Every sync also reports the device's count and unique ids of unsent
  interviews (policy: outstanding work visible server-side).
- Worklist cases (after `digitva-vzk` phase 3): downloaded for offline visits,
  registrations made offline are uploaded with an idempotency key.

## Multilingual UI

- App strings (about thirty) in a JSON dictionary per language with a small
  `t()` helper, no i18n library (`en`, `hi` first; the project's display
  languages next), language chosen in the app, defaulting to the phone's
  language. The questionnaire keeps its own language picker, as on the web.

## Server data (migration)

`auth_device_enrolment_codes` (hash, project, expiry, uses, created_by),
`auth_devices` (device_id, project, name, secret hash, enrolled_at,
revoked_at), `auth_device_sessions` (device, user, refresh hash, access hash,
expiries, revoked_at, last_seen, outstanding count and a JSON list of unsent
unique ids), and `client_draft_id` on `va_web_intake_drafts`. Additive.
`digitva-kmk.6` (migration `e4b8d2f6a1c7`) adds `retired_refresh_hashes`
(GIN), `refreshed_at` and `outstanding_client_draft_ids` to the sessions,
and a `(user_id, event_type, occurred_at)` index on `auth_security_events`.

## Phases

1. Server: enrolment codes and QR on Setup home (with device list and
   revoke), device enrol, device sessions, Bearer `request_loader`, token
   rotation, bootstrap, idempotent submit, superseded-copy path, outstanding
   report, per-device rate limits. Migration and tests.
2a. App: scaffold from the Expo demo (its `AuthSession.ts` already does
   Bearer + refresh rotation), QR provisioning, sign-in, plain SQLite store,
   fill and save drafts, submit and purge, UI strings en/hi. Proves the
   contract. Debug APK on the emulator.
2b. App security: SQLCipher per interviewer, PIN, biometric, auto-lock,
   FLAG_SECURE, wipe on sign-out/revoke/failed PINs. Real-device biometric
   check (emulators do not enforce it). No real data before 2b.
3. Offline worklist cases, attachments as BLOBs (gate before release).
4. Release: signing and distribution (C4), real-device checks.

## Open owner decisions

- C1 refresh lifetime (30 days sliding proposed above).
- C4 signing-key custody and distribution (Play internal track vs MDM vs
  direct APK). Until decided: debug builds, non-production server only.
- Android package id (proposed `org.digitva.collect`) and app name.
- Who may create enrolment codes: admin only, or also project PIs.
- PIN length and wipe threshold (6 digits and 5 attempts proposed).

## API contract (phase 1 + `digitva-kmk.6`; the app is built against this)

All under `/api/v1/device`, JSON, no cookies, CSRF-exempt. Errors are
`{"error": "<message>", "code": "<machine_code>"}` with
400/401/403/404/409/413/422/429 (the role gate's 401/403 carry `error` only).
`Authorization: Bearer <access_token>` on everything after sign-in. Request
bodies are capped: 2 MB for `/submissions`, 128 KB for `/outstanding` and
`/sessions/refresh` (they carry the outstanding report), 16 KB for the rest;
over the cap -> 413 `payload_too_large`.

- `POST /enroll` `{code, device_name, platform: "android", app_version}` ->
  201 `{device_id, device_secret, project: {project_id, name}, server_time}`.
  Code single-use by default; expired/used/unknown -> 404 `enrolment_invalid`.
- `POST /sessions` `{device_id, device_secret, email, password, otp?}` ->
  201 `{access_token, access_expires_at, refresh_token, refresh_expires_at,
  user: {user_id, name, email}}`; 401 `device_invalid`; 401
  `invalid_credentials`; 401 `second_factor_required` when the account has
  factors and `otp` (TOTP or recovery code) is missing/wrong; 429
  `second_factor_locked` after 5 wrong codes for the account in 15 minutes
  (since its last device sign-in); 403 `email_unverified`,
  `password_change_required`, `maintenance`, `no_interviewer_grant`,
  `device_revoked`; 429 when rate-limited.
- `POST /sessions/refresh` `{refresh_token, device_id, device_secret,
  count?, unique_ids?, client_draft_ids?}` -> 200 same token shape, old
  refresh token dead. Refusals and what the app does:

  | Status, code | When | Server | App |
  |---|---|---|---|
  | 401 `device_invalid` | device id/secret missing, wrong, or not the session's device | nothing revoked | sign in again, keep data |
  | 401 `refresh_invalid` | unknown token | nothing revoked | sign in again, keep data |
  | 401 `session_expired` | past the sliding expiry or the 90-day cap | nothing revoked | sign in again, keep data |
  | 401 `refresh_reused` | one of the last 5 retired tokens presented (or any token of a session revoked for that) | session revoked | sign in again, keep data |
  | 409 `refresh_retry_race` | the token rotated away < 60 s ago (a lost response) | session revoked (the app never held the new pair) | sign in again, keep data |
  | 401 `session_ended` | password or factor reset, account deactivated, project closed | session revoked | sign in again, keep data |
  | 401 `session_revoked` | device or admin revoke, grant withdrawn, signed out | session revoked | **wipe that interviewer's store** |
- `DELETE /sessions/current` -> 204 (sign-out; the app wipes that store).
- `GET /bootstrap` -> 200 the intake bootstrap for this interviewer and the
  enrolled project (same shape as `/intake/api/bootstrap`, scoped to the
  device's project), plus `form_options` and `instrument_version`.
- `GET /units` -> 200 the `/api/v1/organization/<project>/units?role=interviewer`
  body for the device's project (interviewer grants only: a unit grant sees
  its subtree plus ancestors as `selectable: false`; a project or site grant
  the whole tree, `scoped: false`); 403 when no unit is reachable.
- `GET /instruments/<code>/translations/<locale>` -> 200 the
  `/api/v1/instruments/...` body with its weak ETag (304 on `If-None-Match`),
  only for the project's default instrument and a locale in its
  `available_locales`; otherwise 404 `not_found`.
- `POST /submissions` `{client_draft_id (uuid), site_id, org_unit_id?,
  death_id?, draft: <WhoVaDraft envelope>, completion: {valid, issues}}` ->
  201 `{va_sid|null, case: {death_id, unique_id, status}, outcome,
  superseded}`; resend of the same `client_draft_id` -> 200 with the same
  body; case already submitted by a teammate -> 201 stored as a superseded
  copy (`superseded: true`). Without `completion.valid: true` the
  `draft.data.interview_outcome` must be `partially_completed` or
  `respondent_unavailable` (else 422). `draft.data` nested deeper than 6 or
  over 1 MB serialized -> 422 `invalid_interview`, nothing stored.
- `POST /outstanding` `{count, unique_ids: [..], client_draft_ids: [uuid..]}`
  -> 204 (also accepted as optional fields on `/sessions/refresh`); at most
  1000 of each.
- Admin: `POST /admin/api/projects/<id>/device-enrolments` `{expires_in_minutes?,
  max_uses?}` -> 201 `{code, qr_payload, qr_svg, expires_at, max_uses}` (code
  shown once); 503 when `DEVICE_PUBLIC_URL` is plain http outside
  development (localhost and 10.0.2.2 excepted);
  `GET /admin/api/projects/<id>/devices`; `POST /admin/api/devices/<id>/revoke`.
