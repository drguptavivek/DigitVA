---
title: PII Slice 1b - Record Sealing, Payload Side Table, Version Fingerprint
doc_type: kb
status: active
owner: engineering
last_updated: 2026-10-21
---

# PII Slice 1b

Slice 1b of [the encryption-at-rest baseline](../policy/pii-encryption-at-rest.md)
(follows [pii-slice-1a.md](pii-slice-1a.md)). **Part I (foundations), part
II-A (write side and backfill, behind `PAYLOAD_PII_SPLIT_ENABLED`) and part
II-B (readers, below) are implemented, uncommitted on 2026-10-21.** The flag
is off everywhere and stays off until the release flips it. No backfill ran on
real data. The release runs the backfill and flips the flag in one sync-paused
window ("Release procedure").

**Review fix batch (2026-10-21, uncommitted).** After two independent
reviews: side rows record their own sealed set (`sealed_ids`, column added to
the uncommitted migration `d4f1b8c2a6e9`); a process with the flag off refuses
split versions; unchanged passes keep the side row; the sealed set is cached
per app context; blind-key rotation (`--recompute-digests`); upstream-change
copies (`flask pii strip-upstream-copies`); backup gate age bound; downgrade
guard; key custody (prod key outside the checkout, beat masks `private/`,
DORIS mounts no checkout). Details below and in
[runtime-and-operations.md](../current-state/runtime-and-operations.md).

**Follow-up (2026-10-21, uncommitted).** Never sealed: the sealed set
(`sealed_field_ids`, `all_sealed_field_ids`) subtracts
`pii_field_registry.NEVER_SEALED_FIELDS` (date of death `Id10022`,
`Id10023`, `Id10023_a`, `Id10023_b`, `Id10024`; sex `Id10019`; the age
fields), so an admin `is_pii` flag on one of them (dev: `Id10023` on
`WHO_2022_VA_SOCIAL`) keeps it in `payload_data`, the SmartVA input (as
before the sealed-set drop) and SmartVA run files; viewer redaction and
export omission still follow the flag (baseline OD9). The national-ID sweep's
`stored_payload_fingerprint` now refuses a split version with the flag off.

## What part I added

- **Crypto** (`app/utils/pii_crypto.py`, additive; the per-value API and its
  tests are unchanged):
  - `record_aad(table, field_id, row_id: bytes) -> bytes`:
    `table || 0x00 || field_id || 0x00 || row_id`.
  - `seal_record(fields: dict[str, str], *, table, row_id) -> (sealed:
    dict[str, str], dek_wrapped, key_id)`: one fresh DEK per record, one
    AES-256-GCM ciphertext (`v1:aes256gcm:`) per field with its own nonce and
    AAD; the DEK wrapped once (`v1:aes256gcm+mlkem768x25519:<key_id>:`) with
    the public key only.
  - `open_record(sealed, dek_wrapped, *, table, row_id, row_ref, only=None)
    -> dict[str, str]`: one unwrap for the record; `only` opens just the named
    fields. Every failure is the generic `PiiCryptoError` (row ref and key id).
  - DEK cache: a dict on `flask.g` keyed by the wrapped-DEK string, at most
    `DEK_CACHE_MAX` (256) entries, oldest evicted, gone with the app context
    (request or job), `clear_dek_cache()` for long batches, never persisted
    or process-wide (OD10). Failed unwraps are not cached.
  - Private KEM objects built once per key object (`KemPrivateKey.kem_objects`,
    a `cached_property`); the keyring is built once per process, so
    `unwrap_dek` no longer rebuilds them from the seed every call.
  - `subkey(class)` = `HKDF-SHA256(ikm = PII_BLIND_INDEX_KEY, salt = none,
    info = b"digitva-pii-bidx/v1/" + class, length = 64)`;
    `class_index(class, normalised)` = `hex(HMAC-SHA-512(subkey, value))`;
    `blind_key_id()` = first 8 hex of `SHA-256(PII_BLIND_INDEX_KEY)`.
    `BLIND_INDEX_CLASSES` = `phone`, `abha_number`, `abha_address`,
    `payload-fp`; any other label raises `ValueError`. No Aadhaar class.
    `blind_index` (registration numbers) is unchanged (Q3).
  - Rewrap: records use the per-value wrap format, so `rewrap_dek` re-wraps a
    record's `dek_wrapped` and leaves every field ciphertext byte-identical.
    `flask pii rewrap` still loops `map_death_identifier` only.
