---
title: Offline PHC Desktop Edition Policy
doc_type: policy
status: active
owner: Vivek Gupta
last_updated: 2026-10-21
---

# Offline PHC Desktop Edition Policy

## Purpose

The **DigitVA Field / PHC Edition** enables health workers and Medical Officers (MOs) at a remote Primary Health Centre (PHC) station to operate offline on a desktop or tablet workstation (Windows, macOS, Linux, Android) using **pure Rust and compiled JavaScript only** (zero Python runtime, zero Docker runtime, zero C/Fortran extensions), and synchronize records with a central DigitVA server either via direct HTTPS (`/api/v1/*` with a device bearer token) or via a signed, hybrid-KEM-sealed `.dvb` bundle ([offline-api-contract.md](../from-server/2026-10-21/policy/offline-api-contract.md), [offline-bundle-and-transfer.md](../from-server/2026-10-21/policy/offline-bundle-and-transfer.md)).

## Scope Boundaries

### Included in the Offline PHC Station Edition

1. **Station Onboarding, Custodian, and Signed Station Config (`digitva-bundle` & `digitva-db`)**:
   - Real fieldwork is ingestable only from an **onboarded** station with a verified **custodian** (`{name, designation, phone, email, onboarded_on, verified_by_user_id}`) and an admin-signed two-line `.station-config` file (`b"digitva-station-config-v1\x00" || line1`).
   - An unprovisioned standalone installation operates strictly as a **local sandbox** (`project_id = 1`, `PHC-STANDALONE`): sandbox data is local-only, never exported as a `.dvb` bundle, and never remapped into a server project.
   - Station roster (`death_reporter`, `interviewer`, `station_supervisor`, `coder`): editable in the standalone sandbox, read-only on a provisioned station (using integer server `user_id`s). A `station_supervisor` role is a roster-level role (never in `/api/v1/me/access`) issued by the server only to a user holding an `interview_supervisor` grant at that site. Every record carries `actor_user_id` and `acting_role`.

2. **Registration-Time DPDP Consent, Identifiers, and Aadhaar Reduction (`digitva-text`, `digitva-db`, `mobile/digitva-collect`)**:
   - **DPDP Consent at Registration**: Respondent consent is captured at death registration (`client_draft_id: null`) before any informant personal data (`informant_name`, `informant_phone`, `informant_phone_2`, `address*`) is saved. The interview reuses the case's granted registration consent and re-asks only when the informant is a different person (`client_draft_id` set). Provisioned projects never fall back to hardcoded notices, purposes, or contacts.
   - **Web-Only Consent Withdrawal & Purge**: Consent withdrawal is recorded on the central web application only. The station receives sorted UUIDs to erase via the `purge` list in the signed station config and in `.dvb` bundle receipts.
   - **Registration Identifiers & Phones**: Validated with NFKC + uppercase + collapsed-whitespace normalisation and anchored full-match regexes (`^(?:...)$`); `letters_digits_hyphen_slash` excludes spaces. Case replies return `identifiers` as a sorted list (`[{code, label, value}]` for value viewers, `[{code, label, present}]` for `coder`) and `warnings: [{code: "identifier_in_use", field, message}]` without other cases' IDs. Indian mobile numbers normalise to 10 ASCII digits (dropping leading `+91`, `91`, or `0` when 10 digits remain) with no partial phone digits anywhere.
   - **Aadhaar / National ID (`Id10073`)**: Reduced at capture to `XXXXXXXXX` + last 3 ASCII digits (`XXXXXXXXX123`) or `XXXXXXXXXXXX` (`< 3` digits), with `answers_sha256` computed over the reduced text and no Aadhaar hash or full number ever stored.

3. **Station Supervisor Corrections (`death_correction` & `identifiers_set`)**:
   - On a provisioned station, a roster user acting as `station_supervisor` may correct death registration details (`death_correction` / `PATCH /api/v1/intake/deaths/<id>`) **only until the interview is completed** (`409 case_completed` thereafter), and may set registration identifiers (`identifiers_set` / `PUT /api/v1/intake/cases/<id>/identifiers`) both before and after interview completion.
   - Closed cases (`cancelled`, `duplicate`) cannot be modified on the station (`409 case_closed`) and require the web.

4. **Offline SmartVA Scoring & Sealed-Field Exclusion (`digitva-smartva`)**:
   - Pure-Rust in-memory execution of the WHO 2022 -> PHMRC transformation and SmartVA Tariff 2.0 scoring engine (`desktop/crates/digitva-smartva`).
   - Coder views, SmartVA inputs, and station CSV exports strip the union of the 19-field `PII_FIELDS_FLOOR` (`Id10007`, `Id10010`, `Id10010a`, `Id10010b`, `Id10010c`, `Id10017`, `Id10018`, `Id10055`, `Id10057`, `Id10061`, `Id10062`, `Id10070`, `Id10071`, `Id10072`, `Id10073`, `visit_address`, `visit_remarks`, `abha_number`, `abha_address`) and the project's `sealed_field_ids` from the signed station config.

5. **Offline ICD-10 / ICD-11 / DORIS Coding & Unwatermarked MCCD PDF (`digitva-icd11` & `digitva-pdf`)**:
   - Local FTS5 reference catalogs (`mas_icd10_2019_2`, `mas_icd11_mms`, `mas_icd_search_terms`, `mas_va_cause_definitions`, `map_icd_cod_buckets`) and in-process WHO ICD-11 `2.6.0` / DORIS engine (`desktop/crates/digitva-icd11`).
   - Deterministic A4 WHO Medical Certificate of Cause of Death (MCCD) PDF generation (`desktop/crates/digitva-pdf`) printed normally **without** a provisional watermark.

6. **Data Protection, SQLCipher Per-User Stores & Sealed `.dvb` Bundles (`digitva-pii`, `digitva-bundle`, `digitva-db`, `digitva-server`)**:
   - **SQLCipher (`bundled-sqlcipher`)**: Local database encrypted at rest using a 256-bit key derived via `HKDF-SHA256` from the OS keystore secret + roster user ID + user PIN (6–16 ASCII digits). Enforces inactivity auto-lock and wipes the user's local store after 5 consecutive wrong PIN attempts (`403 store_wiped_max_pin_attempts`).
   - **PII Envelope (`digitva-pii`)**: Implements [pii-envelope-format.md](../from-server/2026-10-21/policy/pii-envelope-format.md) (`v1:aes256gcm+mlkem768x25519:` DEK wrapping to the server's public key only, `v1:aes256gcm:` value sealing with `record_aad`, and HKDF/HMAC blind indexing).
   - **`.dvb` Bundle Transfer (`digitva-bundle`)**: Writes line-oriented `.dvb` files (JCS manifest line, Ed25519 `b"digitva-bundle-v1\x00"` signature line, and AEAD-sealed record lines in canonical order) and verifies signed server receipts (`b"digitva-receipt-v1\x00"`), deleting local records only upon matching receipt acknowledgement (`received_sha256` verified for interviews).
   - **Loopback Server (`digitva-server`)**: Binds `127.0.0.1` only, requires a constant-time per-launch 256-bit bearer token on every `/api/v1/*` route (GETs included), validates `Host` and `Origin` against DNS rebinding, sends `Cache-Control: no-store` on every reply, and emits zero CORS headers.

### Excluded (Central Server Responsibilities Only)

- Unpacking or ingesting `.dvb` bundles, holding server private KEM keys, or sealing at rest with server private keys.
- Authoritative cross-case duplicate matching, workflow routing, or recording consent withdrawals.
- Closed-case corrections and server-level supervision (`supervised_case_condition`).
- Peer-to-peer station federation.
