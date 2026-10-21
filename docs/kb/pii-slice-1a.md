---
title: PII Slice 1a - National-ID Reduction, SmartVA Drop, Redacted-Only Cache
doc_type: kb
status: active
owner: engineering
last_updated: 2026-10-21
---

# PII Slice 1a

Status of slice 1a of [the encryption-at-rest baseline](../policy/pii-encryption-at-rest.md),
with the owner's 2026-10-21 resolutions: no Aadhaar blind index, no hash of
the number, no `aadhaar_full` field, only the last 3 digits kept, no Aadhaar
duplicate matching; OD5 to OD10 accepted. Implemented, uncommitted on
2026-10-21. Not in this slice: the side table, the fingerprint module, the
payload split, register columns, client (vendor engine, Expo) reduction and
the payload backfill (slices 1b, 1c, 2).

## What shipped

- **Reduction util** `app/utils/national_id.py`: `NATIONAL_ID_KEEP_DIGITS = 3`.
  - `reduce_national_id(value)`: stored form `XXXXXXXXX` plus the last 3
    digits, always 12 characters (a 16-digit VID too). None, blank, `na`,
    `n/a`, `none`, `null` and punctuation-only values (`-`, `"_"`) are "not
    answered" and kept as they are. Anything else is reduced; it is flagged
    for review unless it was a 12- or 16-digit number; fewer than 3 digits
    become `XXXXXXXXXXXX`.
  - `looks_like_national_id(text)`: 12 digits in groups of four (one optional
    space or hyphen between groups), optionally a fourth group (VID). Not
    inside a longer token: not glued to a letter, digit or `-`, not a decimal
    part, not a file name stem (`169512345678.jpg`). 10-digit phones and 11-,
    13-, 14- and 15-digit numbers do not match. A 12-digit phone with a `91`
    prefix does match and is masked (conservative).
  - `redact_national_id_digits(text)`: each match masked to the stored form.
  - `redact_payload_national_ids(payload)`: `Id10073` reduced at any depth,
    every other string swept, `Id10070` flagged only, identifiers and ABHA
    skipped (`SKIP_FIELDS`). Returns the flagged field ids.
  - Digits: Python `\d` matches every Unicode decimal digit (Devanagari,
    Arabic-Indic, fullwidth); kept digits are folded to ASCII with
    `unicodedata.decimal`. NFKC alone would fold only fullwidth digits.
  - Idempotent: the stored form never matches again.
- **ODK sync** (one choke point, `_reduce_incoming_national_ids`): see
  [odk-sync.md](../current-state/odk-sync.md), "National IDs reduced at
  ingest". The payload version service (`ensure_active_payload_version`,
  `create_or_update_pending_upstream_payload_version`,
  `_bootstrap_active_payload_version`) reduces before every write.
  `record_protected_upstream_change` reduces both copies it stores
  (`previous_va_data` may come from a version still holding a full number).
- **Web intake** (server authoritative): `stored_answers` at every draft-row
  write (browser section saves, device sync and upload, superseded copies,
  `final` and `history` sections), `build_web_payload` (submit, revision,
  supervisor choice), the visit note kept in draft meta, prefill answers, and
  register `remarks` and `place_of_death` in `_clean_death_fields`. The
  client's `answers_sha256` is kept as sent (an upload identity).
- **Change detection**: `normalize_payload_for_fingerprint` reduces national
  IDs first, on both sides of every comparison (sync, version service, web
  revision, the upstream-change field diff).
- **SmartVA**: `va_smartva_prepdata` drops the sealed set
  (`pii_field_registry.sealed_field_ids`: `PII_FIELDS` plus the form type's
  admin-flagged `is_pii` fields, minus the never-sealed date of death, sex
  and age fields, `NEVER_SEALED_FIELDS`). SmartVA scores none of it: it only renames
  `Id10073`, `Id10017`, `Id10018`, `Id10057` (`who_data.RENAME_QUESTIONS`,
  read with `row.get(src, '')`) into its output columns `national_id`,
  `name`, `surname`, `geography1`; its only required inputs are the age
  variables. `flask smartva scrub-runs` blanks those cells in existing runs.
- **Section cache**: only the redacted variant is cached; a non-redacted view
  is rendered fresh. `invalidate_section_data_cache` still drops both keys
  (legacy entries); `flush_section_data_cache` / `flask pii flush-cache`
  deletes every `form_data3:*` key.