- **Side table** `map_payload_version_pii`, migration `d4f1b8c2a6e9` on
  `c7e3a9d1f5b2` (columns in
  [data-model.md](../current-state/data-model.md), "Payload Version PII").
  Added to `synthetic_demo_service.DELETE_TABLES` before
  `va_submission_payload_versions`.
- **`app/services/payload_pii_split.py`**: `split_payload`, `join_payload`,
  `pii_digest`, `version_fingerprint`, `fingerprint_of`,
  `stored_fingerprint`, `same_content`.
- **`app/services/payload_pii_accessor.py`**: `get_side_row`, `get_pii`,
  `get_full_payload`, `put_pii`, `strip_version`. Values are sealed as JSON
  text (a `null` or a number round-trips). `put_pii` reduces the national ID
  again and keeps earlier `review_flags`; `strip_version` splits the joined
  payload, so a rerun loses nothing. The caller owns the transaction.
  **Part II invariant:** once a side row exists, `join_payload` lets it win
  over `payload_data`, so a writer that changes a sealed field in
  `payload_data` alone is silently undone by the next join or strip; every
  write of a sealed field goes through `put_pii`.
- `pii_field_registry.PII_COLUMNS` lists the side table's `sealed`,
  `dek_wrapped`, `pii_digest` and both index columns (descriptive; nothing
  reads `PII_COLUMNS` today).

## Where the national ID lives

Per decision 2 ("inside the encrypted blob only") and decision 3 (no partial
digits in plaintext): `Id10073` is in `PII_FIELDS`, so it leaves
`payload_data` with the rest of the sealed set and is sealed in its reduced
form (`XXXXXXXXX123`). In the digest it enters as `{"last3", "present"}`.

## The fingerprint algorithm

1. `split_payload(payload, sealed_ids)`: `redact_payload_national_ids` first
   (slice 1a reduction, free-text sweep, flags), then the top-level keys in
   `sealed_ids` go to `pii`, the rest to `stripped`. The caller passes the
   sealed set: `pii_field_registry.sealed_field_ids(form_type_code)` (OD9).
2. `pii_digest(pii)` = `hex(HMAC-SHA-256(subkey("payload-fp"),
   canonical_json(n)))` where `n` maps each sealed field to its
   `normalize_payload_for_fingerprint` value, a value that normalises to null
   left out (absent, `null`, `""`, whitespace, `na` digest alike), and
   `Id10073` to `{"last3": <3 kept digits, or null when none were kept>,
   "present": true}`, left out when not answered.
3. `version_fingerprint(stripped, digest)` = `hex(SHA-256(canonical_json(
   {"payload": normalize_payload_for_fingerprint(stripped), "pii": digest})))`,
   `canonical_json` = `json.dumps(sort_keys=True, separators=(",", ":"),
   ensure_ascii=True)`.
4. A stored version: `stored_fingerprint(payload_data, side_row, sealed_ids)`
   drops the side row's own `sealed_ids` from `payload_data` and uses
   `side_row.pii_digest` (no decrypt); with no side row it splits
   `payload_data` on *sealed_ids* itself. `same_content(incoming_full,
   version, side_row, sealed_ids)` splits the incoming payload on the same
   set (`comparison_ids`) and compares the two.

"Stable across the move" means: `fingerprint_of(full payload)` equals the
fingerprint of its stored split form (stripped payload plus side-row digest),
and `join_payload(split)` is the reduced payload. It is **not** equal to the
old `canonical_payload_fingerprint`: the rule changes, so part II recomputes
every stored `payload_fingerprint` in the release window. Checked on dev
(2026-10-21, read-only script, all 9,414 versions, sealed set 20 ids):
join exact 9,414, shuffled-key fingerprint equal 9,414, stored split form
equal 9,414 (with and without a side row), sealed key left in the stripped
payload 0; 1,179 carry an answered `Id10073`.

Differences from the old rule, by design: for sealed fields only, absent and
`null` compare equal (today a key present as `null` differs from an absent
one); a changed number with the same last 3 digits is not a change (OD1); the
digest is keyed, so a blind-key rotation must recompute every fingerprint.

