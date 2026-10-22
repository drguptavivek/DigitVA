---
title: API v1 Reference
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-10-22
---

# API v1 Reference

The one route reference for every client (the Jinja pages, Expo web, the
native collection app). Policy: `docs/policy/api-v1.md`. Code:
`app/routes/api/` (`auth.py`, `me.py`, `intake.py`, `organization.py`,
`instruments.py`, `profile.py`, `attachments.py`), `app/services/access_summary_service.py`,
`app/services/device_auth_service.py`. Tests: `tests/routes/test_device_api.py`
(sign-in, tokens, intake), `tests/routes/test_me_access.py`,
`tests/routes/test_client_api.py`, `tests/routes/test_api_v1_credentials.py`.
Design of the device side (tables, sessions, uploads, cases):
[Device Collection API](device-collection-api.md).

## Credentials

Shared collection and coding APIs accept the browser session cookie or
`Authorization: Bearer <access token>` from device sign-in. A bearer request
uses the token alone, ignores a cookie on the same request, and answers 401
`unauthorized` for an invalid token. Shared request bodies are identical.
Device authorization includes only interviewer, death_reporter, coder,
coding_tester and reviewer grants, with their normal scope. An account's
admin, data-manager, PI, collaborator and supervisory powers do not carry
into its device token, and token/refresh replies expose the same restricted
access summary as bearer `GET /me/access`.

Account security (Profile passkeys/password), area dashboards, people/roles
and translation suggestions require a browser cookie session; a bearer gets
403 `cookie_session_required`. Management role gates also deny device tokens.
Terms and maintenance gates still apply (JSON 403 `terms_required` or
`maintenance`); sign-in, refresh, sign-out and accepting terms remain reachable
as specified below.

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

## Error body

