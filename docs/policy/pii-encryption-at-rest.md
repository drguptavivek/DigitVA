---
title: Personal Data Encryption at Rest Policy
doc_type: policy
status: proposed
owner: Vivek Gupta
last_updated: 2026-10-21
---

# Personal Data Encryption at Rest Policy

Proposed baseline (AGENTS.md "Docs": policy before implementation). Only
stage 0 is built (implemented, uncommitted on 2026-10-21). It extends the
envelope scheme already in use for registration numbers
(`app/utils/pii_crypto.py`; spec
[death-registration-identifiers.md](death-registration-identifiers.md),
"Encryption at rest"; library API in
[docs/kb/cryptography-46-to-50-upgrade.md](../kb/cryptography-46-to-50-upgrade.md))
to the personal data on the death register and in the ODK / web interview
payload. Consent for collecting this data is a separate bead (`digitva-athy`,
[respondent-consent-notice-draft.md](respondent-consent-notice-draft.md)).

An independent audit (2026-10-21) found the first draft not ready to
implement. Its confirmed findings are folded in below as design corrections
and summarised as prerequisites in "Ready to implement?" at the end. The
owner resolved OD1-OD10 on 2026-10-21 and **dropped the keyed Aadhaar index
entirely** ("Owner decisions (resolved 2026-10-21)").

## Owner decisions (2026-10-21)

1. **Scope: register columns and payload fields.** `va_death_register`
   personal columns and every payload field in `PII_FIELDS`
   (`app/services/pii_field_registry.py`), listed under "Scope".
2. **Aadhaar: the full number is never stored**, not in the database, not in
   backups, not in any payload copy. At ingest it is reduced to the **last 3
   digits** (constant `AADHAAR_KEEP_DIGITS = 3`; 4 is UIDAI's display
   convention, the owner chose 3), kept **inside the encrypted blob only**.
   There is **no keyed index of the full number** (dropped, OD1-OD3). Reason: the Aadhaar Act and UIDAI's Aadhaar Data Vault rules allow a full
   number only inside an Aadhaar Data Vault; a business system should hold a
   reference or masked value. Sources to verify (not legal advice; numbering
   differs between sources): UIDAI Circular No. 14 of 2025 and the Aadhaar
   (Authentication and Offline Verification) Regulations, 2021.
3. **No partial digits in plaintext anywhere.** No last-N columns, no suffix
   index, no partial digits in lists, exports, logs, audit rows or analytics.
   Reason: last 4 of a phone plus last 3 of Aadhaar plus age, sex, date and a
   small area can single out a death.
4. **Informant phones** are encrypted at rest and stay displayed and
   callable (click-to-call) for the roles that see them today. Decryption
   happens in memory after the existing authorization checks; masking for
   roles without personal-data access stays (with no digits, decision 3).
   Server-side use (notifications, SMS or WhatsApp to the informant when the
   consent allows) decrypts just in time. Search is **exact full number
   only**, through a blind index of the normalised number; suffix search goes.
5. **ABHA number and address**: encrypted, shown to authorised roles,
   exact-match blind index. **Names and addresses**: encrypted, shown under
   the existing visibility rules.
6. **Payload**: PII fields move out of `payload_data` into a side table
   (see "Payload design" for the reasons and the rejected option).
7. **Backfill** is staged, additive, reversible, idempotent and resumable,
   with a verified backup first and plaintext removed only in a later,
   separate step (see "Backfill").
8. **Consent** (DPDP) is `digitva-athy`, cross-referenced only.
9. **Keys**: reuse the KEM key pair (`PII_KEM_*`). Blind indexes (phone, ABHA, payload fingerprint; none for Aadhaar) use one
   **subkey per data class**, derived from `PII_BLIND_INDEX_KEY` by HKDF with
   a class label, so a leaked index of one class does not help with another.
   AAD binds every ciphertext to its table, column (or field id) and row id.
10. **One data key per record** (a register row or a payload version), not
    one per value: smaller storage and far fewer decryptions per page. The
    consequence, accepted by the owner: every writer of these records holds
    the private key (no public-key-only writers for register and payload
    data).
11. **Devices send only the last 3 digits of Aadhaar** and no hash (the full
    number must never exist on a device). The browser reduces at capture
    too (OD4); the server reduces again and is authoritative. There is no
    Aadhaar index, so no duplicate matching by Aadhaar for any channel.
12. **Older database dumps are not purged** (owner answer, 2026-10-21).
    Recorded residual risk, for legal review: on 2026-10-21 the staging and
    dev databases held 9,441 payload versions, 1,179 with a non-empty
    `Id10073`; in the dev dataset 691 of those carry a 12-digit value, so
    existing backups and ODK Central itself very likely hold full national
    IDs. The new pre-backfill dump is deleted after about 7 days.
13. **Key custody stays simple for now** (owner, 2026-10-21): the app and the
    database run on separate hosts (split production). The KEM private key
    and the blind-index key are files or environment values on the **app
    host only**, owned by the deploy user, mode 0600, outside the repository,
    mounted into the app and worker containers only (never the beat
    container). The **database host never holds any key**.
    **As built (fix batch, 2026-10-21):** the private key matches this
    (default `/data/digitva-secrets/pii_kem_private_key`; `make
    ensure-secrets-prod` refuses a path in the checkout; beat masks the
    checkout's `private/`; a non-reader process refuses to start in
    production if it can read a key file; the internet-facing DORIS service
    mounts no checkout). The blind-index key does **not**: it is a `.env`
    value, and `.env` reaches every container that bind-mounts the checkout
    (app, worker **and beat**) through `load_dotenv`, and compose passes it to
    all three; production start requires it in every process that boots the
    app. DORIS holds neither key. Each key has an
    independent offline backup that is kept apart from the database backups.
    No external key manager (Infisical, AWS Secrets Manager or KMS) for now;
    the app reads the key from a file path, so one can be added at deploy
    time later without code changes. Rotation follows the procedure in
    `docs/policy/death-registration-identifiers.md` ("Key rotation").

**Correction to decision 12 (audit, 2026-10-21; the decision stands).**
Dev held **9,414** payload versions (1,179 non-empty `Id10073`, 691 of 12
digits); staging 9,441 (1,179 non-empty; earlier count, not re-run). The
Aadhaar residue is **not only older dumps**: SmartVA run directories and
their S3 archive hold `Id10073` in full. Dev, 2026-10-21: 1,166 CSV files
under `APP_SMARTVA_RUNS` with an `Id10073` column, 13,324 rows, 1,385 of 12
digits (every `*.csv`, digits-only match; the audit counted 2,151
`smartva_input.csv` files and 1,268 of 14,309 rows by another method). They
are scrubbed in "Backfill", step 6; decision 12 does not cover them.