## Call sites part II must switch (verified 2026-10-21 by grep)

Fingerprint comparisons (both sides through `same_content` /
`version_fingerprint`):

- `app/services/submission_payload_version_service.py`: `ensure_active_payload_version`
  `:226, 230, 245` (assign at `:233, 246` and write at `:262` must store the
  stripped payload and `put_pii`); `create_or_update_pending_upstream_payload_version`
  `:291, 293` (assign `:294`, write `:308`); `_bootstrap_active_payload_version`
  `:374`.
- `app/services/va_data_sync/va_data_sync_01_odkcentral.py:763, 773` (release
  `:809`) and `:953, 957`.
- `app/services/web_intake_service.py:2729, 2733` (revision; release `:2783`;
  `prior` from `active.payload_data` at `:2651`, `carry=prior` at `:2727`);
  supervisor choice `prior` `:3000`, `carry` `:3011`, release `:3043`;
  `build_web_payload` takes ABHA from `carry` at `:2116`. The carry must be the
  opened prior (`get_full_payload`), or ABHA drops on every revision.
- `app/services/national_id_sweep_service.py:187` (writes
  `payload_fingerprint` with the old rule; not in the baseline list).
- `app/services/synthetic_demo_service.py:597` (own `sha256(json.dumps(...))`).
- `app/services/data_management_service.py:2672-2673`
  (`_build_upstream_changed_fields`, `:2662`): diff stripped parts, list
  `pii_changed_fields` by field id.

Writers and copies:

- `app/services/workflow/upstream_changes.py:87, 101, 104, 120`
  (`record_protected_upstream_change`, `:72`): stripped copies.
- `app/services/payload_enrichment_backfill_service.py:1029`
  (`_flush_single_update`, `sa.update` `:1038`, payload at `:1041`).

Readers (through the accessor, only when the viewer may see PII): **done in
part II-B**, see "Part II-B: the readers" below for what was switched.

Unchanged per the baseline (no sealed key): `open_submission_repair_service.py:48, 119`;
SmartVA prepdata already drops the sealed set (slice 1a,
`va_smartva_02_prepdata.py:237`).

## Part II-A: the write side (behind the flag)

`PAYLOAD_PII_SPLIT_ENABLED` (config, default false; `.env.example`). Off,
every changed site runs the code it replaced (the existing suites pass
unchanged). On:

- **One writer.** `submission_payload_version_service.write_payload_version(
  version, full_payload, new=...)` is the only code that writes
  `payload_data` and the side row together: split on the form type's sealed
  set (`sealed_ids_for_sid`, OD9), `payload_data` = stripped, `put_pii` (fresh
  DEK; an unflushed version is added and flushed first), `payload_fingerprint`
  = `version_fingerprint(stripped, row.pii_digest)`. The caller passes the
  FULL payload; a writer holding a stripped copy joins the opened PII first.
  Off: `payload_data` as given, and a new version's
  `canonical_payload_fingerprint` (an in-place update keeps its column).
- **One comparison.** `payload_matches(version, full_payload)`: off, old rule
  both sides; on, `same_content(full_payload, version, side_row, sealed)`,
  which splits BOTH sides on `comparison_ids`: the side row's own
  `sealed_ids` (the set its digest was computed under), or today's set for a
  version not yet split. An admin `is_pii` toggle after the split therefore
  never reads as a change; the version moves to the new set on its next
  real write or on a rerun of `split-payloads --apply` (the field-mapping
  edit row says so when the flag changes, and the change is logged by field
  id).
- **Flag off over split rows.** With the flag off, `payload_matches`,
  `write_payload_version` (update in place), `opened_payload` and
  `stored_payload_fingerprint` (the national-ID sweep) raise
  `PayloadSplitStateError` for a version that has a side row: a mis-set
  process can neither rewrite plaintext nor read a stripped payload as a
  change (which would release coding). One `EXISTS` on the side table per
  app context, a primary-key lookup per version only while rows exist.
- **Unchanged passes keep the side row.** When the side row already holds
  the incoming digest under the same sealed set and blind key, with no new
  review flag (`side_row_current`), `write_payload_version` writes no side
  row: no fresh DEK, no KEM wrap, no UPDATE; the section cache is dropped
  only if the stripped payload itself changed. A sync rerun leaves
  `dek_wrapped` byte-identical.