Every error reply of a route under `/api/v1` is `{"error": <message>,
"code": <snake_case machine code>}`, plus documented extra keys (a 409 that
carries the stored result, a 409 coding refusal's `workflow_state`, a terms
refusal's `redirect_url`, an intake 422's `fields`: the list of question
names the interviewer must fix, present only when the error names them, as
`outcome_conflicts_consent` does with `["Id10013", "interview_outcome"]`). The one exception is the doris-clinical
blueprint's own refusals (nested `{"schema_version": 1, "error": {"code",
"message"}}`; policy `docs/policy/api-v1.md`); a framework error on those
paths (404, 405, 413, 415, 500) is flat like any other. A `{"status": "error", "reason"}` inside a 200
(`dm_kpi_scope.py`) is not an HTTP error and is out of scope.

One helper builds it: `request_helpers.error(message, code=None,
status_code=400, **extra)` returns `(response, status)`. When `code` is
omitted it defaults from the status (`request_helpers.STATUS_CODES`, read
also by the app error handler):

| Status | Default code | Status | Default code |
| --- | --- | --- | --- |
| 400 | `invalid_request` | 413 | `payload_too_large` |
| 401 | `unauthorized` | 415 | `unsupported_media_type` |
| 403 | `forbidden` | 422 | `unprocessable` |
| 404 | `not_found` | 429 | `rate_limited` |
| 405 | `method_not_allowed` | 502/503/504 | `bad_gateway` / `unavailable` / `gateway_timeout` |
| 409 | `conflict` | other 5xx | `server_error` |

Any other 4xx statuses default to `invalid_request`. There is no per-blueprint
copy of the helper; a domain code (`no_allocation`, `wrong_state`, ...) is
passed explicitly. A static test (`tests/routes/test_api_v1_error_codes.py`)
fails on any `{"error": ...}` dict without `code` under `app/routes/api/`
(doris-clinical excluded).

Safety net (`app/logging/va_logger.py` with `app/routes/va_errors.py`): any
`HTTPException` with status 400 or above on a `/api/v1/` path that no route
answered (a bare `abort`, 403, 405, 413, 415, 422, 500) is the same JSON, its
`error` the exception's description and its `code` from the table above.
Redirects (3xx) and every path outside `/api/v1/` are unchanged. The role
gate's 401/403, the login gate, CSRF (`csrf_failed`, 400), rate limits
(`rate_limited`) and the terms refusal (`terms_required`, 403; `error` is a
readable sentence, `code` is the
contract) use the same body.

Codes now returned by the blueprints that used to answer without one:

| Blueprint | Codes |
| --- | --- |
| icd10, icd11 | `not_found` (submission, ICD code), `forbidden` (reviewer allocation), `invalid_request`, `wrong_classification` (project codes in the other ICD edition), `payload_too_large` (WHO proxy body), `unsupported_media_type`, `unprocessable`, `unavailable`. Proxied WHO upstream bodies are untouched |
| coding | allocation refusals use the AllocationError code (`_allocation_error`, as before for the other allocation routes), `forbidden` |
| coding-search-demo, va-definitions | `invalid_request`, `not_found` |
| data-management | `forbidden`, `not_found`, `invalid_request`, `unavailable` (Celery not configured), `not_cancellable`, `server_error` |
| area | `not_found`, `invalid_request` |
| cod-buckets | `forbidden`, `no_active_scheme` |
| workflow | `not_found`, `forbidden` |
| analytics, analytics/dm-kpi/sync | `server_error`, `forbidden` |
| organization, profile | unchanged (`invalid_request`, `forbidden`, `not_found`, `conflict`, `unavailable`, `reauth_required`, `cookie_session_required`) |

## Sign-in (`/api/v1/auth`, `app/routes/api/auth.py`)

CSRF-exempt: they authenticate with a device credential (an enrolment code,
the device secret, a refresh token), never the cookie. Request bodies are
capped before anything reads them (256 KB for refresh, 16 KB otherwise; over
it 413 `payload_too_large`). Flows, audit events, lockout and the error codes:
[Authentication and Onboarding](authentication-and-onboarding.md) section 6.

| Call | Notes |
|---|---|
| `POST /auth/enroll` | Body `code`, `device_name`, `platform` (`android`, `ios` or `desktop`, the offline station), `app_version`, optional `signing_public_key` (base64url raw Ed25519 public key, 32 bytes; digitva-gb8w.5). 201 `{device_id, device_secret, project, server_time}`, plus `signing_key_id` (first 16 hex of the key's SHA-256) when a key was sent. A bad key is 400 `invalid_request` with `fields: ["signing_public_key"]`, checked before the code is consumed. 10/min per IP. Code consumed atomically (`use_count < max_uses`). |
| `POST /auth/devices/current/signing-key` | Device bearer only (the device is the session's, never the body; a cookie: 403 `device_session_required`; a revoked device's bearer: 401). Body `{signing_public_key}`. 200 `{signing_key_id}`. Set once: 409 `conflict` when the device has a key; 400 `invalid_request` with `fields` for a bad key. 10/min per IP. Audited `device_signing_key_set` (key id only). |
| `POST /auth/sessions` | Body `device_id`, `device_secret`, `email` (an email or a mobile number), `password`. 201 `{access_token, access_expires_at, refresh_token, refresh_expires_at, user {user_id, name, email}, terms_required, access}`. `access` is the `GET /me/access` body for that user, shown even while terms are pending (it is display only; the terms gate is on requests). Refusals: 401 `device_invalid` (unknown device or wrong secret), 401 `invalid_credentials`, 403 `email_unverified`, `maintenance`, `device_revoked`, `no_interviewer_grant` (no interviewer, coder, coding_tester or reviewer access in any active project; code kept for the app). Limits: 10/min per IP, 10/min per device, 20/hour per account. |
| `POST /auth/sessions/refresh` | Body `refresh_token`, `device_id`, `device_secret` (else 401 `device_invalid`, nothing revoked); optional outstanding-work report `count`, `unique_ids`, `client_draft_ids`, `client_death_ids` (not recorded while terms are pending). 200, the same body as sign-in, `access` included. 401 `refresh_reused` / 409 `refresh_retry_race` (reuse; session revoked); 401 `session_revoked` (device or admin revoke, no active project left, signed out); 401 `session_ended` (account changed; keeps data); 401 `session_expired` and `refresh_invalid` revoke nothing. 30/min per IP. |
| `DELETE /auth/sessions/current` | Bearer only (a cookie: 401 `unauthorized`). 204. `login_required`, not the interviewer role, so a withdrawn interviewer can still sign out; open while terms are pending. |
| `GET /auth/demo-signup/challenge` | Public demo only (`PUBLIC_DEMO_ENABLED`; else 404). No body. 200 `{salt, difficulty, expires, signature}`: a proof-of-work challenge valid 5 minutes, spent by one successful verification. 30/min per IP. |
| `POST /auth/demo-signup` | Public demo only (else 404). Body `{username, password, captcha {salt, difficulty, expires, signature, solution}}`. 201 `{user_id, username}`, no session (the app then calls `POST /auth/sessions`). 400 `captcha_failed` / `invalid_username` / `invalid_password` / `breached_password` (with `fields`); 409 `username_taken`; 429 `rate_limited`; 503 `cap_reached`, `breach_check_unavailable`, `project_missing`, `wrong_database`, `maintenance`. 10/min per IP (IPv6 per /64) plus `PUBLIC_DEMO_SIGNUP_RATE_LIMIT` and `PUBLIC_DEMO_SIGNUP_GLOBAL_RATE_LIMIT`. Audited `account_created`, `terms_accepted`. |
| `POST /auth/demo-enroll` | Public demo only (else 404). Body `{username, password, device_name (<= 64), platform: "android", app_version?}`. 201 as `/auth/enroll`, `{device_id, device_secret, project, server_time}`, with no enrolment code. 401 `invalid_credentials` (also for a non-demo account); 400 `invalid_request`; 503 `wrong_database`, `project_missing`. At `PUBLIC_DEMO_DEVICES_PER_ACCOUNT` (3) live devices the least recently used one is revoked (audited `device_revoked`, reason `demo_device_replaced`) and the new one enrolled. 10/min per IP, 20/hour per username. |

## Public demo (`/api/v1/public-demo`, `app/routes/public_demo.py`; `PUBLIC_DEMO_ENABLED` only)

Every call answers 404 with the flag off. Policy:
[public-demo.md](../policy/public-demo.md) sections 5 to 7; behaviour:
[Public Demo Reports, Downloads And Dashboard](public-demo.md). All GET, so no
CSRF surface.

| Call | Notes |
|---|---|
| `GET /public-demo/my-responses.csv` | Cookie session of a public-demo account (any other account, bearer or not: 404; anonymous: redirect or 401). The caller's own submissions as CSV (UTF-8 with BOM; columns `va_sid, submitted_at, state, smartva_cause, smartva_likelihood, coder_icd11_code, coder_icd11_title, reviewer_icd11_code, reviewer_icd11_title, answers_json`; formula-looking cells get a leading apostrophe), `Content-Disposition: attachment`. `Cache-Control: no-store`. 10/hour per user, shared with the JSON download (429 `rate_limited`); one at a time per user (429 `export_in_progress`). Audited `public_demo_download` (format and case count only). |
| `GET /public-demo/my-responses.json` | Same rules. 200 `{cases: [{va_sid, submitted_at, state, smartva {cause, likelihood, causes[]}, coder {code, title}, reviewer {code, title}, answers}], count, generated_at}`. |
| `GET /public-demo/dashboard.json` | No sign-in. 200 `{generated_at, totals {accounts, submissions, coded, reviewed}, smartva {total, causes[], other}, coder {total, causes[], other}, age_bands[], sex[]}`: aggregates over the demo project only, no ids, usernames or free text. Cached server-side (`PUBLIC_DEMO_DASHBOARD_CACHE_SECONDS`, default 300) and `Cache-Control: public, max-age=60`. 60/min per IP. |

The pages beside them (not JSON): `/public-demo/cases`, `/public-demo/cases/<va_sid>/report`
(submitter only, a case that is not the caller's is 404) and `/public-demo/dashboard`
(`private, no-store` for a signed-in viewer because of the personal navbar,
`public, max-age=60` otherwise).

## Me and reference

| Call | Notes |
|---|---|
| `GET /me/access` | The whole access body, below. Sets `X-CSRFToken` for a cookie request. |
| `GET /me/activity` | The caller's own personal activity counts (overall and per-project), below. Either credential. 120/min. |
| `GET /me/home` | The Home page's one block per role the caller holds, counts only, below. 120/min. |
| `GET /me/notifications?after=<id>` | The caller's own notifications, below. Either credential. 120/min. |
| `POST /me/terms` | Below. Also `POST /profile/terms` (the same view). |
| `GET /organization/<project>/units?role=interviewer` | The unit picker: `web_intake_service.reachable_unit_ids` (grant-based; a project grant or any site grant of the project reaches the whole tree). 403 when nothing is reachable. `role=death_reporter` is the same rule over a death reporter's own unit grants (the Register death picker for a reporter). Other `role` values and none are the browsing views. |
| `GET /organization/<project>/form-options` | `form_options_payload`: `config_version`, `enabled_extensions`, `form_types`, `intake_note`, `default_locale`, `available_locales`, `translation_versions`, `narration_languages`, `show_guidance`, `web_intake_mode` (which capture paths are open), `instrument_version` (the composed form version, `served_form_service.composed_version`), `definition_sha256` (the project's definition fingerprint). Any grant reaching the project. |
| `GET /intake/projects/<project>/prefill-policy` | `web_intake_service.prefill_policy`; the project must be one of the caller's interviewer projects (403 `project_forbidden`). |
| `GET /instruments/<code>/translations/<locale>[?project_id=]` | `translations_response` (weak ETag, 304). Without `project_id`: any servable (active or `in_review`) locale to any signed-in user. With it: also needs a grant reaching the project (403 `forbidden`; unknown or inactive project 404 `not_found`) and serves only that project's instrument and `available_locales`, else 404 `not_found` (the offline app passes it). 120/min. |
| `GET /instruments/<code>/definition?project_id=` | `instrument_definition`: the project's composed form definition (JSON), `served_form_service.served_definition`. `project_id` required (400 `invalid_request`), gated as form-options (404 / 403); 404 for another instrument; 503 `unavailable` if the file is unreadable. Headers `ETag: "<sha256>"`, `X-Definition-SHA256`, `Cache-Control: private, no-cache`; `If-None-Match` match gives a bodiless 304. Body carries `version`, `engineVersion` and `extensions` (the sorted conditional extensions in the slice), not the SHA. Optional `version=<v>&extensions=a,b` (both or neither, else 400; empty `extensions` = none) serves that exact slice of a version recorded in `mas_instrument_versions` (`historical_definition`): 404 `version_unknown`, 422 `invalid_extensions`; same headers, gzip and 304; the project need not enable those extensions today (access check only). 120/min. |
| `GET /instruments/<code>/versions` | `instrument_versions`: `{instrument_code, current, versions: [{version, activated_at}]}`, newest first (at most 200), from `mas_instrument_versions`. Any signed-in user. 404 for another instrument. 120/min. |

A client starts from `GET /me/access` (or the sign-in reply's `access`), then
reads `form-options` and `prefill-policy` per interviewer project it works in
and the `units` picker per project that has a tree.

## Intake (`/api/v1/intake`, `app/routes/api/intake.py`)

Paths are under `/api/v1`. Either credential; the caller needs the
interviewer role (supervision: `interview_supervisor` or `data_manager`). The
death register is the exception: `POST /intake/deaths`, `GET /intake/deaths`
and `PATCH /intake/deaths/<id>` also take a `death_reporter` (unit-scope role
for ANM, MPW and ASHA, `digitva-t6q`), who registers deaths without any
interview right.

| Call | Notes |
|---|---|
| `POST /intake/submissions` | Body `client_draft_id` (UUID), `project_id`, `site_id`, `draft` (envelope: meta keys only, `draft.data` is not read; optional `startedAt`, `completedAt`, `deviceClockAt`, each ISO 8601 with a UTC offset), `answers_json` (string: the exact JSON text of the answers object) and `answers_sha256` (64 hex, SHA-256 of that text's UTF-8 bytes), optional `completion: {valid, issues}`, `death_id`, `org_unit_id`. The server hashes `answers_json` as received, then parses. 422 `answers_hash_required` (a field missing, not a string, or a malformed hash), 422 `answers_hash_invalid` (hash differs; nothing stored), 422 `invalid_interview` (not a JSON object, over 1 MB, nested deeper than 6, or one of the three times present but unparsable or offset-less). 201 on a new upload (also a second upload of a case the caller already submitted: a correction), 200 on a resend (the same hash, or other answers: no 409, the last completed version wins by completion time). Result: `{va_sid, case, outcome, superseded, answers_sha256, kept, received_sha256, locked, can_code_now}` (`can_code_now`: as on `/intake/drafts/<id>/submit`): `answers_sha256` is the coder version's hash, `received_sha256` the hash of the answers this request sent (the app deletes its copy when it equals what it sent), `kept` `incoming` (the coder has these answers) or `server` (they are history only), `locked` true when coding is final or the case closed. A cookie request stores no `meta.deviceId`. Optional `consent` (respondent consent for this attempt; 422 `consent_required` / `consent_invalid` / `consent_conflict`, 409 `conflict`): "Respondent consent" below. Detail: [Device Collection API](device-collection-api.md) "Uploads". |
| `POST /intake/submissions/<va_sid>/revisions` | The submitting interviewer revises their own submitted interview. Body `reason_code` (`interviewer_correction`, `respondent_correction`, `more_information`, `finish_partial`), `answers_json` + `answers_sha256` (as `/submissions`), `completion: {valid, issues}`, `draft` (meta; only `startedAt`/`completedAt` are taken). 200 `{changed, va_sid, payload_version_id, answers_sha256, outcome, workflow_state}`; `changed: false` writes nothing. 404 `not_found` (not the caller's), 409 `revision_locked` / `case_already_submitted` / `case_closed` / `case_state_conflict`, 422 `invalid_reason` (the server's own `resubmitted` is not accepted) / `answers_hash_*` / `invalid_interview`. A completed interview may be revised to a refused or partial one (the case leaves coding). Body cap 2 MB. Detail: [Device Collection API](device-collection-api.md) "Interviewer revisions". |
| `POST /intake/supervision/submissions/<va_sid>/reopen-for-revision` | Reopen a finalised web or device interview for its interviewer to revise (`interview_supervisor`, `data_manager` or `admin`). Body `reason_code` (`cod_review_requested`, `new_information`, `data_correction`). 200 `{va_sid, workflow_state: "finalized_upstream_changed", reason_code}`. From `coder_finalized`, `reviewer_eligible`, `reviewer_finalized`. An admin, or a supervisor or data manager whose supervision reach covers the interview's case (404 otherwise); 409 `not_web_submission` / `case_closed` / `wrong_state`; 422 `invalid_reason`. The final COD stays until the interviewer's revision arrives. |
| `POST /intake/outstanding` | Device session only (a cookie: 403 `device_session_required`). Stores count, sorted unique ids and sorted, normalised `client_draft_ids` and `client_death_ids` (UUIDs) on the session; the admin device list returns all three (`outstanding_client_death_ids` added in `digitva-kmk.4`). |
| `GET /intake/cases?project_id=&mine=&state=&sort=&limit=&cursor=` | The case list, below. 120/min. `project_id` optional. Also open to a `death_reporter`: the list adds the deaths the caller registered that a `death_reporter` grant of theirs still reaches (the scope of `GET /intake/deaths`, nothing wider); such a row reached by no interviewer grant has `can_interview: false` and no `other_draft_*` keys, every other row `can_interview: true`. A reporter's `project_id` may name any project it registers in. `sort=next_visit` (default: next visit, then last activity) or `sort=reported` (newest registration first, keyset on `created_at`, `death_id`; the VA Interview page's Recent chip, index `ix_va_death_register_created`). Any other value is a 400, and a cursor from one order is refused by the other. |
| `GET /intake/cases/<death_id>` | Case detail with full contacts, links and (when the caller may start or resume it) prefill, below. 600/min per user, so a device can fetch each active case's detail after the list; on 429 a client keeps its previous complete copy and retries after `Retry-After`. |
| `POST /intake/cases/<death_id>/flags`, `/pause` | The browser worklist's calls, now for every client. Each replies `{"case": <detail>}`, the body of `GET /intake/cases/<id>` (below). |
| `GET /intake/cases/<death_id>/possible-duplicates` reply | `{"possible_duplicates": [...]}`, up to 50, most similar first, only cases inside the caller's own worklist scope (a case outside it is never returned, no id and no detail). Each: `death_id`, `unique_id`, `unit_name`, `state`, `score`, and `deceased_name`, `date_of_death` (ISO date), `village` (the village or ward of the case's recorded address, `null` when empty; the org unit is `unit_name`), `age_years`, `sex`, `informant_name`, `previous_interviewer_name` (the user who started the interview, `null` when nobody did; new here, since the worklist and case detail never name another interviewer, and shown only for these in-scope candidates by the owner's 2026-10-01 rule) and `reported_by_name` (the user who registered the death, who may be a data manager or death reporter rather than an interviewer; owner, 2026-10-09). The detail keys are additive. No phone or address. The per-row `possible_duplicates` of `GET /intake/cases` and the device list stays `death_id` and `unique_id` only. |
| `GET/POST /intake/deaths` | List (`project_id`, `site_id` required) and register (`project_id` required; `client_death_id` optional, idempotent), below. Register takes optional `consent` (the informant's registration consent); where the project requires consent, informant name, phone or address need a granted one: "Respondent consent" below. |
| `POST /intake/deaths` / `GET /intake/deaths` (death reporter) | A `death_reporter` registers a death as an interviewer does (same body, same 201 `{"case": <detail>}`, same `client_death_id` idempotency) in the unit subtree its grant reaches (403 outside it, or in a project whose `web_intake_mode` keeps no death register). The reply's `case` carries no `prefill` and `links` is only `{"update": "/api/v1/intake/deaths/<id>"}`: no start-interview, attempts or visit link. `GET /intake/deaths` serves a reporter (one with no interviewer right) **its own registered deaths** within reach, newest activity first: query `project_id`, `site_id` (optional narrowing; no reach there is 403), `limit` (default 50, clamped to 200), `cursor`; reply `{"deaths": [<death, as the interviewer's list, `va_sid` null>], "next_cursor": str \| null}`; malformed `limit`/`cursor` 400. Index-backed (`ix_va_death_register_registered_by`). A user who also holds `interviewer` gets the interviewer list unchanged (`project_id` and `site_id` required, no cursor) unless they ask `?registered=mine`, which serves any caller holding a `death_reporter` grant this same paged list (any other value is 400). A reply about a case is reporter-shaped (no `prefill`, `links` only `update`, no `other_draft_*`) for a caller with a `death_reporter` grant that no interviewer grant of theirs reaches the case through. Every other `/intake` route (case detail, drafts, attempts, visit, pause, flags, uploads, outstanding, prefill-policy, supervision) answers a reporter 403. |
| `PATCH /intake/deaths/<death_id>` | Correct a registered death until an interview of it is completed (`interviewer`, `interview_supervisor`, `data_manager`, or the `death_reporter` who registered it and whose grant still reaches its unit; the caller must see or supervise the case, else 404). Body: only the register fields to change, optional `if_updated_at` (the `case.updated_at` last seen), optional `identifiers` (below; may be the only key). 200 `{"case": <detail>, "warnings": [...]}` (a caller whose interviewer or reporter reach does not open the case, e.g. a supervisor, gets the trimmed supervisor row instead: no informant, phones or address, no links or prefill) (`warnings` only when present); 403 `forbidden` / 409 `case_closed` when `identifiers` is sent by a caller who may not change this case's numbers now (the any-time write's own gate, `require_identifier_write`; reaching a case to correct its details is not permission to change its numbers, so a teammate interviewer who neither registered, started nor interviewed it, or a self-coding coder, gets 403 for the whole request), 409 `case_completed` (a completed interview exists) / `details_pending` / `death_stale`; 422 `invalid_death` (`register_death`'s validation, a list or object in a field, a bad number with `fields: ["identifiers.<code>"]`, nothing to change). Audited as `details_edited`: the audit's `reason` names the fields, its `changes` column keeps each one's old and new value (never returned by any API). Policy: [Web Intake](../policy/web-intake.md) "Correcting a registered death". |
| Registration numbers (`identifiers`; `POST /intake/deaths`, `PATCH /intake/deaths/<id>`, reads) | digitva-kzyp stage 2; policy [Death Registration Identifiers](../policy/death-registration-identifiers.md), service `death_identifier_service`. **Write.** Optional body key `identifiers`: an object `{<type code>: <text>}` of the project's ACTIVE types ("Identifier types" below). It has its own parser (the register fields refuse objects, this key is one); a non-object or a non-text value is 422 `invalid_registration` / `invalid_death`. The server trims, collapses spaces, NFKC-normalises and upper-cases (`mccd/ab12` is stored `MCCD/AB12`), then checks length, character type and pattern of the type on the plaintext, then encrypts (AES-256-GCM, AAD `death_id || identifier_type_id`) and stores a keyed blind index. A refusal names the type label and example, never the value: 422 `invalid_registration` on registration (nothing is stored, the case is not created), 422 `invalid_death` on a correction (the PATCH route turns every content refusal into 422, so this is not the 400 the policy sketch names), body `{"error", "code", "fields": ["identifiers.<code>", ...]}`. An unknown or inactive code is refused alike. A registration always enforces the project's `required_at_report` types (422 naming `identifiers.<code>`), even when the key is absent; a correction does not, so the number may arrive later. On a correction only the listed codes change; `null` or an empty string deletes the row; a value equal to the stored one (compared by blind index) is a no-op that writes nothing. `client_death_id` idempotency covers it: a resend returns the stored case with 200, stores one set, writes one audit row and carries no `warnings`. Writers at registration are whoever may register (interviewer, death_reporter). A `PATCH` that carries `identifiers` has the any-time write's own gate, not just the right to correct the register fields: 403 `forbidden` for a caller who may not change this case's numbers now (the `can_edit_identifiers` rule below). The any-time write is `PUT /intake/cases/<id>/identifiers` below. A `PATCH` that carries `identifiers` for a cancelled or confirmed-duplicate case is 409 `case_closed` unless the caller is a supervisor, In-charge, project PI or admin of it (the whole request is refused; register-field edits of a closed case are unchanged). A `PATCH` with only `identifiers` and no `if_updated_at` is last-write-wins. A resend of a registration with the same `client_death_id` returns the stored case and IGNORES a different `identifiers` payload (the first write stands). An offline registration made before a type became `required_at_report` is refused 422 `invalid_registration` with `fields: ["identifiers.<code>"]` naming the type, so the client can ask for the number and resend. One `map_case_transitions` row per write: `action = identifiers_set`, state unchanged, `changes` keyed `identifier:<code>` with blind-index traces `{"bidx": first 16 hex of the blind index}` for `old` and `new` (null for none; no digits, older rows may still carry a legacy `mask`), `reason` the changed codes, and the supervisor grant and cadre as for any supervisor action. The case's `updated_at` moves. **Warnings.** A project-unique type whose number is already on another open case of the project (cancelled and confirmed duplicates excluded) answers 201/200 with `warnings: [{"code": "identifier_in_use", "field": "identifiers.<code>", "message": ...}]`; the write is kept. The message carries case id, unit and the reporter's name and designation (cadre, else job title) only when the writer supervises that other case (`supervised_case_condition`) or is admin; otherwise "This number is already on another case in this project." One query, reporter and cadre included. The same match makes the other case a `possible_duplicates` candidate (score 1, inside the caller's own scope only). **Read.** `identifiers` is on `case` (every single-case reply, incl. supervisor replies), on each row of `GET /intake/cases`, `GET /intake/deaths` (interviewer and reporter lists, for the edit form's prefill), `GET /intake/supervision/cases` and its detail, and `GET /api/v1/cases` rows, in the type `sort_order`. A viewer who reaches the case's project through admin, project_pi, site_pi, interview_supervisor, data_manager, interviewer, death_reporter or collaborator_pii and whose value-granting grant reaches THAT case (per case, not per project: a case reached only by coding, or by an implied self-coding interviewer grant, stays a badge whatever else the user holds in the project; `case_list_service.identifier_value_death_ids`) gets `[{"code", "label", "value"}]` for EVERY active type, `value: null` where nothing is stored (an inactive type shows only if it holds a value, so a new case reads `[{"code": "crs", "label": "CRS number", "value": null}, ...]`, not `[]`); everyone else (coder, coding_tester, reviewer, collaborator, even with a PII grant in another project) gets `[{"code", "label", "present": true|false}]` with the `value` key omitted, not null (`identifier_values_visible`, not `should_redact_pii`). The case list adds a per-row test (field reach, supervision, admin, PII lenses, collaborator_pii) so a row reached by coding alone is badge-only. Two queries per page whatever its size; only rows the viewer may see are decrypted; a value that cannot be decrypted degrades to `present: true` and is logged by row and key id only. **Edit flag.** The same places (case detail, `GET /intake/cases`, `GET /intake/deaths`, supervision rows and detail, `GET /api/v1/cases` rows) carry `can_edit_identifiers`: true only when the caller may change that case's numbers now (below); a closed case is false for everyone but a supervisor. Computed in the same query or one batch query per page (constant statement count). Values and the flag come from ASSIGNED grants only: the interviewer grant a self-coding project implies for a coder confers neither (badge only, `can_edit_identifiers: false`). Registration numbers in the CSV export: see `GET /cases/export.csv` under "Case list". Missing: native entry (stage 4). |
| Known exposure: `PATCH /intake/deaths/<id>` reply | Replies the full interviewer detail (informant name, phones, address) also to a supervisor or data manager. Pre-existing, kept for compatibility; only `PUT /intake/cases/<id>/identifiers` trims the reply for a caller who reaches the case by supervision or as admin. Trimming PATCH is a later change (digitva-kzyp). |
| `PUT /intake/cases/<death_id>/identifiers` | digitva-kzyp stage 3. Add, change or clear a case's registration numbers at any time, **also after the interview is complete**; the case state does not change. Gate `interviewer`, `death_reporter`, `interview_supervisor`, `data_manager`, `admin`, then per case and per request (the id is a claim): admin; a supervisor, In-charge, project PI (tree project) or data manager whose supervision reach covers the case (browser only: a device credential has none of those roles); the `death_reporter` on a death they reported and whose grant still reaches it; the `interviewer` on a case they registered, started or have an interview (draft) of, not every case of their unit subtree (the registrant clause lets a registering interviewer correct the numbers before the first interview, as `PATCH` allows, from the assigned grant only, never the self-coding implied one). Coder, reviewer, tester and collaborators are 403 `forbidden`; an interviewer in reach who did not interview it, 403; a case out of reach 404 `not_found`. **Closed cases** (cancelled, confirmed duplicate): supervisor, In-charge, project PI and admin only; the reporter, interviewer and data manager get 409 `case_closed` (names no value). Body `{"identifiers": {<type code>: <text> or null}, "if_updated_at": <iso, optional>}` (no other key; 1..50 codes; each raw value at most 256 characters, checked before normalising; the body at most 16 KB, else 413 `payload_too_large`); only the listed codes change, null or empty clears. 200 `{"case": <detail incl. identifiers and can_edit_identifiers>, "warnings": [...]}` (`warnings` only when a number is already on another case, as at registration). The `case` is the interviewer detail for a caller whose interviewer or reporter reach opens the case; for a caller who reaches it only by supervision (supervisor, In-charge, project PI, data manager) or as admin it is the trimmed supervisor row (as `GET /intake/supervision/cases`: no informant name, phones or address, no `links`, `prefill` or `my_draft_id`) with `identifiers`, `can_edit_identifiers` and `updated_at`. 400 `invalid_request` with `fields: ["identifiers.<code>"]` for a rule refusal (never the value); 409 `death_stale` when `if_updated_at` is not the case's `updated_at` (a write moves it); CSRF as every browser state change. One `identifiers_set` audit row naming the supervisor grant and cadre where one applies. 429 past the per-user budget ("Case list" below). |
| Death-site GPS fix (`POST /intake/deaths`, `PATCH /intake/deaths/<id>`) | Optional body fields `latitude` (-90..90), `longitude` (-180..180), `accuracy_m` (>= 0), all finite numbers; latitude and longitude come together, accuracy only with them (else 422 `invalid_registration` / `invalid_death`). Replies carry them, plus server-set `captured_at`, in `case.household_address` and in each `GET /intake/deaths` item only where `web_intake_service.shows_gps` allows (owner, 2026-10-20): the caller registered the death (any project; the reporter's own `GET /intake/deaths` list always), or the case is in an organization project (`projects_with_org_tree`) and the caller has personal-data access (`should_redact_pii` false). Otherwise the four keys are omitted, not null. One grant check and one organization-tree query per reply. Never in supervision rows; worklist rows as below. A `captured_at` in the body is ignored/unknown (422 on PATCH). A PATCH omitting the fields keeps the fix; explicit nulls clear it; any change re-stamps `captured_at`. Policy: "Death-site GPS location". |
| `POST /intake/cases/<death_id>/attempts`, `/visit` | Attempts (`client_attempt_id` optional, idempotent) and visits, keyed by the case (no `project_id`), below. |
| `POST /intake/drafts/sync` | The phone's in-progress interview into the caller's one open draft of a case; newer save wins whole, the loser is kept as a `replaced` draft. Reply `{draft, kept, conflict, answers_sha256, message, envelope}`; 422 `answers_hash_*`/`invalid_interview` store nothing; 409 on a closed case. Contract: [Device Collection API](device-collection-api.md) "Draft sync". |
| `PUT /intake/drafts/<id>/attachments/<client_attachment_id>` | One audio, image or PDF file for the caller's own open draft ([Web Intake Policy](../policy/web-intake.md), "Attachments"). Raw body (`Content-Type: application/octet-stream`), `Content-Length` required; optional `X-Content-SHA256` (64 hex: a body that differs is 400 `checksum_mismatch`; on a retried id a different checksum or size is 409); cookie plus `X-CSRFToken`; 120/min. `client_attachment_id` is the page's UUID for the file (the `id` of the answer's attachment reference) and the idempotency key: 201 `{attachment: {id, filename, mime_type, size, created_at}, created: true}` when stored, 200 with the same record and `created: false` when that id is already held (nothing stored again). The type is decided from the leading bytes (webm, wav, amr, mp3, m4a, jpeg, png, pdf), never from the name or `Content-Type`. Bytes go through the attachment store; the uploader's filename is not kept; an `.amr` is converted to MP3 as ODK sync does. Errors: 400 malformed id, 404 `not_found` (not the caller's draft), 409 (draft not open; `attachment_id_conflict`: that id holds a different size), 411 `length_required`, 413 `payload_too_large` (over 50 MB; an `.amr` over 5 MB), 415 `unsupported_media_type`, 422 `empty_attachment` / `attachment_limit` (60 per draft) / `audio_conversion_failed`, 503 `unavailable`. |
| `GET /intake/drafts/<id>/attachments/<client_attachment_id>` | The stored file to the draft's own interviewer (so a form shows a file the device no longer holds), any draft status of the caller's; `no-store`, `Content-Security-Policy: sandbox; default-src 'none'`, a PDF as `Content-Disposition: attachment`, `Range` honoured on the local store. 404 for another's draft or an unknown file. 300/min. |
| `GET/POST /intake/drafts`, `GET/PATCH /intake/drafts/<id>`, `POST /intake/drafts/<id>/discard`, `/submit` | The web draft store. `GET /intake/drafts` rows add the case's `deceased_name`, `deceased_sex`, `age_years` and `date_of_death` (null without a case) and carry `sections_saved`, all fetched for the whole list in two queries. Draft saves and submits take no body cap beyond the service's answer checks. `PATCH` takes optional `if_updated_at` (the last seen `draft.updated_at`): a newer saved version is 409 `draft_stale`, nothing written. One open draft per interviewer per case: `POST` returns the caller's own, another interviewer's never blocks (no 409). `/submit`: 422 `outcome_conflicts_consent` (answers say `Id10013` yes and `interview_outcome` refused, valid form or not; `fields` names both), 409 `attachments_pending` while an answer names a file that has not been uploaded (nothing stored; a device upload keeps such a reference as before); otherwise 201 `{va_sid, draft, superseded: false, validation_err, can_code_now}`; on a draft that is already `submitted` (a stale tab) it is a correction, 200 with the same body plus `kept` and `locked`; on an open draft whose case's winning submission is the caller's own earlier draft it is the same correction (the draft is closed as `replaced`; `va_sid` and `draft` are the winning interview's); on a case already `submitted`, `duplicate` or `cancelled` (a teammate won, or a supervisor closed it) the draft is kept as `superseded` (no submission, case untouched) and the reply is 200 `{va_sid: null, draft, superseded: true, validation_err: null, can_code_now: false}`. `can_code_now` (bool, also on the correction's reply and on the `/intake/submissions` result) is true when the caller may now be offered "Code this case now": a completed interview with valid consent in a self-coding project where the caller holds a coder grant that codes (`web_intake_service.can_code_now`; grants only, the action re-checks). |
| `GET /intake/supervision/cases`, `POST /intake/supervision/cases/<id>/resolve-flag`, `/cancel`, `/reopen`, `/duplicate` | Supervisor list and actions (`interview_supervisor` or `data_manager`). Each action replies `{"case": <row>}`, the case in the supervisor list's row shape (`serialize_supervised_row`: who registered and started it, no contact details, no prefill), not the interviewer's detail: a supervisor need not hold an interviewer grant. The list takes `state`, `flagged`, `candidates` (true: only cases with a second complete interview to choose), `visit_note` (true: only cases whose submission holds a visit note; composes with the others, one query), `needs_decision` (a flag waits or a second interview is to be chosen), `overdue` (open and `next_visit_at` past) and `stuck` (open, `updated_at` older than 30 days) (all true/false, 400 `invalid_request` otherwise), `sort` (`newest` default, `oldest`: `updated_at` ascending; the keyset `cursor` works both ways), `limit`, `cursor`; every row carries `other_complete_interview` (bool). The reply adds `tiles` `{needs_decision, overdue, stuck, total}`, counted in one query over the whole supervision scope with the same predicates as the filters, ignoring every filter; `counts` (per state) is unchanged. |
| `GET /intake/cases` rows and `GET /intake/cases/<id>` | Also carry `started` (bool: someone started the case; no name, the worklist never names an interviewer) and `created_at` (the registration time, the page's Reported column). Also carry `code_now` (bool): the caller's own submission of the case is `ready_for_coding` in a self-coding project where they hold a coder grant that codes, so "Code now" works (`POST /coding/submissions/<va_sid>/code-now`, below). Read from the worklist query (`ready_for_coding` joins `va_submission_workflow`), no per-row query. Not in supervision rows. |
| `GET /intake/cases` rows: `latitude`, `longitude` | The death-site GPS fix (numbers or `null`), for the case card's map pin. Present only for cases in organization projects (a project with an active organization level, `projects_with_org_tree`; never in a sites-mode project's rows, even an interviewer's), and there only where the case detail would show the household address: the caller has personal-data access (`should_redact_pii` is false, as for every interviewer) or registered the death (`registered_by_me`, a death reporter's own rows). Read from the worklist row already loaded; one grant check and one organization-tree query per page, no per-row query. Never in supervision rows (`GET /intake/supervision/cases`). Coordinates are not logged. |
| `GET /intake/supervision/cases/<id>` | One supervised case: `{"case": <supervisor row>, "candidates": [{draft_id, interviewer_name, completed_at, outcome}], "visit_note": {date, address, remarks, redacted} \| null}`, the other complete interviews a supervisor may choose (`outcome` is always `completed`). The interviewers' names are for supervisors only. `visit_note` is the case's visit note as the viewer may see it (`redacted` true, with `address` and `remarks` null, for a viewer `should_redact_pii` redacts), or null when there is none. 404 outside the caller's reach. |
| `GET /intake/supervision/cases/<id>/possible-duplicates` | Cases in the caller's supervision reach that may be the same death as this one, a warning only (`interview_supervisor`, `data_manager` or `admin`; same rules as the interviewer's `GET /intake/cases/<id>/possible-duplicates`). Reply `{"possible_duplicates": [{death_id, unique_id, unit_name, state, score, deceased_name, date_of_death, age_years, sex}]}`, supervisor-row fields only: no `informant_name`, `village` or phone. A case outside the reach is never a candidate. 404 when the subject is outside the caller's reach; 403 for an interviewer-only caller. |
| `POST /intake/supervision/cases/<id>/choose-interview` | Choose another interviewer's complete interview of a submitted case over the one it holds (`interview_supervisor`, `data_manager` or `admin`; [Web Intake Policy](../policy/web-intake.md), "Supervisors"). Body `draft_id` (a candidate), `reason_code` (`better_quality`, `more_complete`, `original_incorrect`, `switch_back`). 200 `{"case": <supervisor row>}`; the case keeps its `va_sid`, coding restarts from any stage (earlier COD kept as history), the other interview stays a candidate. 400 malformed `draft_id`; 404 outside reach or another case's draft; 409 `case_not_submitted` / `not_web_submission` / `not_a_candidate` / `form_mismatch` / `wrong_state` (a reviewer session is live); 422 `invalid_reason`. |
| Admin `POST .../device-enrolments` | Also returns `qr_svg` (segno) and `max_uses`; `Cache-Control: no-store`. The QR server URL is `DEVICE_PUBLIC_URL` (default: scheme and host of `PUBLIC_BASE_URL`; set `http://10.0.2.2:8051` for an emulator). Outside debug/testing a plain-http URL other than localhost, 127.0.0.1 or 10.0.2.2 refuses the code (503, logged); checked when a code is issued, not at startup, so a bad value cannot stop the server. |
| Admin `POST /admin/api/projects/<project_id>/station-registrations` | Register a never-online offline station from its enrolment file (digitva-gb8w.5). Body `name`, `enrolment_file` `{device_id, signing_public_key, app_version}` (no other keys). 201 `{device_id, signing_key_id}`. No device secret is issued (the stored secret hash matches nothing), so the station never signs in; its key verifies its bundles. 400 malformed file or bad key, 404 project, 409 `device_id` already registered. Admin only, CSRF. Audited `device_registered_from_file` and `device_signing_key_set`. |
| Admin `POST /admin/api/devices/<device_id>/revoke` | Optional body `revoked_compromised` (boolean, default false; else 400): lost or stolen, so every bundle the device signed is refused, not only those created after `revoked_at`. A later revoke may set it on a revoked device, never clear it. Reply adds `revoked_compromised`; the `device_revoked` event carries `compromised`. The device list rows add `signing_key_id` and `revoked_compromised`. |
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
app-level hook): 2 MB for `/intake/submissions` and its `/revisions`, 256 KB for
`/intake/outstanding`, 50 MB for `PUT /intake/drafts/<id>/attachments/<id>` (and `Content-Length` is required there, 411), 16 KB otherwise
(draft saves and submits excepted); over it -> 413 `payload_too_large`.

The app wipes an interviewer's store only on `session_revoked`. A refresh
whose response was lost and is retried with the old token answers 409
`refresh_retry_race`, and theft-style reuse 401 `refresh_reused`; both
revoke the session but the app keeps the data and asks the interviewer to
sign in again.

## Case list (`GET /api/v1/cases`, `GET /api/v1/cases/filter-options`, `app/routes/api/cases.py`)

The shared case list of [Case List Views](../policy/case-list-views.md): one row per death, report to coded, for the Deaths, VA Interview, VA Code and Supervision presets (`app/services/case_list_service.py`). Read-only GETs, either credential, `login_required` (no role gate: a caller with no grant gets 200 with `cases: []`, zero `counts`, no `tiles`; `counts` and `tiles` are present on a first page only, below). No CSRF (no mutation); `Cache-Control: no-store`; 120 per minute. `GET /intake/deaths` and `GET /intake/cases` are unchanged. Registration numbers: every row carries `identifiers` and `can_edit_identifiers` (see "Registration numbers" above). Filters (digitva-kzyp stage 3; 400 `invalid_request` for a bad value, never echoed): `identifier=has|missing` (a number of an active type of the case's project, or none; a project with no active type is neither), optionally with `identifier_type=<code>` (that one type; needs `identifier`), an EXISTS on `map_death_identifier` for every role that sees the badge, applied to the rows and to `counts` like the other filters (`tiles` ignore every filter, as before); and `identifier_number=<text>` (at most 256 characters, once): exact search, the server normalises it as a write does (`mccd/1` equals ` MCCD/1 `), computes the blind index per active type (narrowed by `project_id` and `identifier_type`) and matches through `ix_map_death_identifier_type_bidx`; only projects where the caller sees values and only rows whose values they see contribute (a badge-only caller gets an empty page, no error that says why), and it never widens the scope. The number is never logged. Requests that carry `identifiers` (`POST` / `PATCH /intake/deaths`, the `PUT` above) share one per-user budget, `IDENTIFIER_RATE_LIMIT` (default `30 per hour`; 429 `rate_limited`); `identifier_number` searches have their own, `IDENTIFIER_SEARCH_RATE_LIMIT` (default `120 per hour`); requests without numbers are not counted. The search reads every active type of the visible projects (keyset pages, no cap), so no type is silently left out. Every `/api/v1/intake/*` and `/api/v1/cases*` response, errors included, carries `Cache-Control: no-store`. `export.csv`: digitva-kzyp stage 5, below.

Query (every value validated; a bad one is 400 `invalid_request` that never repeats the value; a repeated single-value parameter is also 400):

| Parameter | Meaning |
| --- | --- |
| `preset` | `deaths` (default), `interview`, `coding`, `supervision`. Deaths: every reported death in scope, newest reported first, duplicate and cancelled left out. Interview: default statuses `reported`, `interview_pending`, `interview_in_progress`, newest activity first. Coding: `submitted_awaiting_coding`, `in_coding`, newest activity first. Supervision: the cases the caller supervises only (`supervised_case_condition`; empty under device credentials), oldest first, default `attention=needs_decision`, duplicate and cancelled included. |
| `project_id`, `site_id`, `org_unit_id` | Narrow only; `org_unit_id` takes its whole subtree. An id outside the caller's scope yields no rows and is never echoed. |
| `status` (repeatable, or comma list) | Combined status (below). When present it replaces the preset's default statuses, so `status=duplicate` reaches duplicates in any preset. |
| `state` (repeatable) | The register state (`VaDeathRegister.status`: `registered`, `scheduled`, `in_progress`, `paused`, `not_reachable`, ...), for the supervisor's state chips. |
| `dod_from`, `dod_to`, `reported_from`, `reported_to` | ISO dates `YYYY-MM-DD`, ends inclusive, UTC days (`reported_*` filter `created_at`, which is the report time only for `source = 'register'`, see `reported_at`). A start after its end is 400. |
| `sex`, `age_min`, `age_max` | `male`, `female`, `undetermined`, `unknown`; whole years 0..150 (the client turns an age band into bounds). A case with no age is left out once an age bound is set. |
| `attention` | Supervision preset only: `needs_decision` (default), `overdue`, `stuck`, `total` (no tile filter). The tiles of the policy. |
| `visit_note` | `true`: only supervised cases whose submission holds a visit note. |
| `sort` | `reported` (`created_at` desc), `updated` (`updated_at` desc), `oldest` (`updated_at` asc); default by preset. |
| `limit`, `cursor` | `limit` clamped to 1..200 (default 50). `cursor` is the opaque `next_cursor` of a reply with the same `sort`; a cursor of another sort, or malformed, is 400. Keyset on `(created_at, death_id)` or `(updated_at, death_id)`. |

Reply `{"cases": [...], "counts": {...}, "tiles": {...}, "next_cursor": str | null}`. `counts` and `tiles` are computed (and present) only when the request has no `cursor`, the first page; a reply to a request with a `cursor` omits both keys, since they are sequential scans a client does not need again while it pages (a client keeps the first page's values and refetches without a cursor to refresh them). **Date reported:** `created_at` is when the case row was created; it is the report time only for `source = 'register'`. For `direct` (interview started) and `odk` (sync created the case) it is not a report time, so each row carries `source`, and `reported_at` (equal to `created_at`) is present only when `source = 'register'`. Sorting, the cursor and `reported_*` stay on `created_at`:

```json
{
  "cases": [{
    "death_id": "...", "unique_id": "KA01-000123", "project_id": "UNSW01", "site_id": "KA01",
    "status": "submitted_awaiting_coding", "register_state": "submitted", "source": "register",
    "age_years": 62, "deceased_sex": "female", "date_of_death": "2026-10-01",
    "created_at": "...", "reported_at": "...", "updated_at": "...", "registered_by_me": false, "started_by_me": false,
    "deceased_name": "...", "org_unit_id": "...", "unit_name": "...",
    "reporter_name": "...", "interviewer_name": "...", "coder_name": null,
    "latitude": 28.61, "longitude": 77.2
  }],
  "counts": {"reported": 3, "interview_pending": 0, "interview_in_progress": 1, "submitted_awaiting_coding": 4,
             "in_coding": 2, "coded": 9, "refused": 0, "not_codeable": 0, "duplicate": 1, "cancelled": 0, "total": 20},
  "tiles": {"needs_decision": 2, "overdue": 1, "stuck": 0, "total": 14},
  "next_cursor": null
}
```

- **Combined status**, one SQL `CASE` (`combined_status_case`) shared by the row, the `status` filter and `counts`, first match wins: register `duplicate`/`cancelled`/`refused` stay; a `submitted` case by its workflow state (`not_codeable_by_*` is `not_codeable`, `consent_refused` is `refused`, the finalized states are `coded`, `coding_in_progress`/`coder_step1_saved`/`reviewer_coding_in_progress` are `in_coding`, anything else or no workflow row is `submitted_awaiting_coding`); `in_progress` and `draft_identity` are `interview_in_progress`; `scheduled`, `paused`, `not_reachable` are `interview_pending`; `registered` is `reported`.
- **`counts`** cover the scope and every filter except `status` (and `attention`), computed in one aggregate query; duplicate and cancelled are counted in every preset. **`tiles`** (`needs_decision`, `overdue`, `stuck`, `total`, [Case List Views](../policy/case-list-views.md)) is present only for a caller with supervision scope, in any preset, over the whole supervised scope with every filter ignored (a second aggregate query, `supervision_tiles`, shared with `GET /intake/supervision/cases`).
- **Scope** is the OR of `_worklist_scope` for the interviewer grants, the same for the death_reporter grants limited to the caller's own registrations, `supervised_case_condition`, and `scope_filter(VIEW)` through the case's `va_sid` (coder, reviewer, data manager, collaborator, PI). Admin has no bypass in the first two, so it reaches the cases that have a submission.
- **Field visibility** is decided per row in the same SELECT; a hidden field is omitted, not null. `deceased_name`: field reach (interviewer, own registrations of a death_reporter) and `collaborator_pii`; admin and anyone supervising the case (including a data manager and project_pi) only when the caller has personal-data access (`should_redact_pii` false, checked once per caller; owner, 2026-10-21: admin is a PII holder, so `should_redact_pii` is false for it and it sees names, staff names, GPS and identifier values; it has no scope bypass, only the cases the scope rules give it); not coder, reviewer, plain collaborator, PI or a data manager reaching the row only through the submissions scope. `org_unit_id`/`unit_name` (the site name in a sites-mode project): everyone except a row reached by coding alone. `reporter_name`/`interviewer_name`/`coder_name`: admin, supervision reach and a data manager's submissions reach, each only with personal-data access; a field role gets only its own part (`registered_by_me`, `started_by_me`). `latitude`/`longitude` as decision 6 of the policy and `worklist_page`: organization project, caller not redacted (`should_redact_pii`) or the case's registrant, only on a row the caller's interviewer or reporter reach opens, never in supervision rows. Never informant name, address or phones, or the questionnaire.
- **Supervision rows** add `reason` (`resolve_flag`, `choose_interview`, `reopen` for duplicate and cancelled, `overdue`, `stuck`, or null), `pending_flag`, `next_visit_at`, `waiting_since` (the case's `updated_at`), `va_sid`, `duplicate_of_death_id`, `other_complete_interview`.
- **One page costs a constant number of statements** whatever `limit` is: the page SELECT (joins for unit, site, reporter, interviewer, workflow state, the coder as a scalar subquery), the counts aggregate, the tiles aggregate (both run under `SET LOCAL jit = off`, the caller's `jit` value put back after them), plus the grant reads; a page with a `cursor` omits the counts and tiles statements. Plans: [Case list query plans](../kb/case-list-query-plans.md).

`GET /cases/export.csv` (digitva-kzyp stage 5; `case_export_service`) streams the list as a CSV download: the same query, scope and filters as `GET /cases` (`preset`, `project_id`, ..., `identifier`, `identifier_type`, `identifier_number`; `cursor`, `limit` and `sort` apart: it pages by itself in keyset batches of `WORKLIST_PAGE_MAX`, in the list's order). Gate `data_manager` or `admin` (`effective_roles`, so a project PI and an In-charge, who hold the data manager gate, export too), browser cookie session only (a bearer token is 403 `cookie_session_required`, checked first), anonymous 401, other roles 403; GET, so no CSRF; 10/min per user and, with `identifier_number`, the identifier search budget. `Cache-Control: no-store`, `text/csv; charset=utf-8` with a BOM, `Content-Disposition: attachment; filename="cases.csv"`. Nothing is written to a file or the export store (unlike the data management CSVs, which are stored and cached: registration numbers are not added to those). Columns: `death_id, unique_id, project_id, site_id, org_unit_id, unit_name, status, register_state, source, deceased_sex, age_years, date_of_death, reported_at, created_at, updated_at, reporter_name, interviewer_name, coder_name` (hidden cells empty, as the viewer's rows), never the deceased's name, informant data, coordinates or payload fields. **Registration numbers** (the recorded exception, decision 9): one extra column per ACTIVE type, header = the type label, in `sort_order`, only for the projects where the exporter is admin (admin sees identifier values: admin is a PII holder in the current code) or holds a live ASSIGNED `data_manager`, `project_pi` or `site_pi` grant (`export_roles`; narrower than `identifier_values_visible`: an `interview_supervisor`, `interviewer`, `death_reporter` or `collaborator_pii` grant gives no column); no column at all otherwise. The audited project set and the active type codes are pinned at `prepare` for the whole stream: values are decrypted only for those projects, cells are keyed by type CODE (two active types of one project with the same label get headers `label (code)`; an inactive type holding a value never fills a column), and a number the exporter may see but that cannot be decrypted refuses the whole export: before the audit row and the first byte, `prepare` runs the stream's keyset batches once as a validation pass (decrypting every audited identifier cell in memory, no output, constant statements per batch, memory bounded by one batch), and on a failure answers 500 `export_unreadable` (logged by row id and type code, never a value; no audit row, no body, no file; no event added: `IDENTIFIER_AUDIT_EVENTS` has no failure event). Cost: each audited number is decrypted twice per export (validation, then stream); an export without identifier columns decrypts nothing and skips the pass. A value that breaks between the pass and the stream still aborts the stream (truncated download), never a silent empty cell. **Limits**: over `EXPORT_MAX_ROWS` (default 200000, counted by `export_summary`) the reply is 413 `export_too_large` before anything is written; one running export per user (429 `export_in_progress`, a cache lock freed when the stream ends or after 30 min); the read transaction is ended after each batch so no connection is held while a slow client drains. The response carries `X-Accel-Buffering: no` and `deploy/ingress-routes.conf` proxies this path with `proxy_buffering off; proxy_max_temp_file_size 0` (see split-production-deploy.md). Response header `X-Identifier-Columns`: `full` (every exported row's project qualifies), `partial` (rows of other projects leave those cells empty), absent (no identifier columns, no audit row). Columns are matched by label across qualifying projects. Values are decrypted in memory per batch (`list_cases`, a constant number of statements per batch); an export without the columns decrypts nothing. Every cell starting with `=`, `+`, `-`, `@`, tab, CR or newline, or whitespace followed by one of `=+-@`, gets a leading `'`. **Audit**: after the validation pass and before the first byte, one `map_identifier_audit` row (`event = export_with_identifiers`) per qualifying project (the table's `project_id` is not null, so a multi-project export writes one row per project, same filters and row count), `actor_role` = the grant role in that project (`admin`, `data_manager`, `project_pi`, `site_pi`), `details` = `{filters (set filters only; identifier_number is `true`, never the number), preset, row_count (counted before streaming), type_codes of that project, columns}`; never a value; committed before streaming, so it survives a failure mid-stream.

`GET /cases/filter-options` replies `{"projects": [{project_id, project_name}], "sites": [{project_id, site_id, site_name}], "units": [{org_unit_id, project_id, unit_name}]}`: only what appears in the caller's scoped cases, so nothing outside the scope is named. Units only from rows where the caller may see a unit. There is no `people` part (person filters are deferred). Each list is capped at 500.

## Code this case now (`POST /api/v1/coding/submissions/<va_sid>/code-now`, `app/routes/api/coding.py`)

In a self-coding project (`va_project_master.self_coding_enabled`, intake not
`off`) the interviewer who submitted a case takes it for coding
([Coding Workflow State Machine Policy](../policy/coding-workflow-state-machine.md),
"Self-coding"). Gate `coder` (a coder implies an interviewer there); browser
cookie with `X-CSRFToken`. No body. Service:
`coder_workflow_service.allocate_own_case`, which is `allocate_pick_form` with
the pick-mode check relaxed for this case, so it works in random and pick
projects. 201 `{va_sid, actiontype: "vapickcoding"}`; 200 `varesumecoding` when
the caller already holds this case. Errors `{error, code}` (a 409 for a case
outside the pool also carries `workflow_state`): 404 `not_found`; 403
`forbidden` (not a self-coding project, not the caller's own submitted case, or
outside their coding scope), 403 `allocation_exists` (another active coding
allocation); 409 `not_ready` (attachments or SmartVA still pending: the client
retries), 409 `held_by_another` (a coder holds it), 409 `not_available` (any
other state), 409 `conflict` (retired or confirmed duplicate). The browser
submit screen and the interviewer worklist call it and open `/coding/resume`.

## Coder release (`POST /api/v1/coding/allocation/release`, `app/routes/api/coding.py`)

A coder releases their own active coding allocation
([Coding Allocation Timeout Policy](../policy/coding-allocation-timeouts.md),
"Coder release"). Gate `coder` or `coding_tester`; browser cookie with
`X-CSRFToken`. No body. 200 `{va_sid, workflow_state}` (`ready_for_coding`, or
`coder_finalized` for a recode); 409 `no_allocation` when none is held. Same
effect as the timeout (`coding_allocation_service._release_coding_allocation`),
audited as `va_allocation_released_by_coder` under the coder's user id.

## Coding send-back (`POST /api/v1/coding/submissions/<va_sid>/send-back`, `app/routes/api/coding.py`)

A coder or reviewer sends a finalised web or device interview back to its
interviewer ([Interview Revisions Policy](../policy/interview-revisions.md),
rule 3). Gate `coder` or `reviewer`; browser cookie with `X-CSRFToken`. Body
`reason_code`: `missing_information`, `inconsistent_answers`,
`wrong_respondent_or_case`, `needs_clarification`. 200 `{va_sid, workflow_state:
"finalized_upstream_changed", reason_code}`. Allowed for the coder who authored
the final COD (`coder_finalized`, `reviewer_eligible`) and a reviewer in
reviewing scope on a `reviewer_eligible` submission, on the one whose session
they hold (`reviewer_coding_in_progress`, the session is released first) or on
the one they finalised (`reviewer_finalized`). Errors `{error, code}`: 404
unknown, 403 `forbidden` (outside scope, or not the coder who finalised it),
409 `not_web_submission` (an ODK submission) / `case_closed` (confirmed
duplicate) / `wrong_state`, 422 `invalid_reason`. The final COD stays active
until the interviewer's revision arrives; a data manager's reject cancels the
send-back.

## SmartVA run (`POST /api/v1/coding/submissions/<va_sid>/smartva`, `app/routes/api/coding.py`)

Queues `run_smartva_for_submission` for a case from the coding page's SmartVA
panel ([Coding Workflow State Machine Policy](../policy/coding-workflow-state-machine.md),
"SmartVA status on the coding page"). Gate `coder`, `coding_tester`,
`reviewer`, `data_manager` or `admin`, then a coding-level permission on the
case: `Action.CODE`, `REVIEW` or `TRIAGE` (a view-only grant does not pass); browser
cookie with `X-CSRFToken`; 10 per minute per user. Body (optional)
`{"regenerate": bool}`; `regenerate` must be `true` to replace a finished
result. 202 `{va_sid, status: "queued"}`; a run already `queued` or `running`
answers 202 with that status and queues nothing. Errors `{error, code}`: 404
`not_found` (unknown), 403 `forbidden` (out of coding scope or a view-only grant), 409 `wrong_state` (past
coding or a confirmed duplicate) / `already_done` (a result exists and
`regenerate` is not true), 422 `invalid_request` (`regenerate` not a boolean),
429 `rate_limited`, 503 `queue_unavailable` (the broker refused; no marker is
left). A failed run is queued as a replacement of its failure row. A failed
regeneration keeps the old successful result active and records the failure on
the run only; the audit rows of a requested regeneration carry the requester.

## Coder COD writes (`POST /api/v1/coding/initial|finalize|not-codeable/<va_sid>`, `app/routes/api/coding.py`)

The coder's three saves over JSON (digitva-xl43 phase 1), the same writes the
web partials make: both call `app/services/coder_cod_service.py`
(`submit_coder_initial_cod`, `submit_coder_final_cod`,
`submit_coder_not_codeable`). Gate `coder` or `coding_tester`; cookie with
`X-CSRFToken` or a device bearer. Authorised per request: `Action.CODE`
(`RECODE` in a recode episode) on the case plus the caller's own active coding
allocation on it. The service derives the web's `actiontype` itself: demo
practice stamps `demo_expires_at`, a coding tester's save is tester output
(stored deactive, the case returns to the pool, ODK untouched).

| Route | Body | 200 reply |
| --- | --- | --- |
| `POST /initial/<va_sid>` (masked projects only) | `immediate_cod` (not for masked DORIS), `antecedent_cod`, `other_conditions` (a list from the age group's choices, or one text joined by ` \| `), masked DORIS: `doris_certificate`, `doris_result`, `codedit_result`, `doris_process_token`, `doris_result_digest`, `doris_client_revision` | `{va_sid, initial_assessment_id, workflow_state}` (`coder_step1_saved`) |
| `POST /finalize/<va_sid>` | `conclusive_cod` (required), `remark`, `immediate_cod` and `other_conditions` (text; unmasked simple), the DORIS fields above (unmasked DORIS), `cod_search_id`, `cod_chosen_code` (text), `cod_chosen_rank` (integer); a wrong type is a 400 before anything is saved | `{va_sid, final_assessment_id, workflow_state}` (`coder_finalized`, or the state a coding tester's save returns the case to) |
| `POST /not-codeable/<va_sid>` | `reason` (`narration_language`, `narration_doesnt_match`, `no_info`, `form_is_empty`, `others`), `other` (required for `others`) | `{va_sid, workflow_state, odk_synced}` (`odk_synced`: the ODK Central flag was set; `false` for a coding tester's report or a failed flag) |

Errors `{error, code}`: 400 `invalid_request` (body not an object, wrong type,
a missing required field, a DORIS certificate sent to masked Step 2),
`invalid_cod` (Step 1; `messages` lists every invalid cause) and
`invalid_other_conditions`; 403 `forbidden` / `no_allocation`; 404 `not_found`;
409 `not_masked`, `wrong_state` (a masked final without the caller's own
Step 1: "Save Step 1 first."), `no_payload` and the DORIS conflicts
`DORIS_CERTIFICATE_CHANGED` (carries `processing`, a fresh proof; nothing is
saved), `DORIS_PROCESS_MISMATCH`, `DORIS_PROCESS_EXPIRED`; 413 `payload_too_large`
(any of the three bodies over 1.2 MB, or with no `Content-Length` (chunked); keyed by path only, with no database
lookup); 422 `invalid_request` (`remark`, `other` or an `other_conditions`
item over 4000 characters), `final_blocked` (`messages` lists
every blocking gate: an invalid COD, no active payload, Narrative QA or Social
Autopsy Analysis not yet saved) and `invalid_doris`; 503 `who_unavailable` /
`who_not_configured`. Not codeable also flags ODK Central for revision; a
failed flag is audited and does not fail the save.

## Reviewer COD routes (`POST /api/v1/reviewing/allocation/<va_sid>|initial/<va_sid>|finalize/<va_sid>`, `app/routes/api/reviewing.py`)

The reviewer's start and two saves over JSON, the same writes the web COD panel
makes: both call `app/services/reviewer_coding_service.py`
(`start_reviewer_coding`, `submit_reviewer_initial_cod`,
`submit_reviewer_final_cod`). Gate `reviewer`; cookie with `X-CSRFToken` or a
device bearer. Authorised per request: `Action.REVIEW` on the case, plus the
caller's own active reviewing allocation for the saves.

Errors are flat `{error, code}` (a changed DORIS certificate adds the
reprocessed `processing`; nothing is saved). The HTTP statuses are unchanged:
400 `invalid_request` (body not an object, wrong type, a missing required
field, a DORIS certificate sent to masked Step 2), `invalid_cod` (an invalid
COD or mixed ICD-10 and ICD-11), `wrong_state` (a masked final without the
reviewer's own Step 1) and `final_blocked` (Social Autopsy not yet saved); 403
`forbidden` (outside review scope, language not in the profile, closed
project), `no_allocation`, `wrong_state` (the case is not `reviewer_eligible` /
`reviewer_coding_in_progress`, or already has a reviewer final); 404
`not_found`; 409 `allocation_exists` (another reviewing allocation is held),
`conflict` (retired or confirmed-duplicate case), `not_masked` (Step 1 on an
unmasked project) and the DORIS conflicts `DORIS_CERTIFICATE_CHANGED` (carries
`processing`), `DORIS_PROCESS_MISMATCH`, `DORIS_PROCESS_EXPIRED`; 413
`payload_too_large` (a DORIS body over 1.2 MB); 422 `invalid_doris`; 503
`who_unavailable` / `who_not_configured`. `wrong_state` keeps the status each
route always had: 403 on start and the saves (400 for a masked final without
Step 1), 409 on reviewer release and when a release lands during a final save.

## Coder projects (`GET /api/v1/coding/projects`, `app/routes/api/coding.py`)

`{projects, project_options, last_project_id}`. `last_project_id` is the
project of the caller's most recent coding allocation (any status), or `null`
when there is none or it is not in `project_options`; the queue opens on it
(`digitva-umc4`). One indexed query.

## Coder pick list and history (`GET /api/v1/coding/available|history`, `app/routes/api/coding.py`)

Gate `coder`, `coding_tester` or `admin`. Paging is opt-in, because the web
coder dashboard (`va_code_dashboard.js`) reads both lists whole and renders
them in a client-side table: **without `limit` the body is exactly what it was**
(`{forms, count}`, `{history, count}`, every existing row key unchanged; `recode_until` is added).

| Parameter | Rule |
| --- | --- |
| `limit` | 1 to 200. Switches paging on. |
| `offset` | 0 to 1,000,000, with `limit` only; `offset` alone is 400. |
| `project_id` | Optional, upper-cased, at most 64 characters. Narrows to one project **within** the caller's own reach: a project the caller holds no grant on answers an empty list (`forms` / `history` `[]`), never its rows. Works with or without `limit`. |

With `limit` the body is `{forms|history, count, limit, offset, has_more}`;
`count` is the page's size and `has_more` is answered by fetching one extra
row, so there is no total. A bad parameter is 400 `invalid_request`.
Same rows, same keys and the same authorization as the unpaged body.

- `/available` order is project, site, submission date, masked id, `va_sid`
  (the last added, so a page boundary never splits equal rows). The pool is
  live: a case another coder takes between two pages shifts the later pages
  by one, so a client that must not miss a case refetches from `offset=0`.
- `/history` is the demo rows first (`is_demo`, unexpired), then the caller's
  own finals and not-codeable reviews on cases they may still view, newest
  coding date first, ties broken by submission date, status (completed
  before not-codeable), `va_sid` and row id, so pages never gap or repeat.
- Every `/history` row (paged or not) carries `recode_until`: on a final
  coding, its time plus the project's `recode_window_minutes`, tz-aware ISO
  (UTC offset); null on not-codeable, tester and demo rows. It is set whether
  or not the row is still `recodeable`, so a client can say the window has
  closed ([Coding Workflow State Machine](../policy/coding-workflow-state-machine.md),
  "Recode Window").
  `recodeable` is set on each page row. A paged request bypasses the five
  minute dashboard cache and reads the current rows.
- Cost: `limit` and `offset` run in SQL (`LIMIT`/`OFFSET` over a UNION of the
  two history tables, and on the pick query), at most about a dozen queries
  whatever the size; the history sort reads only the caller's own rows
  (`va_finassess_by` index), the pick query the caller's pick-mode forms
  (`va_form_id` index). No migration.

## Workflow events (`GET /api/v1/workflow/events/<va_sid>`, `app/routes/api/workflow.py`)

Any signed-in user; authorized by `READ_EVENTS` (the submission's VIEW scope):
403 `forbidden`, 404 `not_found`, unchanged by paging. Without `limit` the body
is unchanged: `{va_sid, events}`, every event, **oldest first**. With `limit`
(1 to 200) it is a newest-first page: `{va_sid, events, limit, next_cursor}`;
pass `next_cursor` back as `cursor` for the next older page, `null` on the last
(also when the last page is exactly full). The cursor is opaque, the last
event's `(event_created_at, event_id)`, so events that share an instant never
gap or repeat, and a new event arriving during the walk cannot shift it.
`cursor` without `limit`, a malformed `cursor` or a bad `limit` is 400
`invalid_request`. An event row is `event_id`, `transition_id`,
`previous_state`, `current_state`, `actor_kind`, `actor_role`,
`transition_reason`, `event_created_at`. One query, an index range scan on
`(va_sid, event_created_at)`.

## Reviewer queue (`GET /api/v1/reviewing/stats|available|history`, `app/routes/api/reviewing.py`)

The reviewer dashboard's reads for any client, from
`app/services/reviewer_dashboard_service.py` (the web page calls the same
functions). Gate `reviewer`; every reply is `private, no-store`. Optional
`project_id` (upper-cased, at most 64 characters) narrows each route.

| Route | Reply |
| --- | --- |
| `GET /stats` | `{in_scope, completed, available, allocation}`. `in_scope` and `completed` are the web page's counts (cases in review scope in any state; the caller's active reviewer finals, any scope); `available` is the size of `/available`; `allocation` is `{va_sid}` or `null`, as `GET /allocation`. |
| `GET /available` | `{cases, count, limit, offset, has_more}`. Exactly the cases `POST /allocation/<va_sid>` accepts: `reviewer_eligible`, REVIEW scope, narration language in the caller's profile, in ODK (not retired), not a confirmed duplicate, no active reviewer final, active project-site. A row is `va_sid`, `va_uniqueid_masked`, `va_form_id`, `project_id`, `site_id`, `va_submission_date`, `va_data_collector`, `va_deceased_age`, `va_deceased_gender`, `va_narration_language`. Ordered by project, site, submission date, masked id, `va_sid`. |
| `GET /projects` | `{project_options: [{project_id, project_name}], last_project_id}`. `project_options` are the projects the queue reaches, the scope of `/stats` and `/available`. `last_project_id` is the project of the caller's most recent reviewing allocation (any status), or `null` when there is none or it is not in `project_options` (`digitva-umc4`). |
| `GET /history` | `{history, count, limit, offset, has_more}`. The caller's own active reviewer finals on cases they may still view, newest first. A row is the `/available` keys plus `va_reviewed_at` (UTC ISO timestamp of the final, with `+00:00`). |

`limit` is 1 to 200 (default 50) and `offset` 0 to 1,000,000; anything else is
400 `invalid_request`. `count` is the page's size and `has_more` is answered by
fetching one extra row. One query per route (plus one count on `/stats`).

## Reviewer release (`POST /api/v1/reviewing/allocation/release`, `app/routes/api/reviewing.py`)

A reviewer releases their own active reviewing allocation
([Coding Allocation Timeout Policy](../policy/coding-allocation-timeouts.md),
"Reviewer release"). Gate `reviewer`; browser cookie with `X-CSRFToken` or a
device bearer. No body. 200 `{va_sid, workflow_state}`
(`reviewer_eligible`); 409 `no_allocation` when none is held; 409
`wrong_state` when the case is no longer in a reviewer session (nothing
changes). No scope check: an allocation that outlived a narrowed grant can
still be released. Same effect as the reviewer-session timeout
(`coding_allocation_service._release_reviewer_allocation`): the allocation, the
reviewer's review, NQA and Social Autopsy analysis are deactivated and the
reviewer's saved Step 1 is kept (owner, 2026-10-05). Audited as
`reviewer_allocation_released_by_reviewer` under the reviewer's user id.

## NQA and Social Autopsy errors (`POST /api/v1/va/<va_sid>/narrative-qa|social-autopsy`, `app/routes/api/nqa.py`, `app/routes/api/so.py`)

Errors `{error, code}`; a body that is not a JSON object is 400
`invalid_request`. 400 `invalid_request` (NQA not enabled for the project,
invalid or missing NQA fields, `selected_options` not a list or an invalid
option, an unanswered delay question: the last also carries
`missing_delay_levels`); 403 `forbidden` (reviewer outside review scope,
coder or coding tester outside coding scope (`Action.CODE`), Social Autopsy
disabled for the role, a coder demo session outside a demo/training project),
`no_allocation` (no active reviewing or coding allocation on the case); 404
`not_found`. Admin passes a demo session (`vademo_start_coding`) on a
demo/training submission; anywhere else admin needs its own active coding
allocation (its demo allocation), as admin holds no coding scope
(digitva-en2g). The coding-access check shared with `icd10.py` answers the
same two 403 codes (`require_coding_access`).

## Workspace content (`GET /api/v1/va/<va_sid>/workspace` and `.../categories/<code>`, `app/routes/api/va_case.py`)

The coding and review workspace content for any client (digitva-xl43 phase 2).
The reads are `app/services/case_content_service.py`, which the web partials
(`va_form.renderpartial` GET) render from too. Gate `coder`, `coding_tester` or
`reviewer`; cookie or bearer. `mode` is required: `coding` or `reviewing`
(anything else is 400 `invalid_request`). Authorization runs before any
payload read: `coding` needs a coder or coding tester with `Action.CODE`
(`RECODE` in a recode episode) on the case and their own active coding
allocation (`coder_cod_service.require_coding_session`); `reviewing` needs a
reviewer with `Action.REVIEW` and their own active reviewing allocation
(`reviewer_coding_service.require_reviewing_session`). Admin demo coding is
not served.

`mode=view` (`digitva-xl43.8`) is the read-only opening of a case, the web's
`/coding/area/<sid>`: authorized by `Action.VIEW` (`authz.require`), not by an
allocation, for coder, coding_tester, reviewer, collaborator,
collaborator_pii and admin; outside the caller's scope 403 `forbidden`, a
missing case 404 `not_found`. Categories are the viewer's (no workflow
panel); a caller who sees no personal data (plain `collaborator`) gets the
redacted section. The workspace body has `step: "view"`, `blocked_by: []`;
`doris`, `narrative_qa`, `social_autopsy`, `other_conditions_options` and
`assessments.initial|initial_prefill` are `null`, `case.narrative_qa_enabled`
and `case.social_autopsy_enabled` `false`. A view must not unblind coding: the
COD reference and `smartva` are served only when the case's workflow state is
in the `coded` or `not_codeable` coding bucket
(`workflow.definition.WORKFLOW_CODING_BUCKETS`) and the caller holds no active
coding or reviewing allocation on the case; otherwise `assessments.final`,
`coder_initial`, `reviewer_final`, `not_codeable` and `smartva` are `null`.
When served, `final` is the coder final the authoritative record stands on or
supersedes, `reviewer_final` the latest active reviewer final of any reviewer,
`coder_initial` the display initial, `not_codeable` the active coder review;
for a redacted viewer the staff free text (`remark`, `not_codeable.other`) is
`null`. Category content is unchanged by this. A category body in view never carries
`blocked_by`. `GET|PUT /note` stay allocation-only and answer `mode=view` 400
`invalid_request`. Media (`/api/v1/attachments`) and
`/api/v1/workflow/events/<sid>` already authorize by VIEW.

`GET /<va_sid>/workspace?mode=` answers `Cache-Control: private, no-store`:

Browser presentation also receives additive case fields: `project_code` and
`site_code` (nullable strings), `age` (nullable string or number), `gender`
(nullable string), `survey_district` (nullable string; the payload's survey district
under the same PII redaction and category visibility as the category tables, so null for a
viewer whose tables withhold it, and absent from older servers), `survey_state` (nullable string; same rule and
redaction, shown after the district as `Raisen, Madhya Pradesh`), and `is_demo_project` (boolean). Ordered category entries
include `icon_name` (nullable configured Font Awesome class) and `count`
(nonnegative integer, zero when missing). `attachment_count` is the
nonnegative count derived from the current payload by the shared HTMX helper. These carry the same display
meaning as the HTMX workspace. Clients tolerate their absence; allocation,
view authorization, masking and workflow semantics remain unchanged.

| Key | Content |
| --- | --- |
| `case` | `va_sid`, `instance_name` (the masked id), `form_type_code`, `project_mode` (`masked_simple`, `masked_doris`, `unmasked_simple`, `unmasked_doris`), `icd_classification` (`icd10` or `icd11`: the project setting `icd_coding_value.get_icd_classification_for_submission` reads, default `icd10`; the client calls the matching coding search, `GET /api/v1/icd10/2019-2/coding-search/<va_sid>?q=` or `GET /api/v1/icd11/coding-search/<va_sid>?q=`, and the other one answers 400), `workflow_state`, `narrative_qa_enabled`, `social_autopsy_enabled` |
| `categories`, `default_category` | ordered `[{code, label, nav_label, render_mode}]` the mode's role sees (the COD panel `vacodassessment` last), and the code to open first |
| `step` | `initial`, `final` or `done`. Coding: Step 1 while the caller has neither an active Step 1 nor a not-codeable review (an unmasked project has no Step 1, so `final`); `final` once Step 1 is saved; `done` after a not-codeable review with no Step 1. Reviewing: masked and no own Step 1 is `initial`, own Step 1 or an unmasked project is `final`, a saved reviewer final is `done` |
| `blocked_by` | codes that stop the final save: `narrative_qa` (coders; NQA enabled and not saved by the caller) and `social_autopsy` (the role's analysis required and not saved) |
| `assessments` | always these keys, null when absent. Coding: `initial` (the caller's own active Step 1: `id`, `immediate_cod`, `antecedent_cod`, `other_conditions` as a list, `created_at`), `initial_prefill` (what the Step 1 form opens with: the same row, or in a recode episode the caller's latest prior draft), `final` (the authoritative coder final: `id`, `conclusive_cod`, `immediate_cod`, `other_conditions`, `remark`, `created_at`; only once `step` is `final`, as the web's Step 2 form shows it, so a masked Step 1 stays blind to an earlier coder's result), `not_codeable` (`reason`, `other`, `created_at`; only the caller's own review). Reviewing: `coder_initial`, `final` and `not_codeable` as read-only reference (the web panel shows them to a reviewer; in an `unmasked_doris` project `final` also carries the coder's saved `doris_status` and `doris_code`, codes only, no reports), and the caller's own `reviewer_initial` and `reviewer_final` (another reviewer's final is neither shown nor makes `step` `done`). Another coder's Step 1 is never shown to a coder |
| `smartva` | the active SmartVA result read live (not from the section cache; it completes asynchronously): `age` (a whole number when integral, `"28"` not `"28.0"`), `gender`, `key_symptoms` (always three entries, primary to tertiary, `null` when empty), `causes` (`rank`, `cause`, `icd10`, `icd11` mapping, `likelihood`; all three ranks, `cause` null when empty), `symptoms`; null when none, and on a masked project until the caller has their own Step 1 (Step 1 is blind) |
| `smartva_status`, `smartva_can_run` | status-only `not_requested`, `queued`, `running`, `done` or `failed`, and whether the existing SmartVA action can run; `smartva_can_run` is false in view mode. Masked Step 1 can show status while `smartva` remains null. |
| `other_conditions_options` | the Step 1 other-conditions list of the age group (`coding`); null for `reviewing`, whose form takes free text |
| `doris` | null unless `case.project_mode` is `masked_doris` or `unmasked_doris`; else the DORIS editor's seed (`doris_context_service.workspace_doris`, the same logic the web partials use). Unmasked: `{initial_certificate, prefill_provenance}`, seeded from the reviewer's own final, else the authoritative coder final's certificate, else the interview prefill (`doris_prefill`; a saved certificate carries no prefill markers). Masked adds `saved_processing` (`{certificate, doris, codedit, final_choice}`: the caller's own active Step 1 reopened display-only, null without a result; no process token is minted by the read, so a changed Step 1 still needs `POST /api/v1/doris-clinical/process/<va_sid>`) and `step1_certificate` / `step1_processing` (`{doris, codedit}`: the own Step 1 a Step 2 confirms; null until there is one). A masked coder gets these keys at both steps (so Step 1 can be reopened after it is saved); `initial_certificate` is the own Step 1 certificate, else the interview prefill. A masked reviewer's `initial_certificate` is the reviewer's own Step 1, else the Step 1 behind the authoritative coder final, else the prefill. Masked Step 1 carries no SmartVA and never another coder's Step 1 or final. Every certificate has `AdministrativeData` removed for a viewer `should_redact_pii` redacts, and the prefill is skipped for one. The editor's other URLs are fixed: `/api/v1/doris-clinical/{process,terms,codeinfo,selection-check}/<va_sid>` |
| `narrative_qa` | null unless the project has Narrative QA on; else `{fields, max_score, saved}`. `fields` is `app/services/narrative_qa_service.NARRATIVE_QA_FIELDS`, the list the web form renders: `[{key, label, options: [{value, label}]}]` in question order, `key` being the save body key. `max_score` is 10. `saved` is null, or the caller's own answers on the current payload: `{cannot_grade, values: {key: int}, score, rating}` (`rating` `Good`, `Fair`, `Poor` or `Cannot Grade`); a cannot-grade save stores every value and the score as 0, returned as stored |
| `social_autopsy` | null unless the role's Social Autopsy switch is on (`social_autopsy_enabled` for `coding`, `reviewer_social_autopsy_enabled` for `reviewing`; on when the case has no project, as the save allows); else `{questions, saved}`. `questions` is `SOCIAL_AUTOPSY_ANALYSIS_QUESTIONS`: `[{delay_level, title, options: [{option_code, label, description}]}]`. `saved` is null, or the caller's own analysis on the current payload: `{selected_options: [{delay_level, option_code}] sorted by delay level then option code, remark}` |

The two forms save through the existing `POST /api/v1/va/<va_sid>/narrative-qa`
(body `{va_actiontype, cannot_grade, length, pos_symptoms, neg_symptoms,
chronology, doc_review, comorbidity}`) and `POST /api/v1/va/<va_sid>/social-autopsy`
(body `{va_actiontype, selected_options: [{delay_level, option_code}], remark}`);
errors are in the section above. Both decide coder or reviewer from the body's
`va_actiontype`: a reviewer must send `varesumereviewing` (or
`vastartreviewing`); anything else is taken as a coder save and checked
against a coding allocation. Social Autopsy `none` is exclusive within a delay
level: the server keeps only `none` for a level that has it, drops duplicates,
and every delay level must be answered.

`GET /<va_sid>/categories/<code>?mode=` returns `{code, label, render_mode,
summary_items, subcategories, blocked_by}`. `subcategories` is an ordered list
`[{code, label, source_category, render_mode, items: [{label, value, flip, info}]}]`, never a
label-keyed object (the JSON provider sorts keys); `flip` and `info` are the
mapping's flip and info labels the web badges use. The `workflow_panel`
category (`vacodassessment`) carries the narration and documents and the health
history subcategories the COD panel shows. `source_category` preserves their
configured source grouping; clients tolerate its absence. `blocked_by` is `narrative_qa` or
`social_autopsy` while that category's required form is unsaved. The data is
the section cache (below) with PII redaction. A category the mode's role does
not see is 404 `not_found`, like one that does not exist. Every category reply is
`Cache-Control: private, no-store` (PHI on a shared browser), stricter than the
web partial, which keeps `max-age=300` for data categories.

Attachment item values are `/api/v1/attachments/...` URLs (see Media below),
the same for every client and loadable with the cookie or a bearer.

Errors `{error, code}`: 400 `invalid_request`; 403 `forbidden` (wrong role for
the mode, or the case is outside the caller's scope) and `no_allocation`; 404
`not_found` (unknown case or category).

Section cache: Redis, 30 minutes, key
`form_data2:<sid>:<payload_version_id>:<role>:<category>` plus `:nopii` for a
viewer who must not see personal data. Only that redacted variant is stored
(PII slice 1a, policy OD6): a viewer allowed personal data gets a fresh render
that is never cached, and `flask pii flush-cache` drops every entry (the prefix was bumped from `form_data:`
when the attachment URLs moved to `/api/v1`, so cached cookie-only URLs are
not served). The role bucket (`coder`, `reviewer`,
`data_manager`, `viewer`) keeps roles mapped through different field mappings
from sharing an entry, and the payload version keeps an interviewer revision
from being served the old answers. `invalidate_section_data_cache` drops every
role and PII variant of the current version but has no production caller: the
payload version in the key is what stops stale answers after an interviewer
revision or another interview chosen, while edits to the field mapping or the
PII set still wait out the 30-minute TTL.

## Coding search (`GET /api/v1/icd10/2019-2/coding-search/<va_sid>?q=`, `GET /api/v1/icd11/coding-search/<va_sid>?q=`, `GET /api/v1/coding-search-demo/search?classification=&age_group=&sex=&q=`)

The default answer is a bare JSON list of selectable codes (the mobile client
reads it as is). With `explain=1` the answer is
`{"results": [...same list...], "excluded": {...}}`, and `excluded` is present
only when the age/sex policy removed matches *and* the selectable results do
not fill a page (30). `excluded` is `{"count": n, "examples": [{"code",
"title", "reason"}], "age_group", "sex", "message"}`: `count` is every
policy-excluded text match, `examples` at most 3, `reason` the code's own
restriction in the policy's labels (`neonate only`, `neonate or infant only`,
`infant only`, `child only`, `adult only`, `female only`, `male only`, joined
by a comma when both fail), and `message` a ready sentence
("1 code matches but is not selectable for an infant female: P95 (neonate
only)"). Excluded codes are explanation only, never offered. Admin-disabled
codes and vocabulary or typo-fallback matches are not reported. One extra
LIMITed query, only on `explain=1`. Code:
`app/services/coding_search_explain.py`, `policy_excluded_matches` in
`app/services/icd_coding_policy.py`. Used by the coding screen's "No results"
text and the help search demo. Tests: `tests/services/test_coding_search_excluded.py`.

## Media (`GET /api/v1/attachments/...`, `app/routes/api/attachments.py`)

The attachment URLs of the case content (digitva-xl43 phase 3a). A bearer opens
only `/api/v1/`, so the renderer (`_resolve_attachment_url`, the one producer)
emits these for every client, web pages included; the old `/vaform/attachment`
and `/vaform/media` cookie routes stay for pages rendered before the change.

| Route | Row |
| --- | --- |
| `GET /api/v1/attachments/<storage_name>` | token rows (an opaque `<32 hex>.<ext>` name) |
| `GET /api/v1/attachments/legacy/<va_form_id>/<va_filename>` | rows with no `storage_name` (the ODK filename names the object) |

Gate `coder`, `coding_tester`, `reviewer`, `data_manager`, `site_pi`,
`project_pi`, `collaborator`, `collaborator_pii`, `admin`; cookie or bearer.
The submission-level rule is `attachment_service`'s, shared with the old
routes (`authorize_token_attachment`, `authorize_legacy_attachment`): the VIEW
scope on the submission, never a plain viewer (attachments carry personal
data), evaluated on every request. URLs end in the original extension (the
templates sniff image or audio by it). Delivery is
`attachment_service.deliver` / `deliver_legacy_media` unchanged: the local
store sends the file with `Range` (206), the S3 store answers 302 to a
presigned URL, always `Cache-Control: private, no-store` and
`X-Content-Type-Options: nosniff`.

Errors `{error, code}`, also `private, no-store`: 400 `invalid_request`
(legacy route: malformed form id or filename), 401 `unauthorized`, 403
`forbidden`, 404 `not_found` (bad token, no row, no bytes), 502
`upstream_error` (ODK Central refused or returned a bad redirect), 503
`unavailable` (transient; `Retry-After`), 416 `range_not_satisfiable` (a
`Range` past the end).

Client notes. Native: `source={{uri, headers: {Authorization}}}`. Expo web on
the cookie loads the URL directly; a bearer-only web client fetches with the
header and uses a blob URL. Not verified on a device: a player that forwards
`Authorization` to the S3 presigned redirect is refused by S3 (digitva-p6fs.5).

## Private note (`GET|PUT /api/v1/va/<va_sid>/note?mode=coding|reviewing`, `app/routes/api/va_case.py`)

The caller's private note on a case (digitva-xl43 phase 3a), the row the web
`vausernote` partial edits (`app/services/user_note_service.py`: `get_active_note`,
`save_note`). Gate `coder`, `coding_tester` or `reviewer`; cookie or bearer. The
same allocation check as `workspace` (`_authorize_session`: mode, role, own
active coding or reviewing allocation) but no category is rendered. Own
allocation only; the web also allows a note on its view page, so widen this
when an API view mode lands. One note per user per case, shared by their
coding and reviewing sessions.

- `GET` answers `{va_sid, content, updated_at}` (both null when none),
  `Cache-Control: private, no-store`. Timestamps in this file's workspace and
  note bodies (`updated_at`, the assessments' `created_at`) are ISO 8601 UTC
  with an explicit `+00:00` offset.
- `PUT {"content": text}` upserts and answers as `GET`. 400 `invalid_request`
  for a body that is not an object with text `content`, or empty or
  whitespace-only content or content holding a NUL character; 413 `payload_too_large` over
  64 KB by `Content-Length`, or with no `Content-Length` at all (a chunked body
  is refused, never buffered; keyed by path, before any lookup); 422 `invalid_request` over 20,000
  characters. Errors as `workspace`.

Concurrent first saves can insert two rows (no unique constraint; the web has
the same limit); reads take the latest by `note_updated_at`. Upgrade: a partial
unique index on `(note_by, note_vasubmission)` where active.

## Users (`/api/v1/users`, `app/routes/api/users.py`, `user_directory_service`)

`digitva-75wn`; the web app's Users page (`/users`). Browser session only
(a bearer token: 403 `cookie_session_required`). Gate `admin`, `project_pi`
or `data_manager` (the In-charge passes as data_manager); others 403.
Scope is `authz.user_list_filter` (access-control-model.md, "Users page"):
an admin every account, a project PI the holders of an active grant in their
projects, a data manager the holders of an active grant in their subtree.
`Cache-Control: no-store` on every reply.

- `GET /users?q=&project=&unit=&role=&status=&enrolment=&limit=&offset=`
  (120/min). `q` contains-match on name, email, phone or mobile (wildcards
  literal, max 64); `unit` a unit id (its subtree; unit grants only);
  `role` an access role; `status` `all` (default) | `active` | `inactive`;
  `enrolment` `enrolled` | `revoked` | `none`; `limit` 1..100 (default 50),
  `offset`. Bad value: 400 `invalid_request`. Ordered by name. Reply
  `{users, total, limit, offset, options?}`; each user `{user_id, name,
  email, phone, active, last_signed_in_at, grants, enrolment}`: `grants` are
  the in-scope active grants on active projects `{role, scope, project_id,
  project_name, site_id, site_name, org_unit_id, unit_name, level_name}`;
  `enrolment` `{status: enrolled|revoked|none, devices, revoked_devices,
  last_seen_at}` from the user's device sessions (enrolled: a session that
  is not revoked or expired on a device not revoked; revoked: sessions, none
  live). `options` (first page only) `{projects: [{project_id,
  project_name}], units: [{org_unit_id, unit_name, level_name, depth}]}`:
  the viewer's projects (all active ones for an admin, max 200) and, for the
  chosen `project`, the units they reach (max 500, path order). Three
  queries a page (users with a count, their grants, their sessions grouped
  per user) plus the options; the scope EXISTS is served by
  `ix_va_user_access_grants_user_status`, the unit subtree by
  `ix_mas_org_unit_path`, sessions by `ix_auth_device_sessions_user_id`.
- `GET /users/<user_id>/activity` (120/min): `/me/activity`'s body for that
  user, limited to the viewer's projects (an admin: all), plus `user_id`,
  `name`, `last_signed_in_at`, `last_device_seen_at`, `last_active_at` (the
  later of the two). Out of scope, unknown or malformed id: 404 `not_found`.
- `POST /users/<user_id>/enrolment-code` (10/min, CSRF): body `project_id`,
  `delivery` `show` (default) | `email`, and for show the Devices page's
  optional `expires_in_minutes` (5..10080, default 60) and `max_uses`
  (default 1). The user must be active (400 `user_inactive`) and hold an
  active `interviewer`, `death_reporter`, `coder`, `coding_tester` or
  `reviewer` grant in that project inside the viewer's scope (400
  `no_device_role`); out of scope 404. Show: 201 `{code, qr_payload,
  qr_png (base64 PNG), project_id, expires_at, max_uses}`, the code shown
  once and never logged. Email: 201 `{emailed: true}` (the enrolment
  email's 24-hour code); no email 400 `no_email`, a failed send 502
  `email_failed`. Both audit `device_enrolment_code_created` with the
  issued-for user (mobile-sign-in.md section 6).

### Users page admin tools (digitva-cgmc, `user_admin_tools_service`)

Admin only (`role_required("admin")` and the service: anyone else 403
`forbidden`); browser session, CSRF on POST, `Cache-Control: no-store`.
Policy: access-control-model.md ("Users page admin tools"),
account-onboarding-and-passwords.md ("Admin account upload and invite on
first grant").

- `POST /users/import/preview` (10/min): body `{filename, content}`,
  `filename` ending `.csv` or `.xlsx`, `content` the file in base64 (over 1 MB
  decoded: 413 `payload_too_large`). Headers exactly `name,email,phone`,
  at most 1000 rows (`tabular_import_service.parse_table`, the project user
  import's bounds). Reply `{rows, counts}`: each row `{row, name, email,
  phone (masked), status: new|exists|invalid, reason, phone_clash}`;
  `counts {new, exists, invalid}`. Writes nothing.
- `POST /users/import/apply` (10/min): the same body; re-classifies the file
  and creates only `new` rows. 201 `{rows, counts, created}`. A race on an
  email or number: 409 `conflict`, nothing created. No email is sent. Audits
  `account_upload_applied` `{created, rows}` and `account_created` per account.
- `GET /users/grid?project=&from=&to=&q=&role=&status=&limit=&offset=`
  (120/min). `project` required (unknown or inactive: 404); `from`/`to`
  `YYYY-MM-DD` on `user_created_at` read as the admin's local days; `q` name
  or email contains; `role` holds that role in the project; `limit` 1..100.
  Every account (grantless ones included), newest created first
  (`ix_va_users_user_created_at`). Reply `{users, total, limit, offset,
  options?}`; each user `{user_id, name, email, phone, active, created_at,
  grants, enrolment}`, `grants` the active grants in that project with a
  `unit` key (`project`, `site:<site_id>` or `unit:<org_unit_id>`).
  `options` (first page) `{mode: organization|sites, units: [{key, label,
  depth}], cadres: [{cadre_id, cadre_code, cadre_name}]}`. Three queries a
  page (users with a count, grants, sessions) plus the options.
- `POST /users/<user_id>/grants` (60/min): body `{project_id, unit, roles,
  cadre_id?, name?, phone?, active?}`; `roles` a subset of `death_reporter`,
  `interviewer`, `interview_supervisor`, `coder`, `reviewer`, `data_manager`.
  Sets those six roles at that unit to exactly `roles`: added grants are
  created or reactivated through the admin panel's
  `_resolve_scope_from_payload`, removed ones soft revoked; other units are
  untouched. A refused role: 400 `grant_refused` naming each role and
  reason, nothing written. Phone in use: 400; self-deactivation: 400.
  Reply `{user, changes, invited, enrolment_email, warnings}`; on the
  account's first active grant the invitation (and, for death_reporter or
  interviewer, the enrolment email) is sent once, `other.first_grant_invited_at`
  recording it; mail failures are `warnings`.

## People and roles (`GET /api/v1/projects/<project_id>/people-roles` and `.csv`, `app/routes/api/people_roles.py`)

Read-only; `app/services/people_roles_service.py`; policy
`docs/policy/people-and-roles-page.md` (bead digitva-nk1). Cookie or bearer
session; any user with a live grant in the project (an admin always). A project
the caller holds no grant in, or a closed one, is 404 `not_found` whether it
exists or not; the refusal comes before the parameters are read. Query (all
optional): `level` (level code), `unit` (unit id, must be in the caller's
audience, else 404), `cadre` (cadre code), `capability` (a column key),
`status` (`active` default, `deactivated`, `all`; only the identity tier gets
deactivated grants, others are clamped to active), `q` (name, job title and,
for the identity tier, email; 64 characters), `mode` (`granted_here` default |
`can_act_here`, only with `unit`), `limit` (default 200, clamped 1..500),
`offset`. A bad value is 400 `invalid_request`. `no-store`. `units` and
`cadres` (below) are in the body only when `offset` is 0, so a later page does
not repeat them; the CSV never carries them.

```json
{"project_id": "CSC001",
 "viewer": {"identity": true, "names": "full|initials", "audit": "all|scoped|none"},
 "filters": {"level": null, "unit": null, "cadre": null, "capability": null,
             "status": "active", "q": null, "mode": "granted_here"},
 "dormant_days": 90, "total": 41, "limit": 200, "offset": 0, "truncated": false,
 "columns": [{"key": "code", "label": "Code", "people": 5, "hollow": 2}],
 "rows": [{
   "row_id": "<user>|unit|<unit id>|<cadre id>",
   "person": {"user_id": "<uuid>", "name": "Priya Rao | P. R.", "initials_only": false,
              "email": "<identity tier only, else null>", "job_title": "..|null",
              "active": true, "sees_pii": true},
   "cadre": {"cadre_id": "<uuid>", "code": "MO", "name": "Medical Officer"},
   "location": {"kind": "unit", "org_unit_id": "<uuid>", "unit_code": "P01",
                "unit_name": "PHC One", "level_code": "phc", "level_name": "PHC-AAM",
                "depth": 4, "path": "D01.C01.P01", "active": true},
   "covered_below": 0,
   "grants": [{"role": "coder", "status": "active|deactive"}],
   "cells": {"code": {"state": "granted", "roles": ["coder"]}},
   "audit": {"granted_at": "<iso>|null", "granted_by": "<name>|null",
             "last_sign_in_at": "<iso>|null",
             "flags": ["exceeds_grid"],
             "grants": [{"role": "coder", "status": "active", "granted_at": "<iso>",
                         "granted_by": "<name>|null"}]}}],
 "cadres": [{"cadre_id": "<uuid>", "code": "MO", "name": "Medical Officer"}],
 "units": {"levels": [{"level_code": "phc", "level_name": "PHC-AAM", "depth": 4}],
           "units": [{"org_unit_id": "<uuid>", "unit_code": "P01", "unit_name": "PHC One",
                      "level_code": "phc", "depth": 4, "parent_org_unit_id": "<uuid>|null",
                      "path": "D01.C01.P01", "is_active": true}]}}
```

`cadres` is every distinct cadre among the caller's audience rows (status and
visibility applied, before the level, cadre, capability, `q` and mode filters),
sorted by name, so the cadre filter does not depend on the page. One row per
person x location x cadre. `location.kind`: `unit`, `site` (a
`project_site` grant: `project_site_id`, `site_id`, `site_name`, `active`),
`project` (whole project, visible to every caller; a `site` row only to
whole-project callers and to a caller with a grant at that same site) or `platform` (a global admin, identity tier only);
only `unit` carries `covered_below` (active units strictly below, counting only units in the caller's audience) and gets
red cells. `cells` has one entry per `columns` key, in the one mapping
`CAPABILITY_ROLES` (Report deaths, Interview, Supervise, Code, Review, Test
code, Manage data, View PII, Read-only, Site lead, Manage grants). Site lead is a
`site_pi` grant at site scope only (an In-charge, `site_pi` at a unit, gets
Supervise, Manage data and Manage grants instead). View PII is per person and
**in this project**. `state`: `granted`
(green; an active grant on an active user and unit), `hollow` (red; the
cadre's grid flag *Fill VA* / *Code VA* / *Supervise interviews* allows it at
the level but nothing gives it), `view_only` (a coder grant above the coding
scope level), `inactive` (grey; the grant, user or unit is deactivated) or
`blank`; `roles` names the row's roles that give the cell. `audit` is null
unless the caller is an admin, project PI or project-scope data manager (every
row) or holds a data-manager-shaped grant (rows inside its subtree). Flags:
`exceeds_grid`, `no_cadre`, `inactive_user`, `inactive_unit` (also a
deactivated site), `no_active_grant` (only under `status=deactivated|all`),
`dormant` (no sign-in for 90 days; a null `last_sign_in_at` is "not recorded",
never dormant). `units` is the caller's audience (their units, the units above
them, and below for a wide grant) for cascading pickers; deactivated units only
for the identity tier. At most 10000 grant rows are read; past that
`truncated` is true (the CSV then carries the header `X-Truncated: true`). The
`no_active_grant` flag reads the project's active grants with its own query, so
the cap cannot make it wrong. Cost: 13 queries for any number of people (grants,
units, levels, grid, project, PII set, authz resolution).

`GET .../people-roles.csv` takes the same query (no `limit`/`offset`) through
the same service and redaction, so its rows are the JSON `total` rows in the
same order: one header row (person, email, job_title, person_status, cadre,
location, level, path, units_below, one column per capability, and for any
audit tier granted_at, granted_by, last_sign_in_at, flags), cells as the state
word or empty, text cells starting with `=`, `+`, `-` or `@` prefixed with `'`.
Rate limit 20 per minute (JSON 120). Tests: `tests/test_people_roles.py`.

## Identifier types (`/api/v1/projects/<project_id>/identifier-types`, `app/routes/api/identifier_types.py`; `GET /api/v1/intake/identifier-types`)

Which registration numbers a project collects and how each is validated
(policy [Death Registration Identifiers](../policy/death-registration-identifiers.md),
digitva-kzyp stage 1). Values are written at registration and correction and read in the case replies and lists (stage 2, "Registration numbers" in the intake table); the any-time write endpoint is `PUT /intake/cases/<id>/identifiers` (stage 3, "Registration numbers" above).

- `GET|POST /api/v1/projects/<project_id>/identifier-types` and
  `PUT .../identifier-types/<type_id>`. Browser session only (a device bearer is
  403 `cookie_session_required`); `role_required("admin", "project_pi",
  "data_manager")`, then per project in `identifier_type_service.configuring_role`:
  admin, a live `project_pi` grant on that project, or a `data_manager` grant
  scoped to the WHOLE project (owner, 2026-10-21: a site- or unit-scoped data
  manager is 403). A
  project the caller holds no grant in (or an unknown one) is 404; a grant
  without one of those roles is 403. State changes need `X-CSRFToken`; rate
  limits 120/min read, 30/min write; bodies capped at 8 KB; no DELETE (405):
  deactivate with `is_active: false`.
- Body fields: `code` (`^[a-z][a-z0-9_]{1,31}$`, immutable once values exist,
  else 409 `code_locked`), `label`, `min_length`, `max_length` (1..64),
  `char_type`, `pattern`, `example`, `required_at_report`, `uniqueness_scope`
  (`none`/`project`), `sort_order`, `is_active`. An unknown key is 400. An update
  is merged over the stored type and the whole result checked: length range,
  `char_type`, the pattern's safe subset, and the capitalised `example` against
  every rule; any failure is 400 `invalid_request` with a message that names the
  rule. A duplicate code in the project is 409 `duplicate_code`.
- Replies: `GET` `{"project_id", "identifier_types": [...]}` (all types, active
  or not, at most 200); `POST` 201 and `PUT` 200 `{"identifier_type": {...}}`.
- Each create and update writes one `map_identifier_audit` row (`type_created` /
  `type_updated`, the actor's grant role, changed fields `{old, new}`). A `PUT`
  that changes nothing writes no audit row and returns the type as stored.
  The pattern's safe subset also caps variable-length parts at 3 and refuses
  neighbouring ones that can match the same character, and the pattern must
  also compile in `google-re2`, which does the matching (policy "Pattern
  safety"); a non-text `char_type` is 400 like any unknown value.
- `GET /api/v1/intake/identifier-types?project_id=`: the ACTIVE types
  (`code, label, min_length, max_length, char_type, pattern, example,
  required_at_report, sort_order`, by `sort_order`) for a project where the
  caller may register a death (`register_death_context`) or supervise
  (interview_supervisor, data_manager, In-charge, project_pi on a tree project),
  and for an admin in any project (200, an unknown project lists none).
  Either credential for a registering caller; otherwise 403 `project_forbidden`,
  alike whether the project exists; missing `project_id` 400. Not part of
  `/me/access` (the device caches it for offline registration).
- Client notes (Expo, `mobile/digitva-collect/src/identifiers.ts`): `getIdentifierTypes`
  and `loadIdentifierTypes` (in-memory cache per project, a failure yields no section),
  `putCaseIdentifiers(link, deathId, identifiers, ifUpdatedAt, csrf)` for
  `PUT /intake/cases/<death_id>/identifiers` (X-CSRFToken from the shared requester). The
  client treats an absent `can_edit_identifiers` on a row or detail as false and shows
  "Add registration number" only when it is true. Server refusals are read from
  `fields: ["identifiers.<code>"]` and `error`; `warnings` of kind `identifier_in_use` are shown
  inline with Continue and Edit.

## Respondent consent (`GET /api/v1/intake/consent-config`, `/api/v1/projects/<project_id>/consent-settings|consent-notices`; `app/services/consent_service.py`)

Contract: [Offline API Contract](../policy/offline-api-contract.md) section 5
(digitva-gb8w.3). A project without consent settings, or with
`consent_required` false, behaves exactly as before: the gate is off.

- `GET /api/v1/intake/consent-config?project_id=`: the 5.2 reply
  `{project_id, consent_required, notice_versions, contacts, retention,
  refusal_behaviour}`, every key always present. `notice_versions` lists the
  non-retired versions only when consent is required (else `[]`); each is
  `{notice_version_id, version (int), language, text, text_sha256, purposes
  [{code, label, required}], covered_fields, allowed_modes, witness_allowed}`.
  Not configured: `contacts` with empty strings, `dpo: null`, `districts: {}`;
  `retention: {period_days: null, expiry_action: "erase"}`. Who and errors as
  `GET /intake/identifier-types` (400 `invalid_request` without `project_id`,
  403 `project_forbidden`); either credential; `no-store`; 120/min.
- `consent` on `POST /intake/deaths` and `PATCH /intake/deaths/<id>`
  (`client_draft_id: null`), `POST /intake/submissions` (`client_draft_id`
  equal to the body's) and `POST /intake/submissions/<va_sid>/revisions`
  (equal to the submission's own `client_draft_id`, null for a browser
  interview): the 5.3
  object, validated against the stored notice version (the project's own, not
  retired, language, `notice_sha256` equal to the stored text's hash, exactly
  its purposes, `decision` granted exactly when every required purpose is,
  an allowed `mode`, `witness_present` only where allowed, `supersedes_client_id`
  a consent of the same case, `recorded_at` with an offset; no other key) and
  stored in the request's transaction (registration: case row, then consent).
  Validated whenever sent, also in a project that does not require consent.
  Refusals, body `{error, code, fields: ["consent"]}`: 422 `consent_invalid`;
  422 `consent_required` (consent required, a covered field filled, no granted
  consent sent or on file: the attempt's own, else the case's registration
  consent); 422 `consent_conflict` (a refused consent with a covered field
  filled); 409 `conflict` (a `client_id` already used for other content; the
  same content is a duplicate and stores nothing); 422 `consent_invalid` with
  `fields` naming the covered fields (names only) that are filled but not in
  the granted consent's notice version `covered_fields` (a v1 consent does
  not cover a field only v2 adds). One gate (`consent_service.gate`) serves
  every write of covered data: the register fields a `POST` or `PATCH`
  `/intake/deaths` sets (the registration consent sent or on file), the
  answers of an upload, a revision and `POST /intake/drafts/<id>/submit`, as
  received, before prefill (the attempt's own consent, else the case's
  registration consent; another attempt's never applies). The browser submit
  carries no consent: the interview page records one first on
  `POST /intake/drafts/<id>/consent` (below); covered answers with none on
  file are 422 `consent_required`. Draft autosave (`PATCH /intake/drafts/<id>`,
  `/drafts/sync`) is not gated. A same-hash upload resend returns the first
  result unchecked.
- `GET|PUT /api/v1/projects/<project_id>/consent-settings` and
  `POST .../consent-notices`: admin, project PI or project-scoped data manager
  (the identifier-type rule: 404 unknown project or no grant, 403 other
  role); browser session only, `X-CSRFToken` on writes, `no-store`; 30/min
  for writes. `PUT` takes any of `consent_required` (true needs a current
  notice version, else 400), `contacts` (the 5.2 object, each value text up to
  200 characters, `districts` keyed by org unit UUID), `retention`
  (`{period_days 1..36500 or null, expiry_action erase|lock}`),
  `refusal_behaviour`; unknown keys 400. `POST` adds a version: `language`
  (BCP 47), `text` (stored and hashed exactly as sent, up to 20,000
  characters), `purposes` `[{code, label, required}]`, `allowed_modes`,
  optional `version` (default highest plus one; a translation passes its
  number), `covered_fields` (default the seven informant register fields,
  `Id10007` and the WHO answers the register prefills with address or family
  data: `Id10055`, `Id10057`, `Id10061`, `Id10062`; `Id10055`/`Id10057` are
  prefilled from the org path even without a registered address),
  `witness_allowed` (default true); `text` with a NUL or an unpaired
  surrogate is 400 `fields: ["text"]`; 201 `{notice_version}`; 409
  `conflict` when that version and language exist. The config and settings
  replies list at most 200 versions, the newest. Two concurrent first `PUT`s
  of a project's settings both apply (the later over the earlier), no 500. Versions are never edited.
  Each write adds a `map_consent_audit` row. The configuring reply
  (`GET|PUT .../consent-settings`) also gives each version `created_at`,
  `retired_at` and `approved_at` (null: pending legal review); the 5.2
  config shape does not carry `approved_at`. Screen: Project Setup, Data
  collection, "Respondent consent" (`admin/panels/consent_settings.html`).
  Dev seeding: `flask web-intake seed-consent-notice <project>
  --actor <admin email> [--language en] [--require]`.
- `POST /api/v1/projects/<project_id>/consent-notices/seed` (same roles,
  10/min): version 1 in `en` and `hi` from the policy draft
  (`app/services/consent_notice_seed.py`, kept equal to
  docs/policy/respondent-consent-notice-draft.md by a test), `[PROJECT NAME]`
  filled in; 201 `{notice_versions}`; 409 `conflict` when the project has any
  version. `POST .../consent-notices/<notice_version_id>/approve`: admin only
  (403 otherwise), sets `approved_at`/`approved_by` once (a repeat changes
  nothing), audit `consent_notice_approved`; 404 `not_found` for another
  project's or an unknown id; replies the configuring view.
- `GET|POST /api/v1/intake/drafts/<draft_id>/consent`
  (`app/routes/api/intake_consent.py`): interviewer, the draft's owner only
  (404 otherwise), browser session only, `X-CSRFToken` on `POST`. `GET`
  `{consent_required, decision (granted|refused|withdrawn|null),
  covered_fields (the decision's version), client_draft_id}`: the decision on
  file for the draft's case (the attempt's own, else the registration
  consent). `POST {consent}` (the 5.3 object, `client_draft_id` equal to the
  draft's, null for a browser draft) stores it through `record_consent`
  (channel `web`) on an open draft (409 otherwise); 201 with the `GET` shape;
  refusals as above. The web interview page shows the notice and records the
  decision here before it opens the form when the project requires consent
  and nothing is on file.

## Offline station onboarding and station config (`app/routes/api/station_config.py`; `app/services/station_config_service.py`)

Beads digitva-gb8w.4 and digitva-gb8w.8; contract
[Offline API Contract](../policy/offline-api-contract.md) 3.8 and 4.1; file
format [bundle spec](../policy/offline-bundle-and-transfer.md) 6.4.

- Browser routes: admin, project PI or project-scoped data manager of the
  station's project (the identifier-type rule: 404 unknown project, no grant
  there, or a device of another project; 403 other role); browser session only
  (a bearer: 403); `X-CSRFToken` on writes; `no-store`; 64 KB bodies.
  - `GET /api/v1/projects/<project_id>/stations/<device_id>`: `{device_id,
    designations, custodian | null, roster: [{user_id (UUID), user_number,
    name, designation, roles, active}], config: {config_id, issued_at,
    expires_at, text_sha256} | null}`. 120/min.
  - `PUT .../stations/<device_id>/custodian`: `{name, designation, phone,
    email, onboarded_on}`; `designation` a code of `designations`; `phone`
    normalised to 10 digits (`app/utils/phone.py`) or null, `email` or null,
    at least one; `onboarded_on` `YYYY-MM-DD`, not in the future. The caller
    is recorded as the verifier. 400 `invalid_request` with `fields`. Audit
    `station_custodian_set` (changed field names only). 30/min.
  - `PUT .../stations/<device_id>/roster`: `{"members": [{user_id (UUID),
    designation, roles: [{role, site_id, org_unit_id | null}], active}]}`
    replaces the roster (at most 50 members, 10 roles each). `role` one of
    `death_reporter`, `interviewer`, `coder` (that server grant) or
    `station_supervisor` (a supervising grant: `interview_supervisor`,
    `data_manager` or `site_pi`, owner decision 10), at the site of the
    station's project; a null unit needs a project- or site-wide grant. An
    active member needs a role and an active account. Every member's role
    sites must be active sites of the project and its units units of the
    project's tree (422 `invalid_roster`, `fields:
    ["members[i].roles[j].site_id" | ".org_unit_id"]`); an inactive member's
    roles are not grant-checked, but the user must hold some live grant in
    the project or already be on this station's roster (422 `invalid_roster`,
    `fields: ["members[i].user_id"]`). 400 `invalid_request` with `fields`; 422
    `invalid_roster` with `fields: ["members[i].roles[j]"]` when an active
    member's grant is missing. Audit `station_roster_set` (user ids added, removed, changed). 30/min.
  - `POST /api/v1/projects/<project_id>/station-config?device_id=`: build,
    sign and store a new config (201, the station view). 409
    `station_not_onboarded` (no signing key, no custodian, or no active roster
    member), 409 `device_revoked`, 422 `invalid_roster` (a grant has gone since
    the roster was set; `fields` lists those members' user ids, UUIDs), 409
    `notice_not_nfc` (a consent notice text that is not NFC would fail the
    station's hash check), 409 `config_not_canonical` (a stored value with no
    canonical JSON form), 503 `station_config_unavailable` (no signing key on
    the server, the published test key outside tests, or no
    `DEVICE_PUBLIC_URL`). Audit
    `station_config_issued` (config id, member count, file hash). 30/min.
  - `GET /api/v1/projects/<project_id>/station-config?device_id=`: the config
    in force (the newest issued) as a download,
    `application/vnd.digitva.station-config`, strong `ETag`; 404 `not_found`
    when none is issued. 60/min.
- `GET /api/v1/intake/station-config`: the station's own device bearer (the
  device comes from the session); the same bytes and `ETag` as the download,
  304 on `If-None-Match`; `no-store`; 60/hour per device. 404 `not_found`
  when no config is issued (issued = a custodian and an active roster member
  were set and `POST` was called); 403 `device_session_required` for a cookie;
  a revoked device's bearer is 401 (the revoke ends its sessions), and the
  service answers 403 `device_revoked`.
- The file is two LF-terminated lines: RFC 8785 canonical JSON with NFC
  strings (`canonical_json`), then `{"alg":"ed25519","sig","signing_key_id"}`
  over `b"digitva-station-config-v1\x00" || line1`, signed with
  `BUNDLE_SERVER_SIGNING_KEY_FILE`. Payload keys: `station_config_format_version`
  (1), `config_id`, `issued_at`, `expires_at` (`STATION_CONFIG_VALID_DAYS`,
  180), `device_id`, `server_url` (`DEVICE_PUBLIC_URL`), `kem_public_key`
  `{key_id, public}`, `server_signing_key` `{signing_key_id, public}`,
  `projects: [{project_id, sites, site_names, org_units, org_unit_paths,
  org_unit_sites, identifier_types, consent, sealed_field_ids, coding_mode,
  form_options, translations}]` (the
  station's project; `sites` and `org_units` are those the roster's roles
  name; `site_names` `{site_id: name}`; `org_unit_paths` `{org_unit_id:
  "District, Block, PHC"}`, active unit names from the top of the project
  tree down, ", " joined; `org_unit_sites` `{org_unit_id: site_id}`, the site
  of the role naming the unit (the server has no site per unit: a site grant
  reaches the whole tree); `consent` is exactly
  `GET /intake/consent-config`; `sealed_field_ids` the union over the
  project's active forms' form types; `coding_mode` the station mode locked to
  the project's coding mode, `icd11_doris` for unmasked DORIS, `icd10` for
  unmasked simple, `null` for a masked project, which the station does not
  code: bundle spec 2.4 Q5), `custodian` (`verified_by_user_id` is
  the verifier's `user_number`), `designations`, `roster` (`user_id` is
  `va_users.user_number`, sorted), `purge` (always `[]` until consent
  withdrawal exists, digitva-athy). Conformance fixture:
  `tests/fixtures/station_config/`, checked by
  `tests/test_station_config_fixture.py` and
  `desktop/crates/digitva-bundle/tests/station_config_fixture.rs`.
- Project Setup, Devices card (admin): "Station config" on a station with a
  signing key shows the custodian, roster and config in force, issues a new
  config and links the download. Custodian and roster are set through the API.

## Offline bundle ingest (`app/routes/api/bundles.py`; `app/services/bundle_ingest_service.py`)

Bead digitva-gb8w.2; [bundle spec](../policy/offline-bundle-and-transfer.md)
2-5; contract [Offline API Contract](../policy/offline-api-contract.md) 4,
4.1, 4.2, 7, 8.

- Callers: the station's own device bearer (its device must be the
  manifest's `device_id`, else 403 `forbidden`), or a browser session of an
  admin, or a data manager or interview supervisor with a grant in the
  bundle's project (`X-CSRFToken` on POST; else 403 `forbidden`). Every reply
  is `no-store`; errors `{error, code}`.
- `POST /api/v1/intake/bundles`: body the raw `.dvb` file,
  `Content-Type: application/vnd.digitva.bundle` (else 415), a declared
  `Content-Length` of at most 50 MiB (413 `payload_too_large` before
  reading; none is 413 too). 201 with the report; 200 with the stored report
  for a re-upload of the same bundle. 10/hour per uploader (station or
  browser user) and 10 stored ingests/hour per station (429 `rate_limited`).
- `POST /api/v1/intake/bundles/validate`: the same checks and every service
  call inside a transaction that is rolled back; stores nothing (no ingest
  row, no record, no security event beyond a refusal's). 200, `status:
  validated`, records `not_processed` or `rejected` with the code they would
  get. 10/hour per uploader.
- Whole-bundle refusals (nothing written; one `auth_security_events`
  `bundle_refused` row with the code and claimed ids): 413
  `payload_too_large` (file, manifest or record line over its limit, over
  5,000 records); 422 `manifest_invalid` (not LF lines, not canonical JSON,
  missing or unknown keys, a malformed field, `record_counts` not the
  records), `bundle_version_unsupported`, `device_unknown`,
  `signing_key_unknown` (looked up by `(device_id, signing_key_id)`),
  `signature_invalid`, `body_hash_invalid`, `station_not_onboarded` (no
  custodian, or the manifest's `station_config_id` not issued to this
  device: the unprovisioned sandbox), `bundle_too_old`
  (`BUNDLE_MAX_AGE_DAYS`, 90), `bundle_from_future` (over a day ahead of the
  server), `bundle_key_unknown`; 403 `device_revoked` (compromised, or a
  `created_at` not before `revoked_at`; the earlier of `created_at` and the
  receipt time is compared), 403 `forbidden` (the manifest's `project_ids`
  is not exactly the station's project, or the uploader may not upload);
  409 `bundle_id_reused` (a stored `bundle_id` with other manifest bytes),
  409 `conflict` (another request holds that bundle's ingest lock); 503
  `station_config_unavailable` (no server signing key for the receipt).
  Only the manifest and signature lines are parsed before the uploader
  check; record lines only after the signature, body hash, replay and age.
- A real ingest holds a session advisory lock on its `bundle_id` (its own
  connection) and commits before releasing it. An ingest left `processing`
  (worker killed midway) is resumed by a resend: records it already applied
  come back `duplicate` (idempotent by client id), and it ends with a report
  and receipt. One request applies every record; there is no partial report.
- Records are decrypted in memory one at a time and applied by type in the
  spec order (`death_registration`, `consent`, `death_correction`,
  `interview_submission`, `identifiers_set`, `coding_result`), each in its
  own savepoint, through the HTTPS services under the device projection of
  the actor's grants. Outcomes `accepted`, `duplicate`, `superseded`,
  `pending` (`coding_result` on a case still at SmartVA or attachments, code
  `not_ready`, or whose coder holds another case, `allocation_exists`: held in `va_bundle_pending_coding` and applied by the Celery
  applier once the case leaves those states; a resend while held is
  `pending` again), `rejected`. A coding result needs a station registered
  and active for the project (`offline_coding_disabled` when it was revoked
  after making the bundle; `self_coding_enabled` is not required), an actor
  with the `coder` role on the bundle's signed roster for the case's site,
  still backed by a server grant (`actor_not_station_coder`; an acting role
  other than `coder` is `forbidden`), an interview that same station
  uploaded (`not_available` otherwise), its `coding_mode` matching the project's
  coding mode (`icd11_doris` an unmasked DORIS project, `icd10` an unmasked
  simple one, or a masked simple one with `initial`; else
  `coding_mode_mismatch`; an unknown mode `coding_mode_unsupported`; no mode
  at all masked simple only, the v1 rule) and the coded version
  (`coded_version_superseded`); the station and mode checks run again when a
  held result is applied; it is saved through the online coder save
  in the project's mode, with its codes. An `icd11_doris` final is always
  held (`pending`, `doris_pending`): the applier reprocesses the station's
  certificate with the pinned WHO engines and saves the server's results
  (bundle spec 2.4 Q5).
  Actor: an active roster member of the named config with the acting role
  for that record type, project, site and unit, still holding the server
  grant behind it, and, on an online-enrolled station, with a device session
  on it opened at or before `created_at` (else `actor_unknown_on_device`;
  role or grant: `forbidden`). `attachment_chunk` is rejected
  `attachments_incomplete` (not built). Corrections run the station roster
  path of `update_death` / `put_identifiers` and add a `station_correction`
  case audit row (`authorized_by: station_roster`, acting role, device,
  config, bundle and client ids, custodian, reason); every other newly
  applied registration, consent, interview or coding result adds a
  `station_record` row with the same ids and no reason or values (none for a
  `duplicate`). An interview's actor is checked against its case's site and
  unit; a record naming another site, or a unit that is not the case's, is
  `forbidden`. A registration whose `client_death_id` a bundle applied
  before is `duplicate` with the same bytes, `conflict` with others (one
  registered over HTTPS has no stored hash: same registrant, `duplicate`).
  A string holding NUL or a lone surrogate (also inside `answers_json`), or
  any unexpected failure of a record, is `record_invalid`; the log line
  names only the exception class.
- Report: `{bundle_id, device_id, kem_key_id, status, counts, missing_seq,
  records: [{client_id, record_type, outcome, code, received_sha256,
  death_id, unique_id, fields?}], purge}`; ids, codes, hashes and field
  names only, never a value. `fields` names at most 5, each cut to 64
  characters.
- A dry run (`/validate`) queues no SmartVA run and sets no SmartVA marker,
  and its report carries no `death_id` or `unique_id` (the rows are rolled
  back). It may still consume death-number sequence values (`nextval` is not
  transactional), leaving gaps as any rolled-back registration does.
- `GET /api/v1/intake/bundles/<bundle_id>`: the stored report; a held coding
  result's entry moves from `pending` to its final outcome (`accepted`, or
  `rejected` with its code) and `counts` follow, in every report that named
  it; `GET .../receipt`: the signed receipt (signed afresh from the current
  report, not stored, once an entry has changed), `application/vnd.digitva.receipt`,
  line 1 the report as canonical JSON, line 2 `{alg, sig, signing_key_id}`
  over `b"digitva-receipt-v1\x00" || line1` with
  `BUNDLE_SERVER_SIGNING_KEY_FILE`. For the station's bearer or a browser
  uploader of the project; 404 otherwise. 120/min. Fixtures:
  `tests/fixtures/bundles/` (`tests/test_bundle_fixture.py`,
  `desktop/crates/digitva-bundle/tests/bundle_fixture.rs`).

## Translation suggestions (`/api/v1/translations`, `app/routes/api/translation_suggestions.py`)

Questionnaire translations for grant holders (digitva-5op; policy
`docs/policy/va-form-project-configuration.md`, "District review and
suggestions"). Cookie session, CSRF on POST, `{error, code}` errors; authz is
decided before any parameter is read.

| Route | |
|---|---|
| `GET /translations/<project_id>` | `{project_id, instrument_code, can_decide, locales: [{code, label}]}`: the project's served locales only, never `en` or a draft locale. 404 without a grant in the project. |
| `GET /translations/<project_id>/<locale>/questions?q&page&page_size` | The questions in form order with English and the served translation (`page_size` at most 50); machine drafts are blank. |
| `POST /translations/<project_id>/<locale>/suggestions` | Body `item_kind`, `item_key`, `field`, `proposed_text`, `reason`. 201 `{id, status}`. 400 `invalid_request`; 404; 409 `already_pending` (one pending per user and string) or `too_many_pending` (50 per user); 422 `invalid_translation`; 429 (30 per hour per user). |
| `GET /translations/suggestions?project_id&locale&limit&offset` | The pending queue the caller may decide (admin: all; project PI: own projects, locales the project serves): `{total, limit, offset, items}`; `total` is the badge. 403 for anyone else. |
| `POST /translations/suggestions/<id>/accept`, `/reject` | Body `note` optional. 200 `{id, status, version, changes_all_projects}`. 404 (not the caller's to decide), 403 (locale not served by the caller's project; `own_suggestion` when a PI accepts their own), 409 `already_decided` or `stale` `{current_text}`, 422 `invalid_translation` or a reference mismatch. Accepting changes the language for every project that serves it. |

Translation text is validated in `update_string` for every writer (admin
editor and accepted suggestions): `${name}` references only as in the English
string, markup only as in the English string, links only http(s), no control
characters other than tab and line ends.

## GET /api/v1/me/access (body)

The signed-in user's whole access in one body. Rate limit 120 per minute; `Cache-Control: no-store`.
Policy: `docs/policy/api-v1.md`, "Access summary". Every value is the output of
the predicate the server enforces. `grants[]` lists every resolved grant with
`active`; every other list (`roles`, `sites[].roles`, `units[].roles`,
`actions`) counts active grants only. Explicit grants only: demo-training
virtual grants are never listed.

```json
{
  "user": {"user_id": "...", "name": "...", "landing_page": "coder", "coding_languages": ["en"]},
  "is_admin": false,
  "account": {
    "privileged": true,
    "pii_visible": true,
    "device_access": true,
    "mentor": {"member": false, "admin_of": [{"institute_code": "...", "institute_name": "..."}]}
  },
  "roles": ["coder", "data_manager", "interview_supervisor", "site_pi"],
  "admin_actions": [],
  "demo_coding": {"available": true, "project_ids": ["DEMO01"]},
  "projects": [{
    "project_id": "TST001", "project_name": "...", "has_tree": true,
    "settings": {"web_intake_mode": "both",
                 "coding_scope": {"level_code": "phc", "above_mode": "view_only"}},
    "self_coding": {"enabled": false, "code_now": false},
    "grants": [
      {"role": "interviewer", "scope": "org_unit", "org_unit_id": "...", "unit_name": "...",
       "active": true, "source": "assigned"},
      {"role": "coder", "scope": "project_site", "site_id": "...", "codes": false,
       "active": false, "source": "assigned"},
      {"role": "project_pi", "scope": "project", "active": true, "source": "assigned"}
    ],
    "actions": {
      "view": {"project": false, "site_ids": [], "org_unit_ids": ["..."]},
      "triage": {"project": true, "site_ids": [], "org_unit_ids": []},
      "interview": [{"site_id": "...", "site_name": "...", "web_intake_mode": "both",
                     "org_units": [{"org_unit_id": "...", "unit_code": "...", "unit_name": "...", "path": "D1.C1"}]}]
    },
    "sites": [{"site_id": "...", "site_name": "...", "roles": ["coder"]}],
    "levels": [{"level_code": "phc", "level_name": "PHC", "depth": 3}],
    "units": [{"org_unit_id": "...", "unit_code": "...", "unit_name": "...",
               "level_code": "phc", "depth": 3, "parent_code": "...", "path": "D1.C1.P1",
               "is_active": true, "roles": ["interviewer"], "selectable": true,
               "can_code": false}]
  }]
}
```

Built by `app/services/access_summary_service.py` from `resolve_grants`
(cached) plus a fixed number of queries per user (mentor, factor,
`interviewer_context`, computed once and shared with `device_access`) and per
project (names, sites, granted-unit names, one tree load). No query per grant,
site or unit.

- `user`: id, name, `landing_page` (`VaUsers.landing_page`) and
  `coding_languages` (`VaUsers.vacode_language`, a list of language codes).
  No email or mobile.
- `is_admin`: the global admin grant. Admin gets no implicit project:
  `projects` lists only projects where the user holds an explicit grant.
- `roles`: the roles whose screen gates the user opens, sorted:
  `role_flags(user, virtual=False)`, so derived roles are included (an
  In-charge, `site_pi` at a unit, and a `project_pi` on a tree project also
  hold `data_manager` and `interview_supervisor`; `admin` for an admin) and
  demo-training virtual grants are not. A grant whose gate is shut (below) is
  not counted. `collaborator` and `collaborator_pii` open the same screens, so
  either lists both; whether personal details show is `account.pii_visible`.
- `admin_actions`: for an admin, the actions the bypass reaches on any
  project, closed ones included (`ADMIN_BYPASS` in `authz/actions.py`, action
  names as in `actions`; `list_unrouted` only on tree projects); `[]` for
  everyone else. Coding and reviewing are not bypassed.
- `account`:
  - `privileged`: an admin or effective data_manager role within the current
    credential scope; false for device credentials. Web password and passkey
    sign-in are both available; there is no factor-enrolment gate.
  - `pii_visible`: `not viewer_pii_service.should_redact_pii(user)`.
  - `device_access`: `device_auth_service.has_device_access`, the sign-in and
    refresh check: an interviewing context in some project, or an open
    explicit coder, coding_tester or reviewer gate.
  - `mentor`: `member` of an active mentoring institute
    (`mentor_institute_service.member_user_ids`) and `admin_of`, the active
    institutes the user administers (`administered_institutes`).
- `demo_coding`: where demo coding practice is open to the user (same rule
  as the virtual grants in `resolve_grants`); `available` is true when
  `project_ids` is not empty.
- `projects[]`, sorted by `project_id`: only active projects with an active
  grant row. Closed projects and inactive project-sites and units never
  appear.
  - `settings`, from the project's `ProjectSettings` in `resolve_grants`:
    `web_intake_mode` (`off`, `direct`, `death_register`, `both`);
    `coding_scope` `{level_code, above_mode}`
    (`view_only` or `code_any`) or `null` when the project sets no scope level.
  - `self_coding`: `enabled`, the project's self-coding setting as
    `resolve_grants` applies it (self-coding on and web intake not off, the
    rule that implies the interviewer grant); `code_now`, whether the user is
    offered "Code this case now" there (`self_coding_project_ids`: a coder
    grant that codes). The interviewing it adds is in `grants[]` with
    `source: "self_coding"` and in `actions.interview`.
  - `grants`: every explicit resolved grant in the project, for every role.
    `scope` is `project`, `project_site` (with `site_id`) or `org_unit` (with
    `org_unit_id`, `unit_name`). `active` is `Grant.opens_gate`: `false` only
    for a project or project_site grant of a form-resolved role that reaches no
    active form yet (coder, coding_tester: an active form on an active
    project-site; reviewer, interviewer: any active form); the server's role
    gate refuses it. `source` is `assigned` (a grant row) or `self_coding` (the
    interviewer grant implied by a coder grant on a self-coding project, never
    written). Grants of role `coder`, `coding_tester` and `reviewer` also carry
    `codes`: whether the grant codes under the project's coding scope level (a
    project or site grant is above any level, so it codes only with no level or
    `code_any`; a unit grant codes at or below the level; `coding_tester` is
    exempt, so always `true`).
  - `actions`: reach, not a decision. Per action (names as `authz.actions.Action`
    values), only where some active grant reaches it:
    `{"project": bool, "site_ids": [...], "org_unit_ids": [...]}`, from
    `predicates.action_reach`, which reads `RULES` x `_lens_groups` (the coding
    scope rule included), so a new action or lens appears with no summary
    change. `project` is a project-scope grant, `site_ids` project-site grants,
    `org_unit_ids` unit grants (their subtrees). `list_unrouted` (and the
    unrouted half of `route_pin`) is decided per project, not per grant: a
    data-manager power on a tree project reaches its whole unrouted queue
    (`project: true`, `dm_projects`), and a project with no tree has none. Whether an action is allowed on
    one case also depends on that case's form, project-site and unit, and is
    decided per request (`can`, `scope_filter`). `site_pi_report` and
    `supervise_intake` are decided outside `RULES` (per target in
    `_can_site_pi_report`, and in SQL in `authz/supervision.py`) and are not
    listed; `roles` and `units[].roles` carry them. One key is not reach:
    `interview`, the project's entries of `web_intake_service.interviewer_context`
    (the intake routes' check; one entry per site, with `web_intake_mode` and the
    interviewer's units there). `register_death` is the same shape for the
    register-death routes' check (`web_intake_service.register_death_context`):
    the sites and units where the caller, as an interviewer or a
    `death_reporter`, may register a death, in a project whose
    `web_intake_mode` is `death_register` or `both`. An app shows Register
    death from this list, with or without interview rights; `interview` alone
    gates the interview screens.
  - `sites`: active project-sites the active grants reach, with the roles that
    reach each: a project or unit grant reaches every active site of the
    project, a site grant its own site; derived `data_manager` and
    `interview_supervisor` as in `roles`. `interviewer` is listed at a site
    only where `interviewer_context` lists that site (web intake on, an active
    form there); `death_reporter` only where `register_death` lists it. A site with no role left is omitted.
  - `supervises_deaths`: true when an active grant holds `data_manager` or
    `interview_supervisor` (derived included) and the project's
    `web_intake_mode` is not `off` (direct-only included: supervision lives in
    the Deaths menu, owner 2026-10-22); interviewers of a direct-only project
    get no Deaths menu.
  - `has_tree`, `levels`, `units`: `levels` and `units` only when `has_tree`.
    Units are active and placed (unplaced units are skipped), in path order.
    Fields as the organization API's `/units`, plus `roles`, `selectable` and
    `can_code`.
- `units[].roles`: which roles reach the unit: tree reach for the picker and
  browsing (the same answer as `/organization/<project>/units?role=...`), not
  action capability; actions are still decided per request. Active grants
  only. Per role the reach is the whole tree for a project or project_site
  grant (a site grant reaches that site's cases in any unit, so the whole tree
  is shown for it); a `project_pi` on the project holds every role they have
  there, `data_manager` and `interview_supervisor` included, on every unit,
  except `interviewer` and `death_reporter`: web intake has no PI bypass, so a
  unit interviewer or death_reporter grant stays its subtree (`web_intake_service.reachable_unit_ids`); an In-charge (`site_pi` at a unit) holds the derived
  `data_manager` and `interview_supervisor` on that unit's subtree only;
  otherwise the subtrees of that role's unit grants. `interviewer` is on no
  unit when the project's `actions.interview` is empty (web intake off).
- `units[].can_code`: some active `coder` or `coding_tester` grant covering the
  unit codes there (`codes` above, the server's coding scope rule). A client
  never offers coding where this is `false`.
- `units[].selectable`: `true` for a unit some role reaches (`roles` not
  empty). `false` with `roles: []` for an ancestor shown only as context above
  a reached unit; never a choice. The server's own scope checks never read it.

Resolved grants are cached (`authz/grant_cache.py`, format 3: it carries each
grant's `source` and the project settings above). Deploy: bump the authz
global version so no old-format entry lingers (an entry of another format is
discarded and re-read from the database in any case).

Errors: 401 `unauthorized` when signed out or on a bad bearer; 403
`terms_required`, `maintenance` from the gates (the same codes for every
`/api/v1` route; the old browser bootstrap's `password_change_required` and
`redirect_url` are gone); 429 over
the limit. Response header (cookie request only): `X-CSRFToken`.

## GET /api/v1/me/kpis (body)

The home KPI strip (`digitva-qu7x`, `app/routes/api/me.py`,
`area_dashboard_service.home_kpis`). Signed in only; JSON 401 otherwise.
`{"projects": [{project_id, project_name, deaths_reported, interviews_done,
coded, interviews_pct, coded_pct}]}`, one row per active project in the
caller's area (the scope of `/api/v1/area/projects`, any grant). Totals only,
no names. `deaths_reported` excludes duplicate and cancelled cases;
`interviews_done` is total VA submissions in scope; `coded` is submissions
with a final COD. Both percentages are integers of `deaths_reported`, rounded
half up, `null` when it is under 20 or smaller than the count (policy: `docs/policy/area-dashboard.md`, "Home
KPIs"). A user with no grants gets `{"projects": []}`. Cached 60 seconds per
user; 120 requests per minute.

## GET /api/v1/me/home (body)

The Expo Home page (`app/routes/api/me.py`,
`user_home_service.get_home_blocks`). Signed in only; JSON 401 otherwise.
Built for the browser session: a bearer token gets the same role list, and
the supervisor block then counts nothing (`supervised_case_condition` is
browser-only).
`roles` are the access summary's (explicit grants only). `blocks` holds a key
only for a role held, each counted inside that role's own scope by the
service its screen uses; nothing is summed across roles or projects.

```json
{
  "roles": ["coder", "death_reporter", "interviewer", "project_pi"],
  "blocks": {
    "death_reporter": {"registered": 12, "awaiting_interview": 3},
    "interviewer": {"drafts_in_progress": 2, "needing_visit": 5},
    "interview_supervisor": {"flagged": 1, "needs_decision": 2, "open": 40, "submitted": 210},
    "coder": {"ready": 14, "practice": false, "completed": 80, "recodeable": 2},
    "reviewer": {"available": 6, "completed": 31},
    "data_manager": {"screening_pending": 4, "ready_for_coding": 14, "not_codeable": 2},
    "progress": {"roles": ["project_pi"]}
  }
}
```

- `death_reporter`: register entries the caller registered (as
  `/me/activity` `deaths_reported`, "Deaths I registered", not the
  scope-wide count of `/me/kpis`); `awaiting_interview` those still
  `registered`, `scheduled`, `in_progress`, `paused` or `not_reachable`.
- `interviewer`: own open drafts; `needing_visit` open cases (same states)
  in the worklist's scope under its "Mine" rule.
- `interview_supervisor`: cases of `supervised_case_condition`; `flagged`
  holds a flag awaiting a supervisor (`pending_flag`), `needs_decision` a
  flag or a second complete interview to choose (the supervision list's
  `needs_decision` filter), `open` the states above.
- `coder` (a coder or coding tester): `ready` is the `/coding/stats` ready
  pool (random plus pick). A coding tester without a coder grant gets
  `practice: true` and `ready` only; otherwise `completed` (as
  `/coding/stats`) and `recodeable` (own codings still inside the recode
  window, `get_coder_recodeable_sids`).
- `reviewer`: `available` and `completed` as `/reviewing/stats`.
- `data_manager`: submissions of the data manager dashboard's scope in
  `screening_pending`, `ready_for_coding` and either not-codeable state,
  from the analytics snapshot.
- `progress`: present for `project_pi`, `site_pi` or a collaborator, with
  the roles held and no counts: the client loads `/me/kpis` when the block
  is opened.

## GET /api/v1/me/activity (body)

The caller's own personal activity counts across all projects and per project
(`digitva-dsj2`, `app/routes/api/me.py`,
`user_home_service.get_user_activity_summary`). Signed in only; JSON 401
otherwise. 120 requests per minute; `Cache-Control: no-store`.

```json
{
  "totals": {
    "deaths_reported": 12,
    "interviews_submitted": 10,
    "drafts_in_progress": 2,
    "coded": 8,
    "not_codeable": 1,
    "reviewed": 4
  },
  "by_project": {
    "TST001": {
      "deaths_reported": 12,
      "interviews_submitted": 10,
      "drafts_in_progress": 2,
      "coded": 8,
      "not_codeable": 1,
      "reviewed": 4
    }
  }
}
```

- `deaths_reported`: register entries (`source = 'register'`) in
  `va_death_register` registered by the caller, excluding `duplicate` and
  `cancelled` cases. A direct start is an interview, not a reported death.
- `interviews_submitted` and `drafts_in_progress`: the caller's rows in
  `va_web_intake_draft` (`status` `"submitted"` and `"draft"`), excluding
  confirmed duplicate and cancelled cases.
- `coded` and `not_codeable`: distinct submissions where the caller holds an
  active final assessment (`va_final_assessments`) or active not-codeable coder
  review (`va_coder_review`), excluding demo-training projects.
- `reviewed`: distinct submissions where the caller holds an active reviewer
  final assessment (`va_reviewer_final_assessments`), excluding demo-training
  projects.
- `by_project` includes an entry for every active project in the caller's
  resolved grants plus any project where the caller has recorded activity. A
  user with no grants and no activity receives zeroed `totals` and
  `"by_project": {}`.

## My organization (`GET /api/v1/organization/me` and `.../units/<org_unit_id>/people`, `app/routes/api/organization.py`)

`digitva-e7sz`. Every project where the caller holds a live explicit grant
(sites-mode projects included since 2026-10-20, with empty tree lists).

- `GET /me`: per project `has_tree`, `my_positions`
  (`{project_roles: string[], sites: [{site_id, site_name, roles: string[]}]}`:
  the caller's project-scope roles and project_site roles, role values as
  granted, sites only where a site grant exists), `my_units` (own unit grants
  and worker placements, with cadre names and `roles: [{role, cadre|null}]`
  from the unit grants), `above` (ancestor units, root first, each with
  `people`), `my_level` (people at each own unit), `below` (child units of
  own units with `people_count` and `has_children`, or the root units when the
  caller has no unit). Every unit in `above`, `my_level`, `below` and
  `children` also carries `parent_org_unit_id` (uuid string or `null`), so a
  client can nest units by real parentage (an own unit can sit under another
  own unit, and `below` excludes own units).
- `GET /units/<org_unit_id>/people`: `{unit, people, children}` for one unit;
  404 when the unit is unknown, inactive, or in a project the caller holds no
  grant in.

People are `{name, cadre, roles}` only (`roles: string[]`, sorted role labels
(`ROLE_LABELS` in `app/models/va_selectives.py`, also the admin Access grants panel's source)
from the linked user's active grants in that project, `[]` without a linked
user; computed in the same query as the people), at most 500 per unit; never phone, email,
worker code or user id (policy: `docs/policy/organization-model.md`, "Who sees
worker names").

## UI string corrections (`GET /api/v1/ui-strings/<locale>`, `app/routes/api/ui_strings.py`)

`digitva-fsjz`. Public, no sign-in (the sign-in screen is translated too).
Returns `{version, strings}`, where `strings` holds an administrator's
corrections for one bundled locale only; the app keeps its bundled text for
every other key. `version` is the ETag; a matching `If-None-Match` gets 304.
`Cache-Control: public, max-age=60`. `en` and unknown or unshipped locales
return 404 `not_found`. Policy: `docs/policy/ui-strings.md`.

## GET /api/v1/me/notifications (body)

`app/routes/api/me.py`, `notification_service.poll`; policy
`docs/policy/app-notifications.md`. Query `after` (default 0): the last
`id` the client has seen; anything but a non-negative integer that fits a
bigint is 400 `invalid_request`. Reply, rows with `id > after`, oldest first, at most 100:

```json
{"notifications": [{"id": 17, "kind": "revision_requested",
  "created_at": "2026-10-05T09:30:00+00:00", "project_id": "ABC01",
  "death_id": "<uuid>|null", "draft_id": "<uuid>|null", "va_sid": "<sid>|null"}],
 "next_cursor": 17}
```

`next_cursor` is the last returned id, or `after` when there is nothing newer;
send it as the next `after`. A reply of 100 rows may have more: poll again at
once. Kinds: `revision_requested` (`va_sid`, `death_id`, `draft_id` of the
submission's draft), `other_draft_started` and `case_submitted_by_other`
(`death_id` and the recipient's own `draft_id`), `case_reopened` (`death_id`;
`draft_id` for an open draft holder), `interview_chosen` (`death_id`, the
recipient's own `draft_id`; `va_sid` only for the interviewer whose interview
was chosen). An unknown kind is ignored by a client.

Cost: Redis key `digitva_msg:last:<user_id>` (the newest id written, 5-minute
TTL, raised after the event's commit) answers an up-to-date poll with no
database query; otherwise one query on `(user_id, id)`. A complete read seeds
an absent key. Redis errors fall back to the database. Rows are not guaranteed
to commit in id order, so a concurrent event can be passed once; sync carries the
state. Always `Cache-Control: no-store`.

## POST /api/v1/me/terms (body)

Body `{"accept_terms": true}`. The same view as `POST /api/v1/profile/terms`:
records the acceptance and audits `terms_accepted`; 200
`{"message": "Terms accepted.", "terms_accepted": true}`; any other body is 400
`{"error", "code": "invalid_request"}`. Exempt from the terms gate, so it works
while terms are pending; limited to 5 per minute per user, one counter shared with the
profile URL.