Everything else below is a proposal built on these decisions; **Q** marks an
open question.

## Owner decisions (resolved 2026-10-21)

The owner accepted OD1-OD10 except the keyed Aadhaar index, which is **out of
scope and dropped entirely**. Why: a keyed hash of a 12-digit number can be
enumerated by a key holder (about 10^11 values), which a legal reviewer may
read as storing the number; the matching it bought (duplicates by Aadhaar) is
not worth that risk. Consequences, applied throughout this document: no
`aadhaar_bidx` column, no Aadhaar blind-index class, no
`PII_BLIND_INDEX_PREVIOUS_KEYS` for Aadhaar, no `aadhaar_full` browser field,
no Aadhaar duplicate matching, no Aadhaar legal enumeration risk, and the
Aadhaar rotation problem (audit finding 2) disappears.

- **OD1. Aadhaar out of the fingerprint.** Superseded: index dropped. The
  fingerprint covers only the redacted value (last 3 digits and a flag that a
  number was present), recomputable from the sealed blob. **Accepted
  limitation:** a changed upstream Aadhaar with the same last 3 digits is
  **not** detected as a change (no new version, no release, no upstream-change
  row). The owner accepts this.
- **OD2. Rotating the `aadhaar` index class.** Superseded: index dropped;
  nothing to rotate.
- **OD3. Legal review of the Aadhaar index.** Superseded: index dropped. The
  residual dump and ODK Central copies (decision 12) stay in the legal review.
- **OD4. Client-side reduction.** Accepted, changed: devices (vendor form
  engine, Expo) **and the browser** reduce `Id10073` at capture, and the
  server reduces again; the server is authoritative ("Client stage").
- **OD5. Aadhaar-like digits in other fields.** Accepted: redact and flag in
  free text; flag only in long-number fields (`Id10070`) ("Backfill", step 7).
- **OD6. Redis section cache.** Accepted: cache only the redacted variant.
- **OD7. SmartVA.** Accepted: drop the sealed set from the SmartVA input and
  scrub existing run directories and S3 objects in place.
- **OD8. `Id10072`.** Accepted: the instrument labels it "Place of
  registration" (`vendor/who-va-2022/src/generated/`, en, hi, fr); the
  registry comment says "death certificate identifier"
  (`pii_field_registry.py:149`). Fix the comment, keep it in `PII_FIELDS` (an
  office plus a date narrows a death).
- **OD9. Sealed set.** Accepted: global `PII_FIELDS` **union** the form's
  admin-flagged `is_pii` rows (`get_pii_set_status(...).field_ids`, used by
  `payload_for_viewer`, `case_content_service.py:147-162`, and
  `_filter_export_payload`). A later flag is sealed by rerunning the payload
  backfill for that form. **Never sealed** (owner, 2026-10-21):
  `pii_field_registry.NEVER_SEALED_FIELDS` is subtracted from the sealed set
  (`sealed_field_ids`, `all_sealed_field_ids`): the date of death (`Id10022`,
  `Id10023`, `Id10023_a`, `Id10023_b`, `Id10024`), sex (`Id10019`) and the
  age fields (`ageInYears`, `ageInMonths`, `ageInDays`, `ageInMonthsByYear`,
  `finalAgeInYears`, `isNeonatal`, `isChild`, `isAdult`, `age_group`) stay in
  `payload_data`, the SmartVA input and SmartVA run files even when an admin
  flags them `is_pii`, so coding and the case record read them in plain form.
  The admin flag keeps driving viewer redaction and export omission as
  before. Exact date of birth (`Id10021`) is not on the list (Q1).
- **OD10. DEK cache.** Accepted: per request or job batch, keyed by the
  wrapped-DEK string, bounded by page size; no process-wide DEK cache.

## Scope

**Register** (`va_death_register`, `app/models/va_web_intake.py`):
`deceased_name`, `father_name`, `mother_name`, `informant_name`,
`informant_phone`, `informant_phone_2`, `abha_number`, `abha_address`,
`address`, `address_house_street`, `address_village_ward`,
`address_landmark`, `place_of_death`, `remarks`, and the GPS fix
(`latitude`, `longitude`, `accuracy_m`; one sealed field `location`). Not
encrypted: `deceased_sex`, `date_of_death`, `date_of_birth`,
`date_of_birth_partial`, `age_years`, status and ids. They drive filters,
the duplicate window and indexes; they are quasi-identifiers under decision
3 and the export rules (**Q1**).

**Payload** (`va_submission_payload_versions.payload_data`, every
`version_status`): the `PII_FIELDS` keys `Id10007`, `Id10010`, `Id10010a`,
`Id10010b`, `Id10010c`, `Id10017`, `Id10018`, `Id10055`, `Id10057`,
`Id10061`, `Id10062`, `Id10070`, `Id10071`, `Id10072`, `Id10073`,
`visit_address`, `visit_remarks`, `abha_number`, `abha_address`, plus the
form's admin-flagged fields, minus the never-sealed fields (OD9). Read at run
time, never copied.