- **Sealed set per app context.** `sealed_ids_for_sid` resolves the form
  type's set once per form per request or Celery task (`flask.g`), not per
  submission; `FieldMappingService.clear_cache` bumps a generation that
  drops it. A toggle in another process applies from its next request or
  task; comparisons stay correct meanwhile (`comparison_ids`).
- **Open check.** `get_pii` recomputes the digest of the opened fields and
  fails like any open (`PiiCryptoError`, row id only) when it differs from
  `pii_digest` under the current blind key (a blob and digest from two
  different writes).
- **Section cache.** `put_pii` (and `strip_version`) call
  `invalidate_section_data_cache(va_sid)` unless `invalidate_cache=False`
  (the backfill flushes once instead); with the flag on the invalidation
  decides category visibility on the joined payload, since a category may be
  shown because of a sealed answer.

Per call site:

| Site | Change |
| --- | --- |
| `ensure_active_payload_version` (both "unchanged" branches and "new") | `payload_matches`, `write_payload_version`; the unchanged branches no longer write the incoming full payload back |
| `create_or_update_pending_upstream_payload_version` (unchanged and new) | the same |
| `_bootstrap_active_payload_version` | `write_payload_version(new=True)` |
| ODK sync `_upsert_form_submissions` (release decision, protected branch) and `_finalize_enriched_submissions_for_form` | `payload_matches` instead of two `canonical_payload_fingerprint` calls |
| `record_protected_upstream_change` | both copies through `payload_copy` (reduced; stripped with the flag on); an existing pending row also gets its old `previous_va_data` re-passed, so a row opened before the flip never keeps a plaintext previous copy beside a stripped incoming one |
| `data_management_service.dm_upstream_change_details` | adds `pii_changed` and, when true, one changed-field row `sealed_personal_data` ("Personal data (sealed; values not shown)"): the two versions' `pii_digest` differ. One digest per version names no field, so the review never lists which sealed field changed (the baseline's `pii_changed_fields` by field id would need a per-field digest; not built). `_build_upstream_changed_fields` itself is unchanged: it diffs the stripped copies; both copies go through `payload_copy` first, so a pre-flip plaintext copy never shows a sealed value (or a "changed to empty") |
| Web revision (`revise_submission`) | `prior = opened_payload(active)` (the carry keeps ABHA when no locked answer brings it back); `payload_matches(active, payload)` for the no-op test |
| Supervisor choice (`choose_interview`) | `prior = opened_payload(active)` |
| `payload_enrichment_backfill_service._flush_single_update` | flag on: `write_payload_version(version, join_payload(enriched, get_pii(version)))`; off: the direct update |
| `national_id_sweep_service._write_row` | `stored_payload_fingerprint` (new rule with the flag on; flag off, refused for a split version, so the sweep stops instead of writing an old-rule fingerprint) |
| `synthetic_demo_service._seed_cases` | `write_payload_version(new=True)` (its own `sha256(json.dumps)` is gone; flag off the column is now `canonical_payload_fingerprint`, never compared) |

Readers: see "Part II-B" below. Upstream-change
rows written before the flip are stripped by `flask pii strip-upstream-copies`
(below).

## Part II-B: the readers (flag on)

Flag off, every reader returns `payload_data` as stored (the existing suites
pass unchanged). On, a reader that needs a sealed field joins the side row in:

- **`submission_payload_version_service.joined_payload(version)`**: the reader
  entry point. Flag off: `version.payload_data` (no refusal and no database
  access; a split version read by a mis-set process shows the stripped payload,
  while the writers and `opened_payload` still refuse it). Flag on:
  `payload_pii_accessor.get_full_payload`. One DEK unwrap per version per
  request (DEK cache).
- **`payload_pii_accessor.get_pii_many(version_ids)`**: the list form, one
  query for a chunk, `{payload_version_id: opened fields}` for versions that
  have a side row. No N+1.
- **`case_content_service.viewer_source_payload(version, redact_pii)`**: a
  viewer who may see PII gets `joined_payload`; a redacting viewer gets the
  stripped `payload_data` and never causes a decrypt; `payload_for_viewer`
  then applies the PII-set redaction (so a pre-split version is redacted as
  before).

Switched:

| Site | Reads |
| --- | --- |
| `case_content_service.get_section_data` | `viewer_source_payload` (category tables and summary) |
| `coding_service.render_va_coding_page` | joined payload: category visibility, attachment counts, the header visit note (address and remarks redacted by `visit_note_for_viewer` for a redacting viewer) |
| `routes/va_form.renderpartial` | joined payload for `get_visible_category_codes`; `other_conditions_choices` and `submit_coder_initial_cod(payload_data=...)` read the age flags only |
| `routes/api/va_case._authorize` (visible categories), `_survey_location` input | joined payload; `viewer_source_payload` through `payload_for_viewer` |
| `reviewer_coding_service._reviewer_social_autopsy_required`, `_doris_prefill_snapshot` | joined payload |
| `coder_cod_service` final: `_social_autopsy_required` input and both `doris_prefill_record` calls | joined payload (the record is recomputed from the payload the display prefill used) |
| `doris_context_service.doris_initial` | joined payload for `doris_prefill_from_payload` (non-redacting viewers only; a date of birth an admin flagged `is_pii` is sealed) |
| `data_management_service.dm_accept_upstream_change`, `dm_keep_current_icd_on_upstream_change` | `apply_payload_to_submission_summary(joined_payload(pending))`: the category list and summary derive from the whole answer set |
| `visit_note.has_visit_note_condition` | adds `EXISTS` on the side row with `sealed ? 'visit_address'` (no decrypt) beside the payload keys |
| `visit_note.visit_notes_for(va_sids, *, redact_pii)` | the keyword is required: a redacting viewer's address and remarks stay sealed, others get one `get_pii_many` batch; callers `data_management_service` (list) and `routes/api/intake.supervised_case_detail` |
| `odk_case_service.backfill_odk_cases` | `get_pii_many` per chunk of `BACKFILL_CHUNK` for unlinked rows (name `Id10017`/`Id10018`), joined before `_identity_or_none` and `_insert_case` |

Checked and left as they are:

- `odk_case_service.ensure_case_for_odk_submission` / `_insert_case` on the
  sync path read the incoming plaintext `va_submission`, which the sync passes
  before any split. `org_routing.route_submission(payload=...)` and the
  projections (`_submission_projection_fields`, web intake
  `build_submission_projection`) are likewise derived from the full payload
  before `write_payload_version`.
- Exports (`dm_submissions_export_csv`, the SmartVA input export): both drop
  every `is_pii` field of the confirmed set (`_filter_export_payload`) and
  withhold an unconfirmed form type, and the sealed set is a subset of the
  flagged set (the registry flags `PII_FIELDS` on every form type; the sealed
  set also subtracts `NEVER_SEALED_FIELDS`), so a stripped payload loses
  nothing an export carries.
- `sync_tasks` repair scan (`KEY`, `FormVersion`, `DeviceID`, `SubmitterID`,
  `instanceID`, attachment counts), `_count_attachments_per_category`,
  `other_conditions_choices`, the analytics MV and `not_analysable` read no
  sealed key. Dev flags only `PII_FIELDS` plus `Id10023`
  (never sealed). An admin who flags one of those operational keys `is_pii`
  would seal it; the repair scan would then read it as missing, so do not
  flag them.
- `payload_enrichment_backfill_service` reads `KEY` and the attachment
  fields; its write already joins the opened PII (part II-A).
- `invalidate_section_data_cache` already joined the payload in part II-A.

Cost: a coding screen or API workspace request opens the side row once for
category visibility even for a redacting viewer (the visibility decision must
not depend on the viewer; only the category codes, never a value, reach that
viewer). Tests: `tests/services/test_payload_pii_readers.py`.

## Backfill: `flask pii split-payloads`

`app/services/payload_pii_backfill_service.py`, CLI in `app/commands/pii.py`.

- Dry run (default): counts per `version_status`: `versions`,
  `with_sealed_fields`, `side_rows`, `to_strip`, `to_recompute`,
  `already_split`. Never a value or a row id.
