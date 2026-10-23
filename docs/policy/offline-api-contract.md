---
title: Offline API Contract v1
doc_type: policy
status: proposed
owner: Vivek Gupta
last_updated: 2026-10-23
---

# Offline API Contract v1

The one authoritative contract between the central DigitVA server (ours) and
the offline PHC app (the offline team's: its UI, its device-local server
`digitva-server` and its bundle writer crate). Where this document and an
older design note disagree, this document wins. The bundle byte format is
specified in [offline-bundle-and-transfer.md](offline-bundle-and-transfer.md)
(the "bundle spec") and the sealed-value format in
[pii-envelope-format.md](pii-envelope-format.md); this contract references
them and does not repeat them.

**Contract version:** `offline-api/1`. **Bundle format:** `bundle_format_version: 1`.
**Station config format:** `station_config_format_version: 1`.

**Read-me-first caveat (2026-10-21).** The specs and code this contract cites
are in the **main checkout and not yet committed**:
[offline-bundle-and-transfer.md](offline-bundle-and-transfer.md),
[pii-encryption-at-rest.md](pii-encryption-at-rest.md),
[pii-envelope-format.md](pii-envelope-format.md),
[respondent-consent-notice-draft.md](respondent-consent-notice-draft.md), this
file, `app/utils/national_id.py`, `app/utils/pii_crypto.py`,
`app/services/death_identifier_rules.py`,
`tests/fixtures/pii_envelope_vectors.json`, and edits to
`app/services/pii_field_registry.py`. The owner commits them (commit
`a91fc7cc8`); line numbers below are of the working tree on 2026-10-21
and may move by a few lines in that commit. Do not build against a line
number, build against the named function.

**Status markers.** Every item is one of: `implemented today` (in the server
code now, cited), `specified, not built (<bead>)` (agreed here, server work
ours, tracked by that bead), or `not for devices` (exists, but no device
credential may use it; browser only).

## 1. Scope and actors

| Actor | Where | Contract role |
| --- | --- | --- |
| Death reporter | station | registers a death; takes DPDP consent **at registration** when informant name, phone or address are entered (5.4) |
| Interviewer | station | registers a death (optional), takes consent at registration, or at the interview start when none is on file or the informant is a different person; interviews |
| Coder | station | on the station's signed roster with the `coder` role; codes completed interviews that station uploaded, in the coding mode the station config locks to the project's (`icd11_doris` or `icd10`, 4.3; bundle spec 2.4 Q5) |
| Station supervisor | station, provisioned only | a **station roster role** (4.1), not a server grant: corrects death details and registration numbers of cases in its roster scope (4.2, 3.4, 3.5) |
| Station custodian | station | the responsible person identified at onboarding; named in the enrolment and the signed station config (4.1) |
| Local server (`digitva-server`) | station | **the app's own backend**, accepted by the owner (2026-10-21: "the local app will need a local server"); limits in section 9 |
| Central server (ours) | DigitVA | all central duties: bundle ingest and unpacking, sealing at rest with server private keys, authoritative validation and cross-case duplicate matching, consent enforcement as the authority, workflow, authorization, audit |
| Courier / uploader | district office | carries a `.dvb` file; uploads in a browser session (bundle spec 5.1) |
| Supervisor / data manager | web only | consent withdrawal, duplicates, corrections and identifier writes on cases they supervise, closed-case corrections |

What the station **never** does: unpack or ingest bundles, hold a server
private key, seal with a server key, decide validity, duplicates, routing,
workflow state or consent authority for the server, record a consent
withdrawal, correct a closed case, sync or federate with another station, or
receive a server case list (the app keeps its own **local** case list of
what it registered, interviewed or is coding).

## 2. The two transfer paths

1. **HTTPS**: the existing `/api/v1` endpoints (section 3) with a device
   bearer token from `POST /auth/sessions`, when the station is online.
2. **Bundle**: a signed, sealed `.dvb` file (bundle spec sections 2-3) the
   courier uploads; the central server ingests it (bundle spec 5).

Both carry the **same client ids** (`client_death_id`, `client_draft_id`,
consent `client_id`, coding `client_id`, correction `client_id`), so a record sent both ways is a
duplicate, never a second record (bundle spec 4). The station keeps a record
until a matching acknowledgement: the HTTPS reply (`received_sha256` equal to
what it sent, `device-collection-api.md` "Result body") or a receipt naming it
`accepted`, `duplicate` or `superseded` (bundle spec 5.6).

**Corrections on the bundle path** (owner decision 6): on a provisioned
station a roster user acting as `station_supervisor` corrects death details
(`death_correction`) and registration numbers (`identifiers_set`) offline;
both travel in a bundle or over HTTPS (3.4, 3.5, 4.2).

**HTTPS only in v1**: a contact attempt, a visit, an interviewer revision, an
allocation release, and a correction or later number made under a
non-supervisor acting role (`interviewer`, `death_reporter`). The app MUST
say so in its UI where they are entered offline: "Saved on this device. Sent
only when the station is online." (bundle spec Q8.)

## 3. HTTPS endpoints

Common to every row: base `/api/v1`; JSON bodies; errors are
`{"error": <text>, "code": <code>}` plus `fields` when the refusal names the
inputs to fix (`app/routes/api/request_helpers.py:50-53`, `:134-138`), and
**no `reason` key**; every `/intake/*` reply carries `Cache-Control: no-store`
(`app/routes/api/intake.py:93-97`); a device bearer needs no CSRF token and
gets the **device projection** of its grants only: `interviewer`,
`death_reporter`, `coder`, `coding_tester`, `reviewer`; admin, data manager,
PI and supervisor powers are excluded (`app/services/authz/grants.py:59-65`,
`:401-416`). Body caps: 16 KB default, 2 MiB for `/intake/submissions` and
revisions, 256 KB for `/intake/outstanding`, 413 `payload_too_large` before
reading (`intake.py:55-90`). A client MUST NOT send keys this contract does
not list.

### 3.1 Authentication and access

| Item | Value |
| --- | --- |
| Endpoints | `POST /auth/enroll`, `POST /auth/sessions`, `POST /auth/sessions/refresh`, `DELETE /auth/sessions/current`, `GET /me/access`, `POST /me/terms` |
| Device caller | the station (enrol), each roster user (sign in with their own account) |
| Request / response | as [api-v1.md](../current-state/api-v1.md) "Auth" rows (`api-v1.md:121-124`) and [device-collection-api.md](../current-state/device-collection-api.md) "Authentication" |
| Errors | `device_invalid`, `invalid_credentials`, `email_unverified`, `maintenance`, `device_revoked`, `no_interviewer_grant`, `refresh_reused`, `refresh_retry_race`, `session_revoked` (the only code the app wipes on), `session_ended` (keeps data), `session_expired`, `refresh_invalid`, `terms_required` |
| Idempotency | none; refresh rotates both tokens |
| Limits | enrol 10/min per IP; sign-in 10/min per IP, 10/min per device, 20/hour per account; refresh 30/min per IP (`app/routes/api/auth.py:109-148`) |
| Status | `implemented today` |
| Addition | optional `signing_public_key` (b64url, 32 bytes) on `POST /auth/enroll`, and `POST /auth/devices/current/signing-key` (device bearer, set once): `implemented today` (digitva-gb8w.5, `app/routes/api/auth.py` `enroll` and `set_device_signing_key`, `app/services/device_signing_service.py`); a bad key is 400 `invalid_request` with `fields: ["signing_public_key"]`; bundle spec 3.2 |

### 3.2 Reference data

| Item | Value |
| --- | --- |
| Endpoints | `GET /intake/identifier-types?project_id=`; `GET /instruments/<code>/definition?project_id=` (+ `/translations/<locale>`, `/versions`); `GET /organization/<project>/form-options`; `GET /organization/<project>/units?role=interviewer`; `GET /intake/projects/<project>/prefill-policy` |
| Device caller | a roster user who may register or interview in the project |
| Response (identifier types) | `{"project_id", "identifier_types": [{code, label, min_length, max_length, char_type, pattern, example, required_at_report, sort_order}]}`, active types only, by `sort_order` (`intake.py:181-204`, `api-v1.md:809-817`) |
| Errors | 400 `invalid_request` (missing `project_id`), 403 `project_forbidden` |
| Limits | identifier types 120/min (`intake.py:183`); definition 120/min, `ETag` / 304 (`api-v1.md:139`) |
| Status | `implemented today`; the station serves these from the signed config (4.3) |

### 3.3 Register a death: `POST /intake/deaths`

