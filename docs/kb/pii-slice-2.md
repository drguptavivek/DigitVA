---
title: PII Slice 2 - Sealed Death Register
doc_type: kb
status: active
owner: engineering
last_updated: 2026-10-21
---

# PII Slice 2

Slice 2 of [the encryption-at-rest baseline](../policy/pii-encryption-at-rest.md)
("Register design"), after [pii-slice-1b.md](pii-slice-1b.md) (the payload
side this mirrors). **Task T1 (migration, model, accessor, writers, flag) is
implemented, uncommitted on 2026-10-21.** `REGISTER_PII_SPLIT_ENABLED` is off
everywhere and stays off until the readers, duplicate matching and backfill
ship; with it off all behaviour and tests are unchanged. Bead `digitva-vt9j`.

## T1 as built

- **Migration** `e5a2c7b9d3f1` on `d4f1b8c2a6e9`: columns, indexes, CHECKs and
  the `map_case_transitions` pair as in
  [data-model.md](../current-state/data-model.md) ("Sealed personal data").
  The four presence flags are filled in the migration (`col IS NOT NULL`, plain
  SQL so `updated_at` stays). Downgrade refuses while any register row has
  `pii_sealed` or any audit row has `changes_dek_wrapped`. Tests:
  `tests/migrations/test_add_register_pii_columns.py` (real upgrade/downgrade
  on a scratch database) and `test_schema_drift.py`.
- **CHECKs** (names via `op.f`, no doubled prefix):
  - `ck_va_death_register_identity`: `status IN ('draft_identity',
    'cancelled') OR (has_deceased_name AND date_of_death IS NOT NULL AND
    deceased_sex IS NOT NULL)`.
  - `ck_va_death_register_location_all_or_none`: `(latitude IS NULL) =
    (longitude IS NULL) AND (has_location = (captured_at IS NOT NULL)) AND
    (has_location OR accuracy_m IS NULL) AND (latitude IS NULL OR
    has_location)`. For plaintext rows (`has_location = latitude IS NOT NULL`)
    this is the old rule; a sealed row (coordinates NULL, flag true, a
    `captured_at`) passes.
- **Presence flags**: `before_insert` / `before_update` listener on
  `VaDeathRegister` (non-null plaintext sets the flag; NULL clears it only when
  `pii_sealed` is NULL), a context-sensitive column default so a Core insert
  is right too, and the seal writer. A Core `UPDATE` that sets a sealed column
  does not run the listener; none exists in the app.
- **`identity_complete`** reads `has_deceased_name or deceased_name` (the
  column still counts for an object not yet flushed, whose flag is set at
  flush).
- **Writers** (each goes through the accessor; flag off they run old code):
  `web_intake_service.register_death` (`seal_new_row` before `open_case`),
  `_correct_register_fields` (current values from `current_values`,
  `write_fields`), `_sync_case_identity`, `odk_case_service._insert_case`,
  `synthetic_demo_service._seed_cases`. `case_transition_service._audit` seals
  the sealed fields of `changes` (so `_audit_details_change` and
  `record_action` follow). `national_id_sweep_service` **refuses** while any
  register row is sealed (`SweepRefused`, counts only; sweep the other tables
  with `--table`): a sealed row's plaintext is NULL, so the scan would report
  it clean; free text is reduced at write (`_clean_death_fields`) and the
  backfill seals the already-reduced values. No `DELETE_TABLES` change: the
  blob lives in the register row.
- **Not done in T1**: serialisers, `case_list_service`, prefill, worklist
  filters, duplicate matching, search, exports, the backfill/verify CLI,
  `rewrap` for the register and audit rows, restore-to-plaintext. With the flag
  on, those readers see NULL for sealed columns, so **do not turn the flag on
  before the reader task**.

## Accessor interface (`app/services/register_pii_accessor.py`)

For the reader, duplicate-matching and backfill tasks.

