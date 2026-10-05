---
title: API v1 Reference
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-10-06
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

## Error body

Every error reply of a route under `/api/v1` is `{"error": <message>,
"code": <snake_case machine code>}`, plus documented extra keys (a 409 that
carries the stored result, a 409 coding refusal's `workflow_state`, a terms
refusal's `redirect_url`). The one exception is the doris-clinical
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
(`rate_limited`) and the terms and factor-setup refusals (`terms_required`,
`factor_setup_required`, 403; `error` is a readable sentence, `code` is the
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
| `POST /auth/enroll` | Body `code`, `device_name`, `platform`, `app_version`. 201 `{device_id, device_secret, project, server_time}`. 10/min per IP. Code consumed atomically (`use_count < max_uses`). |
| `POST /auth/sessions` | Body `device_id`, `device_secret`, `email` (an email or a mobile number), `password`, optional `otp`. 201 `{access_token, access_expires_at, refresh_token, refresh_expires_at, user {user_id, name, email}, terms_required, access}`. `access` is the `GET /me/access` body for that user, shown even while terms are pending (it is display only; the terms gate is on requests). Refusals: 401 `device_invalid` (unknown device or wrong secret), 401 `invalid_credentials`, 401/403 `second_factor_required`, 429 `second_factor_locked`, 403 `email_unverified`, `maintenance`, `device_revoked`, `no_interviewer_grant` (no interviewer, coder, coding_tester or reviewer access in any active project; code kept for the app). Limits: 10/min per IP, 10/min per device, 20/hour per account. |
| `POST /auth/sessions/refresh` | Body `refresh_token`, `device_id`, `device_secret` (else 401 `device_invalid`, nothing revoked); optional outstanding-work report `count`, `unique_ids`, `client_draft_ids`, `client_death_ids` (not recorded while terms are pending). 200, the same body as sign-in, `access` included. 401 `refresh_reused` / 409 `refresh_retry_race` (reuse; session revoked); 401 `session_revoked` (device or admin revoke, no active project left, signed out); 401 `session_ended` (account changed; keeps data); 401 `session_expired` and `refresh_invalid` revoke nothing. 30/min per IP. |
| `DELETE /auth/sessions/current` | Bearer only (a cookie: 401 `unauthorized`). 204. `login_required`, not the interviewer role, so a withdrawn interviewer can still sign out; open while terms are pending. |

## Me and reference

| Call | Notes |
|---|---|
| `GET /me/access` | The whole access body, below. Sets `X-CSRFToken` for a cookie request. |
| `GET /me/notifications?after=<id>` | The caller's own notifications, below. Either credential. 120/min. |
| `POST /me/terms` | Below. Also `POST /profile/terms` (the same view). |
| `GET /organization/<project>/units?role=interviewer` | The unit picker: `web_intake_service.reachable_unit_ids` (grant-based; a project grant or any site grant of the project reaches the whole tree). 403 when nothing is reachable. Other `role` values and none are the browsing views. |
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
interviewer role (supervision: `interview_supervisor` or `data_manager`).

| Call | Notes |
|---|---|
| `POST /intake/submissions` | Body `client_draft_id` (UUID), `project_id`, `site_id`, `draft` (envelope: meta keys only, `draft.data` is not read; optional `startedAt`, `completedAt`, `deviceClockAt`, each ISO 8601 with a UTC offset), `answers_json` (string: the exact JSON text of the answers object) and `answers_sha256` (64 hex, SHA-256 of that text's UTF-8 bytes), optional `completion: {valid, issues}`, `death_id`, `org_unit_id`. The server hashes `answers_json` as received, then parses. 422 `answers_hash_required` (a field missing, not a string, or a malformed hash), 422 `answers_hash_invalid` (hash differs; nothing stored), 422 `invalid_interview` (not a JSON object, over 1 MB, nested deeper than 6, or one of the three times present but unparsable or offset-less). 201 on a new upload (also a second upload of a case the caller already submitted: a correction), 200 on a resend (the same hash, or other answers: no 409, the last completed version wins by completion time). Result: `{va_sid, case, outcome, superseded, answers_sha256, kept, received_sha256, locked, can_code_now}` (`can_code_now`: as on `/intake/drafts/<id>/submit`): `answers_sha256` is the coder version's hash, `received_sha256` the hash of the answers this request sent (the app deletes its copy when it equals what it sent), `kept` `incoming` (the coder has these answers) or `server` (they are history only), `locked` true when coding is final or the case closed. A cookie request stores no `meta.deviceId`. Detail: [Device Collection API](device-collection-api.md) "Uploads". |
| `POST /intake/submissions/<va_sid>/revisions` | The submitting interviewer revises their own submitted interview. Body `reason_code` (`interviewer_correction`, `respondent_correction`, `more_information`, `finish_partial`), `answers_json` + `answers_sha256` (as `/submissions`), `completion: {valid, issues}`, `draft` (meta; only `startedAt`/`completedAt` are taken). 200 `{changed, va_sid, payload_version_id, answers_sha256, outcome, workflow_state}`; `changed: false` writes nothing. 404 `not_found` (not the caller's), 409 `revision_locked` / `case_already_submitted` / `case_closed` / `case_state_conflict`, 422 `invalid_reason` (the server's own `resubmitted` is not accepted) / `answers_hash_*` / `invalid_interview`. A completed interview may be revised to a refused or partial one (the case leaves coding). Body cap 2 MB. Detail: [Device Collection API](device-collection-api.md) "Interviewer revisions". |
| `POST /intake/supervision/submissions/<va_sid>/reopen-for-revision` | Reopen a finalised web or device interview for its interviewer to revise (`interview_supervisor`, `data_manager` or `admin`). Body `reason_code` (`cod_review_requested`, `new_information`, `data_correction`). 200 `{va_sid, workflow_state: "finalized_upstream_changed", reason_code}`. From `coder_finalized`, `reviewer_eligible`, `reviewer_finalized`. An admin, or a supervisor or data manager whose supervision reach covers the interview's case (404 otherwise); 409 `not_web_submission` / `case_closed` / `wrong_state`; 422 `invalid_reason`. The final COD stays until the interviewer's revision arrives. |
| `POST /intake/outstanding` | Device session only (a cookie: 403 `device_session_required`). Stores count, sorted unique ids and sorted, normalised `client_draft_ids` and `client_death_ids` (UUIDs) on the session; the admin device list returns all three (`outstanding_client_death_ids` added in `digitva-kmk.4`). |
| `GET /intake/cases?project_id=&mine=&state=&limit=&cursor=` | The case list, below. 120/min. `project_id` optional. |
| `GET /intake/cases/<death_id>` | Case detail with full contacts, links and (when the caller may start or resume it) prefill, below. 600/min per user, so a device can fetch each active case's detail after the list; on 429 a client keeps its previous complete copy and retries after `Retry-After`. |
| `POST /intake/cases/<death_id>/flags`, `/pause` | The browser worklist's calls, now for every client. Each replies `{"case": <detail>}`, the body of `GET /intake/cases/<id>` (below). |
| `GET /intake/cases/<death_id>/possible-duplicates` reply | `{"possible_duplicates": [...]}`, up to 50, most similar first, only cases inside the caller's own worklist scope (a case outside it is never returned, no id and no detail). Each: `death_id`, `unique_id`, `unit_name`, `state`, `score`, and `deceased_name`, `date_of_death` (ISO date), `village` (the village or ward of the case's recorded address, `null` when empty; the org unit is `unit_name`), `age_years`, `sex`, `informant_name`, `previous_interviewer_name` (the user who started the interview, `null` when nobody did; new here, since the worklist and case detail never name another interviewer, and shown only for these in-scope candidates by the owner's 2026-10-01 rule). The detail keys are additive. No phone or address. The per-row `possible_duplicates` of `GET /intake/cases` and the device list stays `death_id` and `unique_id` only. |
| `GET/POST /intake/deaths` | List (`project_id`, `site_id` required) and register (`project_id` required; `client_death_id` optional, idempotent), below. |
| `PATCH /intake/deaths/<death_id>` | Correct a registered death until an interview of it is completed (`interviewer`, `interview_supervisor` or `data_manager`; the caller must see or supervise the case, else 404). Body: only the register fields to change, optional `if_updated_at` (the `case.updated_at` last seen). 200 `{"case": <detail>}`; 409 `case_completed` (a completed interview exists) / `details_pending` / `death_stale`; 422 `invalid_death` (`register_death`'s validation, a list or object in a field, nothing to change). Audited as `details_edited`: the audit's `reason` names the fields, its `changes` column keeps each one's old and new value (never returned by any API). Policy: [Web Intake](../policy/web-intake.md) "Correcting a registered death". |
| `POST /intake/cases/<death_id>/attempts`, `/visit` | Attempts (`client_attempt_id` optional, idempotent) and visits, keyed by the case (no `project_id`), below. |
| `POST /intake/drafts/sync` | The phone's in-progress interview into the caller's one open draft of a case; newer save wins whole, the loser is kept as a `replaced` draft. Reply `{draft, kept, conflict, answers_sha256, message, envelope}`; 422 `answers_hash_*`/`invalid_interview` store nothing; 409 on a closed case. Contract: [Device Collection API](device-collection-api.md) "Draft sync". |
| `GET/POST /intake/drafts`, `GET/PATCH /intake/drafts/<id>`, `POST /intake/drafts/<id>/discard`, `/submit` | The web draft store. Draft saves and submits take no body cap beyond the service's answer checks. `PATCH` takes optional `if_updated_at` (the last seen `draft.updated_at`): a newer saved version is 409 `draft_stale`, nothing written. One open draft per interviewer per case: `POST` returns the caller's own, another interviewer's never blocks (no 409). `/submit`: 201 `{va_sid, draft, superseded: false, validation_err, can_code_now}`; on a draft that is already `submitted` (a stale tab) it is a correction, 200 with the same body plus `kept` and `locked`; on an open draft whose case's winning submission is the caller's own earlier draft it is the same correction (the draft is closed as `replaced`; `va_sid` and `draft` are the winning interview's); on a case already `submitted`, `duplicate` or `cancelled` (a teammate won, or a supervisor closed it) the draft is kept as `superseded` (no submission, case untouched) and the reply is 200 `{va_sid: null, draft, superseded: true, validation_err: null, can_code_now: false}`. `can_code_now` (bool, also on the correction's reply and on the `/intake/submissions` result) is true when the caller may now be offered "Code this case now": a completed interview with valid consent in a self-coding project where the caller holds a coder grant that codes (`web_intake_service.can_code_now`; grants only, the action re-checks). |
| `GET /intake/supervision/cases`, `POST /intake/supervision/cases/<id>/resolve-flag`, `/cancel`, `/reopen`, `/duplicate` | Supervisor list and actions (`interview_supervisor` or `data_manager`). Each action replies `{"case": <row>}`, the case in the supervisor list's row shape (`serialize_supervised_row`: who registered and started it, no contact details, no prefill), not the interviewer's detail: a supervisor need not hold an interviewer grant. The list takes `state`, `flagged`, `candidates` (true: only cases with a second complete interview to choose), `limit`, `cursor`; every row carries `other_complete_interview` (bool). |
| `GET /intake/cases` rows and `GET /intake/cases/<id>` | Also carry `code_now` (bool): the caller's own submission of the case is `ready_for_coding` in a self-coding project where they hold a coder grant that codes, so "Code now" works (`POST /coding/submissions/<va_sid>/code-now`, below). Read from the worklist query (`ready_for_coding` joins `va_submission_workflow`), no per-row query. Not in supervision rows. |
| `GET /intake/supervision/cases/<id>` | One supervised case: `{"case": <supervisor row>, "candidates": [{draft_id, interviewer_name, completed_at, outcome}]}`, the other complete interviews a supervisor may choose (`outcome` is always `completed`). The interviewers' names are for supervisors only. 404 outside the caller's reach. |
| `POST /intake/supervision/cases/<id>/choose-interview` | Choose another interviewer's complete interview of a submitted case over the one it holds (`interview_supervisor`, `data_manager` or `admin`; [Web Intake Policy](../policy/web-intake.md), "Supervisors"). Body `draft_id` (a candidate), `reason_code` (`better_quality`, `more_complete`, `original_incorrect`, `switch_back`). 200 `{"case": <supervisor row>}`; the case keeps its `va_sid`, coding restarts from any stage (earlier COD kept as history), the other interview stays a candidate. 400 malformed `draft_id`; 404 outside reach or another case's draft; 409 `case_not_submitted` / `not_web_submission` / `not_a_candidate` / `form_mismatch` / `wrong_state` (a reviewer session is live); 422 `invalid_reason`. |
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
app-level hook): 2 MB for `/intake/submissions` and its `/revisions`, 256 KB for
`/intake/outstanding`, 16 KB otherwise
(draft saves and submits excepted); over it -> 413 `payload_too_large`.

The app wipes an interviewer's store only on `session_revoked`. A refresh
whose response was lost and is retried with the old token answers 409
`refresh_retry_race`, and theft-style reuse 401 `refresh_reused`; both
revoke the session but the app keeps the data and asks the interviewer to
sign in again.

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

## Reviewer queue (`GET /api/v1/reviewing/stats|available|history`, `app/routes/api/reviewing.py`)

The reviewer dashboard's reads for any client, from
`app/services/reviewer_dashboard_service.py` (the web page calls the same
functions). Gate `reviewer`; every reply is `private, no-store`. Optional
`project_id` (upper-cased, at most 64 characters) narrows each route.

| Route | Reply |
| --- | --- |
| `GET /stats` | `{in_scope, completed, available, allocation}`. `in_scope` and `completed` are the web page's counts (cases in review scope in any state; the caller's active reviewer finals, any scope); `available` is the size of `/available`; `allocation` is `{va_sid}` or `null`, as `GET /allocation`. |
| `GET /available` | `{cases, count, limit, offset, has_more}`. Exactly the cases `POST /allocation/<va_sid>` accepts: `reviewer_eligible`, REVIEW scope, narration language in the caller's profile, in ODK (not retired), not a confirmed duplicate, no active reviewer final, active project-site. A row is `va_sid`, `va_uniqueid_masked`, `va_form_id`, `project_id`, `site_id`, `va_submission_date`, `va_data_collector`, `va_deceased_age`, `va_deceased_gender`, `va_narration_language`. Ordered by project, site, submission date, masked id, `va_sid`. |
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
Social Autopsy disabled for the role, a demo session outside a demo/training
project), `no_allocation` (no active reviewing or coding allocation on the
case); 404 `not_found`. The coding-allocation check shared with `icd10.py`
answers the same two 403 codes (`require_coding_access`).

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

| Key | Content |
| --- | --- |
| `case` | `va_sid`, `instance_name` (the masked id), `form_type_code`, `project_mode` (`masked_simple`, `masked_doris`, `unmasked_simple`, `unmasked_doris`), `icd_classification` (`icd10` or `icd11`: the project setting `icd_coding_value.get_icd_classification_for_submission` reads, default `icd10`; the client calls the matching coding search, `GET /api/v1/icd10/2019-2/coding-search/<va_sid>?q=` or `GET /api/v1/icd11/coding-search/<va_sid>?q=`, and the other one answers 400), `workflow_state`, `narrative_qa_enabled`, `social_autopsy_enabled` |
| `categories`, `default_category` | ordered `[{code, label, nav_label, render_mode}]` the mode's role sees (the COD panel `vacodassessment` last), and the code to open first |
| `step` | `initial`, `final` or `done`. Coding: Step 1 while the caller has neither an active Step 1 nor a not-codeable review (an unmasked project has no Step 1, so `final`); `final` once Step 1 is saved; `done` after a not-codeable review with no Step 1. Reviewing: masked and no own Step 1 is `initial`, own Step 1 or an unmasked project is `final`, a saved reviewer final is `done` |
| `blocked_by` | codes that stop the final save: `narrative_qa` (coders; NQA enabled and not saved by the caller) and `social_autopsy` (the role's analysis required and not saved) |
| `assessments` | always these keys, null when absent. Coding: `initial` (the caller's own active Step 1: `id`, `immediate_cod`, `antecedent_cod`, `other_conditions` as a list, `created_at`), `initial_prefill` (what the Step 1 form opens with: the same row, or in a recode episode the caller's latest prior draft), `final` (the authoritative coder final: `id`, `conclusive_cod`, `immediate_cod`, `other_conditions`, `remark`, `created_at`; only once `step` is `final`, as the web's Step 2 form shows it, so a masked Step 1 stays blind to an earlier coder's result), `not_codeable` (`reason`, `other`, `created_at`; only the caller's own review). Reviewing: `coder_initial`, `final` and `not_codeable` as read-only reference (the web panel shows them to a reviewer), and the caller's own `reviewer_initial` and `reviewer_final` (another reviewer's final is neither shown nor makes `step` `done`). Another coder's Step 1 is never shown to a coder |
| `smartva` | the active SmartVA result read live (not from the section cache; it completes asynchronously): `age`, `gender`, `key_symptoms`, `causes` (`rank`, `cause`, `icd10`, `icd11` mapping, `likelihood`), `symptoms`; null when none, and on a masked project until the caller has their own Step 1 (Step 1 is blind) |
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
`[{code, label, render_mode, items: [{label, value, flip, info}]}]`, never a
label-keyed object (the JSON provider sorts keys); `flip` and `info` are the
mapping's flip and info labels the web badges use. The `workflow_panel`
category (`vacodassessment`) carries the narration and documents and the health
history subcategories the COD panel shows. `blocked_by` is `narrative_qa` or
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
viewer who must not see personal data (the prefix was bumped from `form_data:`
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
    "second_factor": {"required": true, "configured": true},
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
  - `privileged`: an active admin or data_manager grant
    (`totp_service.is_privileged`), the users factor enforcement applies to.
  - `second_factor`: `required` is `totp_service.needs_second_factor` (sign-in
    asks for a second factor), `configured` is `totp_service.has_any_factor`
    (a confirmed TOTP enrolment or any passkey).
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
    interviewer's units there).
  - `sites`: active project-sites the active grants reach, with the roles that
    reach each: a project or unit grant reaches every active site of the
    project, a site grant its own site; derived `data_manager` and
    `interview_supervisor` as in `roles`. `interviewer` is listed at a site
    only where `interviewer_context` lists that site (web intake on, an active
    form there). A site with no role left is omitted.
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
  except `interviewer`: web intake has no PI bypass, so a unit interviewer
  grant stays its subtree (`web_intake_service.reachable_unit_ids`); an In-charge (`site_pi` at a unit) holds the derived
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
`terms_required`, `maintenance`, `factor_setup_required` from the gates (the
same codes for every `/api/v1` route; the old browser bootstrap's
`password_change_required` and `redirect_url` are gone: terms are
`terms_required`, factor setup goes to `/profile/#passkeys-card`); 429 over
the limit. Response header (cookie request only): `X-CSRFToken`.

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