| Item | Value |
| --- | --- |
| Device caller | `interviewer` or `death_reporter` of the project and site |
| Request | `project_id`, `site_id`, `org_unit_id`, the register fields (`web_intake_service.py` `REGISTER_FIELDS`), optional `identifiers` `{<type code>: <text>}` (section 6), optional `client_death_id` (UUID). **Informant fields** (`informant_name`, `informant_phone`, `informant_phone_2`, address fields): only with a granted registration consent (5.4, 5.5) |
| Response | 201 new, 200 resend: `{"case": <detail>, "warnings": [...]}`; `warnings` only when present. The client reads `case.death_id`, `case.unique_id`, `case.updated_at`, `case.identifiers`, `case.can_edit_identifiers` (section 6) |
| Errors | 400 `invalid_request` (malformed: bad UUID, no `site_id`); 403 `project_forbidden` / `forbidden`; 409 `conflict` (the `client_death_id` belongs to another user's registration, `web_intake_service.py:3633-3643`); 422 `invalid_registration` for every content refusal, with `fields: ["identifiers.<code>", ...]` for a number (`intake.py:461`, `:129-142`); 429 `rate_limited` when `identifiers` is sent past the budget |
| Idempotency | `client_death_id`: a resend returns the stored case with 200, no warnings, and **ignores a different `identifiers` payload** (`intake.py:455-458`) |
| Limits | 16 KB body; `IDENTIFIER_RATE_LIMIT` 30/hour per user on requests carrying `identifiers` (`config.py:469`) |
| Status | `implemented today`; the `consent` object on this endpoint (section 5.4): server `implemented today` (uncommitted, digitva-gb8w.3); web and Expo capture `specified, not built (digitva-athy)` |

### 3.4 Correct a registration: `PATCH /intake/deaths/<death_id>`

| Item | Value |
| --- | --- |
| Device caller | interviewer whose reach opens the case, or the `death_reporter` who registered it; with `identifiers` only the identifier writer of section 6.3. **Station roster path** (owner decision 6): a roster user of a provisioned station acting as `station_supervisor` (section 6.3) |
| Request | only the register fields to change, optional `if_updated_at`, optional `identifiers` (may be the only key), optional `consent` (5.3, `client_draft_id: null`: a registration consent; an informant field the patch fills needs it granted, or a granted registration consent on file, 5.5). Station roster path adds (additive, 13): `acting_role: "station_supervisor"`, `reason` (text, 1..500 characters), `client_id` (UUID v4, the same id as the `death_correction` record of 4.2) |
| Response | 200 `{"case": <detail>, "warnings": [...]}` |
| Errors | 403 `forbidden` (also: station roster path without a station config in force, roster role, custodian or reach); 404 `not_found`; 409 `case_completed` (an interview is complete: this holds for every caller, web supervisors included, `web_intake_service.py:1177-1178`), `details_pending`, `death_stale` (`if_updated_at` is not current), `case_closed` (identifiers on a cancelled or confirmed-duplicate case; on the station roster path **any** change to a closed case); 409 `conflict` (a `client_id` reused with other content); 422 `invalid_death` (`intake.py:509`; unknown key, a list or object in a field, bad number with `fields: ["identifiers.<code>"]`, nothing to change); 422 `consent_required` / `consent_conflict` / `consent_invalid` as 5.3 |
| Idempotency | none today; without `if_updated_at` last write wins. Station roster path: `client_id` (same content returns the stored result) |
| Limits | 16 KB; identifier budget as 3.3 |
| Status | `implemented today` for interviewer and reporter; the station roster path: `implemented today` for the bundle `death_correction` record (uncommitted, digitva-gb8w.2: `update_death(..., station_roster=True)`); the HTTPS request keys `acting_role`, `reason`, `client_id`: `specified, not built (digitva-gb8w.8)` |

### 3.5 Registration numbers at any time: `PUT /intake/cases/<death_id>/identifiers`

| Item | Value |
| --- | --- |
| Device caller | the interviewer who registered, started or has an interview (draft) of the case, or the `death_reporter` who registered it and whose grant still reaches it (`web_intake_service.py:959-979`); or, on the **station roster path**, a roster user of a provisioned station acting as `station_supervisor` (section 6.3). Server supervisor, In-charge, PI and data manager writes stay **browser only**: under a device credential `supervised_case_condition` is false |
| Request | `{"identifiers": {<code>: <text> or null}, "if_updated_at": <iso, optional>}`, 1..50 codes, raw value at most 256 characters (`intake.py:543-548`, `death_identifier_service.py:67-68`). Station roster path adds (additive, 13): `acting_role: "station_supervisor"`, `reason` (text, 1..500), `client_id` (UUID v4, the same id as the `identifiers_set` record of 4.2). Any other key: 400 |
| Response | 200 `{"case": <detail>, "warnings": [...]}`; the case state does not change |
| Errors | 400 `invalid_request` with `fields: ["identifiers.<code>"]` for a rule refusal (note: **400 here**, 422 on POST and PATCH); 403 `forbidden`; 404 `not_found`; 409 `case_closed` (any device writer on a closed case, the station roster path included), `death_stale`, `conflict` (`client_id` reused with other content); 413; 429 `rate_limited` |
| Idempotency | a value equal to the stored one (blind index) is a no-op; station roster path also `client_id` |
| Limits | 16 KB; identifier budget |
| Status | `implemented today` for interviewer and reporter; the station roster path: `implemented today` for the bundle `identifiers_set` record (uncommitted, digitva-gb8w.2: `put_identifiers(..., station_roster=True)`); the HTTPS request keys: `specified, not built (digitva-gb8w.8)` |

### 3.6 Upload an interview: `POST /intake/submissions`

| Item | Value |
| --- | --- |
| Device caller | `interviewer` of the project and site |
| Request | `project_id`, `site_id`, optional `org_unit_id`, `death_id` (the server case id; on HTTPS a station-registered case is registered first, 3.3, and its returned `death_id` used), `client_draft_id` (UUID), `draft` (meta: `instrumentVersion`, `definitionSha256`, `definitionExtensions`, `startedAt`, `completedAt`, `deviceClockAt`, `interviewOutcome`), `completion: {valid, issues}`, `answers_json` (text), `answers_sha256` (64 hex) (`intake.py:872-949`) |
| Response | `{va_sid, case: {death_id, unique_id, status}, outcome, superseded, answers_sha256, kept, received_sha256, locked, can_code_now}` (`device-collection-api.md` "Result body") |
| Errors | 400 `invalid_request` (`client_draft_id` not a UUID); 409 `conflict` (another interviewer's `client_draft_id`, `web_intake_service.py:3140-3148`); 422 `answers_hash_required`, `answers_hash_invalid`, `invalid_interview` (over 1 MiB of answers, `web_intake_service.py:3097`; not an object; deeper than 6; a bad time or definition identity, `:3129-3138`) |
| Idempotency | `client_draft_id`; same hash returns the first result, other answers are a later version (last completed wins) |
| Limits | 2 MiB body, 1 MiB `answers_json` |
| Status | `implemented today`; the optional `consent` object (5.3), the reuse of a registration consent (5.4) and 422 `consent_required` / `consent_invalid` / `consent_conflict`: `implemented today` (uncommitted, digitva-gb8w.3) |

### 3.7 Other intake calls

| Endpoint | Device caller | Notes | Status |
| --- | --- | --- | --- |
| `POST /intake/submissions/<va_sid>/revisions` | the submitting interviewer | `api-v1.md:158`; HTTPS only | `implemented today` |
| `POST /intake/outstanding` | interviewer with a device session | 204; a cookie is 403 `device_session_required` (`intake.py:995-1008`) | `implemented today` |
| `GET /intake/cases`, `GET /intake/cases/<id>`, `GET /intake/deaths` | interviewer, reporter | exist and accept a bearer (Expo uses them); **not used by the offline app** (bundle spec Q6) | `implemented today` |
| `GET /coding/available`, `POST /coding/allocation`, `POST /coding/initial|finalize|not-codeable/<va_sid>` | coder | role gate `coder` / `coding_tester` verified (`app/routes/api/coding.py:144-145`, `:441-539`); per-route bearer acceptance of `/coding/allocation` and the workspace read **not independently verified** (bundle spec 6.1) | `implemented today` (gate); acceptance check in `digitva-gb8w.7` |

### 3.8 New for the offline app

| Endpoint | Device caller | Request / response | Errors | Idempotency / limits | Status |
| --- | --- | --- | --- | --- | --- |
| `GET /intake/consent-config?project_id=` | a roster user who may interview or register in the project | section 5.2 | 400 `invalid_request`, 403 `project_forbidden` | `no-store`; 120/min | `implemented today` (uncommitted, digitva-gb8w.3) |
| `GET /intake/station-config` | the station's **own device bearer** only (device id from the session) | the signed two-line station config file of bundle spec 6.4, same bytes as the browser export; carries `roster`, `custodian`, `designations` (4.1) and `purge` (section 7) | 401; 403 `device_revoked`; 404 `not_found` (no config issued) | `ETag` / 304; 60/hour per device | `implemented today` (uncommitted, digitva-gb8w.4; `app/routes/api/station_config.py`; "issued" = a custodian and an active roster member set and a config issued; owner decision 5) |
| `POST /auth/devices/current/signing-key` | station bearer | `{signing_public_key}`; 200 `{signing_key_id}` | 409 `conflict` (already set) | set once | `implemented today` (digitva-gb8w.5; a cookie gets 403 `device_session_required`, a bad key 400 `invalid_request` with `fields`; 10/min per IP) |
| `POST /intake/bundles`, `POST /intake/bundles/validate`, `GET /intake/bundles/<bundle_id>`, `GET .../receipt` | the station's own bearer (`device_id` equal to the manifest's) or a browser uploader | bundle spec 5.1-5.6 | bundle spec 5.2 codes (section 8) | `bundle_id`; 50 MiB; 10/hour per device and per uploader | `implemented today` (uncommitted, digitva-gb8w.2; `app/routes/api/bundles.py`, `app/services/bundle_ingest_service.py`; [api-v1.md](../current-state/api-v1.md) "Offline bundle ingest") |
| `GET /projects/<project_id>/station-config?device_id=` | none | admin, project PI or project data manager, browser: downloads the config in force. Issuing is a separate `POST` on the same path (CSRF, audited), so a GET never mints a config; custodian and roster: `PUT /projects/<id>/stations/<device_id>/custodian|roster` ([api-v1.md](../current-state/api-v1.md)) | 404 `not_found` (none issued) | | `not for devices`; `implemented today` (uncommitted, `digitva-gb8w.4`, `.8`) |

`not for devices` also: every `/intake/supervision/*` route, identifier-type
configuration (`/projects/<id>/identifier-types`), `GET /cases/export.csv`,
device enrolment codes, consent withdrawal recording (section 7), any
correction of a closed case.

## 4. Bundle records and station config

By reference, not repeated: container, limits and manifest (bundle spec 2.1,
2.2), sealed record lines (2.3), record types `death_registration`, `consent`,
`death_correction`, `interview_submission`, `identifiers_set`,
`coding_result`, `attachment_chunk` (reserved, not built, `digitva-jkvl`)
(2.4), what never goes in a bundle (2.5), signature (3.2), replay and age
(3.3), receipt (5.6), station config fields (6.4). Status: the station
config (6.4) and the device key (3.2) `implemented today` (digitva-gb8w.4,
.5, .8, uncommitted); the ingest of every record type but `attachment_chunk`, the report and the receipt `implemented today` (uncommitted, digitva-gb8w.2).

Fixed by this contract on top of the bundle spec:

- Every record's envelope carries `actor_user_id` **and** `acting_role`
  (4.1).
- `death_registration` gains optional `consent_client_id` (section 5.5).
- `consent.client_draft_id` is `null` for a registration consent (5.3).
- New record types `death_correction` and `identifiers_set` (4.2).
- The station config's `projects[]` entries gain `sealed_field_ids` (the
  served sealed set, section 6.6) and `consent` is exactly the consent-config
  object of 5.2; the config carries `roster`, `custodian` and `designations`
  (4.1).