| Name | Meaning |
| --- | --- |
| `SEALED_COLUMNS`, `LOCATION_COLUMNS`, `SEALED_FIELDS`, `SEALED_ATTRS` | the 14 columns; the three coordinates; blob keys (`location` replaces the three); attribute names of results |
| `split_enabled() -> bool` | `REGISTER_PII_SPLIT_ENABLED` |
| `is_sealed(death) -> bool` | `pii_sealed IS NOT NULL` |
| `open_register_pii(rows, *, only=None) -> {death_id: {attr: value}}` | rows are loaded `VaDeathRegister`; sealed rows open from the blob (one DEK unwrap each, `pii_crypto` cache), others return plaintext columns. `only` limits attributes and skips the unwrap when nothing requested is in the blob. Coordinates come back flat. No query (the blob is a column). Raises `PiiCryptoError` naming the row id. Authorize first |
| `current_values(death, names=None) -> dict` | one row |
| `seal_register_pii(death, fields=None)` | seal the stored blob plus plaintext still on the object plus `fields` (`None` clears), fresh DEK, plaintext NULLed, `pii_*`, flags and indexes set. No flag check. The backfill calls this per row inside its own transaction |
| `write_fields(death, values)` | writer door for existing rows: flag off sets columns and raises `RegisterSplitStateError` only when a sealed row would get a sealed attribute written (non-sealed attributes such as `age_years` write normally, so a rollback does not abort an interview submission); flag on re-seals sealed attributes together (one DEK) and sets the rest. Empty `values` is a no-op |
| `seal_new_row(death)` | flag on: seal a row built with plaintext before it is added |
| `RegisterSplitStateError` | flag-off writer met a sealed row |
| `phone_bidx(v)` (rule in `app/utils/phone.py`, `normalise_phone`; `web_intake_service._clean_phone` calls it: one rule, `PhoneRuleTests`), `abha_number_bidx(v)`, `abha_address_bidx(v)` | normalise and index (phone: separators dropped, leading `+91`/`91`/`0` stripped to 10 ASCII digits, else `None`; Devanagari or Arabic-Indic digits are not a phone). The same phone index serves both phone columns, so a match query is `informant_phone_bidx = :b OR informant_phone_2_bidx = :b` with `project_id` |
| `seal_audit_changes(changes, transition_id) -> (changes, dek_wrapped, key_id)` / `open_audit_changes(transition)` | audit sealing; the latter for the admin audit tool only |

Notes for later tasks:

- **Readers** replace `getattr(death, "<sealed column>")` with the opened dict
  for the page's rows (batch: `open_register_pii(rows, only=...)`), and use
  `has_*` for presence and filters. A viewer who may not see a field is not
  given it (`only` excludes it, no unwrap).
- **Duplicate matching**: phone and ABHA hints compare the stored `*_bidx`
  columns; names are opened per windowed candidate (design (a)).
- **Backfill / verify / strip**: `seal_register_pii(death)` seals and nulls in
  one step, so the policy's separate "strip" is now the flag-on write itself
  for new rows; for old rows decide whether backfill seals and nulls at once
  or keeps plaintext through a hold (then add a variant that keeps the
  columns). Rotation: re-wrap `pii_dek_wrapped` and `changes_dek_wrapped`
  (`pii_crypto.rewrap_dek`); recompute the four indexes from the opened record
  when `pii_blind_key_id` differs from `pii_crypto.blind_key_id()`.
- **Audit rows** written before the flag stay plaintext; `changes_dek_wrapped
  IS NULL` tells them apart.

## Backfill, verify, strip, restore (T4)

`app/services/register_pii_backfill_service.py`, CLI `flask pii seal-register`
in `app/commands/pii.py`. Counts only: no output or log line carries a value
or a row id.

