---
title: Offline PHC App, Bundle Format and Transfer
doc_type: policy
status: proposed
owner: Vivek Gupta
last_updated: 2026-10-21
---

# Offline PHC App, Bundle Format and Transfer

Proposed baseline (AGENTS.md "Docs": policy before implementation). Nothing
here is built. It is the spec the offline team builds its client crate (the
bundle writer) against, and the design of the server work, which is ours.

Owner decisions (2026-10-21) this spec starts from:

- The offline PHC app is simple. A reporter or interviewer **takes the
  respondent's DPDP consent at registration** (the interview reuses it, and
  asks again only when the informant is a different person); an interviewer
  interviews; a coder codes (masked); a station supervisor may correct death
  details and registration numbers on a provisioned station;
  the data is **pushed** to the server. The app holds **none of the central
  server's duties**: no bundle ingest or unpacking, no sealing with server
  private keys (nothing beyond what this document specifies), no
  authoritative validation or cross-case duplicate matching, no consent
  authority, no sync or federation logic. **Amended 2026-10-21**: the
  device-local server (`digitva-server`) is accepted as the app's own
  backend (owner: "the local app will need a local server"), within
  section 10 "Local server requirements". The authoritative contract is
  [offline-api-contract.md](offline-api-contract.md).
- Two transfer paths: **(1) HTTPS** to the existing endpoints with a device
  bearer token when the station is online; **(2) offline bundle**: the app
  writes a file that a person carries and uploads, and the server ingests it.