- `projects[]` entries also carry display maps (additive, optional for a
  reader; `implemented today`, uncommitted, digitva-gb8w.4): `site_names`
  `{site_id: name}` for `sites`; `org_unit_paths` `{org_unit_id: "District,
  Block, PHC"}` for `org_units` (active unit names from the top of the
  project tree down to the unit, `", "` joined); `org_unit_sites`
  `{org_unit_id: site_id}`, the site of the roster role naming the unit. A
  roster grant with a null org unit covers the org units of its site. The
  server keeps no site per unit (a site grant reaches the whole tree), so the
  roster is the source of this map.
- The receipt body gains `purge` (section 7).
- `projects[]` entries carry the project's form policy (additive; 4.3):
  `form_options` and `translations`.
- `projects[]` entries carry `coding_mode` (additive, so
  `station_config_format_version` stays 1 under section 13: a reader ignores
  it; 4.3): `icd11_doris`, `icd10` or `null`.

### 4.1 Station roster, custodian and acting role (`digitva-gb8w.8`)

**Onboarding** (owner decisions 1, 2). A station is **onboarded** when it is
enrolled (`auth_devices` row with a signing key) **and** a responsible person
from the station, the **custodian**, has been identified and verified by an
admin or project data manager, and a station config has been issued for it.
The custodian is recorded in the enrolment (server side, audited) and in
every signed station config. Only an onboarded station's bundles are ingested
(bundle spec 5.2, `station_not_onboarded`).

Station config keys (`implemented today`, uncommitted, digitva-gb8w.4, digitva-gb8w.8; `app/services/station_config_service.py`; `user_id` and `verified_by_user_id` are `va_users.user_number`, an integer column added for this because `va_users.user_id` is a UUID):

| Key | Shape |
| --- | --- |
| `custodian` | `{name, designation, phone, email, onboarded_on, verified_by_user_id}`: `designation` a code of `designations`; `phone` 10 digits or `null`, `email` text or `null`, at least one present; `onboarded_on` `YYYY-MM-DD`; `verified_by_user_id` the server user who verified |
| `designations` | `[{code, label}]`, the list the roster's `designation` uses; default `medical_officer` "Medical Officer", `health_supervisor` "Health Supervisor", `health_worker` "Health Worker / ANM / MPW", `other` "Other" |
| `roster` | `[{user_id, name, designation, roles: [{role, project_id, site_id, org_unit_id}], active}]`, sorted by `user_id`: `user_id` the **server** user id (integer); `name` display name; `designation` a code; `role` one of `death_reporter`, `interviewer`, `station_supervisor`, `coder`; `org_unit_id` may be `null` (the whole site); `active` boolean. No email, phone, password or PIN |

Who issues it: the admin or project data manager who exports the config;
each roster role is chosen by the issuer and audited. `death_reporter`,
`interviewer` and `coder` roster roles are issued only to users holding that
server grant on the same project and site.

**Roles and the device projection.** Device tokens carry only `interviewer`,
`death_reporter`, `coder`, `coding_tester`, `reviewer`
(`grants.py:59-65`). The roster roles `death_reporter`, `interviewer` and
`coder` are those server grants, re-checked at ingest. `station_supervisor`
is a **roster-level role, not a device grant**: it never appears in
`/me/access`, never widens `supervised_case_condition`, and authorizes only
the two correction writes of 4.2 and the station roster path of 3.4 and 3.5.
Its authorization basis is: the admin-signed roster names the user with
`station_supervisor` for the case's project and site, on an onboarded station
(custodian recorded), in the station config in force (the bundle's
`station_config_id`, or the newest config issued to the bearer's device on
HTTPS), the user is active and still holds an active server grant in the
device projection on that site. Interviewer-of-the-case and reporter-who-
registered rules are unchanged for every other acting role.

**Acting role.** The user picks the acting role **per task** from their
active roster roles; the app shows only that role's screens. Every record
carries `actor_user_id` and `acting_role`; the server refuses a record whose
`acting_role` is not one of that user's roster roles in scope (`forbidden`).
A `coder` acting role always gets the **masked view** (no informant data, the
sealed set of 6.6 omitted), even when the same person is also an interviewer
on the station.

**Provisioned vs sandbox.**

| | Provisioned (onboarded) station | Unprovisioned sandbox |
| --- | --- | --- |
| Roster source | the signed station config, **read-only** on the roster screen | a local editable setting |
| `user_id` | server user id | a local UUID, never sent |
| Edits | none on the station (a new config from the server) | names, designation from an editable designation list (same defaults), ticks for reporter, interviewer, station supervisor, coder, active; a local change log of each edit (who, when, what) |
| Sign-in | per-user PIN and encrypted store (section 10) | no passwords; a "who am I now" picker |
| Ingestable | yes | **never**: the bundle writer refuses without a station config, and sandbox records are never remapped into a project |

### 4.2 Correction records: `death_correction` and `identifiers_set`

Owner decision 6. Sent by a roster user acting as `station_supervisor` on a
provisioned station; the server applies them through the **same services** as
`PATCH /intake/deaths/<id>` (`update_death`) and
`PUT /intake/cases/<id>/identifiers` (`put_identifiers`), with the
authorization of 4.1 in place of the device writer rule.
Bundle records: `implemented today` (uncommitted, digitva-gb8w.2); the HTTPS
station roster keys: `specified, not built (digitva-gb8w.8)`.

Common fields (plus the envelope `record_type`, `client_id`, `project_id`,
`actor_user_id`, `acting_role` = `station_supervisor`, `recorded_at`):

| Field | Rule |
| --- | --- |
| `client_id` | UUID v4, new per correction; the idempotency key (same content: `duplicate`; other content: `conflict`); equal to the HTTPS `client_id` of 3.4 / 3.5 when sent both ways |
| `death_ref` | the target case: `{"client_death_id": uuid}` or `{"death_id": uuid}` |
| `reason` | text, 1..500 characters, NFC; stored in the audit row only, never logged |
| `if_updated_at` | the case's server `updated_at` the station last received, or `null` when it has none |
| `base_client_id` | when `if_updated_at` is `null`: the `client_id` of the last station write this edit builds on (the `death_registration` or an earlier correction of the same case); else `null` |

Type fields:

- `death_correction`: `changes` `{<register field>: <value>}`, only the
  fields changed, names of `REGISTER_FIELDS`; informant fields only with a
  granted consent on the case (5.4). No `identifiers` key (that is
  `identifiers_set`).
- `identifiers_set`: `identifiers` `{<type code>: <text> or null}`, 1..50
  codes, as `PUT .../identifiers`.

Server rules (all server validation still applies):

- Identifier rules of 6.1; duplicates warn, never block (6.4).
- **Stale**: `if_updated_at` not current, or `base_client_id` not the last
  applied station write of that case: `rejected`, reason `death_stale`; the
  station shows it to a supervisor to redo against the current case.