| Command | Does |
| --- | --- |
| `seal-register` | dry run: register counts (`rows`, `already_sealed`, `to_seal`, `stale_blind_key`) and what `--strip` will in the end do to the audit rows of every case (`audit_rows`, `audit_to_seal`, `audit_mask_to_scrub`, `audit_skipped`) |
| `seal-register --apply --confirm-backup K` | seals every row through the accessor and **keeps the plaintext columns** (`seal_register_pii(..., keep_plaintext=True)`); sets the four indexes, blind key id, `pii_sealed_at`, flags. Does not touch `map_case_transitions` (audit plaintext stays recoverable through the hold). Keyset by primary key, `FOR UPDATE`, one commit per batch, DEK cache cleared per batch; each batch is reopened after its commit and compared with the plaintext, or the run stops (`BackfillRefused`). Idempotent: a row sealed under the current blind key whose blob keys match its plaintext is skipped without a decrypt, so wrapped keys stay byte-identical |
| `--verify` | no decrypt: `unsealed`, `blind_key_stale`, `flag_mismatch` (flags vs the blob's keys), `sealed_set_changed`, `audit_unsealed`, `audit_mask` (these two only with `--after-strip`, and only over audit rows of stripped cases: held cases' audit rows stay plaintext, so they are expected); then `--sample N` (default 200) register rows opened (equal to plaintext while it is there, recomputed indexes equal) and audit rows opened. Exit non-zero on any problem |
| `--strip --confirm-backup K [--hold-days 30]` | runs verify (audit not checked) and refuses on any problem; NULLs the sealed columns of rows whose `pii_sealed_at` is at least `--hold-days` old (younger ones count as `held`) and that open to exactly the plaintext about to go (else `failed`, kept). Flags stay true. Then, only for audit rows of **stripped** cases, seals the old/new values of sealed attributes in `map_case_transitions.changes` (AAD per `seal_audit_changes`) and scrubs the legacy `mask` member of `identifier:*` entries (counts `audit_written`, `audit_skipped`; a skipped row fails the command). A case is stripped when its register row has `pii_sealed` set and every sealed plaintext column NULL (a row sealed with nothing to seal counts at once); one `EXISTS` on `death_id`, keyset batches. Audit rows of cases still in the hold stay plaintext, `mask` included (so `--hold-days` really keeps them recoverable; the mask scrub is deferred with them: one rule, and it removes a value held nowhere else, so waiting costs nothing); a later strip run, after their hold, seals them. Idempotent, resumable. Prints a reminder to run `flask pii flush-cache` |
| `--restore --confirm-backup K` | refused while `REGISTER_PII_SPLIT_ENABLED` is on; opened values back into the plaintext columns, `pii_*` and indexes cleared, audit `changes` opened (the scrubbed `mask` is not restored). Rows that do not open are counted and kept sealed; writers stay paused until `failed=0` |
| `--recompute-digests [--apply]` | blind-key rotation: the four indexes and `pii_blind_key_id` of sealed rows not on the current blind key, from the opened values, no re-seal |
| `rewrap` | now also moves `va_death_register` (`pii_dek_wrapped`, `pii_key_id`) and `map_case_transitions` (`changes_dek_wrapped`, `changes_key_id`); ciphertexts untouched, compare-and-set |

Every write is a Core update with `updated_at` set to itself (the column has
`onupdate` and drives keyset cursors and the worklist sort). Apply, strip,
restore and recompute-digests take the backup gate (`confirm_db_backup`,
`PII_BACKUP_MAX_AGE_HOURS`, `--allow-old-backup`) and log
`pii seal-register <step> | backup_key=... | counts` at WARNING.

A row with nothing to seal is sealed with an empty record. The audit rows are
sealed at `--strip`, per case once its register row is stripped, not at apply: until then everything is recoverable through
the hold; after it the audit plaintext is recoverable only by `--restore` or the
dump. Audit rows written with the flag on are sealed at write (T1).

### Release procedure (slice 2)

Mirrors [pii-slice-1b.md](pii-slice-1b.md), "Release procedure"; the readers
(T2) and duplicate matching must already be in the deployed code before the flag
flip.

1. Pause writers: ODK sync beat row off and a running sync stopped, site
   maintenance on (web intake writes the register).
2. `flask backups db-dump --no-prune`; confirm the sha256 with `flask backups
   db-list`. Back up the KEM private key and `PII_BLIND_INDEX_KEY` apart.
3. Deploy with `REGISTER_PII_SPLIT_ENABLED=false` (migration `e5a2c7b9d3f1`).
4. `flask pii seal-register` (record the counts), `flask pii seal-register
   --apply --confirm-backup K`, `flask pii seal-register --verify` (exit 0),
   `flask pii flush-cache`.