**Aadhaar class is `Id10073`** ("National identification number of
deceased"; a newborn may carry a parent's ID). It is a free string with no
constraint in the instrument and is treated as Aadhaar class **whatever it
holds**: a mistyped Aadhaar fails any format check and would otherwise be
kept. A 16-digit Virtual ID there is reduced the same way (last 3). The register has no Aadhaar column; web registration collects ABHA.

**Aadhaar-like digits elsewhere.** Free text is not format-checked: `Id10070`
held a 12-digit value on dev, and `Id10476` / `narration`, `comment`,
`Id10436`, `Id10054`, `Id10066`, register `remarks` and `place_of_death`,
and `visit_remarks` could. The sweep in "Backfill", step 7, handles them.

**Copies of the same data** (each follows the same rule, or the encryption
is moot):

| Holder | Today | Change |
| --- | --- | --- |
| `va_submission_upstream_changes.previous_va_data`, `incoming_va_data` (`workflow/upstream_changes.py:94`) | full payload copies | stripped payload plus `pii_changed_fields` (field ids only) |
| `map_case_transitions.changes` | old/new plaintext of register fields on `details_edited`, `identity_from_interview` | each value sealed (AAD = transition id and field); identifiers keep only `bidx` |
| `va_web_intake_draft_sections.data`, `va_web_intake_drafts.prefill`, draft history (`_keep_history`, `_keep_losing_version`, `web_intake_service.py:3399, 3414`) | answers, prefill, kept versions | Aadhaar reduced at every save; a reopened draft shows "recorded, ending in 3 digits" and accepts it on resubmit; other fields **Q2** |
| `va_submissions.va_instance_name` (`submission_payload_projection_service.py:60`) | ODK `instanceName`; web sets `<unique_id>_WHOVA2022` (`web_intake_service.py:2119`) | check each ODK form's `instance_name` in stage 3; if built from names, store the web-style id. Omitted from exports |
| SmartVA input CSV (`va_smartva_02_prepdata.py:209-215, 251`) | every key except `_SMARTVA_DROP_PREFIXES` (`sa*`, `survey_block`, `telephonic_consent`): `Id10073` included | drop the sealed set (OD7); SmartVA does not score it ([demographic-general.md](../kb/smart-va/demographic-general.md), [trace-summary-matrix.md](../kb/smart-va/trace-summary-matrix.md)). Stage 1 |
| SmartVA run directories (`smartva_service._copy_form_run_workspace`, `:215-228`; `APP_SMARTVA_RUNS`, `config.py:183`) | whole workspace on disk | scrub ("Backfill", step 6) |
| SmartVA S3 archive (`smartva_run_archive_service.archive_form_run`; `smartva_runs/` prefix, `config.py:265-275`) | archived run directories | scrub ("Backfill", step 6) |
| Redis section cache (`case_content_service.py:240`, `SECTION_CACHE_TIMEOUT = 1800`; `RedisCache`, `app/__init__.py:258`) | per role and PII variant, non-redacted included: plaintext PII in Redis for 30 min | redacted only (OD6); flush after each backfill and strip; `invalidate_section_data_cache` (`:113`) also on side-table writes |
| Devices (vendor engine `vendor/who-va-2022`, Expo `mobile/digitva-collect`, existing local drafts) | full `Id10073` in the encrypted local store until upload | reduced at capture ("Client stage") |
| ODK Central | full submission, full Aadhaar | out of our control ("Open issues") |

## Keys and blind indexes

- **Envelope**: as the identifiers spec: AES-256-GCM data cipher, DEK
  wrapped by hybrid ML-KEM-768 + X25519, `v1:` prefixes, generic failure
  naming row id and key id only.
- **One DEK per record** (decision 10): a register row or a payload version.
  Every write draws a fresh DEK and re-seals all its fields, each with its
  own nonce and AAD. A wrapped DEK is about 1.5 KB: per value that is about
  20 KB a register row and 28 KB a payload version, and 200 instead of 50
  unwraps a 50-row page. Every writer holds the private key: a one-field
  edit needs the other fields, and sync opens the stored record for
  `pii_changed_fields`. Registration identifiers keep one DEK per value.
- **AAD** = `table || 0x00 || column or field id || 0x00 || row id bytes`
  (`death_id`, `payload_version_id`, `transition_id`).
- **Subkeys**: `subkey(class) = HKDF-SHA256(ikm = PII_BLIND_INDEX_KEY, salt =
  none, info = b"digitva-pii-bidx/v1/" + class, length = 64)`; `bidx =
  hex(HMAC-SHA-512(subkey(class), normalised))`. Classes: `phone`
  (both informant columns, so a number matches in either), `abha_number`,
  `abha_address`, and `payload-fp` (fingerprint digest). No Aadhaar class.
  One class per kind of number, so register and payload correlate for
  duplicates. **Q3**:
  `map_death_identifier.value_blind_index` uses the raw key with a type-id
  context: keep, or recompute under a `registration` class.
- **Honest limit**: phones (10^10) are enumerable by any subkey holder.
  Aadhaar has no index, so this risk does not exist for it. HKDF separation helps when one subkey leaks, not the
  master key or process memory.
- **Normalisation**: phone: digits, strip leading `+91`, `91` or `0` to 10
  digits, else sealed with no index. Aadhaar: digits; reduced to the last 3
  with a flag that a number was present (no index, no Verhoeff check needed). ABHA number: 14 digits; ABHA address: trimmed, lower-case.
- **Blind key id** beside every index column (first 8 hex of `SHA-256(master
  key)`), so a rotation can tell old from new.
- KEM key files, mounts and start-up refusal as the identifiers spec. No
  `PII_BLIND_INDEX_PREVIOUS_KEYS`: every index class is recomputable from
  the opened records, so rotation needs no old key.
- **Rotation**: KEM: `flask pii rewrap` re-wraps one DEK per record.
  `PII_BLIND_INDEX_KEY`, writes and sync paused: recompute phone and ABHA
  indexes, every `pii_digest` and every `payload_fingerprint` from the opened
  records (payload side: `flask pii split-payloads --recompute-digests
  --apply`, procedure in [pii-slice-1b.md](../kb/pii-slice-1b.md),
  "Blind-key rotation"). The identifiers spec "Key rotation" points
  here for these classes.

**New crypto code.** `pii_crypto.py` is per-value today: `encrypt_value`
draws a DEK per call, `decrypt_value` unwraps per call, and `unwrap_dek`
rebuilds the ML-KEM and X25519 private objects from the seed every call
(`:333-390`). Needed: `seal_record(fields, aad_for) -> (sealed, dek_wrapped,
key_id)` (one DEK, AAD per field); `open_record(sealed, dek_wrapped, aad_for,
*, row_ref, only=None)` (one unwrap, opens only what is asked); the OD10 DEK
cache; private key objects built once per process; `subkey(class)` and
`class_index(class, value)` (HKDF is net-new; `blind_index`, `:401`, stays
for registration numbers). `flask pii rewrap` (`app/commands/pii.py`,
`rewrap_pending`) is hard-wired to `MapDeathIdentifier`: add one keyset loop
per table (register, side table, sealed audit rows), same compare-and-set.

## Fingerprint and change detection

**Today** every "same payload?" decision recomputes
`canonical_payload_fingerprint(payload_data)`
(`submission_payload_version_service.py:111`) on both sides; the stored
`payload_fingerprint` is written but never compared, on purpose
(`web_intake_service.py:2711-2713`). Sites: ODK sync
`va_data_sync_01_odkcentral.py:742/752` and `932/936` (a difference releases
coding, `:788`, or writes an upstream-change record on a protected case);
version service `ensure_active_payload_version` (`:206, 210, 225`),
`create_or_update_pending_upstream_payload_version` (`:270, 272`),
`_bootstrap_active_payload_version` (`:352`), column written at `:242, 287,
352`; web revision `web_intake_service.py:2710/2714` (release `:2764`);
supervisor choice `:2985-3003` via `ensure_active_payload_version` (release
`:3024`); `synthetic_demo_service.py:596` (own `sha256(json.dumps(...))`);
`data_management_service._build_upstream_changed_fields` (`:2660`, field
diff).

**Failure if unchanged.** After the strip the stored side lacks the PII
keys and incoming ODK data has them: every sync "changes" every case,
releasing coding or writing upstream-change rows on every run. Changing the
rule without recomputing stored values does the same.

**The rule.** One new module, `app/services/payload_pii_split.py`, called by
every site above on both sides:

- `split_payload(raw, form_type_code) -> PayloadSplit`: `stripped` (raw
  minus the sealed set), `pii` (normalised plaintext, Aadhaar reduced),
  `aadhaar` (`last3`, `present`), `pii_digest`.
- `pii_digest = hex(HMAC-SHA-256(subkey("payload-fp"), canonical_json(pii)))`,
  `Id10073` entering as `{last3, present}` (OD1). One digest per version,
  not per field, so it reveals no per-field equality across records.
- `version_fingerprint(stripped, pii_digest)` =
  `sha256(canonical_json({"payload": normalize_payload_for_fingerprint(stripped),
  "pii": pii_digest}))`: the only fingerprint function; the stored
  `payload_fingerprint` is its value.
- `same_content(split, version, side_row)`: fingerprints equal (the stored
  stripped part recomputed, as today; `pii_digest` read from the side row, so
  no compare decrypts). There is no separate Aadhaar check: a changed upstream
  Aadhaar with the same last 3 digits is **not detected** (OD1, accepted).
- An incoming `Id10073` that is already redacted (a revision or supervisor
  choice built from the opened prior, a reduced device upload) contributes
  only `{last3, present}`, the same as a full number would.
- The incoming payload is split **before** comparing. The "unchanged"
  branches today assign the incoming full payload
  (`submission_payload_version_service.py:213, 226, 273`); they assign
  `split.stripped` and rewrite the side row, or a no-op rerun re-introduces
  plaintext.
- Web revision and supervisor choice (`web_intake_service.py:2631-2632,
  2706-2708, 2985-2992`) build `carry` from the **opened** prior (stripped
  payload plus opened side fields). `build_web_payload` takes ABHA (`:2098-2099`)
  and identity keys (`:2108`) from `carry`; a stripped one would drop ABHA on
  every revision. `:2714` becomes `same_content(split_payload(payload), ...)`,
  never stripped against unstripped.
- `_build_upstream_changed_fields` diffs stripped parts and lists
  `pii_changed_fields` by field id.

**Release.** Rule, chokepoint split and the strip of a class ship in **one
release** inside one window: stop beat and the sync queue, deploy, split
and recompute `payload_fingerprint` and `pii_digest` for **every** version
(every `version_status`) in the same transaction per batch, verify, resume.
Nothing syncs in between.

**Merge-gate test.** After backfill and strip, rerunning the ODK sync over
unchanged ODK data for a finalised and a coding-in-progress case creates no
version, no upstream-change row and no release, and leaves no sealed key in
`payload_data`; a changed `Id10073` with a different last 3 is detected (the same last 3 is
not, by design, OD1); an identical web resubmission creates no version and keeps ABHA.

## Register design (stage 2)

**Decided 2026-10-21; task T1 implemented, uncommitted** (columns, accessor,
writers, flag: [pii-slice-2.md](../kb/pii-slice-2.md)). Additive columns on
`va_death_register`: `pii_sealed` (JSONB `{field: "v1:aes256gcm:..."}`),
`pii_dek_wrapped`, `pii_key_id`, `pii_blind_key_id`, `pii_sealed_at`; blind
indexes `informant_phone_bidx`, `informant_phone_2_bidx`, `abha_number_bidx`,
`abha_address_bidx` (String(128), nullable; partial indexes `(project_id,
<bidx>) WHERE <bidx> IS NOT NULL`); four presence flags, Boolean not null
default false: `has_deceased_name`, `has_informant_phone`,
`has_informant_phone_2`, `has_location`.

- **Sealed set (14 columns plus one field).** `deceased_name`, `father_name`,
  `mother_name`, `informant_name`, `informant_phone`, `informant_phone_2`,
  `abha_number`, `abha_address`, `address`, `address_house_street`,
  `address_village_ward`, `address_landmark`, `place_of_death`, `remarks`,
  and `latitude`, `longitude`, `accuracy_m` sealed as **one field**
  `location` (JSON). Phones are sealed in full (shown and callable later);
  no partial digits anywhere. Plaintext: `deceased_sex`, `date_of_death`,
  `date_of_birth`, `date_of_birth_partial`, `age_years`, `captured_at`,
  `status`, `pending_flag`, `source`, `next_visit_at`, `last_contact_at`
  and every id. One DEK per record, AAD = `va_death_register`, field,
  `death_id`.
- **Flag `REGISTER_PII_SPLIT_ENABLED`** (default false; replaces the draft
  names `PII_SEAL_REGISTER` and `PII_READ_SEALED`), 1b semantics. Off: every
  writer runs its old code, and a writer meeting a sealed row raises
  `RegisterSplitStateError` (as `PayloadSplitStateError`); reading sealed
  rows still opens them. On: a write seals the record and **nulls the
  plaintext columns in the same write**, sets `pii_sealed_at`, the presence
  flags and the blind indexes. Strip is therefore not a separate step for
  new writes; the backfill (T-later) seals existing rows the same way.
- **One accessor**: `app/services/register_pii_accessor.py`.
  `open_register_pii(rows, only=...)` returns `{death_id: {attr: value}}` in
  the shape `serialize_death`, `serialize_worklist_row` and the supervision
  serialisers use (plaintext columns for an unsealed row, so flag-off and
  pre-backfill are identical); authorization stays with the caller. Writes go
  through `seal_register_pii` / `write_fields` / `seal_new_row`.
- **Presence**: the four flags are what filters, the worklist and
  `case_transition_service.identity_complete` read, never the sealed column.
  A mapper listener sets each flag from its plaintext column on insert and
  update (a flag-off writer needs no code), and leaves a flag alone when the
  plaintext is NULL because the row is sealed. CHECK
  `ck_va_death_register_identity`: `status IN ('draft_identity',
  'cancelled') OR (has_deceased_name AND date_of_death IS NOT NULL AND
  deceased_sex IS NOT NULL)`. CHECK `ck_va_death_register_location_all_or_none`:
  `(latitude IS NULL) = (longitude IS NULL) AND (has_location = (captured_at
  IS NOT NULL)) AND (has_location OR accuracy_m IS NULL) AND (latitude IS NULL
  OR has_location)`. Any other truthiness test on a sealed column moves to the
  flag in the stage 2 review.
- **Audit**: `map_case_transitions.changes_dek_wrapped` and `changes_key_id`;
  with the flag on, the old and new values of sealed fields in `changes` are
  ciphertexts (AAD = `map_case_transitions`, `<field>.old|new`,
  `transition_id`), other fields stay plain.
- **Rollback**: flag-off rollback is safe only before the first new sealed
  write. After it, sealed rows exist nowhere else: restore from the verified
  dump (or a restore-to-plaintext task), then downgrade; the migration's
  downgrade refuses while any register or audit row is sealed.
- **Duplicate matching on names**: `_possible_duplicate_rows`
  (`web_intake_service.py:4091-4255`; `similarity()` `:4124`, `by_number`
  `:4198`, union `:4236`, `rank <= per_case` `:4250`), called per worklist
  page (`:3927`, `per_case=3`) and per case (`:4270`,
  `DUPLICATE_CANDIDATES_MAX = 50`). pg_trgm cannot score ciphertext and the
  cut follows scoring, so a Python scorer opens every windowed candidate.
  Options: (a) keep the non-PII predicates in SQL (project,
  `DUPLICATE_DAYS`, sex, unit adjacency, open status, scope), add a cheap
  prefilter (age band, nearer units first) and a per-subject recency cap
  before any decrypt, open names (one unwrap per candidate, OD10 cache),
  score with a Python trigram matching pg_trgm, then cut to `per_case`;
  (b) exact name blind index (loses fuzzy matching); (c) keep
  `deceased_name` plaintext as an exception. **Recommended: (a).** Cost:
  page size × windowed candidates per subject; the merge gate measures the
  95th percentile on staging and sets the cap above it (proposed 50). The
  `by_number` branch is unaffected. The hint's `informant_name` and
  `address_village_ward` come from the same opened records.
- **Phone and ABHA hints**: exact blind-index matches, score 1.
  Built (T3, `register_duplicate_service.py`, 2026-10-21): design (a) with
  the cap `DUPLICATE_PREFILTER_MAX` (default 50) applied per subject in SQL
  to sealed candidates only (plaintext-name candidates are scored uncapped, as
  before), before any decrypt, nearest first (same unit, closest date, id);
  the score-1 branches are cut per subject at `DUPLICATE_STRONG_MAX` (default
  50) the same way; no age band (it would change results). Phone (either column against either) and
  ABHA number and address are separate equality branches of one UNION, each
  on the `(project_id, bidx)` partial index, only for a subject that has the
  index (unsealed rows have none and match nothing); they ignore the date,
  sex and unit gates like the registration-number branch.

## Payload design (stage 3)

**Recommended: a side table**, `map_payload_version_pii`:
`payload_version_id` (PK, FK), `va_sid` (indexed), `sealed` (JSONB
`{field_id: "v1:..."}`), `dek_wrapped`, `key_id`, `pii_digest`,
`abha_number_bidx`, `abha_address_bidx` (indexed, with blind
key ids), `review_flags` (JSONB, from the sweep). The PII keys are
**removed** from `payload_data`. Rejected: envelope strings in place.

- **Fail closed.** In place, every `payload.get(field)` reader silently
  receives ciphertext (exports, SmartVA, analytics, DORIS prefill); with a
  side table the field is absent, which readers already handle.
- **Reuse.** `payload_for_viewer` and `_filter_export_payload` already strip
  PII by key; the stored payload becomes their output for PII fields.
- **Presence** stays queryable: `sealed ? 'visit_address'`.

**Derived columns are computed before the split.** `apply_submission_projection`
(`submission_payload_projection_service.py:59-77`) derives `va_summary`,
`va_catcount` and `va_category_list` from the full payload before
`split_payload`, so categories do not change. `invalidate_section_data_cache`
(`case_content_service.py:126`) reads `va_category_list` instead of the
stored payload.

**Write chokepoints**: `ensure_active_payload_version`,
`create_or_update_pending_upstream_payload_version`,
`_bootstrap_active_payload_version` (both their "new" and "unchanged"
branches). Bypasses routed through the same split:
`payload_enrichment_backfill_service._flush_single_update` (`:1029`,
`sa.update` `:1038`) and `synthetic_demo_service` (`:594`). A test asserts no
sealed key is ever stored in `payload_data`.

**Readers of `payload_data`**:

| Reader | Uses PII? | Change |
| --- | --- | --- |
| Coding screens: `coding_service.py:117`, `case_content_service.py:124, 207`, `routes/va_form.py:287`, `routes/api/va_case.py:213, 436, 536`, `reviewer_coding_service.py:212, 234`, `utils/va_mapping/va_mapping_01_fieldsitepi.py` | yes, when `should_redact_pii` allows | `payload_for_viewer` merges opened fields only when not redacting |
| Section cache `case_content_service.py:240` | caches non-redacted render | redacted only (OD6) |
| `odk_case_service._insert_case` (sync) | yes | reads incoming plaintext before the split |
| `odk_case_service.backfill_odk_cases` (`:175-214`, `_identity_or_none(row.payload_data)` in keyset chunks) | yes | joins the side table and opens names per chunk; else every row is `identity_missing` after strip |
| `visit_note.py:24-45` (SQL `payload_data[key]`: `visit_date`, `visit_address`, `visit_remarks`) | yes | `visit_date` stays; presence drops the address term for `sealed ? 'visit_address'`; text via accessor |
| Web revision, supervisor choice (`web_intake_service.py:2631-2714, 2985-3003`) | yes (carry, compare) | opened prior as `carry`; `same_content` |
| Upstream change record `workflow/upstream_changes.py:94`; diff `data_management_service.py:2660` | copies | stripped plus `pii_changed_fields` |
| ODK sync `va_data_sync_01_odkcentral.py:742-949`; version service | writes, compares | chokepoint and `same_content` |
| Enrichment backfill `payload_enrichment_backfill_service.py:260-432, 1038` | rewrites | through the split |
| SmartVA `va_smartva_02_prepdata.py:209-215` | copies every key | drop the sealed set (OD7) |
| `open_submission_repair_service.py:48, 119` | no PII key | unchanged; check in stage 3 review |
| Export `data_management_service.py:1407, 1556, 1572, 1936, 1959, 2895, 3041` | strips PII already | unchanged |
| `submission_analytics_mv.py:576, 679, 873-891, 1500` | no `PII_FIELDS` key | unchanged; narrative is Q4 |
| `not_analysable.py:24`, `coder_cod_service.py:211-839`, `doris_context_service.py:59`, `coding_service.py:38`, `tasks/sync_tasks.py:867-903`, `commands/payload_backfill.py` | no `PII_FIELDS` key | unchanged |
| `synthetic_demo_service.DELETE_TABLES` (`:56`) | n/a | add `map_payload_version_pii` before `va_submission_payload_versions` (FK order) |

**Register readers**: `web_intake_service.py` serialisers
(`serialize_death` ~4495, `serialize_worklist_row` ~4553, case detail
~4606), duplicate matching (`:4091-4255`), prefill (~1410, 1502, 2097),
identity sync (~1800, 2688); `case_list_service.py:585, 673`;
`case_transition_service.py`; `routes/api/intake.py`; `odk_case_service.py`;
`synthetic_demo_service.py`; `va_frontpages/va_intake_death.html`,
`static/js/intake/duplicates.js`, `intake_supervision.js`,
`intake_worklist.js`, `summary.js`; the Expo client. No server code messages
informants today; a future sender decrypts just in time and logs ids only.

**Fixtures.** 48 test files reference `payload_data` (grep, 2026-10-21).
Those asserting PII in a stored payload move to the side table or accessor,
among them `tests/services/test_viewer_pii_redaction.py` and
`tests/routes/test_va_form_pii_redaction.py`; the stage 3 plan gives every
file of `grep -rl payload_data tests` a verdict.

## Client stage (stage 1c)

Decision 11 says the full number never exists on a device; today it does
(vendor engine and Expo keep `Id10073` as typed until upload). With OD4 the
browser reduces too, and the server reduces again as the authority:

- The form engine reduces `Id10073` when the answer is committed, to the
  form the server stores (last 3 and a "present" flag; no hash). The form accepts the
  redacted value on reopen.
- Upload hash: `answers_json` + `answers_sha256` verified at
  `routes/api/intake.py:833-844`; `sync_device_draft`
  (`web_intake_service.py:3444`) compares the stored hash (`:3480-3481`) and
  keeps it in history. The client hashes the reduced text, so the server's
  reduction is a no-op and the stored draft matches the hash.
- Implemented (digitva-vi5p): `vendor/who-va-2022/src/national-id.ts` ports
  `reduce_national_id`; the session (`setAnswer`, initial data, `replaceData`)
  and `decodeWhoVaDraft` reduce, the text control buffers the typed number
  and commits it, reduced, on blur, end or submit editing, unmount, or a flush
  the form runs before it advances, saves, goes back, switches section or
  submits (a native Next or Save tap does not blur a focused field; never key
  by key). A buffer is dropped when the answer changes from outside while it
  is focused (`replaceData`, server merge, relevance reset). The Expo draft
  store reduces on save, and so do the revision store (seed, autosave,
  freeze) and the browser revision snapshot. Both sides are held to
  `vendor/who-va-2022/tests/national-id-vectors.json`, including Python
  `str.strip()` whitespace (`\x1c`-`\x1f`, `\x85`; not U+FEFF) and non-ASCII
  digits. The browser form is the same Expo web export, so it inherits all
  of it. Drafts already on a device stay full at rest until their next
  save; they are reduced on load, when marked completed, and when listed for
  upload (the upload hash is of the reduced text). The bundles
  (`app/static/vendor/who-va-2022`, the Expo web export) must be rebuilt to
  ship it.
- A local draft from before the update is reduced on the device before it
  uploads, so the hash matches the stored text. Only an older app that does
  not reduce still sends the full number: the server reduces it and keeps the
  client hash as sent (an upload identity, never recomputed from stored
  content), a mismatch that is accepted; a test pins it.
- Browser entry: the browser form reduces at capture like the device
  engines and hashes the **reduced** answers. There is no `aadhaar_full`
  field and no separate channel: the full number never reaches the server
  from a client that reduces. A client that did not reduce (an older app, a
  direct API call) is reduced by the server. The revision path's hash test
  (`web_intake_service.py:2715`) compares like with like.

## Search and duplicate matching

- Exact phone search: the server normalises the query and matches the
  `phone` index in either column, only for viewers who may see phones. Exact
  ABHA search likewise. There is no Aadhaar search. No suffix search (stage 0 removed the
  client match on the masked phone).
- Name search stays client-side over the page's opened names.
- Duplicates: names per "Register design" (a); phones and ABHA by blind
  index (built, T3). No Aadhaar duplicate matching.

## Audit and logging

- Registration identifiers in `map_case_transitions.changes` carry `bidx`
  only (stage 0; identifiers spec, "Audit content"). Register PII fields:
  `{"old": "<sealed>", "new": "<sealed>"}`, admin tool only, never an API.
- Logs, task arguments, error reports and audit `reason`: ids, field ids,
  counts. A decrypt failure names the row id and key id.

## Exports and analytics

- The data manager CSV omits the sealed set; Aadhaar is never exported, not
  even its last digits. Registration numbers keep their audited exception
  (identifiers spec, decision 9). No partial digits anywhere (decision 3).
- The case list CSV (`case-list-views.md`) never carries informant name,
  address or phones; the deceased's name is opened per streamed keyset batch,
  no plaintext temp file.
- Research-repository export (bead `digitva-fx2c`, not built; decided
  2026-10-21): only for cases whose respondent granted the research-sharing
  purpose. Carries the district, rural or urban status, the month and year
  of death (day dropped) and the age group; never the exact address (no
  village, sub-district or street), names, phones, Aadhaar, ABHA or
  registration numbers. GPS only as a jittered point: a random displacement
  of up to 2 km (one configurable constant, default 2 km), fixed per case
  from a secret seed, with no district-boundary check.

## Performance

- Open only what is rendered: one unwrap per visible row; redacted viewers
  none. A coding screen: one; a 50-row worklist: about 50 plus the duplicate
  check (page × capped candidates).
- Filters, counts, tiles and sync comparisons never decrypt (non-PII
  columns, blind indexes, `pii_digest`, key presence).
- The merge gate times a page, the duplicate check, a sync of 1,000
  unchanged submissions and a 10,000-row backfill batch on staging and
  records them here.

## Backfill

One CLI group, `flask pii`, run in `minerva_app_service`:

1. **Backup first**: `flask backups db-dump --no-prune`, confirm the sha256
   with `flask backups db-list`
   ([split-production-deploy.md](../current-state/split-production-deploy.md),
   "Back up"). Back up the KEM private key and `PII_BLIND_INDEX_KEY` apart.
2. `flask pii backfill <register|payload|aadhaar> [--dry-run] [--batch-size N]`:
   keyset batches, one commit per batch, idempotent, resumable, counts only
   (`sealed`, `skipped`, `failed`, failing row ids). Covers every version
   status, upstream change rows, audit `changes`, draft sections and draft
   history for Aadhaar. Each payload batch writes the side row, the stripped
   payload (at strip) and the recomputed `payload_fingerprint` in one
   transaction, inside the sync-paused window.
3. `flask pii verify <class> --sample N`: opens a sample, compares with the
   plaintext still present, recomputes indexes (phone, ABHA) and `version_fingerprint`,
   fails on any mismatch or unsealed row; counts recorded.
4. **Strip**, separately: `flask pii strip <class>` after a passing verify and
   a hold (proposed 30 days). Aadhaar has **no hold**: it strips right after
   verify; the "full number held nowhere by us" claim is true only once
   steps 6 and 7 have also run. Dropping columns is a later migration.
5. **Cache flush** (`flask pii flush-cache`) after every backfill and strip.
6. **SmartVA scrub** (`flask pii scrub-smartva [--dry-run]`), after the OD7
   prepdata change is live: list every run directory under
   `APP_SMARTVA_RUNS` and every `smartva_runs/` S3 object with a sealed-set
   column (paths and counts), back the list up, rewrite each CSV in place
   without those columns (S3: same key, re-read the header to verify, then
   remove prior object versions if versioned). Idempotent, counts only.
7. **Aadhaar-like sweep** (`flask pii sweep [--dry-run]`): every string value
   in payload versions, draft sections, draft history and register text,
   matching `\b\d{4}\s?\d{4}\s?\d{4}\b` and the 16-digit
   `\b\d{4}(\s?\d{4}){3}\b`, skipping ODK metadata (`KEY`, `instanceID`,
   `sid`, `site_individual_id`) and non-string instrument fields. Dev,
   2026-10-21: 12 digits once in `Id10070`; 16 digits in `Id10070` (16) and
   `Id10213` (32, numeric, excluded); none in drafts or register text. On a
   hit (OD5): free text is redacted in place and the field id added to
   `review_flags`; `Id10070` is flagged only. Counts and row ids only.

**Sync reruns** go through the chokepoints and `same_content`: no plaintext
written back, no version added, no side row orphaned (one row per version,
FK, same transaction).

**Data loss and recovery.** Losing the KEM private keys loses every sealed
value; keys are backed up apart and kept while any retained backup needs
them. Before strip, rollback is the read flag off. After strip: `flask pii
restore` (needs the private key) or the pre-backfill dump. The full Aadhaar
cannot be restored by design (ODK Central is the only source), and nothing
needs it: there is no Aadhaar index to rebuild. The SmartVA
scrub and the sweep are reversible only from that dump and the step 6 list.
The dump holds full numbers and is deleted about 7 days after the Aadhaar
verify passes (decision 12).

## Rollout order

Every stage: migration chained onto a committed revision (`flask db heads`
before and after), flag default off, writes first, readers behind the
accessor, then backfill, verify, strip. Flags: `PII_SEAL_AADHAAR`,
`REGISTER_PII_SPLIT_ENABLED` (register) and `PAYLOAD_PII_SPLIT_ENABLED` (payload).

0. **No keys — implemented, uncommitted (2026-10-21).** `mask_phone` gone;
   worklist rows carry `has_informant_phone` / `has_informant_phone_2`; the
   Expo phone fact, a11y label and client phone match removed; new
   identifier audit rows carry `bidx` only. Docs already match
   (`docs/current-state/device-collection-api.md`, identifiers spec "Audit
   content"). Left: scrub the legacy `mask` member from existing
   `map_case_transitions.changes`. Irreversible, so gated by "Backfill" step
   1 (verified dump and sha256), dry run first, keyset batches, counts only.
1. **Aadhaar**: crypto functions, HKDF known-answer tests (phone, ABHA,
   fingerprint classes), side table with `Id10073` (last 3 and flag), `payload_pii_split` at every site, reduction at chokepoints,
   draft saves, history and upstream copies, SmartVA drop (OD7), redacted-only
   cache (OD6); one release; then backfill with fingerprint recompute,
   verify, strip, SmartVA scrub, sweep, cache flush, dump purge. 1c (client)
   ships with or before it.
2. **Register**: columns, indexes, accessor, `has_deceased_name`, duplicate
   design (a), phone and ABHA indexes, audit sealing; backfill, verify, hold,
   strip. Depends on 1.
3. **Payload**: the rest of the sealed set, readers per the table, fixtures;
   backfill with recompute, verify, hold, strip, flush. Depends on 1 and 2.

Each stage updates `docs/current-state/data-model.md`, `odk-sync.md`,
`api-v1.md` and `expo-client.md`.

## Tests

Beyond the merge-gate test in "Fingerprint and change detection":

- Crypto: HKDF known-answer vector per class; one number, two classes, two
  indexes; AAD moved to another row, column or field fails; one DEK per
  record write; full-record round trip; one unwrap per record with the cache.
- Aadhaar: after an ODK sync, web submit, device upload, draft save and
  enrichment re-fetch, no column, payload, upstream row, draft section,
  history, SmartVA input, cache entry or log line holds the 12 digits
  (assert the record exists first); the blob opens to last 3; a 16-digit VID
  is reduced the same way; `AADHAAR_KEEP_DIGITS` is honoured; no Aadhaar
  index column or class exists.
- Device: a reduced upload's stored hash equals the client's; a legacy
  full-number upload is reduced, keeps its hash, and its resend is recognised;
  a browser entry stores no full number and its hash equals the stored
  reduced answers; the server reduces a direct API upload that still carries
  the full number.
- No partial digits in worklist, supervision, case list, export or analytics
  for roles without phone access; no `_masked` field.
- Visibility unchanged per role (present for an allowed role first, then
  absent for a redacted one); redacted pages decrypt nothing; Redis never
  holds a non-redacted render.
- Fingerprint: "unchanged" branches leave no sealed key; a changed PII value
  adds a version; blind-key rotation then unchanged sync adds no version; an upstream
  Aadhaar change with the same last 3 adds none either (pins the accepted
  limitation, OD1).
- Derived: `va_category_list`, `va_summary`, `va_catcount` equal before and
  after the split on the baseline dataset; `identity_complete` and
  `backfill_odk_cases` unchanged after strip.
- Duplicates: Python trigram equals pg_trgm on fixtures; hints identical
  before and after stage 2 at `per_case` 3 and 50; phone and ABHA score 1;
  constant queries per page.
- Backfill: dry run writes nothing; rerun no-op; interrupted run resumes;
  verify fails on a tampered row; strip refuses without verify; constant
  queries per batch; sweep redacts free text and flags `Id10070`; SmartVA
  scrub idempotent.
- Rotation: `flask pii rewrap` moves register and side rows, ciphertext
  unchanged.

## Non-goals

- No HSM or KMS in the first stages (Q7). No decrypt service.
- No fuzzy or partial search on any number.
- No change to who may see what.
- No encryption of the device's local store (already encrypted) or of
  attachments (separate storage policy).
- Consent capture and notice (`digitva-athy`).

## Open issues

- **ODK Central holds the full Aadhaar** in every submission and its
  backups; we cannot redact it there. Owner options: ask projects to stop
  collecting full Aadhaar in `Id10073` (form change), or accept the ODK copy
  under the project's data agreement.

## Open questions

1. Seal `date_of_birth` and `date_of_birth_partial` too? The age band is
   used for filtering; the dates are not.
2. Seal the other sealed-set fields in draft sections and prefill (Aadhaar
   is covered by decision 2)?
3. Registration-number blind index: legacy raw-key derivation or an HKDF
   class?
4. Narrative free text (`Id10476`, `narration`) can contain names; it is not
   in `PII_FIELDS` and stays plaintext (the sweep handles digits only).
5. Research-repository exports: resolved 2026-10-21 (month and year of
   death, district, rural or urban, age group, jittered GPS; see "Exports and
   analytics").
6. Existing dumps holding full Aadhaar: answered by decision 12 (not
   purged); SmartVA copies are scrubbed regardless (step 6).
6a. **Owner decision pending:** retention of the `flask backups db-dump`
   dumps taken before the payload split (they hold every sealed field in
   plaintext, and upstream-change copies too). Decision 12 says the
   pre-backfill dump is deleted after about 7 days; older dumps are not
   purged. Not decided here.
6b. **Investigate:** `va_submissions.va_uniqueid_real` (and
   `va_instance_name` built from it) on dev has the shape `<letters><digits>
   <letter>_<4-9 capital letters>` for about 1,400 of 8,300 submissions on 8
   forms, which may embed part of a name; it is not sealed. Check each ODK
   form's `unique_id` calculation (counts only, 2026-10-21).
7. HSM or cloud KMS for the KEM private key.
8. Does DPDP cover the deceased's data? It protects living "Data
   Principals"; informant and family data is covered either way. Treated as
   covered.
9. `Id10073` with a parent's or non-Aadhaar ID: treated as Aadhaar class; is
   a type selector wanted?

## Ready to implement?

Owner decisions OD1-OD10 are resolved (2026-10-21). Still not implemented:
P = prerequisite, T = test; a stage starts when its P items are built.

- [ ] F1 P: `payload_pii_split` at every listed site, both sides; "unchanged"
  branches store the stripped payload; rule and strip in one release in a
  sync-paused window; fingerprint recompute for every version in the split's
  transaction. T: the merge-gate test.
- [x] F2 P: OD1, OD2, OD3 resolved (index dropped). Left: blind key id
  beside every phone and ABHA index; identifiers spec rotation note points
  here. T: rotation then unchanged sync adds no version.
- [ ] F3 P: OD7 prepdata drop; scrub command with list-first backup. T: no
  sealed column in a new `smartva_input.csv`; scrub idempotent.
- [ ] F4 P: opened prior as `carry`; `same_content` at `:2714` and in
  supervisor choice; a redacted incoming Aadhaar contributes the same
  `{last3, present}`. T: identical resubmission adds no version and keeps
  ABHA.
- [ ] F5 P: OD6 (resolved); flush after backfill and strip; invalidation on side writes.
  T: Redis holds no non-redacted render.
- [ ] F6 P: OD5 (resolved); sweep with dry run; `review_flags`. T: redact free text,
  flag `Id10070`, skip numeric fields.
- [ ] F7 P: OD4 in the vendor engine, Expo and the browser form; reduced-answer
  hash on every client; server reduces again; legacy-draft hash rule. T: the device and browser tests.
- [ ] F8 P: design (a), recency cap measured on staging. T: hint parity at
  `per_case` 3 and 50; constant queries.
- [ ] F9 P: `seal_record`, `open_record`, OD10 cache, cached key objects, HKDF
  subkeys; `flask pii rewrap` over the new tables. T: crypto tests.
- [ ] F10 P: `has_deceased_name`; `backfill_odk_cases` opens names;
  `visit_note` via the side table; `DELETE_TABLES`; projection before split;
  verdicts for the 48 fixture files. T: derived-column and identity tests.
- [ ] F11 P: stage 0 committed; legacy `mask` scrub behind a verified dump.
- [ ] F12 P: OD8, OD9 (resolved); counts re-run on staging before stage 1.

Slice 1b part I implemented (foundations); see docs/kb/pii-slice-1b.md.

## Language-neutral format

The byte-exact format of sealed values, records, wrapped DEKs and blind
indexes, with cross-implementation test vectors for a second (Rust)
implementation, is in [pii-envelope-format.md](pii-envelope-format.md)
(vectors `tests/fixtures/pii_envelope_vectors.json`, checker
`scripts/check_pii_blob.py`).

Offline PHC bundles (sealed to the `PII_KEM_*` public key, Aadhaar last 3 digits only): see [offline-bundle-and-transfer.md](offline-bundle-and-transfer.md).

Slice 1b part II-A implemented behind PAYLOAD_PII_SPLIT_ENABLED, with the
2026-10-21 review fix batch (sealed set per side row, flag-off guard,
rotation, upstream copies, key custody); part II-B (readers) implemented, flag stays false
until the release
(docs/kb/pii-slice-1b.md, "Part II-A", "Release procedure", "Blind-key
rotation"). Follow-up 2026-10-21: the never-sealed list (OD9) and the flag-off
refusal in `stored_payload_fingerprint` (the national-ID sweep) are
implemented.