- **Interview complete**: a `death_correction` on a case with a completed
  interview is `rejected` `case_completed` (as for every caller today);
  `identifiers_set` is allowed after the interview.
- **Closed cases** (cancelled or confirmed duplicate): station supervisors
  may **not** correct them: both types `rejected` `case_closed`; closed-case
  corrections need the web. (Stricter than the server today, which lets
  anyone with reach edit register fields of a closed case.)
- **Sealing**: values are sealed at rest by the server as any register write.
- **Limits**: at most 500 correction records per bundle; each record's body
  at most 16 KB; `identifiers_set` counts against `IDENTIFIER_RATE_LIMIT` of
  the actor.
- **Audit**: every accepted correction writes the existing `details_edited`
  / identifier audit with before and after values (in `changes`, never in a
  log or `reason` text) plus `actor_user_id`, `acting_role`, `device_id` (the
  station id; v1 has no separate station table), `station_config_id`,
  `bundle_id` (`null` on HTTPS), `client_id` and
  `authorized_by: "station_roster"`.
- Consent withdrawal is **not** a correction: web only (section 7).

### 4.3 Forms, modules and languages on the station

`implemented today` (uncommitted). The station offers exactly the
instruments, modules and languages the project offers on the server, under
the same per-project policy. Where no policy governs a choice, the station's
Settings decide it (below, "Station Settings").

- **What the config carries.** Each `projects[]` entry has `form_options`:
  the body `GET /organization/<project>/form-options` serves
  (`form_types`, `enabled_extensions`, `default_locale`, `available_locales`,
  `narration_languages`, `translation_versions`, `instrument_version`,
  `definition_sha256`, ...), built by `form_options_payload`; and
  `translations`: `{locale: body}`, the body
  `GET /instruments/<code>/translations/<locale>` serves (`export_translations`)
  for each non-English locale in `available_locales` that is servable
  (active or `in_review`, the `translations_response` gate). Built by
  `station_config_service._form_policy`. Canonical JSON makes those strings
  NFC; nothing hashes them.
- **The definition.** The station binary embeds
  `app/data/who-va-2022.composed.json` and serves a project's slice exactly as
  `served_form_service` does: the items of disabled modules dropped,
  top-level `extensions` = the sorted enabled names that are composed-file
  tags, Python `json.dumps(ensure_ascii=False, separators=(",", ":"),
  sort_keys=True)` bytes, so the SHA-256 is the server's. Pinned by
  `tests/fixtures/served_definition_vectors.json` (Python authority
  `tests/test_served_definition_vectors.py`, Rust
  `digitva-db` `instrument::tests::served_definition_vectors`).
- **Import.** A config whose `form_options` names an instrument other than the
  composed one, an `instrument_version` the binary does not carry, or a
  `definition_sha256` its slice does not match is refused whole: 422
  `instrument_version_unsupported`, the message naming both versions. A
  config with a project lacking `form_options` (issued before this change) is
  refused alike: 422 `form_policy_missing`, issue a new one. The import
  accepts files up to 16 MB (translations make a config of a few MB).
- **Serving** (`digitva-server`): `GET /organization/<project>/form-options`
  returns the stored body; `GET /instruments/<code>/definition?project_id=`
  returns the slice with `ETag` = `X-Definition-SHA256` and 304 on
  `If-None-Match`, and `?version=&extensions=` the exact earlier slice (404
  `version_unknown` for another version, 422 `invalid_extensions`);
  `GET /instruments/<code>/translations/<locale>` returns the stored body
  (`en`: version 0, empty maps), with `?project_id=` only an offered locale,
  else 404. The interviewer picks the interview language from
  `available_locales` in the shared UI, as online.
- **Drafts.** The station accepts the app's autosave
  `PATCH /intake/drafts/<id>` (`{sections, current_section, meta}`) and keeps
  the definition pin from `meta`; the `interview_submission` record's `draft`
  carries that `instrumentVersion`, `definitionSha256` and
  `definitionExtensions` (`definitionSha256` absent only for a draft that
  recorded none).
- **Sandbox.** Before any config (project `1`, never exported) the station
  serves the composed form with the modules chosen in Settings (default every
  module) and English only; it is not a server project, so this overrides no
  policy. The served bytes and SHA-256 equal the server's for the same set
  (`instrument::tests::sandbox_selection_equal_to_a_vector_set_yields_its_sha`).