5. Flip `REGISTER_PII_SPLIT_ENABLED=true`; restart app, worker and beat.
6. Resume: end site maintenance, re-enable the beat row.
7. **After the hold** (30 days, `--hold-days`): `flask pii seal-register
   --verify`, then `flask pii seal-register --strip --confirm-backup K` with a
   fresh dump (this also seals the audit rows of the cases it strips; rerun after the remaining holds end), then `flask pii seal-register
   --verify --after-strip` (exit 0) and `flask pii flush-cache`. Until then the plaintext columns
   still hold the personal data, so the release does not yet remove it; a
   rollback in the hold is flag off plus `--restore`.

Rollback after the strip, or after new sealed writes with the flag on: pause
writers, flag false, restart, `--restore --confirm-backup K`; `flask db
downgrade` refuses while any register or audit row is sealed.

## T2 as built (readers, bead `digitva-9iy4`, uncommitted 2026-10-21)

Flag-off output is unchanged; a sealed row yields the same output as its
plaintext twin. Readers never touch a sealed column directly; an object is
opened once with `current_values` (one row) or `open_register_pii` (a page,
`only=` the fields the viewer may see, so a hidden field is never decrypted).

| Reader | How |
| --- | --- |
| `serialize_death`, `serialize_worklist_row`, `serialize_case_detail`, `serialize_supervised_row` | optional `register=` (the row's opened dict) so a list opens its page once; else opened per row. Worklist row opens `deceased_name` only and reads `has_informant_phone(_2)` from the flags. Case detail never opens ABHA or parents' names, and the fix only with `show_gps`. `serialize_death` opens the fix only with `show_gps`. |
| `serialize_drafts` | loads the case entities in the same one query, opens names for the page. |
| `worklist_page` | names opened once per page; the fix opened only for rows with `has_location` that the viewer may see. |
| `_prefill_from_death`, `_case_address`, `build_web_payload` (ABHA), `revise_submission` identity check | one `current_values` per case. |
| `case_list_service.list_cases` | the page SELECT carries `pii_sealed` / `pii_dek_wrapped` under the `can_name` `CASE` (the fix rides in the same blob; `via_field` implies `can_name`) and `has_location`; latitude/longitude are `CASE`d on `via_field`. `_open_page` opens a row once (name plus fix where the fix is shown). `with_names=False` leaves the blob out of the SELECT and opens nothing; `case_export_service` passes it (no name or GPS column). |
| `routes/api/intake.py` | the register list and supervision list open their page and pass `register=`; no response shape changed. |

Other readers searched and found clean: `case_transition_service`
(`identity_complete` only), dashboards (`area_dashboard_service`,
`user_home_service`), DORIS, SmartVA preparation, ODK sync, templates (form
inputs only), exports. **Left for T3:** `_possible_duplicate_rows` (name
`similarity()`, `deceased_name IS NOT NULL` gates, `informant_name` and
`address_village_ward` selected) and `possible_duplicates` (reads those
columns from the rows). T3 (below) closes that.

Tests: `tests/services/test_register_pii_readers.py`,
`tests/routes/test_register_pii_case_list.py` (the whole case-list module run
over a sealed fixture) and `tests/routes/test_register_pii_intake_routes.py`
(intake, worklist, prefill, death-reporter and export routes with the flag on).

## T3 as built (duplicate matching, bead `digitva-gu3i`, uncommitted 2026-10-21)

`app/services/register_duplicate_service.py` (`possible_duplicate_rows`); the
old `_possible_duplicate_rows` and the SQL `_normalised_name` in
`web_intake_service` are gone, its call sites (`_worklist_page_rows`,
`possible_duplicates`) call the service. Flag-off results are unchanged; a
sealed row gives the same hints as its plaintext twin (tests compare the two
at `per_case` 3 and 50, and run the whole `test_possible_duplicates.py` suite
again with the flag on).

- **Two statements for any page**: (1) the candidate pairs, one UNION: the
  name branch (all the old gates; `has_deceased_name` instead of
  `deceased_name IS NOT NULL`; no name selected, none compared), the
  registration-number branch (unchanged), four phone branches (either subject
  column against either candidate column), ABHA number, ABHA address. (2) the
  rows of the subjects and candidates, only the columns the accessor needs
  (`pii_sealed`, `pii_dek_wrapped`, and the plaintext of `deceased_name`,
  `informant_name`, `address_village_ward` for unsealed rows). Names never
  appear in a statement or parameter (a test records them).
- **Caps**: the name branch keeps at most `DUPLICATE_PREFILTER_MAX` (config,
  env, default 50) **sealed** candidates per subject before any decrypt,
  ordered same unit, then `abs(date difference)`, then `death_id`; candidates
  whose name is still a plaintext column (flag off, not yet sealed) are never
  capped and are scored exactly as the old query did (their names are read
  from the plaintext columns in Python, never sent to Postgres), so the cap
  cannot drop a true duplicate the old query returned. Each score-1 branch
  (registration number, four phone, ABHA number, ABHA address) keeps at most
  `DUPLICATE_STRONG_MAX` (default 50) candidates per subject in the same
  order, before any entity is loaded: one shared helpline number cannot load
  thousands of rows. Warnings with counts only (`subjects`, `max_candidates`,
  `cap`) are logged when a cap cuts. After the caps the merge cuts to `per_case`. No age-band prefilter (it would change results).
- **Opens**: `deceased_name` only, once per distinct row (subjects and
  scored candidates), kept as trigram sets; then `informant_name` and
  `address_village_ward` (and `deceased_name` again) only for the survivors
  after the cut to `per_case`. Unwraps per page = distinct sealed rows among
  the subjects and scored candidates (each row opened once; candidates shared
  by subjects count once), plus at most one more per survivor when the 256
  entry DEK cache has evicted it. Worst case page 200 x cap 50 = 10,000
  distinct rows; an unwrap costs about 0.035 ms measured in the dev
  container, so about 0.35 s, and normally far fewer (candidates repeat across
  a worklist page). Out-of-scope candidates are filtered in SQL and never
  opened (tested). No explicit cache clear: the cache evicts oldest first, so
  memory is bounded whatever the page.
- **Python port** (parity is the risk): `normalised_name` is the old SQL
  step by step; `trigrams` / `similarity` are pg_trgm's (each word padded
  with two spaces before and one after, set of 3-character windows,
  `common / (|A| + |B| - common)` rounded to float4, 0 when either set is
  empty). The classes "word character" (what pg_trgm and `\m \M` call
  alphanumeric), `[[:punct:]]` and `\s` for characters at U+0080 and above
  are probed once per process from the database by code point (no name
  involved), because a glibc locale classes many Indic combining marks as
  punctuation or non-word and `unicodedata` disagrees. `tests/services/test_register_duplicates.py`
  compares the normalised string and the score with live Postgres for every
  pair of a 66-name corpus (Latin with titles and punctuation, accents,
  Devanagari with danda and ZWJ/ZWNJ, Kannada, Telugu, Bengali, Tamil,
  Arabic, emoji, empty and one- and two-letter names): all equal.