- `--apply --confirm-backup <key or sha256>`: the sweep's backup gate
  (`confirm_db_backup`: a successful `va_db_backups` row with a sha256).
  Every version of every status, keyset batches by `payload_version_id`
  (`FOR UPDATE` on the batch), side rows loaded in one query per batch, the
  sealed set resolved once per form. Per version: `strip_version` (side row,
  stripped `payload_data`, new-rule fingerprint), also for versions with no
  sealed field (empty side row, recomputed fingerprint). One commit per
  batch, DEK cache cleared per batch. Idempotent: a version with a side row
  holding only sealed fields, no sealed key left and a current fingerprint
  is skipped without a decrypt (a rerun writes nothing; wrapped keys stay
  byte-identical). Resumable: committed batches stay. Section cache flushed
  once at the end. Audit log line: backup key and counts.
- In-batch check (the "pre-strip hash recorded in the batch"): no column
  holds it, so it is kept in memory per batch. After the commit, every
  written version is reopened: `sha256(json(sorted join))` must equal the
  hash of its reduced pre-strip payload, and the stored fingerprint must equal
  both `stored_fingerprint` and `fingerprint_of(join)`. A mismatch stops the
  run with an error (that batch is committed: `--restore` or the dump).
- `--verify`: over every version (no decrypt): `without_side_row`,
  `sealed_key_in_payload`, `fingerprint_mismatch`; then a random sample
  (`--sample`, default 200) of side rows opened: digest of the opened fields
  equals `pii_digest`, fingerprint of the join equals the stored one. Exits
  non-zero on any problem.
- `--restore --confirm-backup ...`: refused with the flag on (set it false
  and restart first). For every version with a side row: the opened fields
  back into `payload_data` (**plaintext again**), the old-rule
  `canonical_payload_fingerprint`, the side row deleted; batches, resumable,
  a row that does not open is counted and kept. Possible only while the KEM
  private key exists. Restoring reintroduces plaintext, so it takes the same
  backup gate.
- `flask pii strip-upstream-copies [--apply --confirm-backup ...]`: both
  copies of every `va_submission_upstream_changes` row through the copy rule
  (national IDs reduced, sealed set stripped) whatever the flag. Lossless:
  the referenced versions hold the sealed fields. Keyset batches with the
  form joined (one sealed-set lookup per form), compare-and-set on both
  columns, dry run by default, idempotent, counts only.
- The backup gate (`confirm_db_backup`) also bounds the dump's age:
  `PII_BACKUP_MAX_AGE_HOURS` (default 24) unless `--allow-old-backup`
  (logged with the age).
- `_is_split` requires the side row's `sealed_ids` to equal today's set and
  its `blind_key_id` to be current, so `--apply` rewrites flag-changed and
  rotated rows; `--verify` counts `sealed_set_changed` and
  `blind_key_stale` as problems.
- Migration `d4f1b8c2a6e9` downgrade refuses while the table holds rows
  (`split-payloads --restore` first).
- `flask pii rewrap` now also loops `map_payload_version_pii` (keyset by
  `payload_version_id`, compare-and-set on `dek_wrapped`, field ciphertexts
  untouched).

## Release procedure

Rule and strip ship together (baseline, "Release"); nothing syncs or writes
in between. Part II-B (readers, implemented) must be in the deployed code before step 5.