- **Station Settings** (owner decision 2026-10-21, `digitva-7o4h`,
  `digitva-r7gr`). `GET /api/v1/station/settings` returns
  `{modules: [{code, label, enabled}], modules_locked, coding_mode,
  coding_mode_locked, available_coding_modes: ["icd11_doris", "icd10"]}`;
  `modules` lists every tag of the composed file (`abha`, `death_summary`,
  `medical_records`, `narration_language`, `social_autopsy`) with a fixed
  English label (the composed file carries none). `PUT` takes
  `{enabled_modules?: [code], coding_mode?}` (at least one): 400
  `validation_error` for an unknown module or mode, 409 `policy_locked` for a
  field a policy governs; nothing is saved unless the whole request is valid.
  Precedence: a provisioned project's `form_options.enabled_extensions` wins
  (`modules_locked` true; the GET shows the union over the config's projects);
  a project whose `form_options` lacks `enabled_extensions` is served the local
  selection. Coding mode `icd11_doris` sets the
  workspace's `project_mode: "unmasked_doris"`, `icd_classification: "icd11"`;
  `icd10` sets `project_mode: "unmasked_simple"`, `icd_classification:
  "icd10"`, `doris: null` (search `GET /icd10/2019-2/coding-search/<va_sid>`).
- **Coding mode in the config** (owner decision 2026-10-22, `digitva-lmxr`).
  Each `projects[]` entry carries `coding_mode`, the station mode the
  project's own coding mode locks the station to: `icd11_doris` for an
  unmasked DORIS (ICD-11) project, `icd10` for an unmasked simple (ICD-10)
  project, and **`null` when the project's mode has no station equivalent**:
  masked DORIS (no station workspace), and masked simple (its final needs
  the coder's Step 1 `initial`, which the station's unmasked workspaces never
  make, so ingest could not land it). For a project with `null` the station
  does not code at all: no coding queue or workspace for it, and no
  `coding_result` for it. A provisioned station shows the mode as locked
  (`coding_mode_locked` true, `PUT` of `coding_mode` 409 `policy_locked`); a
  config before this key (absent) leaves the local choice. With `null`,
  `GET /coding/projects` leaves the project out (`station_coding_disabled`
  true when none is left), the coding queue and history leave its cases out,
  and the workspace (other than `mode=view`), allocation, code-now and the
  initial, final and not-codeable saves answer 409
  `station_coding_not_enabled` ("Coding for this project is done on the
  server."). Settings shows the first project's (by id) mode with `coding_mode`
  null when that project is not coded on the station. Station side
  `implemented today` (uncommitted, `digitva-db` `project_coding_mode`); server
  `implemented today` (uncommitted, `station_config_service._project_entry`).
- **Coding mode on the record.** A `coding_result` record carries
  `coding_mode` (`icd11_doris` | `icd10`), the mode the station was in when the
  final or not-codeable result was saved (absent on records saved before this
  field). Server ingest (`digitva-lmxr`, bundle spec 2.4 Q5) accepts a result
  from a station registered and active for the project (else
  `offline_coding_disabled`; `self_coding_enabled` is not required) whose
  actor is on the bundle's signed roster with the `coder` role on the case's
  site (else `actor_not_station_coder`), for an interview that station
  uploaded (else `not_available`), when the mode matches the project's coding
  mode:
  `icd11_doris` an unmasked DORIS project, `icd10` an unmasked simple project
  or a masked simple one when the record carries `initial`; another pair is
  `coding_mode_mismatch`, an unknown mode `coding_mode_unsupported`, and a
  record without `coding_mode` keeps the v1 rule (masked simple only). The
  server validates as the online coder save does; an `icd11_doris` final is
  held `pending` (`doris_pending`) and the server reprocesses its certificate
  with the WHO engines it pins (the station's own engine results are
  advisory), so a receipt names it applied only after that run.

## 5. Consent

### 5.1 Where consent is taken

| Channel | When | Status |
| --- | --- | --- |
| Web, Expo and offline app registration | at registration, before informant name, phone or address are saved (owner decision 4); informant fields may be entered once a granted record exists | `specified, not built (digitva-athy; station: digitva-gb8w.3)` |
| Interview (all channels) | reuses the case's granted registration consent; a new consent at the interview start only when none is on file for the case or the informant is a different person (that consent names the attempt's `client_draft_id`) | `specified, not built (digitva-gb8w.3, digitva-athy)` |
| Withdrawal | web only, recorded by a supervisor or data manager; the station is told to purge (section 7) | `specified, not built (digitva-athy)` |

There is **no `consent_status` on any case reply**, and no rule of the form
"phone shown only if granted": phones are shown to the roles that see them
today (pii-encryption-at-rest decision 4).

### 5.2 `GET /intake/consent-config` reply

```json
{"project_id": "P1", "consent_required": true,
 "notice_versions": [
  {"notice_version_id": "<uuid>", "version": 3, "language": "hi",
   "text": "<exact notice text>", "text_sha256": "<64 hex>",
   "purposes": [{"code": "record_interview", "label": "...", "required": true}],
   "covered_fields": ["informant_name", "informant_phone", "informant_phone_2",
                      "address", "Id10007"],
   "allowed_modes": ["spoken", "tap", "signed"], "witness_allowed": true}],
 "contacts": {"deletion": {"email": "...", "phone": "..."},
   "mentor_institution": {"name": "...", "email": "...", "phone": "..."},
   "central_team": {"email": "...", "phone": "..."},
   "dpo": {"name": "...", "email": "...", "phone": "..."},
   "districts": {"<org_unit_id>": {"name": "...", "email": "...", "phone": "..."}}},
 "retention": {"period_days": 1825, "expiry_action": "erase"},
 "refusal_behaviour": "interview_without_informant_data"}
```

- `notice_versions`: only non-retired versions; `version` is an integer and
  the client compares it **numerically**, never as text. `text` is the exact
  string the client shows (it may contain Markdown; the client renders it but
  hashes the string). `text_sha256` = lowercase hex SHA-256 of the UTF-8 bytes
  of `text`; the client MUST check it and refuse a version that does not match.
- `purposes`: every purpose of the version, from the project's consent
  settings; `required` is per purpose.
- `covered_fields`: register field names and payload field ids whose
  non-empty value needs a granted consent.
- `allowed_modes`: non-empty subset of `spoken`, `tap`, `signed`.
- `witness_allowed`: boolean. When false the client sends
  `witness_present: false` always; when true it records whether a witness was
  present. No witness name ever.
- `contacts.districts`: keyed by the district unit's `org_unit_id`; a
  district without a contact is **absent**, and the client shows
  `central_team` instead. `dpo` may be `null`.
- `retention`: `period_days` (integer, or `null` for "until the project
  ends") and `expiry_action` `erase` or `lock`. Shown in the notice; the
  client enforces nothing from it.
- `refusal_behaviour`: v1 has one value, `interview_without_informant_data`:
  if a required purpose is refused the interview may still run, but every
  `covered_fields` field must be empty in what is sent. New values are added,
  never changed; a client that meets an unknown value MUST NOT start an
  interview in that project ("consent settings need an app update").
- A project with `consent_required: false` sends `notice_versions: []`; the
  submission rules of today apply unchanged.

### 5.3 The consent object

One shape everywhere: the `consent` key of `POST /intake/submissions`, the
`consent` key of `POST /intake/deaths` (5.4), and the body of a bundle
`consent` record (bundle spec 2.4).

| Field | Rule |
| --- | --- |
| `client_id` | UUID v4, lowercase; the idempotency key (server column `client_consent_id`) |
| `client_draft_id` | the interview attempt it was taken for, or `null` for a registration consent (5.4); the record is keyed by the case. On `/intake/submissions` it MUST equal the body's `client_draft_id` |
| `notice_version_id` | from the consent config |
| `notice_language` | BCP 47 code of the text shown, equal to the version's `language` |
| `notice_sha256` | the version's `text_sha256`, recomputed by the client over the exact `text` string served (not the rendered Markdown) |
| `decision` | `granted` or `refused` (`refused`: some required purpose refused) |
| `purposes` | `[{"code": str, "granted": bool}]`, **every** purpose of that version, sorted by `code` |
| `mode` | one of the version's `allowed_modes` |
| `witness_present` | boolean (no witness name) |
| `supersedes_client_id` | UUID of the consent it corrects, or `null` |
| `recorded_at` | RFC 3339 with offset, the station clock |

In a bundle the record also carries `death_ref` (`{"client_death_id"}` or
`{"death_id"}`) and the record envelope keys (`record_type`, `project_id`,
`actor_user_id`; bundle spec 2.4); on HTTPS the case comes from the body.

Server checks (`implemented today`, uncommitted, digitva-gb8w.3; one gate for `POST`
and `PATCH /intake/deaths`, `/intake/submissions`, its `/revisions` and the browser's
`/intake/drafts/<id>/submit`, which carries no consent and relies on one on file): 422 `consent_required`
with `fields: ["consent"]` when the project requires consent, the answers or
register fields carry a non-empty covered field, and no granted consent with
every required purpose granted is given or on file for that interview attempt
or, for a registration or a submission not carrying a new consent, for the
case (5.4);
422 `consent_invalid` with `fields: ["consent"]` for an unknown or retired
notice version, a language mismatch, a hash mismatch, a missing or extra
purpose, a mode not allowed, `witness_present: true` where not allowed, or a
`client_draft_id` other than the body's, or a granted consent whose notice
version's `covered_fields` lack a filled covered field (`fields` then names those
fields, never values); 409 `conflict` when a `client_id`
is reused with different content (same content is a duplicate, 200); 422
`consent_conflict` for a refused consent with a covered field filled. Body
`{error, code, fields}`, no `reason` key. Append-only: a correction is a new
consent with `supersedes_client_id`.

### 5.4 Consent at registration (owner decision 4)

Web, Expo and the offline app alike: when the project requires consent and
the registration carries a non-empty informant name, phone or address field,
the body MUST carry `consent` with `client_draft_id: null` (a registration
consent), else 422 `consent_required`, `fields: ["consent"]`. The interview
reuses it: a later submission on that case needs no new consent unless the
informant is a different person, in which case the app takes a new one for
that attempt (with its `client_draft_id`). The server accepts an interview's
covered data when a granted consent exists for that `client_draft_id`, or a
granted registration consent exists on the case and the submission does not
carry a new one. Server: `implemented today` (uncommitted, digitva-gb8w.3); web capture: `implemented today` (uncommitted, digitva-athy: registration sends `consent`; a browser interview records its decision first on `POST /intake/drafts/<id>/consent`, see [respondent-consent-notice-draft.md](respondent-consent-notice-draft.md) "Web flow"); Expo native capture: `implemented today` (uncommitted, digitva-0vgh; see [respondent-consent-notice-draft.md](respondent-consent-notice-draft.md) "Phone flow").

### 5.5 Informant fields on a station registration

A station registration carries informant fields (`informant_name`,
`informant_phone`, `informant_phone_2`, `address`, `address_house_street`,
`address_village_ward`, `address_landmark`) only once a granted registration
consent exists: on HTTPS as `consent` on `POST /intake/deaths`
(`client_draft_id: null`), in a bundle as
`death_registration.consent_client_id` naming that `consent` record, which the
server processes in the same savepoint as the registration (case row, then
consent, then the informant fields); without a granted consent the
registration is rejected `consent_required`. A registration made without
consent carries none of them; they can be added later with the consent by
`PATCH` (3.4) or, by a station supervisor, a `death_correction` (4.2), both
only until an interview is complete. The WHO 2022 instrument has no informant
phone question, so the register is the only place the phone travels.

### 5.6 Client consent-gate rules (the offline team implements)

- The gate is keyed on the **case**: a granted registration consent covers
  the registration's informant fields and every later interview attempt with
  the same informant. The app asks again, as a consent naming the attempt's
  `client_draft_id`, only when none is on file for the case or the informant
  is a different person.
- No interview starts without a usable consent config: on a parse error, an
  unknown `refusal_behaviour`, a hash mismatch or an expired station config
  the app blocks new interviews in that project. **No silent fallback** to
  hardcoded defaults or an older version.
- **Strict capture (station, 2026-10-22)**: a consent is captured only against
  a notice version served in the project's consent config (`notice_version_id`,
  `language`, `text_sha256`, purpose codes all from that config). When the
  project has no usable notice or purposes loaded, the station records no
  consent and writes no informant fields, with no fallback to a default
  notice: 422 `consent_notice_unavailable` ("This project has no consent
  notice yet, so informant details cannot be recorded offline.").
- Notice version choice compares `version` as an integer.
- A `client_id` is never reused for different content; a correction is a new
  record with `supersedes_client_id`.
- Scrubbing covered fields after a refusal never edits a hashed text in
  place: the scrubbed answers are a new revision with a new `answers_json` and
  a new `answers_sha256`.

## 6. Registration identifiers

### 6.1 Write

`identifiers` is an object `{<type code>: <text>}` of the project's active
types; non-object or non-text is a content refusal. The server normalises
(NFKC, trim, collapse whitespace, upper-case:
`death_identifier_rules.py:64-73`) then checks length, character type and the
type's `pattern` with an **anchored full match** (`re2.fullmatch`,
`death_identifier_rules.py:304-333`). A client pre-check MUST normalise the
same way and use a full match (Rust: `Regex::new(&format!("^(?:{})$", p))`;
`is_match` on the bare pattern is wrong); the server is authoritative.
`required_at_report` types are enforced at registration (422
`invalid_registration` naming `identifiers.<code>`). Status: `implemented today`.

### 6.2 Read

Every case reply carries `identifiers` as a **list** in `sort_order`
(`death_identifier_service.py:338-404`):

- a value viewer: `[{"code", "label", "value"}]` for every active type,
  `value: null` where nothing is stored;