- **Parity residuals**: (1) Postgres hashes a trigram of non-ASCII characters
  to 24 bits, so two different ones may collide there and not here (a score
  can differ in the last place; none in the corpus; the hash was not
  reproduced). (2) Code points above U+FFFF are classed by Python (`str`
  methods; punctuation and symbols count as punctuation) rather than by the
  database. (3) A database moved to a different locale needs a restart of the
  workers to re-probe. (4) `lower()` is taken one character to one, as
  Postgres does.
- **Phone / ABHA**: only a row that carries the index matches (sealed rows,
  or anything the backfill has indexed); a plaintext legacy row has none, so
  it neither finds nor is found. Obeys the same subject gates (open, no
  pending flag), the candidate's project, open status and the caller's scope;
  not the date, sex or unit gates, as for registration numbers. Score 1.
  Plan at volume not measured (scratch database is empty): each branch is an
  equality on `(project_id, bidx)` with a partial index.
- Tests: `tests/services/test_register_duplicates.py` (sealed rerun of the
  duplicate suite, parity, hints, cap, statements, unwraps, trigram corpus);
  `test_possible_duplicates.py` now uses the Python normaliser and allows two
  statements; `test_register_pii_readers.py` stubs the duplicate check where
  it counts blob opens.

## Remaining tasks

1. (done in T2 above; phone search by `phone` index is not built.)
2. ~~Duplicate matching on names (policy design (a)), phone/ABHA by index~~ (T3, above).
3. ~~Backfill, verify, strip CLI~~ (T4, above).
4. Release: backup, backfill, verify, flag on in one sync-paused window.