1. **Pause writers.** Disable the ODK sync beat row ("ODK Sync — every 6
   hours", `celery_periodictask.enabled`, or `docker compose stop
   minerva_celery_beat`); stop a running sync with the admin sync stop
   (`POST /admin/api/sync/stop`) and wait until `GET /admin/api/sync/status`
   shows none running. Start site maintenance (`POST
   /admin/api/site-maintenance`, `site_maintenance_service`) so non-admin web
   writes stop after its 15-minute cutoff.
2. **Back up.** `flask backups db-dump --no-prune`; confirm the sha256 with
   `flask backups db-list`. Back up the KEM private key and
   `PII_BLIND_INDEX_KEY` apart.
3. **Deploy** the code with `PAYLOAD_PII_SPLIT_ENABLED=false`.
4. `flask pii split-payloads` (dry run: record the counts), then
   `flask pii split-payloads --apply --confirm-backup <key or sha256>`, then
   `flask pii split-payloads --verify` (must exit 0), then
   `flask pii strip-upstream-copies` (dry run) and
   `flask pii strip-upstream-copies --apply --confirm-backup <key or sha256>`.
5. **Flip** `PAYLOAD_PII_SPLIT_ENABLED=true` in `.env`; restart
   `minerva_app_service` and `minerva_celery_worker` in the same window. The
   value reaches beat too (`load_dotenv`); beat writes no payload, but restart
   it so no process runs with a stale flag. A process left on false refuses
   split versions (`PayloadSplitStateError`) rather than corrupting them.
   Only once part II-B (readers) has shipped: the CLI says not to flip before.
6. **Merge-gate rerun check**: run one ODK sync by hand for one form
   (`POST /admin/api/sync/form/<form_id>`) and confirm 0 added, 0 updated, no new
   `va_submission_upstream_changes` row and no new payload version for
   unchanged submissions; `flask pii split-payloads --verify` again.
7. **Resume**: end site maintenance, re-enable the beat row (or start beat).

The tests pin the gate (`tests/services/test_payload_pii_split_writes.py`,
`tests/routes/test_payload_pii_split_web.py`); with the old comparison
restored under the flag the gate tests fail (checked 2026-10-21).

Rollback before any new write: pause every writer (step 1), flag false,
restart, `split-payloads --restore --confirm-backup ...`. After new writes
with the flag on: the same (the restore joins every side row) or the dump.
**Writers stay paused until `--restore` reports `failed=0`**: while side rows
remain, a flag-off writer refuses those versions (`PayloadSplitStateError`),
so a sync run mid-restore errors instead of rewriting them. Only after that
can `flask db downgrade` drop the table (it refuses while rows exist).

## Blind-key rotation

`pii_digest` and both ABHA indexes are keyed by `PII_BLIND_INDEX_KEY`
(`subkey`), so a new key would make every unchanged sync read as a change.
Procedure, writers paused (Release procedure step 1) and a fresh dump:

1. Back up the old `PII_BLIND_INDEX_KEY` apart (needed only to read old
   dumps' indexes; nothing in the app keeps it).
2. Set the new key in `.env`; restart app, worker and beat.
3. `flask pii split-payloads --recompute-digests` (dry run: `to_recompute`),
   then `flask pii split-payloads --recompute-digests --apply --confirm-backup
   <key or sha256>`: every side row whose `blind_key_id` is not the current
   key's is opened and gets `pii_digest`, `abha_number_bidx`,
   `abha_address_bidx`, `blind_key_id` and the version's
   `payload_fingerprint` recomputed; blobs and wrapped DEKs stay
   byte-identical. Keyset batches, rows locked, one commit per batch,
   resumable (recomputed rows leave the selection), a row that does not open
   is counted and skipped. `--apply` would also fix a rotated row (it is not
   "already split"), by a full re-seal.
4. `flask pii split-payloads --verify` (`blind_key_stale=0`).
5. Resume writers. The register's phone and ABHA indexes (stage 2) need the
   same step when they exist.

Pinned by `test_blind_key_rotation_then_recompute_keeps_an_unchanged_sync_quiet`
(tests/services/test_payload_pii_split_writes.py): after the rotation an
unchanged record compares as changed; after the recompute an unchanged sync
adds no version and no upstream-change row.

## Open questions

1. Resolved (fix batch): a field flagged or unflagged `is_pii` after the
   split no longer reads as a change (each side row compares on its own
   `sealed_ids`). Until `split-payloads --apply` reruns, a newly flagged field
   stays in `payload_data` of the versions already split (plaintext) and an
   unflagged one in the side row; `--verify` counts them
   (`sealed_set_changed`). Rerun `--apply` in the sync-paused window after a
   flag change; the admin row says so.
2. Sealed keys below the top level: none on dev (0 of 9,414); `split_payload`
   handles the top level only.
   Part II-A: `split-payloads --apply` handles both (a side row holding an
   unflagged field is not "already split", so it is rewritten).
3. Done in part II-A: `flask pii rewrap` covers `map_payload_version_pii`.
4. Done in part II-A: `map_death_identifier` is in
   `synthetic_demo_service.DELETE_TABLES` before `va_death_register` (the
   reset refused with `unknown_dependency` since migration `c7e3a9d1f5b2`).
5. Done (fix batch): `flask pii strip-upstream-copies` strips them
   (lossless; the restore path is the referenced versions plus the dump).
6b. Owner decision pending: how long pre-split `db-dump` backups (which hold
   the sealed fields in plaintext) are kept; see the baseline's open
   questions.
6. `pii_changed_fields` by field id (baseline table) is not built: the
   review shows one "personal data changed" row by digest.