This replaces the `.digitva-export` envelope (X25519 plus ChaCha20-Poly1305)
and the `POST /api/v1/federation/ingest` endpoint proposed in the offline
worktree (`offline-phc-desktop-edition.md`, `digitva-ke83`): there is one
sealed format (the server's hybrid KEM, below) and no second ingest code path.

Related: consent bead `digitva-athy` and
[respondent-consent-notice-draft.md](respondent-consent-notice-draft.md);
[pii-encryption-at-rest.md](pii-encryption-at-rest.md) (Aadhaar last 3
digits, no partial digits, key custody on the app host);
[death-registration-identifiers.md](death-registration-identifiers.md);
[field-data-collection.md](field-data-collection.md) ("Upload integrity under
connection drops", "Interview times", "Coding is masked");
[web-intake.md](web-intake.md); [data-manager-workflow.md](data-manager-workflow.md);
[../current-state/device-collection-api.md](../current-state/device-collection-api.md);
[../current-state/api-v1.md](../current-state/api-v1.md). Encrypted offline
attachments are `digitva-jkvl` (linked, not designed here).

**Sealed-record format reference.** The byte layout of the sealed value and
the wrapped data key is specified in [pii-envelope-format.md](pii-envelope-format.md) with
test vectors in `tests/fixtures/pii_envelope_vectors.json`; this document
references them and does not repeat them (envelope spec sections 2.3, 3, 4
and 5.2; the code is `app/utils/pii_crypto.py`). What this spec uses from it,
and the crate must reproduce exactly:

1. The value form `v1:aes256gcm:<b64url(nonce(12) || ciphertext || tag(16))>`.
2. The wrapped-DEK form `v1:aes256gcm+mlkem768x25519:<key_id>:<b64url(
   mlkem_ct(1088) || x25519_eph_pub(32) || nonce(12) || wrapped_dek(48))>`,
   the HKDF-SHA256 combiner `info` layout (label, length-prefixed algorithm
   id, key id, both KEM ciphertexts, both recipient public keys), and the
   wrap AAD `"<key_id>|aes256gcm+mlkem768x25519"`.
3. `record_aad(table, field_id, row_id) = table || 0x00 || field_id(UTF-8) ||
   0x00 || row_id bytes`.
4. b64url without padding (RFC 4648 section 5, `=` stripped).
5. The public key text form `<b64url ML-KEM-768 public(1184)>.<b64url X25519
   public(32)>` with a `key_id` matching `^[A-Za-z0-9_-]{1,16}$`.

## 1. Scope and actors

| Actor | On the station | On the server |
| --- | --- | --- |
| Death reporter | registers a death, takes consent at registration | a user with a `death_reporter` grant on the record's project and site |
| Interviewer | registers a death (optional), takes consent at registration (or at the interview when none is on file or the informant differs), interviews | a user with an `interviewer` grant on the record's project and site |
| Coder (masked) | codes completed interviews without seeing personal data | a user with a `coder` grant, coding through the coder write services |
| Station supervisor | corrects death details and registration numbers (provisioned station only) | a roster user with the roster role `station_supervisor` (contract 4.1); not a server grant |
| Custodian | the responsible person identified at onboarding | recorded in the enrolment and the signed station config |
| Courier / uploader | carries the bundle file | a browser session of a data manager or interview supervisor (section 5) |
| Station | one enrolled device (`auth_devices` row), signs bundles | verifies the signature, decrypts, ingests |
| Local server | the app's own backend on the station (section 10) | nothing: it is never called by the central server |
| Server (ours) | none of its duties run on the station | all authoritative validation, sealing at rest, workflow, authz, audit, ingest |

The app **does**: capture answers with the served form definition, reduce
`Id10073` to its last 3 digits at capture, record consent, write a coder's
masked result, write the bundle (crate), import the station config and the
ingest receipt, and delete a record only after a matching receipt.

The app **does not**: decide anything the server decides (validity, routing,
duplicates, workflow state, coding gates, locked prefill), hold any private
key other than its own signing key, sync with other stations, or run any of
the central server's duties (its own local server is allowed, section 10).

**Which path when.** HTTPS whenever the station can reach the server; the
bundle when it cannot for the working period, or when the upload would not
finish on the link. Both carry the same client ids, so a record sent by one
path and then the other is a duplicate, never a second record. The app keeps
sending a record by either path until a matching acknowledgement arrives.

## 2. Bundle format

### 2.1 Container: one line-delimited file

A bundle is **one file** of UTF-8 lines, each ending in exactly one LF
(`0x0A`), no BOM, no CR. Extension `.dvb`, media type
`application/vnd.digitva.bundle`.

```
line 1   manifest   (canonical JSON, section 2.2)
line 2   signature  (canonical JSON, section 3.2)
line 3.. records    (canonical JSON, one sealed record per line, section 2.3)
```

Why not zip or tar: a single stream needs no member names, so there is no
path traversal, no duplicate members, no compression and therefore no
decompression bomb, and the server reads it line by line with the standard
library. Random access is not needed: the server verifies the manifest and
the body hash first, then streams the records. Why not one JSON document: a
streaming reader cannot verify or bound it record by record.

Limits (server enforced, crate must respect):

| Limit | Value | Reason |
| --- | --- | --- |
| `BUNDLE_MAX_BYTES` | 50 MiB | under the ingress `client_max_body_size 55m` (`deploy/ingress-routes.conf`), no new proxy rule |
| Records per bundle | 5,000 | bounded ingest transaction count and report size |
| One line | 2 MiB + 64 KiB | a record holds `answers_json` (1 MB cap, as `POST /intake/submissions`) plus envelope overhead |
| Manifest line | 256 KiB | |

A writer with more data writes several bundles (`bundle_seq` increments).
An over-limit bundle is refused whole (413 `payload_too_large`) before any
decryption.

### 2.2 Manifest

Plaintext, so the server can check identity, signature and age before it
spends a KEM decapsulation. It holds **no personal data**: ids, counts,
versions, times and hashes only.

| Field | Type | Rule |
| --- | --- | --- |
| `bundle_format_version` | integer | `1` |
| `bundle_id` | string | UUID v4, lowercase hyphenated; unique forever |
| `bundle_seq` | integer | station-local counter from 1, +1 per bundle written; gaps are reported, not refused |
| `device_id` | string | the station's `auth_devices.device_id` (the station id; there is no separate station table) |
| `signing_key_id` | string | section 3.2 |
| `project_ids` | array of string | sorted, unique; every record's project is listed |
| `created_at` | string | RFC 3339 UTC, `YYYY-MM-DDTHH:MM:SSZ` (no fraction) |
| `app_version` | string | the station app's version |
| `crate_version` | string | the bundle writer's version |
| `instrument_versions` | array of string | sorted, unique: every `instrumentVersion` used |
| `station_config_id` | string | the `config_id` of the station config in force (section 6.4) |
| `kem_key_id` | string | the server KEM `key_id` the DEK is wrapped to |
| `dek_wrapped` | string | the bundle DEK, wrapped (reference item 2) |
| `record_counts` | object | `{record_type: integer}` for every type present; keys sorted by JCS |
| `body_sha256` | string | lowercase hex SHA-256 of the exact bytes from the first byte of line 3 to the end of file, every LF included |

Unknown manifest keys are refused (`manifest_invalid`), so a version change
is explicit.

### 2.3 Sealed records (lines 3..)

**One DEK per bundle.** A wrapped DEK is about 1.6 KB and one ML-KEM-768 plus
one X25519 decapsulation; per record that is 8 MB and 5,000 decapsulations
for a full bundle on the app host. Per bundle is one of each, and each record
still gets its own random 96-bit nonce and an AAD that binds it to its bundle,
type and client id. (The at-rest policy's "one DEK per record" is about
database rows; a bundle is one transport record.) The DEK is 32 random bytes
from the OS CSPRNG, never reused across bundles; at 5,000 records per DEK the
random-nonce bound of AES-GCM is far away.

Each record line is canonical JSON:

```json
{"client_id":"<uuid>","ct":"v1:aes256gcm:<b64url>","record_type":"<type>"}
```

- `ct` seals the record's plaintext (the canonical JSON object of 2.4) with
  AES-256-GCM under the bundle DEK, nonce fresh per record,
  `AAD = record_aad("digitva_bundle", record_type + "/" + client_id, bundle_id_bytes)`,
  where `bundle_id_bytes` are the 16 raw bytes of the UUID. So a record moved
  to another bundle, retyped, or given another client id does not open.
- `client_id` and `record_type` are in the clear on the line (random ids and
  a type name, no personal data) so the report can name a record that fails
  to open.
- Line order is the ingest order (section 5.3); the crate writes types in
  that order.

### 2.4 Record types (plaintext inside `ct`)

Every record carries `record_type`, `client_id` (equal to the line's),
`project_id`, `actor_user_id` (integer, the server user id from the station
config roster), `acting_role` (the roster role the user acted in:
`death_reporter`, `interviewer`, `station_supervisor` or `coder`; contract
4.1) and `recorded_at` (RFC 3339 with offset, the station clock). Unknown
keys are refused per record (`record_invalid`).

**`death_registration`** (optional; when the case is not yet on the server):
`client_id` is the `client_death_id`. Body = the `POST /intake/deaths` body
(`site_id`, `org_unit_id`, the register fields, optional `identifiers`)
exactly as the HTTPS call, plus optional `consent_client_id`. **Informant
fields** (`informant_name`, `informant_phone`, `informant_phone_2`,
`address`, `address_house_street`, `address_village_ward`,
`address_landmark`): carried only with `consent_client_id` naming a granted
registration `consent` record (owner decision 4), which the server processes
in the same savepoint as the registration; otherwise `consent_required`. A
registration without consent carries none of them.

**`death_correction`** and **`identifiers_set`** (owner decision 6): a
station supervisor's correction of death details or registration numbers,
`acting_role: station_supervisor` only. Fields, server rules (stale,
`case_completed`, closed cases refused, limits) and audit: contract
section 4.2. A correction or later number under any other acting role is
HTTPS only, and the app says so where it is entered offline ("Saved on this
device. Sent only when the station is online.").

**`consent`** (append-only; never edited, a correction is a new record that
names `supersedes_client_id`; keyed by the case, taken at registration and
reused by the interview, or taken for one interview attempt when the
informant differs):

| Field | Rule |
| --- | --- |
| `death_ref` | `{"client_death_id": uuid}` or `{"death_id": uuid}` |
| `client_draft_id` | the interview attempt it was taken for, or `null` for a registration consent |
| `notice_version_id` | from the station config |
| `notice_language` | BCP 47 code of the text shown |
| `notice_sha256` | lowercase hex SHA-256 of the exact notice text bytes shown (from the config) |
| `decision` | `granted` or `refused` (refused: some required purpose refused) |
| `purposes` | `[{"code": str, "granted": bool}]`, every purpose of that notice version, sorted by code |
| `mode` | one of the project's allowed modes: `spoken`, `tap`, `signed` |
| `witness_present` | boolean (no witness name: it would be more personal data) |
| `supersedes_client_id` | uuid or null |

**`interview_submission`**: `client_id` is the `client_draft_id`. Fields
exactly as `POST /intake/submissions`: `site_id`, optional `org_unit_id`,
`death_ref` (as above), `draft` (meta: `instrumentVersion`,
`definitionSha256`, `definitionExtensions`, `startedAt`, `completedAt`,
`deviceClockAt` = the bundle's `created_at`, `interviewOutcome`),
`completion: {valid, issues}`, `answers_json` (string) and `answers_sha256`,
and `consent_client_id` (the consent record this interview relies on: the
case's registration consent or one taken for this attempt; or null).
**`answers_json` is not canonicalised**: it is the exact text the form
engine produced and hashed, as the existing upload ("Exact text and hash",
field-data-collection.md). JCS escapes it as a string; the server hashes the
decoded string's UTF-8 bytes.

**`coding_result`** (masked coder): `client_id` is a new UUID per result.

| Field | Rule |
| --- | --- |
| `client_draft_id` | the interview coded (no `va_sid` exists offline) |
| `coded_answers_sha256` | the `answers_sha256` of the version the coder saw |
| `kind` | `final` or `not_codeable` |
| `initial` | for masked projects: `{immediate_cod, antecedent_cod, other_conditions}` as `POST /coding/initial` |
| `final` | `{conclusive_cod, remark, cod_search_id, cod_chosen_code, cod_chosen_rank}` as `POST /coding/finalize` |
| `not_codeable` | `{reason, other}` as `POST /coding/not-codeable` |

Only `masked_simple` projects in v1: DORIS needs a server-issued process
token and cannot run offline (refused `coding_mode_unsupported`).

**`attachment_chunk`** (shape reserved, **not built**; `digitva-jkvl`):
`attachment_id` (uuid, the `client_attachment_id`), `client_draft_id`,
`question_name`, `media_type`, `chunk_index` (0-based), `chunk_count`,
`total_bytes`, `sha256` (of the whole file), `data` (b64url of the chunk, at
most 4 MiB raw). Record `client_id` = `<attachment_id>` for chunk 0 and a
fresh UUID per later chunk; the AAD field id also carries
`/<chunk_index>/<chunk_count>` so chunks cannot be reordered or truncated
unnoticed. An interview whose attachments are incomplete is rejected
`attachments_incomplete` (owner rule in `digitva-jkvl`: no submit with a
missing file).

### 2.5 What never goes in a bundle

- The full Aadhaar or Virtual ID: `Id10073` holds only the reduced form (last
  3 digits and the present flag) the form engine writes at capture: exactly
  `XXXXXXXXX` plus the last 3 ASCII digits, or `XXXXXXXXXXXX` when fewer
  than 3 digits were typed (`app/utils/national_id.py`
  `is_reduced_national_id`; both accepted unflagged). No hash. The server
  reduces again and stays authoritative.
- Partial digits of any number outside the sealed body: no last-4 of a phone
  in the manifest, a record line, a file name, a log or a report.
- Server secrets: no private KEM key, no blind-index key, no session or
  refresh token, no device secret, no password or PIN.
- Research or de-identified exports, SmartVA outputs, PDFs or certificates.
- Another station's records.

## 3. Protection

### 3.1 Confidentiality

The bundle DEK is wrapped to the **server's** hybrid KEM public key
(ML-KEM-768 plus X25519, the `PII_KEM_*` pair), public-key-only. The station
never holds a private KEM key, so a lost or copied USB stick discloses no
personal data: only the plaintext manifest (project ids, station id, counts,
times, versions).

**One key pair, not a separate transport pair.** The PII pair's private key
is already on the app host only (pii-encryption-at-rest decision 13); a second
pair on the same host adds custody work and no isolation. Domain separation
comes from the AAD table label `digitva_bundle`, which no at-rest record uses.
Recorded as open question Q2.

### 3.2 Device authenticity: Ed25519

- At enrolment the station generates an Ed25519 key pair and keeps the
  private key in its own encrypted store. `signing_key_id` = the first 16
  lowercase hex characters of SHA-256 of the raw 32-byte public key.
- **Online enrolment**: `POST /auth/enroll` gains an optional
  `signing_public_key` (b64url, 32 bytes). **Existing device**: a new
  `POST /auth/devices/current/signing-key` (device bearer) sets it once.
  **Never-online station**: the admin registers the device in Project Setup
  and pastes or uploads the station's enrolment file (`device_id`,
  `signing_public_key`, `app_version`), audited.
- Stored on `auth_devices` (migration later): `signing_public_key`,
  `signing_key_id`, `signing_key_set_at`. A replacement key is a new row
  value with the old kept in `auth_device_signing_keys` (key, set at,
  retired at), so bundles signed before a re-key still verify.
- **Revocation** is the existing admin device revoke (`device_revoked`
  event). New field `revoked_compromised` (boolean): a lost or stolen
  station's bundles are all refused (`device_revoked`); a decommissioned one's
  bundles with `created_at` before `revoked_at` are accepted for
  `BUNDLE_MAX_AGE_DAYS`. Who revokes: admin, as today.

**Signature line** (canonical JSON):

```json
{"alg":"ed25519","sig":"<b64url 64 bytes>","signing_key_id":"<16 hex>"}
```

`sig = Ed25519(private, b"digitva-bundle-v1\x00" || manifest_line_bytes)`,
where `manifest_line_bytes` is line 1 without its LF. The manifest carries
`body_sha256`, so the signature covers every record line: a changed, added,
removed or reordered record fails before any decryption.

### 3.3 Replay and age

- `bundle_id` is unique in the ingest table: the same id with the same
  manifest bytes is a no-op returning the stored report; with other bytes it
  is refused 409 `bundle_id_reused`.
- `created_at` must be within `[now - BUNDLE_MAX_AGE_DAYS, now + 1 day]`
  (default 90 days, the `DEVICE_SESSION_MAX_DAYS` bound); else 422
  `bundle_too_old` / `bundle_from_future`.
- Even a fresh replay of old content cannot duplicate: every record is
  idempotent by client id (section 4).

### 3.4 Server key rotation

The manifest names `kem_key_id`. The server opens it with the current key or
any key in `PII_KEM_PREVIOUS_PRIVATE_KEY_FILES` (`build_keyring`). Rotation
runbook addition: keep the previous private key file for at least
`BUNDLE_MAX_AGE_DAYS` after a new station config carries the new public key.
A `kem_key_id` not in the keyring is refused 422 `bundle_key_unknown` with the
message "Bundle sealed to a retired server key; import the current station
configuration and export again." The station still holds the records, so
nothing is lost.

## 4. Idempotency and conflicts

- **Client ids for every record**: `client_death_id`, consent `client_id`,
  `client_draft_id`, coding `client_id`, correction `client_id`,
  `attachment_id`. They are the same ids
  the HTTPS path uses, so either path dedupes against the other.
- **Per-record outcome**: `accepted`, `duplicate` (already stored with the
  same content; the stored result), `superseded` (stored as history, the
  server keeps a newer version: the HTTPS `kept: "server"`), `pending`
  (coding held until the case is ready, 5.5), `rejected` (with a reason code),
  `not_processed` (dry run). **Partial acceptance** is normal: each record has
  its own savepoint; one rejection never rolls back another.
- **Re-upload of the same bundle**: the stored report, nothing written.
- **Same interview edited after export**: a later bundle carries the same
  `client_draft_id` with other answers. It runs through
  `submit_device_interview` unchanged: the last completed version wins by
  completion time (`meta.effectiveSavedAt`, `completedAt` corrected by
  `deviceClockAt` = bundle `created_at`); an older one is stored as a
  `replaced` history row; coding final or case closed: history, `locked`.
- **Case already on the server** (registered on web): the interview names it
  with `{"death_id": ...}` (known from an earlier online fetch; no case list
  in the station config in v1, Q6) or the station
  registered its own case; a station registration of the same death becomes a
  second case and the normal possible-duplicate flow lets a supervisor mark it.
  The server never merges by guess.
- **Reporter vs interviewer**: registration ownership (`registered_by`) is the
  record's `actor_user_id`; another interviewer's draft on the case is never
  touched (one open draft per interviewer per case, as today); a different
  interviewer's `client_draft_id` is rejected `conflict`.
- **Dependencies**: a record whose prerequisite was rejected in the same
  ingest (an interview whose registration failed, coding whose interview was
  rejected) is rejected `depends_on_rejected` naming the other `client_id`.

## 5. Server ingest design (ours; later, not built here)

### 5.1 Route

`POST /api/v1/intake/bundles` and `POST /api/v1/intake/bundles/validate`
(dry run: every check and every service call inside a transaction that is
rolled back; outcomes `not_processed` or the reason it would be rejected).
`GET /api/v1/intake/bundles/<bundle_id>` returns the stored report (pending
coding results move on there) and `GET .../receipt` the signed receipt.

- **Uploader**: a **browser session** of a `data_manager` or
  `interview_supervisor` whose scope covers every project in the manifest, or
  an admin; CSRF `X-CSRFToken`. The courier is a person at a district office,
  and device tokens deliberately exclude data-manager powers. Also the
  station's **own device bearer** (bearer `device_id` equal to the manifest's),
  so an online station can push a bundle instead of many calls. The uploader
  gates who may hand in files and is audited; **authority for each record comes
  from the device signature and the actor's grants**, never from the
  uploader.
- Body: the raw file, `Content-Type: application/vnd.digitva.bundle`; a
  `Content-Length` over `BUNDLE_MAX_BYTES`, or none, is 413 before reading.
  Nginx buffers it to a temp file; it is ciphertext there. Rate limit 10 per
  hour per uploader and per device. `Cache-Control: no-store` on every reply.
- Errors use the `/api/v1` body `{error, code}`.

### 5.2 Order of checks (whole-bundle refusals, nothing written)

1. Size and line limits; line 1 and 2 parse as canonical JSON; manifest keys
   and types (`manifest_invalid`); `bundle_format_version` known
   (`bundle_version_unsupported`).
2. `device_id` known (`device_unknown`), not compromised-revoked
   (`device_revoked`), `signing_key_id` registered for it (`signing_key_unknown`),
   the station **onboarded**: a custodian recorded and the manifest's
   `station_config_id` issued to this device (`station_not_onboarded`; owner
   decision 2, contract 4.1).
3. Signature (`signature_invalid`), then `body_sha256` over the streamed body
   (`body_hash_invalid`).
4. `bundle_id` replay (3.3), `created_at` window, `kem_key_id` in keyring.
5. Unwrap the DEK once (`unwrap_dek`; failure `bundle_key_unknown`).

### 5.3 Records

Decrypt in memory, record by record; plaintext is never written to disk or
logged. Processing order: `death_registration`, `consent`,
`death_correction`, `interview_submission`, `identifiers_set`,
`attachment_chunk`, `coding_result`; within a type, by `recorded_at`.
(`death_correction` runs before the interviews, since a completed interview
ends register corrections.) A `death_registration` naming
`consent_client_id` is applied together with that consent record in one
savepoint, after the consent is parsed (case row, then consent, then the
informant fields), and is rejected `consent_required` if that consent is not
granted. Each record:
parse against its schema (`record_invalid`), then the **same service
functions as the HTTPS endpoints**, with the actor as the user:

| Record | Service (no second path) |
| --- | --- |
| `death_registration` | the `POST /intake/deaths` handler's `get_device_case` lookup then `register_death(..., client_death_id=...)` |
| `consent` | new `consent_service.record_consent` (shared with the HTTPS `consent` object, 6.2) |
| `death_correction` | `web_intake_service.update_death` with the station-roster authorization (contract 4.1, 4.2) |
| `interview_submission` | `check_device_answers`, the answers-hash check, `check_device_times`, then `submit_device_interview` |
| `identifiers_set` | `death_identifier_write.put_identifiers` with the station-roster authorization |
| `coding_result` | coder allocation (`coder_workflow_service.allocate_pick_form` for the actor) then `coder_cod_service.submit_coder_initial_cod` / `submit_coder_final_cod` / `submit_coder_not_codeable` |

The route bodies' validation (hash before parse, size caps, 422 codes) moves
into functions both paths call, so the bundle path cannot drift.

**Actor trust.** An offline record has no bearer of its own. The server
accepts `actor_user_id` only when (a) the user is on the station config
roster the bundle names, and (b) an `auth_device_sessions` row exists for
(this device, this user) opened at or before `created_at` (the person signed
in on that station online at least once; expired is fine). Otherwise
`actor_unknown_on_device`. **Paste-enrolled stations** (owner decision
2026-10-21, contract decision 1): a never-online station enrolled by the
admin paste path can have no device session, so condition (b) can never
hold. Its trust comes from **onboarding**: a responsible person from the
station (the custodian) is identified and recorded, and the admin-signed
roster in the station config the bundle names is the attestation; (b) is not
required. The weaker trust and the custodian's accountability are in the
threat table (section 8). Then the usual grant checks run for that user at
ingest time: the device projection only (interviewer, death_reporter, coder,
coding_tester, reviewer), with project, site and unit scope; a lapsed grant is
`forbidden`. The record's `acting_role` must be one of that user's roster
roles in scope (`forbidden`); `station_supervisor` is checked by the
station-roster rule of contract 4.1, not by a server supervisor grant. Q4.

**Consent gate.** When the project's consent config says required, an
`interview_submission` carrying informant personal data (any non-empty field
the notice version lists as covered, at least the informant name and phone
fields of `PII_FIELDS`) needs `consent_client_id` naming a consent record for
the same `client_draft_id`, or the case's registration consent, with
`decision: granted`, every required purpose
granted, a notice version valid for that project and language, and a
`notice_sha256` equal to the stored text's hash. Else `consent_required`.
A refused consent with `interviewOutcome: completed` is `consent_conflict`.
WHO `Id10013` keeps its existing role (routing to `consent_refused`); the
DPDP record does not replace it.

**PII sealing** follows the at-rest baseline: the server reduces `Id10073`
again and seals register and payload PII with its own record keys; bundle
ciphertext is never stored as the at-rest form.

### 5.4 Consent tables (sketch; migration with the consent work)

- `mas_consent_notice_versions`: `id`, `project_id`, `version` (int),
  `language`, `text`, `text_sha256`, `purposes` (JSONB: code, label, required),
  `covered_fields` (JSONB), `allowed_modes`, `contacts_snapshot` (JSONB,
  including the district contacts), `created_at`, `created_by`, `retired_at`.
  Unique (`project_id`, `version`, `language`). Never updated after use.
- `va_consent_records` (append-only; no UPDATE or DELETE grant for the app
  role, enforced by a trigger): `consent_id` (uuid pk), `client_consent_id`
  (unique), `project_id`, `death_id`, `draft_id` (null for a registration
  consent), `notice_version_id` (FK),
  `notice_language`, `notice_sha256`, `event` (`granted`, `refused`,
  `withdrawn`), `mode`, `witness_present`, `recorded_by`, `recorded_at`,
  `received_at`, `channel` (`web`, `device`, `bundle`), `bundle_ingest_id`,
  `supersedes_consent_id`. Indexes on `death_id`, `draft_id`.
- `va_consent_record_purposes`: `consent_id`, `purpose_code`, `required`,
  `granted`; pk (`consent_id`, `purpose_code`).
- Withdrawal is a new `withdrawn` row recorded on the web by a supervisor or
  data manager (bead athy), never on the station; the station gets the
  withdrawn consent's `client_id` in the `purge` list of the next station
  config or receipt. On the HTTPS path the station fetches the same signed
  station config with its device bearer (`GET /api/v1/intake/station-config`;
  contract section 7, owner decision 5); same format on both paths. The
  receipt body gains `purge` (sorted client ids).

### 5.5 Coding results

The coder writes need the coder's own active allocation; the ingest takes it
for the actor (pick-mode check relaxed as `allocate_own_case` does), writes,
and the case moves as a web save would. If the case is not ready (SmartVA or
attachments pending: today's `not_ready`), the result is kept in
`va_bundle_pending_coding` (ciphertext-free JSON of the masked result only,
no personal data) with outcome `pending`, applied by a Celery task when the
case reaches `ready_for_coding`, final outcome on
`GET /intake/bundles/<id>`. Rejections: `coded_version_superseded`
(`coded_answers_sha256` differs from the coder version), `held_by_another`,
`not_available`, `coding_mode_unsupported`, `invalid_cod`, `final_blocked`
(Narrative QA or Social Autopsy on in the project and not in the record).
Q5: whether offline coding requires a self-coding project.

### 5.6 Report, audit, retention

Report (also the signed receipt body):

```json
{"bundle_id":"...","device_id":"...","kem_key_id":"...","status":"processed",
 "counts":{"accepted":0,"duplicate":0,"superseded":0,"pending":0,"rejected":0},
 "missing_seq":[3],
 "records":[{"client_id":"...","record_type":"interview_submission",
   "outcome":"accepted","code":null,"received_sha256":"<64 hex>",
   "death_id":"...","unique_id":"..."}]}
```

It **never echoes a value**: ids, outcomes, reason codes, hashes and the
server's own ids only (no names, phones, answers, Aadhaar digits; a field
error names the question, as `fields` does today). `missing_seq` lists
`bundle_seq` gaps from this station.

**Receipt**: the report as canonical JSON on line 1 and
`{"alg":"ed25519","sig":...,"signing_key_id":...}` on line 2, signed with a
server Ed25519 key (`BUNDLE_SERVER_SIGNING_KEY_FILE`, app host, 0600, as the
KEM key) over `b"digitva-receipt-v1\x00" || line1`. The courier carries it
back; the station deletes a record only when the receipt names it
`accepted`, `duplicate` or `superseded` and, for an interview,
`received_sha256` equals the hash it sent (the HTTPS acknowledgement rule).

**Audit**: `va_bundle_ingests` (`bundle_id` unique, `device_id`, `bundle_seq`,
`manifest_sha256`, `uploader_user_id`, `channel` (browser or device),
`kem_key_id`, `created_at` claimed, `received_at`, `counts`, `report` JSONB,
`dry_run`), one `auth_security_events` row per refused bundle (reason code
only), and per record the existing service audit (transitions, `details_edited`,
coding events) with `bundle_ingest_id` in the reason metadata; a
`death_correction` or `identifiers_set` also records `acting_role`,
`device_id`, `station_config_id`, `bundle_id`, `client_id` and
`authorized_by: "station_roster"` beside the before and after values
(contract 4.2).

**Retention**: the uploaded file is ciphertext; it is kept 7 days in an
app-host directory outside the repo (mode 0700) for support, then deleted by
a beat task; a whole-bundle refusal deletes it at once. Plaintext is never on
disk. Q7.

**Runtime note**: `open_record`'s DEK cache and `authz.resolve_grants` live
on `flask.g`; a background ingest pushes one app context per bundle and one
grant cache per actor; `clear_dek_cache` at the end.

## 6. HTTPS path

### 6.1 Existing endpoints the app uses

| Purpose | Endpoint |
| --- | --- |
| Enrol, sign in, refresh, sign out | `POST /auth/enroll`, `POST /auth/sessions`, `POST /auth/sessions/refresh`, `DELETE /auth/sessions/current` |
| Access, terms | `GET /me/access`, `POST /me/terms` |
| Project setup | `GET /organization/<project>/form-options`, `GET /intake/projects/<project>/prefill-policy`, `GET /organization/<project>/units?role=interviewer` |
| Form | `GET /instruments/<code>/definition`, `/translations/<locale>`, `/versions` |
| Identifier types | `GET /intake/identifier-types?project_id=` |
| Register | `POST /intake/deaths` (`client_death_id`, registration `consent`) |
| Correct (station supervisor or own case) | `PATCH /intake/deaths/<id>`, `PUT /intake/cases/<id>/identifiers` (station roster path: contract 3.4, 3.5) |
| Interview | `POST /intake/submissions`, `POST /intake/submissions/<va_sid>/revisions` |
| Outstanding report | `POST /intake/outstanding` |
| Coding | `GET /coding/available`, `POST /coding/allocation`, `POST /coding/initial|finalize|not-codeable/<va_sid>` |

`POST /coding/allocation` and `GET /api/v1/va/<va_sid>/workspace` must be
checked for device-bearer acceptance when this is built (the three COD writes
already take one; `code-now` and release are cookie only).

### 6.2 New

- `GET /api/v1/intake/consent-config?project_id=` (either credential; a caller
  who may interview or register in the project; 403 `project_forbidden`
  otherwise; `no-store`): `{project_id, consent_required, notice_versions:
  [{notice_version_id, version, language, text, text_sha256, purposes:
  [{code, label, required}], covered_fields, allowed_modes,
  witness_allowed}], contacts: {deletion: {email, phone}, mentor_institution,
  central_team, dpo, districts: {<org_unit_id>: {name, email, phone}}},
  retention, refusal_behaviour}`. A district with no contact is absent and the
  app shows the central team (notice draft "Contact variables"). Shapes
  defined 2026-10-21 (contract section 5.2): `witness_allowed` boolean per
  notice version (false: `witness_present` is always false);
  `retention: {period_days: int | null, expiry_action: "erase" | "lock"}`;
  `refusal_behaviour`: v1 value `interview_without_informant_data` (the
  interview may run, every covered field empty); an unknown value blocks new
  interviews in the app. `version` compares as an integer; `text_sha256` is
  over the UTF-8 bytes of the served `text` string, not rendered Markdown.
- `consent` on `POST /intake/submissions` (optional key): the consent record
  fields of 2.4 without `death_ref`/`client_draft_id` (taken from the body),
  `client_id` as `client_consent_id`. Stored by the same `record_consent`, in
  the submission's transaction, idempotent by `client_consent_id`. 422
  `consent_required` (with `fields: ["consent"]`) only when the project
  requires consent and the answers carry covered informant data; a project
  without consent configured is unchanged (backward compatible). 422
  `consent_invalid` for an unknown notice version, a hash mismatch or a
  missing purpose.

### 6.3 Ordering

As today: registrations, then consent (inside the submission), then
interviews, then coding.

### 6.4 Station config (bundle path provisioning)

A never-online station gets its configuration as a **signed file** produced by
the server (`GET /api/v1/projects/<project_id>/station-config?device_id=`,
browser session, admin or project data manager; audited) and imported by the
app. Same two-line form as a receipt: canonical JSON on line 1, server Ed25519
signature over `b"digitva-station-config-v1\x00" || line1` on line 2. The
server signing public key is pinned in the app at first import (shown as a
fingerprint for the admin to compare) and changes only through a config
signed by the old key.

| Field | Content |
| --- | --- |
| `station_config_format_version` | `1` |
| `config_id` | UUID; `issued_at`, `expires_at` (default 180 days) |
| `device_id` | the station it is for (a config for another device is refused) |
| `server_url` | for the HTTPS path |
| `kem_public_key` | `{key_id, public}` (reference item 5) |
| `server_signing_key` | `{signing_key_id, public}` |
| `projects` | per project: sites and org units the roster may use, `form_options`, `prefill_policy`, `identifier_types`, the consent config of 6.2, the instrument definition hash and versions, `sealed_field_ids` (the server's sealed set for the project's form type, contract 6.6; the app never hardcodes it) |
| `custodian` | `{name, designation, phone, email, onboarded_on, verified_by_user_id}`: the responsible person identified at onboarding (contract 4.1) |
| `designations` | `[{code, label}]`: default Medical Officer, Health Supervisor, Health Worker / ANM / MPW, Other |
| `roster` | `[{user_id, name, designation, roles: [{role, project_id, site_id, org_unit_id}], active}]`, `role` one of `death_reporter`, `interviewer`, `station_supervisor`, `coder`: who may act on this station, read-only on the station; no email, phone, password or PIN (contract 4.1) |
| `purge` | client ids the station must delete (withdrawals, closed cases): sorted, unique UUID strings, each a `client_death_id`, `client_draft_id` or consent `client_id`; a case id purges everything under it; no reason, no personal data |

The same signed file is served to the station's own device bearer at
`GET /api/v1/intake/station-config` (amended 2026-10-21; the HTTPS path's
purge channel, contract section 7), fetched at sign-in and at least daily
while online.

Large parts (form definition, translations) are fetched by `definition_sha256`
from a sibling file the same endpoint serves, so the signed line stays small.

## 7. Client crate spec (the offline team builds)

**Inputs**: the imported station config, the station's Ed25519 private key
(from the app's encrypted store, passed in, not stored by the crate), the
`bundle_seq`, and the records (typed structs matching 2.4).
**Output**: the bundle bytes, the manifest, and the list of `(client_id,
record_type, answers_sha256?)` it contains.

**Canonical JSON** (manifest, signature, record lines and record plaintext):
RFC 8785 (JCS): object keys sorted by UTF-16 code units, no insignificant
whitespace, strings in UTF-8 with JCS escaping. All text is Unicode NFC before
writing, **except `answers_json`, which is passed through byte-exact**.
Numbers: **integers only**, in `[-(2^53-1), 2^53-1]`; anything else (a
decimal, a time, a score) is a string. Booleans and null as JSON. UUIDs
lowercase hyphenated; hex lowercase; times as specified per field.

**Crypto**: CSPRNG DEK and nonces; the wrap and value forms of the reference;
Ed25519 per RFC 8032 (pure, no prehash). No other primitive.

**Errors**: the crate refuses to write (typed error, no partial file) when a
record breaks its schema, a limit, the Aadhaar rule (`Id10073` not in the
reduced form), the integer rule, or when the station config is expired or for
another device. It writes atomically (temp file, fsync, rename).

**Must not**: store any key other than the KEM public key it is given; log or
print plaintext, answers, names, numbers or keys (logs name `bundle_id`,
`client_id`, counts and error codes only); compress; add fields; re-serialise
`answers_json`; delete records (the app deletes on a receipt).

**Test vectors** (main repo will provide, under `tests/fixtures/bundles/`):

1. A published **test** KEM key pair and test Ed25519 station key (fixed
   files, never used outside tests; not `dev_keyring`).
2. Canonical JSON cases: key order, NFC, escapes, the integer rule (inputs and
   expected bytes).
3. A sample bundle with a fixed DEK and fixed nonces (test-only hook) of one
   each of registration, consent, interview, coding and a correction, with every
   intermediate: plaintext bytes, AAD bytes, `ct`, `dek_wrapped`,
   `body_sha256`, signed message bytes, signature.
4. The expected server report for that bundle, and for its tampered,
   replayed, expired, unknown-key and consent-missing variants.

**Conformance**: the crate reproduces vectors 2 and 3 byte for byte (with the
test hook), and bundles it writes with random DEKs and nonces are accepted by
`POST /intake/bundles/validate` on a test server with the expected report.

## 8. Privacy

- **DPDP touchpoints**: the notice is shown and the choices recorded at
  registration (or at the interview start when none is on file or the
  informant differs), before any respondent data is saved on the station;
  every consent record names the exact notice version, language and text
  hash; refusal of a required purpose means no informant data in the
  interview; withdrawal is recorded on the web and reaches the station as a
  purge.
- **Minimisation**: only the questionnaire, consent and masked coding go in a
  bundle; no witness name, no research data, no exports. De-identification for
  research is a server export concern, not part of the bundle.
- **Retention**: the station keeps a record until a matching receipt (C3 in
  field-data-collection: no ceiling, purge after confirmed push); the server
  keeps the encrypted file 7 days (Q7) and the data under the project's
  retention setting.
- **Legal review open**: whether a consent taken offline with mode `tap` or
  `spoken` is sufficient; deceased's data under the Act.

| Threat | Mitigation | Residual |
| --- | --- | --- |
| Lost USB stick or copied file | DEK wrapped to the server KEM key; no private key on stations | manifest metadata (counts, project, station, times) |
| Tampered bundle | Ed25519 over manifest with `body_sha256`; AEAD with AAD per record | none known |
| Replay | `bundle_id` unique, age window, client-id idempotency | none known |
| Rogue or stolen station | per-device key; compromised revoke refuses all its bundles; actor must have signed in on it; grants re-checked | records signed before the theft is noticed |
| Station user impersonating another | roster plus prior device session for the actor | a station holder can attribute a record to another roster user of that station (Q4) |
| Paste-enrolled station actor (decision 1) | onboarding identifies and records a custodian accountable for the station; admin-signed roster; per-user PIN stores on the station; grants re-checked at ingest; audit names the station and custodian | weaker than the session rule: any holder of the station signing key can attribute a record to any roster user, with no server-side evidence that user ever used the station; accountability rests on the custodian |
| Widened correction authority (decision 6) | only an onboarded station with a known custodian; `station_supervisor` only from the admin-signed roster, scoped to project and site; every server validation (identifier rules, stale 409, closed cases refused, `case_completed`); 500 corrections per bundle and the identifier budget; audit with `authorized_by: station_roster`; web supervisors review | a station supervisor, or a holder of the station key, can change death details and numbers of in-scope open cases without a server-side sign-in |
| Custodian and roster names in the station config | the config is signed, not encrypted: roster carries names and designations only; the custodian's contact is the one contact it holds; the file stays on the station | the custodian's name and contact on a copied config file |
| Sandbox data | never ingestable, never remapped; the writer refuses without a station config | none on the server |
| Local server reached by another app or a web page | section 10: loopback bind, per-launch bearer on every route, Host and Origin checks, no CORS | a process with the user's own privileges on the station |
| Coder seeing PII | coding view renders only mapped subcategory fields (field-data-collection, "Coding is masked"); coding records carry no PII | the station stores PII for the interviewer; local role separation is the app's |
| Server key leak | key on app host only; rotation and previous-key window | as the at-rest policy |
| Oversized or malformed file | size and line caps before decryption; no compression | none known |

## 9. Rollout, tests, open questions

**Stages**: (0) this spec agreed and `pii-envelope-format.md` landed; (1)
consent tables, `consent-config`, `consent` on `/intake/submissions`; (2)
device signing key on enrolment and the admin paste path; (3) validate-only
ingest and the test vectors; (4) full ingest with registration, consent and
interview; (5) coding results; (6) attachments with `digitva-jkvl`.

**Server tests** (each a focused pytest):

- Ingest idempotency: the same bundle twice gives the same report and no new
  rows; the same records by HTTPS then bundle are `duplicate`.
- Tamper: a changed manifest byte, record byte, reordered or dropped record
  line each refused before decryption; a record moved between bundles fails to
  open.
- Replay: reused `bundle_id` with other bytes 409; too old and future refused.
- Unknown and previous `kem_key_id`: previous key opens, unknown refused.
- Revoked and compromised device; unknown signing key; actor without a prior
  session on the device; a station with no custodian (`station_not_onboarded`).
- Corrections: `death_correction` and `identifiers_set` accepted for a roster
  `station_supervisor`, refused for another acting role or outside the roster
  scope; stale by `if_updated_at` and by `base_client_id`; `case_completed`;
  closed case refused; audit carries `authorized_by: station_roster`.
- Registration consent reused by the interview; a new consent for a
  different informant.
- `consent_required` and `consent_conflict` per record; a project without
  consent config unchanged; HTTPS `consent` idempotent.
- Partial acceptance: one invalid record among valid ones; dependency
  rejection.
- Newer vs older version of the same interview across two bundles.
- Coding: masked result applied, `pending` until ready, superseded version
  refused, the report and the pending row hold no personal data.
- Size limit 413 before reading; line limit; record count.
- Report and logs never contain a value (a sentinel phone and name in the
  records never appear in the report, logs or audit).
- Dry run writes nothing.

**Questions put to the owner** (all resolved below; the accepted default in brackets):

1. Q1. Bundle uploader: data manager and interview supervisor browser
   sessions plus the station's own bearer? [yes]
2. Q2. Reuse the `PII_KEM_*` key pair for bundles rather than a separate
   transport pair? [reuse, AAD label `digitva_bundle`]
3. Q3. `BUNDLE_MAX_AGE_DAYS` and previous-key retention? [90 days; keep the
   previous KEM private key at least that long after rotation]
4. Q4. Actor trust: roster plus a prior device session, no per-user keys in
   v1? [yes; per-user signing keys later if impersonation becomes a concern]
5. Q5. Offline coding only in self-coding, `masked_simple` projects, and the
   PHC coder needs a `coder` grant on the site? [yes]
6. Q6. Should the station config carry a case list for cases registered on the
   web (with informant contacts, which would need a station KEM key)? [no in
   v1: stations register their own cases; supervisors resolve duplicates]
7. Q7. Encrypted bundle file retention on the server? [7 days, then delete]
8. Q8. Contact attempts and visits in bundles? [not in v1]
9. Q9. Station config lifetime? [180 days; the station warns at 30 days left]
10. Q10. Consent at registration for web and Expo death reporters (bead
    athy). Decided below; the station also takes it at registration
    (contract decision 4).

## 10. Local server requirements (added 2026-10-21)

The station app's local server (`digitva-server`, Axum) is accepted as the
app's own backend. It serves the app's UI on the station and does none of
the central server's duties (section 1). It MUST:

1. Bind `127.0.0.1` only; on Android prefer an in-process bridge to a TCP
   port.
2. Require a random per-launch 256-bit bearer token on **every** route, GETs
   included, compared in constant time and kept in memory only.
3. Check the `Host` header (`127.0.0.1:<port>` or `localhost:<port>`) and
   `Origin` (the app's own origin or none) on every request (DNS
   rebinding).
4. Send no CORS headers (remove tower-http's `cors` feature) and
   `Cache-Control: no-store` on every reply.
5. Keep personal data out of URLs, query strings, logs and crash dumps.
6. Never mint central-server ids: local rows are keyed by client UUIDs
   (`client_death_id`, `client_draft_id`, consent `client_id`, coding
   `client_id`); a local project key (`project_id = 1`, `PHC-STANDALONE`)
   never travels; records carry the server ids from the station config.
7. Never hand the shared web JS an access body with supervisor, data
   manager, PI or admin powers: its `/me/access` equivalent is the device
   projection (interviewer, death_reporter, coder, coding_tester, reviewer)
   of the signed-in roster user's roles; `station_supervisor` is a roster
   role that enables only the local correction screens.

**Station modes.** An unprovisioned standalone station is a labelled local
sandbox with an editable local roster; its records are never ingestable and
never remapped (contract decision 2). Real fieldwork uses an onboarded
station (enrolled, custodian recorded) with a signed station config and a
read-only roster; every roster user has their own PIN and encrypted store
(SQLCipher keyed from the OS keystore plus the PIN; auto-lock; 5 wrong PINs
wipe that user's store); each record carries the roster `user_id` and the
acting role; station supervisors may correct death details and numbers
locally (contract 4.2); an MCCD PDF from an offline coded result is not
marked provisional or disabled (contract decision 3). Records are
deleted on a matching receipt or HTTPS acknowledgement; station exports carry
no Aadhaar digits (not even the last 3), no partial digits, no informant name
or phone, and omit the sealed set.

## Owner decisions (resolved 2026-10-21)

The owner accepted the recommended defaults for Q1 to Q9 above and decided Q10
separately. Recorded as decisions:

1. Q1: a data manager or interview supervisor uploads a bundle in the browser
   (with CSRF), or the station uploads with its own device bearer token.
2. Q2: bundles are sealed to the existing `PII_KEM_*` public key (no separate
   transport key pair); the AAD label keeps the two uses apart.
3. Q3: a bundle is valid for 90 days, and the previous private key is kept at
   least that long after a rotation.
4. Q4: a record's actor is accepted only when the user is on the signed
   station roster and has signed in on that device at least once. No per-user
   signing keys for now. Paste-enrolled stations, which cannot have a device
   session, rely on onboarding and the signed roster instead (section 5.3
   "Actor trust", contract decision 1).
5. Q5: offline coding only in self-coding projects with `masked_simple`.
6. Q6: no server-provided case list in the station config. The offline app
   keeps its own **local case list** of the cases the station registered,
   interviewed or is coding; the bundle carries them. A server-to-station case
   download is out of scope. Supervisors resolve duplicates on the server.
7. Q7: the encrypted upload is kept 7 days; plaintext is never written to disk.
8. Q8: no contact attempts or visits in bundles for now.
9. Q9: station config lasts 180 days, with a warning at 30 days left.
10. Q10: consent is taken at registration whenever informant name, phone or
    address are entered, on web, Expo and the offline station alike (bead
    `digitva-athy`, contract decision 4); the interview reuses it and asks
    again only when the informant is a different person.
11. Further decisions of 2026-10-21 (contract section 12): onboarding with a
    custodian; ingest only from an onboarded station; no "provisional" MCCD
    PDF; purge on HTTPS via the station config; station supervisor
    corrections (`death_correction`, `identifiers_set`); the station roster.