- everyone else: `[{"code", "label", "present": true|false}]` with the
  `value` key **omitted**;
- an undecryptable value degrades to `present: true`.

`can_edit_identifiers` (boolean) rides on the same replies; the client treats
an **absent** flag as `false` (`api-v1.md:822`). Status: `implemented today`.

### 6.3 Who writes from a device

Registration: whoever may register. Later (`PATCH` with `identifiers`, `PUT`):
the interviewer who registered, started or interviewed the case, or the
reporter who registered it (3.5), `implemented today`; or a roster user acting
as `station_supervisor` on a provisioned station, under the authorization
basis of 4.1, never on a closed case: in a bundle `implemented today`
(uncommitted, digitva-gb8w.2), over HTTPS `specified, not built
(digitva-gb8w.8)`. Server supervisor, In-charge, PI and data
manager writes are browser only.

### 6.4 Warnings

`warnings: [{"code": "identifier_in_use", "field": "identifiers.<code>",
"message": <text>}]` (`death_identifier_service.py:182-238`): the write is
kept. Under a device credential the message is always the generic "This
number is already on another case in this project." (the detail needs
supervision reach or admin, both absent from the device projection). There
are **no `matching_death_ids`** or other case ids in a warning: an offline
`identifier_warnings` shape that lists them would leak other cases and is not
part of this contract. Status: `implemented today`.

### 6.5 Aadhaar (`Id10073`) and phones

- `Id10073` leaves the capture screen reduced: the only accepted forms are
  absent / not answered, `XXXXXXXXX` followed by the last 3 ASCII digits
  (`XXXXXXXXX123`), or `XXXXXXXXXXXX` (fewer than 3 digits typed). The server
  accepts both unflagged (`national_id.py:72-81`, `:101-102`) and reduces
  again as the authority. No hash of the number, no full number on the
  device, ever (pii-encryption-at-rest decision 11). A 12- or 16-digit run in
  any other free-text answer is masked by the server; the app should not
  produce one. `answers_sha256` is over the reduced text. Status:
  `implemented today` (server side).
- Phones: exactly 10 ASCII digits; the client strips spaces, hyphens and
  parentheses, then drops a leading `+91`, `91` or `0` when 10 digits remain
  (field-data-collection "Phone numbers"; server `web_intake_service.py:185`,
  `:656-670`), shows 3-3-4, sends the 10 digits. No partial digits anywhere:
  not in a list, notification, log, export or file name; masking means no
  digits at all. Phones are encrypted on the server and shown and callable
  for the roles that see them today. Status: `implemented today`.

### 6.6 The sealed set (the coder view's exclusion list)

The masked coder view and every export of the offline app MUST omit the
server's sealed set, which is `PII_FIELDS` plus the form type's admin-flagged
`is_pii` fields (`pii_field_registry.py:137-161`, `sealed_field_ids` at
`:184-194`). Today's `PII_FIELDS`: `Id10007`, `Id10010`, `Id10010a`,
`Id10010b`, `Id10010c`, `Id10017`, `Id10018`, `Id10055`, `Id10057`,
`Id10061`, `Id10062`, `Id10070`, `Id10071`, `Id10072`, `Id10073`,
`visit_address`, `visit_remarks`, `abha_number`, `abha_address`. The offline
lists reviewed on 2026-10-21 miss `Id10055`, `Id10057`, `Id10071`, `Id10072`,
`Id10010a/b/c`, `visit_address` and `visit_remarks`. The app MUST NOT
hardcode the list: it reads `projects[].sealed_field_ids` from the station
config (`implemented today`, uncommitted, digitva-gb8w.4: the union over the
project's active forms' form types); the list above is the floor.

**Open check.** The narrative `Id10476` is not in `PII_FIELDS` and coders see
it today (`app/utils/va_mapping/va_mapping_02_fieldcoder.py`). Whether the
offline app's SmartVA input treats `Id10476` exactly as the server's SmartVA
preparation does is not verified; to be checked before offline SmartVA
results are compared with the server's.

## 7. Purge (withdrawal and closed cases)

A withdrawal is recorded on the web by a supervisor or data manager
(`digitva-athy`); the station never records one. The station learns of it
through a `purge` list: an array of client ids (UUID strings), sorted,
unique. A withdrawal puts the withdrawn consent's `client_id` on it; a closed
case puts its `client_death_id` (or a `client_draft_id`). The station deletes
every local record carrying that id and everything under it (a consent
`client_id` purges that consent and the informant data recorded under it; a
`client_death_id` purges the case's interviews, consents and coding
results), then drops it from its local case list. **One format on both
paths** (owner decision 5):

| Channel | Carrier | Status |
| --- | --- | --- |
| Bundle path | `purge` in the signed station config (bundle spec 6.4) and in every receipt body | station config: `implemented today` (uncommitted, digitva-gb8w.4; always `[]` until withdrawal exists, hook `station_config_service.purge_client_ids`, digitva-athy, which must issue a new config on a withdrawal); receipt: `implemented today` (uncommitted, digitva-gb8w.2; the same hook) |
| HTTPS path | the same signed station config served to the station's device bearer, `GET /intake/station-config` (3.8); the app fetches it at sign-in and at least daily while online | `implemented today` (uncommitted, digitva-gb8w.4) |

Rejected alternative for HTTPS: a purge list on the refresh reply. The
refresh is per user session while purge is per station, and the signed file
gives one verification path online and offline. The server never sends a
reason or any personal data with a purge id.

## 8. Errors catalogue

HTTP shape: `{"error", "code"}` (+ `fields`). Codes a device can receive:

| Status | Codes |
| --- | --- |
| 400 | `invalid_request` (malformed; on `PUT .../identifiers` also a rule refusal with `fields`) |
| 401 | `unauthorized`, `device_invalid`, `invalid_credentials`, `refresh_reused`, `session_revoked`, `session_ended`, `session_expired`, `refresh_invalid` |
| 403 | `forbidden`, `project_forbidden`, `terms_required`, `device_session_required`, `email_unverified`, `maintenance`, `device_revoked`, `no_interviewer_grant` |
| 404 | `not_found` |
| 409 | `conflict` (client id of another user, consent id reuse), `case_closed`, `death_stale`, `case_completed`, `details_pending`, `refresh_retry_race`, `revision_locked`, `case_already_submitted`, `case_state_conflict`; station only: `policy_locked`, `station_coding_not_enabled` (4.3) |
| 411 / 413 | `length_required`, `payload_too_large` |
| 422 | `invalid_registration`, `invalid_death`, `invalid_interview`, `answers_hash_required`, `answers_hash_invalid`, `invalid_reason`, `invalid_attempt`, `invalid_visit`; new: `consent_required`, `consent_invalid`, `consent_conflict` (`digitva-gb8w.3`) |
| 429 | `rate_limited` |