- **Registry**: `Id10072` comment fixed to "place of registration" (kept in
  `PII_FIELDS`); `Id10073` is in `PII_FIELDS`.

## Review flags

There is no stored flag in slice 1a (no side table, no `review_flags`).
Flags are logged at ingest as field ids only, and the sweep's dry run is the
inventory (counts by field). Slice 1b stores them.

## Sync rerun safety (the merge gate)

`tests/services/test_national_id_sync_rerun.py`, all on `_upsert_form_submissions`
with `enrich_payloads=False` as production calls it:

- finalised case, full `Id10073` incoming, reduced stored: no version, no
  upstream-change row, state unchanged;
- the same with the **full** number still stored (first sync after deploy);
- a coding-in-progress case: allocation and first pass kept, no release;
- the finalize pass on a protected case reduces the stored version in place,
  no new version;
- a changed kept digit is still a change (upstream-change row, reduced copy).

With the reduction removed from the fingerprint those tests fail (checked).

## What is gated

Nothing is gated on slice 1b in this slice: because the fingerprint reduces
both sides, `sweep-national-id --apply` on `payload_data` is safe for change
detection (`test_after_apply_an_unchanged_odk_rerun_adds_no_version`) and is
enabled behind the backup gate. Slice 1b still replaces the fingerprint rule
with `version_fingerprint` and recomputes every stored fingerprint.

## Commands

```
flask pii sweep-national-id                       # dry run, counts only
flask backups db-dump --no-prune                  # then, with its key or sha256:
flask pii sweep-national-id --apply --confirm-backup <key or sha256>
flask pii flush-cache
flask smartva scrub-runs                          # dry run, counts per file kind
flask smartva scrub-runs --apply --confirm-backup <key or sha256>         # LOCAL first
flask smartva scrub-runs --s3 [--apply --confirm-backup <key or sha256> --versioning-noted]
```

**Backup gate.** Every `--apply` takes `confirm_db_backup`: the object key or
sha256 of a successful `flask backups db-dump` recorded in `va_db_backups`,
started at most `PII_BACKUP_MAX_AGE_HOURS` (default 24) ago, or
`--allow-old-backup` (logged). The SmartVA scrub used to accept any 64-hex
string; it now takes the same recorded lookup. A database dump does **not**
contain the run files: archive the run directories (or the S3 listing and
objects) yourself before the scrub; that copy is the scrub's only reversal.

**Order: local, then S3.** `archive_form_run` re-uploads every local file
whose size differs from its object, so an unscrubbed local copy of an
archived run would undo an S3 scrub on the next archive sweep. `--s3 --apply`
therefore refuses while any local run file still has a cell to blank. Run
`scrub-runs --apply` (local), then `scrub-runs --s3 --apply`; a scrubbed local
file and its scrubbed object have the same size, so nothing is re-uploaded.
Keep `archive-runs` from running between the two (it would upload the
scrubbed local copy, which is harmless).

`--apply` was not run against any real data. The S3 scrub never deletes
earlier object versions: with bucket versioning on, the operator expires them
through the bucket lifecycle.

## Dev dry-run counts (2026-10-21)

`flask pii sweep-national-id`:

| Table | Scanned | Would change |
| --- | --- | --- |
| `va_submission_payload_versions` | 9,414 | 787 |
| `va_submission_upstream_changes` | 949 | 0 |
| `va_web_intake_draft_sections` | 91 | 0 |
| `va_web_intake_drafts` | 13 | 0 |
| `va_death_register` | 14 | 0 |

By field: `payload_data.Id10073` redacted 787; flagged `Id10073` 155
(not a 12- or 16-digit number), `Id10070` 2. No free-text hit.

`flask smartva scrub-runs` (local; dev has no S3 store): 2,154
`smartva_input.csv` (1,261 with cells, 118,902 cells);
`individual-cause-of-death.csv` 1,165 (1,070 with cells, 21,714 cells);
`adult-predictions.csv` 1,503 (1,065, 21,031); `adult-raw-data.csv` 1,065
(1,065, 21,031); `child-predictions.csv` and `child-raw-data.csv` 109 each
(383 cells each); `neonate-predictions.csv` and `neonate-raw-data.csv` 97
each (300 cells each); `cleanheaders.csv` 96 (1,127); `adult-prepped.csv` 96
(1,116); `child-prepped.csv` 9 (9); `neonate-prepped.csv` 2 (2). Every other
file kind: 0. Errors: 0.