Bundle whole-file refusals (bundle spec 5.2, 3.3, 3.4): `payload_too_large`,
`manifest_invalid`, `bundle_version_unsupported`, `device_unknown`,
`device_revoked`, `signing_key_unknown`, `signature_invalid`,
`body_hash_invalid`, `bundle_id_reused`, `bundle_too_old`,
`bundle_from_future`, `bundle_key_unknown`, `station_not_onboarded` (no
custodian recorded, or the manifest's `station_config_id` was not issued to
this device), `station_config_expired` (the bundle's `created_at` is after
the `expires_at` of the station config it names; import a renewed config and
export again). Per-record outcomes `accepted`, `duplicate`, `superseded`,
`pending`, `rejected`, `not_processed`, with reasons `record_invalid`,
`conflict`, `depends_on_rejected`, `actor_unknown_on_device`, `forbidden`,
`consent_required`, `consent_invalid`, `consent_conflict`,
`offline_coding_disabled` (the station is not registered and active for the
project: revoked since it made the bundle), `actor_not_station_coder` (the
actor's roster entry in the bundle's config names no `coder` role for the
case's project and site, or its server grant has gone),
`coding_mode_unsupported`, `coding_mode_mismatch`,
`coded_version_superseded`, `held_by_another`, `not_available`, `invalid_cod`,
`invalid_doris`, `final_blocked`, `attachments_incomplete`,
`death_stale`, `case_completed`, `case_closed`, plus every HTTPS content code
above. `implemented today` (uncommitted, digitva-gb8w.2); also 403
`forbidden` for a bundle whose `project_ids` is not the station's project or
an uploader who may not upload, 409 `conflict` for a bundle still being
ingested, 413 for a record line or record count over its limit, and the
per-record `not_ready`, `allocation_exists` or `doris_pending` code on a
`pending` coding result.

A client branches on `code`, never on `error` text, and treats an unknown
code by its HTTP status class.

## 9. Local server requirements (`digitva-server`)

Accepted as the app's own backend. It MUST:

1. Bind `127.0.0.1` only (never `0.0.0.0` or a LAN address); on Android
   prefer an in-process bridge over a TCP port.
2. Require a random per-launch 256-bit bearer token on **every** route,
   GETs included, compared in constant time; the token lives in memory only.
3. Check `Host` (exactly `127.0.0.1:<port>` or `localhost:<port>`) and
   `Origin` (the app's own origin or none) on every request, against DNS
   rebinding.
4. Send **no CORS headers** (drop tower-http's `cors` feature) and
   `Cache-Control: no-store` on every reply.
5. Put no personal data in URLs, query strings, logs or crash dumps (ids,
   counts and error codes only).
6. Never mint central-server ids: local rows are keyed by client UUIDs
   (`client_death_id`, `client_draft_id`, consent `client_id`, coding
   `client_id`); a local project key such as `project_id = 1`
   `PHC-STANDALONE` never leaves the station; records carry the server
   `project_id`, `site_id` and roster `user_id` from the station config.
7. Never serve the shared web JS an access body with supervisor, data
   manager, PI or admin powers: its `/me/access` equivalent is the device
   projection (interviewer, death_reporter, coder, coding_tester, reviewer)
   of the signed-in roster user's roster roles. A `station_supervisor` roster
   role enables only the local correction screens of 4.2 under that acting
   role; it is never presented as a server supervisor grant.
8. Do none of the central duties of section 1.

### 9.1 Station behaviour (2026-10-22)

- **Bundle export** (`.dvb` download and its JSON form): a pending record that
  fails the bundle rules is held back, not dropped; it stays pending and is
  listed as `{client_id, reason}`. A registration whose consent is held back
  is held back with it. The JSON reply carries `records_held_back` (the list)
  and `sandbox_records_excluded` (count of pending sandbox records, which are
  never exportable, 4.1); the binary download carries the header
  `x-bundle-records-held-back` (the count) beside `x-bundle-record-count`.
  When every pending record is held back no bundle is built: 422
  `records_held_back` with the list in `records_held_back`.
- **Coder Step 1**: station workspaces are unmasked only, so
  `POST` of an initial (Step 1) coding returns 409 `not_masked` and the
  station goes straight to the final (single-step) coding save. The final
  reply is `{va_sid, workflow_state, <assessment id>}` and has no
  `odk_synced` (no ODK on a station).
- **Receipt import** reply: `accepted_count` is the number of receipt records
  whose outcome is `accepted`, `duplicate` or `superseded`; `pending_count` those
  `pending` (kept, with the server code such as `doris_pending`);
  `rejected_count` those `rejected` (kept, `sync_state = rejected`).
  `deleted_count` (also `acknowledged_deleted_count`) is the number of local
  records actually deleted, which can be lower than `accepted_count` when a
  record was already deleted earlier. `purged_count` and `purged_ids` as
  section 7.
- **Coding history** keeps a coding result the server holds as `pending` or
  refused after a receipt deletes its accepted interview. The coding row
  stores the case unique id and form code at coding time (no age, sex or
  answers); the history reads from them with the server status and code, and
  drops the row when a later receipt accepts the result and the row is
  deleted.


## 10. Station modes and data protection

- **Standalone (unprovisioned)**: a clearly labelled local **sandbox** with
  the editable local roster of 4.1. Its records are never ingestable and
  never remapped (owner decision 2): project, identifier type codes (a local
  `crs_reg_no` / `mccd_cert_no` is not a server code), notice version and
  hash would all be guesses, and the station has no custodian. The bundle
  writer refuses to run without a valid station config; data entered before
  onboarding stays local.
- **Provisioned offline (real fieldwork)**: an onboarded station (4.1) with a
  signed station config; the roster screen is read-only; every roster user
  has their own PIN and their own encrypted store; each record carries that
  roster `user_id` and the acting role. Station supervisors may correct
  death details and registration numbers locally (4.2). An MCCD PDF printed
  from an offline coded result is **not** marked provisional and **not**
  disabled (owner decision 3): coded is coded; any review goes through the
  existing review process with its logging.
- **Device store**: SQLCipher (rusqlite `bundled-sqlcipher`) keyed from an OS
  keystore secret joined with the user's PIN (6-16 digits); one store per
  user; auto-lock after inactivity; 5 wrong PINs wipe that user's store only
  (field-data-collection "Path B — native app with encrypted storage" and
  "Path B design", as the Expo app does).
- **Delete on receipt**: a record is deleted when acknowledged (section 2);
  no long-term personal-data archive on the station.
- **Exports from the station** (any CSV, report or print): no Aadhaar digits
  (not even the last 3), no partial digits of any number, no informant name
  or phone, the sealed set (6.6) omitted.

## 11. Canonical JSON and hashing

- Bundle envelope (manifest, signature line, record lines, record
  plaintext), receipt line 1 and station config line 1: RFC 8785 (JCS) with
  the integer and NFC rules of bundle spec section 7.
- `answers_json` is **byte-exact**, never canonicalised or re-serialised;
  `answers_sha256` = lowercase hex SHA-256 of its UTF-8 bytes (HTTPS and
  bundle alike; `intake.py:839-844`).
- `notice_sha256` = SHA-256 of the UTF-8 bytes of the served `text` string.
- HTTPS bodies are ordinary JSON; only `answers_json` needs exact bytes.
- Do **not** reuse the server's payload fingerprint form
  (`canonical_payload_fingerprint`, `submission_payload_version_service.py:125-129`:
  `json.dumps(sort_keys=True)` with numeric folding, not JCS) for anything a
  client produces.

## 12. Owner decisions (resolved 2026-10-21)

1. **Never-online / paste-enrolled station trust** comes from the
   **onboarding** process, where a responsible person from the station (the
   custodian) is identified. For such a station the admin-signed roster in
   its station config is the attestation; no per-user online sign-in is
   required. Enrolment and the signed station config record the custodian
   (name, designation, contact, onboarding date, who verified; 4.1). The
   weaker trust and the custodian's accountability are in the bundle spec
   threat table. Online-enrolled stations keep the prior-session condition
   (bundle spec 5.3).
2. **Ingestion only from an onboarded station.** Sandbox or pre-onboarding
   data is never guessed into a project and never remapped (10).
3. **Offline-coded MCCD PDF** is not marked provisional and not disabled:
   coded is coded; review is by the existing review process with its logging.
4. **Consent at registration on the station too**, as on web and Expo; the
   interview reuses it and asks again only when the informant is a different
   person. Informant name, phone and address may be entered at registration
   once a granted record exists (5.1, 5.3-5.6).
5. **HTTPS purge channel**: the signed station config served to the device
   bearer (`GET /intake/station-config`) carries the purge list; same format
   as the bundle path (7).
6. **Local supervisor-style corrections** on a provisioned station: a roster
   user acting as `station_supervisor` may edit death details and, after the
   interview, registration numbers; the server accepts them with the user id
   in the audit (4.2, 3.4, 3.5). Closed cases need the web. Consent
   withdrawal stays web only; the station purges via the purge list.
7. **Station roster** (`digitva-gb8w.8`): fields, acting-role rules and the
   provisioned / sandbox split of 4.1.

### Later owner decisions (2026-10-21)

8. **Death details after the interview** (confirmed): a station supervisor
   may correct death details only until the interview completes; after it,
   only registration identifiers, exactly as on the web (`update_death`
   answers 409 `case_completed`).
9. **Closed cases** (confirmed): cancelled and confirmed-duplicate cases need
   the web; the server answers 409 `case_closed` to any station correction.
10. **Issuing `station_supervisor`** (decided): a roster may give
    `station_supervisor` only to a person who already holds a server
    `interview_supervisor` (or an equivalent supervising) grant at that site.
    The station cannot invent a supervisor; the server checks the grant when
    it issues the config and again when it accepts a correction.
11. **Accepted as written** by the owner: bundle corrections are
    `station_supervisor` only (an interviewer or reporter correcting their own
    case goes over HTTPS), roster roles are scoped by project, site and org
    unit, `base_client_id` is the stale check for a case the server has not
    yet acknowledged, `device_id` plus `station_config_id` stand in for a
    station id in v1, and the purge list also carries case ids of closed
    cases.

## 13. Versioning and change policy

- `offline-api/1` changes only additively: new optional request keys, new
  reply keys, new error codes for new situations, new values only where an
  enum is marked open (`refusal_behaviour`). A client MUST ignore unknown
  reply keys and MUST NOT send unknown request keys (`PATCH` refuses them 422,
  `PUT .../identifiers` 400).
- The bundle manifest and records refuse unknown keys, so any bundle change
  bumps `bundle_format_version`; the server accepts the previous version for
  at least `BUNDLE_MAX_AGE_DAYS` (90) after a new one ships. Same for
  `station_config_format_version`.
- A breaking change is `offline-api/2`, announced with an overlap period;
  this file keeps a dated change log at its end.

## 14. Conformance and test vectors

| Vector set | Where | Status |
| --- | --- | --- |
| Signed station config: test server key, payload, signed file (bundle spec 6.4; authority `app/services/station_config_service.py`) | `tests/fixtures/station_config/`, checked by `tests/test_station_config_fixture.py` and `desktop/crates/digitva-bundle/tests/station_config_fixture.rs` | `implemented today` (uncommitted) |
| Sealed values and wrapped DEKs, both directions | `tests/fixtures/pii_envelope_vectors.json`, checker `scripts/check_pii_blob.py` (envelope spec section 10) | `implemented today` (uncommitted) |
| Phone normalisation (6.5; authority `app/utils/phone.py`) | `tests/fixtures/phone_vectors.json` | `implemented today` |
| Identifier normalisation and validation against a rule (6.1; authority `app/services/death_identifier_rules.py`) | `tests/fixtures/identifier_vectors.json` | `implemented today` |
| `Id10073` reduction and its review flag (6.5; authority `app/utils/national_id.py`) | `tests/fixtures/national_id_vectors.json` | `implemented today` |
| The sealed set's floor, `PII_FIELDS` (6.6; authority `app/services/pii_field_registry.py`) | `tests/fixtures/pii_fields_floor.json` | `implemented today` |

The four rule files are read by `tests/test_offline_shared_vectors.py`, the
`digitva-text` Rust tests and `mobile/digitva-collect/__tests__/offline-shared-vectors.test.ts`.
The Python functions are the authority: a client that disagrees changes, the
vector does not.
| A sample bundle (registration, consent, interview) written by `build_bundle_deterministic` with the test KEM key `tv1` and station seed `0x52 * 32`, and the server's signed receipt for it | `tests/fixtures/bundles/sample_bundle.dvb`, `sample_receipt.dvr`; checked by `tests/test_bundle_fixture.py` and `desktop/crates/digitva-bundle/tests/bundle_fixture.rs` | `implemented today` (uncommitted, digitva-gb8w.2) |
| Canonical JSON cases, every intermediate of the sample, expected reports for tampered, replayed, expired, unknown-key and consent-missing variants | `tests/fixtures/bundles/` (bundle spec section 7) | `specified, not built (digitva-gb8w.6)` |
| Server tests | bundle spec section 9 list | partly `implemented today` (uncommitted, `tests/routes/test_bundle_ingest_api.py`: idempotency, tamper, replay, previous and unknown KEM key, revocation, onboarding, actors, corrections, consent, partial acceptance, two versions of one interview, coding pending / applied / superseded / `coding_mode_unsupported`, both station coding modes, `coding_mode_mismatch`, `offline_coding_disabled` for a revoked station, `actor_not_station_coder`, another station's interview `not_available`, `invalid_doris`, dry run; `tests/routes/test_station_config_api.py`: `coding_mode` per project mode); the rest `specified, not built (digitva-gb8w.7)` |

Procedure: (1) the crate passes the envelope vectors both ways; (2) it
reproduces the bundle vectors byte for byte with the test hook; (3) bundles it
writes with random DEKs are accepted by `POST /intake/bundles/validate` on a
staging server with the expected report; (4) the app's HTTPS calls pass
against staging with test accounts we issue.

## 15. Client MUST / MUST NOT

MUST: send the same client ids on both paths; keep a record until acknowledged
(2); reduce `Id10073` at capture and hash the reduced answers; normalise phones
and identifiers as 6.1 and 6.5; take consent at registration before informant
fields are saved and reuse it at the interview unless the informant differs,
with the exact served notice (5.3-5.6); verify `text_sha256` and the station
config signature; read `code`, `fields` and `warnings`; treat an absent
`can_edit_identifiers` as false; put `actor_user_id` and `acting_role` on
every record; give a `coder` acting role the masked view; omit the sealed set
from coder views and exports; apply `purge` lists; follow sections 9 and 10.

MUST NOT: send a full Aadhaar or VID, a hash of one, or partial digits of any
number; send a witness name; reuse a client id for other content; canonicalise
`answers_json`; expect `consent_status` or other cases' ids in a reply; write
corrections or identifiers under any supervisor role other than the roster's
`station_supervisor`, or on a closed case; send an attempt, visit, revision,
or a correction under a non-supervisor acting role in a bundle; record a
consent withdrawal; send sandbox records; ingest bundles, hold a server
private key, or decide anything section 1 gives the central server.

## 16. Server-side changes we must make

| Bead | Change |
| --- | --- |
| `digitva-gb8w.2` | `POST /intake/bundles` (+ validate, report, receipt with `purge`), per-record outcomes, `death_registration.consent_client_id`, paste-enrolled actor rule (decision 1), `station_not_onboarded`, `death_correction` / `identifiers_set` ingest: implemented (uncommitted; `va_bundle_ingests`, `map_bundle_records`). `va_bundle_pending_coding` and its Celery applier: implemented (uncommitted; a not-ready coding result is held `pending`, applied when the case is ready, and the stored report and its receipt (signed again on request) then carry its final outcome; the station keeps it until then). Not built: the station roster request keys on `PATCH /intake/deaths/<id>` and `PUT /intake/cases/<id>/identifiers` over HTTPS, the 7-day ciphertext retention, `IDENTIFIER_RATE_LIMIT` for `identifiers_set` |
| `digitva-gb8w.3` | consent tables (keyed by case, `client_draft_id` optional), `GET /intake/consent-config` (5.2), `consent` on `/intake/submissions` and `/intake/deaths` (station included), `consent_required` / `consent_invalid` / `consent_conflict`: `implemented today` (uncommitted; `consent_service.record_consent` is the function bundle ingest reuses) |
| `digitva-gb8w.4` | signed station config (browser export and `GET /intake/station-config` for the device bearer), `sealed_field_ids`, `purge`, `custodian`, `designations`, `roster`: implemented (uncommitted; server key `BUNDLE_SERVER_SIGNING_KEY_FILE`; fixture `tests/fixtures/station_config/`) |
| `digitva-gb8w.8` | roster issuing and audit, custodian record at onboarding: implemented (uncommitted; `auth_station_custodians`, `auth_station_roster`, audit events `station_custodian_set`, `station_roster_set`); `acting_role` checks and the `authorized_by: station_roster` audit at ingest: with digitva-gb8w.2; the roster screen (offline team) |
| `digitva-gb8w.5` | device Ed25519 signing key on enrolment, `POST /auth/devices/current/signing-key`, admin paste path, `revoked_compromised`: implemented (admin paste `POST /admin/api/projects/<id>/station-registrations`; revoke body `revoked_compromised`; ingest lookup `device_signing_service.bundle_signing_key` and `verify_bundle_signature` for gb8w.2; enrol `platform` also accepts `desktop`) |
| `digitva-gb8w.6` | `tests/fixtures/bundles/` vectors; client crate support |
| `digitva-gb8w.7` | server tests (bundle spec 9) and the bearer-acceptance check of `/coding/allocation` and the workspace read |
| `digitva-athy` | registration consent on web and Expo, withdrawal on the web, purge emission |

## Change log

- 2026-10-21: v1 proposed.
- 2026-10-21: owner decisions 1-7 applied (section 12): onboarding and
  custodian, onboarded-only ingest, no provisional MCCD PDF, station consent
  at registration, purge via the station config on HTTPS, station supervisor
  corrections (`death_correction`, `identifiers_set`), station roster.
- 2026-10-21: device signing keys built (`digitva-gb8w.5`): sections 3.1,
  3.8 and 16 marked implemented.
- 2026-10-21: signed station config, custodian and roster built
  (`digitva-gb8w.4`, server half of `digitva-gb8w.8`): 3.8, 4.1, 6.6, 7, 14
  and 16 marked implemented. Issuing is a `POST`; the contract's `GET` serves
  the issued file. Roster and custodian user ids are the new integer
  `va_users.user_number`.
- 2026-10-21: bundle ingest built (`digitva-gb8w.2`): 3.4, 3.5, 3.8, 4, 4.2,
  6.3, 7, 8, 14 and 16 marked implemented for the bundle path; the HTTPS
  station roster keys stay with `digitva-gb8w.8`.
- 2026-10-21: bundle coding results held `pending` server-side
  (`va_bundle_pending_coding`, Celery applier; the report and a newly
  signed receipt carry the final outcome), dry runs queue no SmartVA run, station
  config `projects[]` display maps `site_names`, `org_unit_paths`,
  `org_unit_sites` (4), roster places and inactive members checked (4.1).
- 2026-10-21: station config `projects[]` carry `form_options` and
  `translations`; the station embeds the composed definition and serves the
  project's forms, modules and languages from them (4.3); `/me/home` and
  draft autosave on the station.
- 2026-10-22: station coding modes at ingest (`digitva-lmxr`): 4.3 and 8.
  A `coding_result` in `icd11_doris` or `icd10` is accepted for a
  self-coding project whose coding mode matches; new codes
  `offline_coding_disabled`, `coding_mode_mismatch` and pending
  `doris_pending`.
- 2026-10-22: the station coding gate is the station's registration and its
  roster `coder` role, not `self_coding_enabled` (`digitva-lmxr`): new code
  `actor_not_station_coder`, `offline_coding_disabled` redefined, a station
  codes only interviews it uploaded (`not_available`); station config
  `projects[]` gain `coding_mode` (`icd11_doris`, `icd10` or null), format
  version unchanged (additive) (1, 4, 4.3, 8).
- 2026-10-22: the server refuses a bundle made under an expired station config
  (`digitva-xo2n`, owner decision): new whole-bundle code
  `station_config_expired` (422) when `created_at` is after the named
  config's `expires_at` (bundle spec 5.2); a superseded, unexpired config is
  still accepted (8).
