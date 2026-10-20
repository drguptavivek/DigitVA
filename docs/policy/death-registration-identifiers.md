---
title: Death Registration Identifiers Policy
doc_type: policy
status: proposed
owner: Vivek Gupta
last_updated: 2026-10-20
---

# Death Registration Identifiers Policy

Bead `digitva-kzyp`. Proposed baseline; nothing here is built.

## Purpose

A reported death often has official numbers issued by other systems: the
Civil Registration (CRS) number, the MCCD (Medical Certificate of Cause of
Death) number, a death certificate number, and others that differ by state
and project. Supervisors use them to match a reported death with the civil
record and to find duplicates. Today the register (`va_death_register`,
`app/models/va_web_intake.py`) has no place for them.

This policy lets a project define which identifier types it collects, with a
validation pattern for each, and lets the right people add and correct the
numbers on a case, including days after the death was reported, because the
numbers are often issued later.

## Owner decisions (2026-10-20)

1. A reported death can carry **several** registration identifiers, at most
   one value per identifier type.
2. Identifier **types and their validation pattern are configured per
   project**.
3. The rules apply when a death is reported. A number **may be absent at
   report time** and be added or edited **later**.
4. A **supervisor** may add or edit the numbers of any death in their scope,
   at any time.
5. Death lists show the numbers.
6. The entry field is **monospaced**.
7. Each identifier type's validation can combine (a) a **minimum and maximum
   length**, (b) a **character type** chosen from a short list (digits only;
   letters only; letters and digits; letters, digits and hyphen or slash) and
   (c) an **optional regular expression**. **All rules set on the type must
   pass.**
8. Values are **always captured and stored in CAPITALS**. The client
   upper-cases as the user types in the monospaced field; the server
   upper-cases and trims again before validating, so the client is advice
   only. Uniqueness and duplicate warnings compare the normalised (capital)
   value.
9. **CSV export.** Registration numbers **are** included in the data manager
   CSV export, **only for exporters with PII access in that project**, and
   every such export is **audited**. This is a recorded exception to the
   "direct local identifiers" rule for bulk extracts in
   `data-manager-workflow.md` (see "CSV export").
10. **Duplicate numbers warn, never block.** A number already on another death
    in the same project returns a warning and the user may continue. The
    message names the other case id and unit and that case's reporting user's
    name and designation (cadre): "This number is already on case X (unit Y),
    reported by <name> - <designation>". The other case's details are shown
    only to roles allowed to see reporter identity. The match also raises a
    possible-duplicate hint for the supervisor.
11. **Who may add or edit after the interview is complete:** the In-charge
    (`site_pi` at a unit; this also covers supervisors in scope), the death
    reporter on deaths they reported, the interviewer on cases they
    interviewed, and data managers within their project scope. Every write is
    audited.
12. **Closed cases** (cancelled or confirmed duplicate): numbers **may still
    be added or edited, by supervisors and the In-charge only**, audited. The
    death reporter, interviewer and data manager are read-only on closed
    cases.
13. **Who may configure types:** admin, `project_pi` and `data_manager`, each
    within their project. Every change is audited. Patterns are still
    validated at save time (safe subset, ReDoS guard).
14. **Who sees values:** roles with PII access in the project, and
    `collaborator_pii`. Everyone else (coders, reviewers, coding testers,
    roles without PII) sees only a **has number / missing** badge, never the
    value.
15. **Column-level encryption.** Values are encrypted in the database with
    AES-256-GCM, with a separate keyed blind index for duplicate checks, the
    has-number filter and exact search. Validation runs on the plaintext
    before encryption. Amended the same day: data keys are wrapped with a
    **post-quantum hybrid KEM** (ML-KEM-768 with X25519), and the library is
    `cryptography>=48`. See "Encryption at rest".

Everything else below is a proposal built on these decisions; items marked
**Q** are open questions.

## Data model

Additive, two new tables for types and values, one append-only audit table
for configuration and export events, and no change to `va_death_register`.
Names follow the `mas_*` (master) and `map_*` (mapping) rules in `AGENTS.md`.

### `mas_death_identifier_type` (per-project types)

Modelled on `MasOrgLevel` (`app/models/mas_organization.py`): a per-project
master with a project-unique code and an `is_active` switch.

| Column | Type | Notes |
| --- | --- | --- |
| `identifier_type_id` | UUID PK | |
| `project_id` | `String(6)` FK `va_project_master` | indexed |
| `code` | `String(32)` | stable machine code, e.g. `crs`, `mccd`; `^[a-z][a-z0-9_]{1,31}$`; never reused for another meaning |
| `label` | `String(128)` | shown to users, e.g. "MCCD number" |
| `min_length` | `Integer`, default 1 | 1..`max_length`; shortest accepted value |
| `max_length` | `Integer`, default 64 | `min_length`..64; the value cap for this type |
| `char_type` | `String(32)`, nullable | one of `digits`, `letters`, `letters_digits`, `letters_digits_hyphen_slash` (ASCII only; see "Validation"); NULL puts no character restriction |
| `pattern` | `String(200)`, nullable | optional regular expression (see "Pattern safety"), written for the capitalised value; NULL means no pattern rule |
| `example` | `String(64)`, nullable | hint text shown under the field; must satisfy every rule above (capitalised). An illustrative format, never a real number; stored in plaintext |
| `required_at_report` | `Boolean`, default false | true refuses a registration without it (see "Validation") |
| `uniqueness_scope` | `String(16)`, default `project` | `none` or `project`; what a duplicate number is checked against |
| `sort_order` | `Integer` | order on forms, cards and exports |
| `is_active` | `Boolean`, default true | inactive types take no new values; stored values stay readable |
| `created_at`, `updated_at` | timestamptz | |

Constraints: `unique(project_id, code)`; `CHECK uniqueness_scope IN ('none',
'project')`; `CHECK min_length >= 1 AND max_length <= 64 AND min_length <=
max_length`; `CHECK char_type IS NULL OR char_type IN ('digits', 'letters',
'letters_digits', 'letters_digits_hyphen_slash')`. A type is never deleted once
a value uses it; it is deactivated. Changing `code` after values exist is
refused.

### `map_death_identifier` (values per death)

The value is never stored in plaintext (decision 15).

| Column | Type | Notes |
| --- | --- | --- |
| `death_identifier_id` | UUID PK | |
| `death_id` | UUID FK `va_death_register` | |
| `identifier_type_id` | UUID FK `mas_death_identifier_type` | |
| `value_ciphertext` | `Text`, not null | `v1:aes256gcm:...`, AES-256-GCM ciphertext of the normalised value under its own DEK (see "Encryption at rest") |
| `dek_wrapped` | `Text`, not null | the value's DEK wrapped by the hybrid PQC KEM, with algorithm id and key id in its prefix |
| `value_blind_index` | `String(128)`, not null | hex HMAC-SHA-512 of the normalised value (see "Blind index") |
| `key_id` | `String(16)`, not null | KEM key id that wrapped `dek_wrapped`; drives rotation |
| `entered_by` | UUID FK `va_users` | first writer |
| `entered_at` | timestamptz | server time |
| `updated_by` | UUID FK `va_users`, nullable | last writer |
| `updated_at` | timestamptz, nullable | server time |

Constraints and indexes:

- `unique(death_id, identifier_type_id)`: one value per type per death.
- `ix_map_death_identifier_type_bidx (identifier_type_id, value_blind_index)`:
  the duplicate-number check and the "find by number" search. **Not
  unique**: a duplicate number is a warning, not a constraint (decision 10).
- `ix_map_death_identifier_key (key_id)`: lets the rotation job find rows
  still on an old key without a full scan.
- The `death_id` lookup is covered by the unique constraint's leading column;
  no extra index.

Clearing a value deletes its row (the audit keeps a masked trace, below);
there is no empty-string row. "Has number" is the existence of a row; there
is no plaintext column to test.

### `map_identifier_audit` (configuration and export events)

Append-only; no update or delete path in the application.

| Column | Type | Notes |
| --- | --- | --- |
| `audit_id` | UUID PK | |
| `project_id` | `String(6)` FK `va_project_master` | indexed with `created_at` |
| `event` | `String(32)` | `type_created`, `type_updated`, `export_with_identifiers` |
| `actor_user_id` | UUID FK `va_users` | |
| `actor_role` | `String(30)` | the grant role that authorised the action |
| `identifier_type_id` | UUID, nullable | for type events |
| `details` | JSONB | type events: changed rule fields `{field: {old, new}}` (labels, lengths, char type, pattern, example, flags; none is personal data). Export: the filter set, row count, and the type codes exported. **Never a value** |
| `created_at` | timestamptz | server time |

Alternative rejected: reusing `va_submissions_auditlog`, which is keyed by
`va_sid` and cannot record a project-level configuration change or an export
across many cases.

### History of values

Value writes use the existing append-only `map_case_transitions`, which
already names the actor and, for a supervisor, the authorizing grant and cadre
(`authorizing_grant_id`, `authorizing_cadre_id`, web-intake.md "Supervisors",
decision 15). Each identifier write adds one row:

- `action = 'identifiers_set'`, `from_state = to_state =` the case's current
  state (the state does not change);
- `changes` keyed `identifier:<code>`, with `old` and `new` each a **masked
  trace, never the plaintext** (see "Audit content");
- `reason` lists only the changed type codes, never a value;
- for a supervisor or In-charge write, the authorizing grant and cadre as for
  every supervisor action.

Alternative rejected: a separate `map_death_identifier_history` table would
duplicate the actor, grant and personal-data rules the transition audit
already enforces.

### Normalisation

Applied on the server before validation, in this order:

1. Reject non-text input (a JSON object or list is 400, as other register
   fields).
2. Unicode NFKC, then strip leading and trailing whitespace.
3. Collapse internal runs of whitespace to one space.
4. Upper-case, always (every type; there is no per-type switch).
5. Empty after this means "no value" (clears on update, absent on create).

The normalised (capital) value is what is validated, encrypted and blind
indexed, so `mccd/1` and ` MCCD/1 ` are the same number. Hyphens and slashes
are kept: they are often part of the official format and the character type or
pattern decides whether they are allowed. The client applies the same
upper-casing as the user types (cursor position kept); the server never trusts
it and normalises again.

## Pattern safety

Patterns are entered by configurers (decision 13) and run on every write.
`pyproject.toml` has no `re2` binding and Python's `re` has no timeout, so
safety comes from what a pattern may contain, checked when it is saved.

- **Anchored by the server.** Values are tested with `re.fullmatch`; the
  configurer does not write `^` and `$` (leading `^` or trailing `$` are
  stripped on save so both forms behave the same). Compiled with `re.ASCII`,
  as the XForm `regex()` evaluator does
  (`app/services/xform_expression_evaluator.py`).
- **Length caps.** Pattern at most 200 characters; value length within the
  type's `min_length`..`max_length` (64 at most), checked **before** the
  character type and the pattern run.
- **Safe subset, checked on save** by parsing the pattern (Python's own
  parser, `re._parser`, or a small tokenizer) and refusing:
  backreferences, lookahead and lookbehind, named groups, conditionals,
  inline flags, possessive and lazy quantifiers, a quantifier applied to a
  group that itself contains a quantifier or an alternation (the nested
  repetition behind catastrophic backtracking), and any `{m,n}` with n
  greater than 64. Allowed: literals, escapes `\d \w \s` and escaped
  punctuation, character classes and ranges, `.`, groups, alternation
  between fixed alternatives, and `? * + {n} {m,n}` on a single atom.
- **One dialect for server and app.** The subset is also valid JavaScript
  `RegExp` syntax with the same meaning, so the Expo client can show the hint
  and pre-check as the user types. The server is authoritative; the client
  check is advice only.
- **Example must satisfy every rule.** Saving a type with an `example` that
  fails the length, character type or pattern (after upper-casing) is
  refused, so a rule set that rejects every real number is caught at save.
- **Invalid patterns are rejected**, never stored and fixed later. A pattern
  that fails to compile, uses a refused construct or exceeds a cap is a 400
  naming the reason.
- **No database CHECK** with the pattern: it is per-project data,
  PostgreSQL's regex dialect differs from Python's, and the column holds
  ciphertext.
- **Changing any rule** (length, character type or pattern) does not
  re-validate stored values. A stored value that no longer matches is shown
  as is and must be corrected in the same edit that next touches that type
  (the rule `update_death` already applies to stored register fields).

**Q:** add `google-re2` (linear time) as a second guard, or is the safe
subset enough? A dependency change needs the image rebuild in `AGENTS.md`.

## Validation and error shape

Per identifier in a write, after normalisation and **before encryption**
(validation always sees the plaintext; nothing is validated on ciphertext):

1. The type code must be an active type of the case's project; an unknown
   or inactive code is refused.
2. Length within `min_length`..`max_length`.
3. Character type, when the type has one: `digits` is `[0-9]+`; `letters` is
   `[A-Z]+`; `letters_digits` is `[A-Z0-9]+`;
   `letters_digits_hyphen_slash` is `[A-Z0-9/-]+` (ASCII, applied to the
   capitalised value).
4. `fullmatch` against the pattern, when the type has one.
5. On registration only: every `required_at_report` type must have a value.

All set rules must pass; the first failing rule names the refusal (length,
character type, then pattern). Save-time checks on a type: `min_length <=
max_length` within 1..64; the `example` (capitalised) satisfies length,
character type and pattern; the pattern is in the safe subset ("Pattern
safety"); `char_type` is one of the four listed values; the code is unchanged
once values exist.

Errors use the existing intake envelope (`request_helpers.error` and
`intake_error`): `{"error": <message>, "code": <code>, "fields": [...]}`.

- Registration (`POST /api/v1/intake/deaths`): a content refusal is **422
  `invalid_registration`**, as every other register field
  (`_content_refusals`), so the offline queue reopens the item for editing.
  `fields` names `identifiers.<code>`.
- Later writes: **400** with `fields` naming `identifiers.<code>`, the same
  status `update_death` uses for a bad value.
- The message names the type label and shows the example ("MCCD number must
  look like MCCD/2026/000123"), or the length and character rule when there
  is no example. It **never echoes the submitted value**.
- Out-of-scope case: **404**, as other intake case endpoints.
- A role allowed on open cases but not on closed ones (decision 12): **409
  `case_closed`**, naming no value.
- Concurrent edit: **409 `death_stale`** when `if_updated_at` does not match,
  reusing the register's optimistic check.

Default for `required_at_report` is false, because numbers are usually issued
later. A project that sets it true accepts that a registration without the
number is refused.

## Duplicate numbers

Decision 10. For a type with `uniqueness_scope = project`:

- The check compares `value_blind_index` on
  `ix_map_death_identifier_type_bidx` against **other** cases of the same
  project; no decryption is needed to find a match. Confirmed duplicates and
  cancelled cases are excluded from the match.
- The write **succeeds** and the reply carries a warning:
  `warnings: [{"code": "identifier_in_use", "field": "identifiers.<code>",
  ...}]`. The client shows it and the user may continue; nothing is blocked.
- **Detail in the warning** (other case id, unit name, the other case's
  reporting user's name and designation / cadre) is included only when the
  writer may see reporter identity for that other case: the other case is in
  the writer's supervision reach (`supervised_case_condition`, which covers
  interview_supervisor, site_pi, data_manager and project_pi) or the writer
  is admin. Otherwise the warning carries only the code and field, with the
  text "This number is already on another case in this project". The
  reporter's name and designation come from `registered_by` and the
  reporter's cadre, loaded in the same query as the match.
  - Not `should_redact_pii` alone: it lifts redaction for coders and
    reviewers (who must not see reporter identity here) and does not lift it
    for `interview_supervisor` (who must). See "Contradictions to resolve".
- The match feeds the existing duplicate flow (web-intake.md, "Duplicate and
  cancel flags" and "Possible duplicates"): `possible_duplicates` lists a
  case with the same blind index as a strong candidate, which is the
  supervisor's possible-duplicate hint. Cases are never merged; only a
  supervisor confirms a duplicate.

## Authorization

Every write is checked server-side per request and per case, through the
existing predicates; a `death_id` in a request is a claim, not permission.

| Role | Configure types | Enter at report | Add / edit after interview complete | Closed cases (cancelled, confirmed duplicate) | See values |
| --- | --- | --- | --- | --- | --- |
| admin | yes, any project | no (does not register) | yes (any case) | yes | yes |
| project_pi | yes, own project | no | yes, as a supervisor of the project (`_SUPERVISING_ROLES` includes `project_pi`) | yes | yes |
| site_pi (In-charge) | no | no | yes, any case in scope | yes | yes |
| interview_supervisor | no | no | yes, any case in scope (`supervised_case_condition`) | yes | yes, in scope |
| data_manager | yes, own project | no | yes, any case in project scope | **read-only** | yes |
| interviewer | no | yes, on registrations they create | yes, on cases they interviewed | **read-only** | yes, on cases in reach |
| death_reporter | no | yes, on registrations they create | yes, on deaths they reported (`_reporter_reaches`) | **read-only** | yes, on cases they registered |
| collaborator_pii | no | no | no | no | **yes** |
| coder, coding_tester, reviewer | no | no | no | no | **badge only** |
| collaborator | no | no | no | no | **badge only** |

"See values" (decision 14) is a dedicated per-project check, not
`should_redact_pii`: a user sees a value when they reach the case through a
role in the "yes" rows **in that case's project**. Coding and review reach
never shows a value, even when the same user also holds a PII-lifting grant
in another project. Badge-only viewers get `{code, label, present: true}`
per type, the value omitted from the payload (not blanked in the client).

Notes grounded in the code:

- **Type configuration** today would sit beside `admin_update_project`
  (`app/routes/admin.py`), which is `@role_required("admin")` plus
  `is_admin()`. The type endpoints instead authorise per project:
  admin, or a live `project_pi` or `data_manager` grant on that project
  (`_current_user_can_manage_project` covers project PIs; data managers need
  the same per-project check). Every create or update writes a
  `map_identifier_audit` row.
- **Later edits cannot go through `update_death`.** It refuses 409
  `case_completed` once an interview is completed, because the interview
  then holds the case details. Identifiers are not interview answers and the
  numbers arrive later, so identifier writes have their own service function
  that is **not** gated on interview completion and does not change the case
  state. It applies decision 11 (who) and decision 12 (closed cases).
- **Interviewer "cases they interviewed"** means the interviewer who started
  or completed an interview on the case, not every case in their unit
  subtree; seeing a case in the worklist is not enough to edit its numbers
  after completion.
- **Closed cases:** the supervisor and In-charge write path checks
  `supervising_grant` for `interview_supervisor`, `site_pi` or `project_pi`
  (and admin). `data_manager` is in `SUPERVISING_ROLES`
  (`app/services/authz/actions.py`), so the closed-case check must exclude it
  explicitly.
- Supervisor reach is `supervised_case_condition` / `supervising_grant`
  (`app/services/authz/supervision.py`), which already returns nothing under
  device (bearer) credentials. Supervisor, In-charge and data manager writes
  are therefore **browser only**; reporter and interviewer writes also work
  from the device.

## Encryption at rest

Decision 15, amended by the owner the same day to use post-quantum
cryptography (PQC) for key wrapping. Registration numbers are encrypted per
column; the database, its replicas and its backups never hold them in
plaintext. The design follows the shape of `app/services/totp_service.py`
(AES-256-GCM, HKDF, versioned prefix, AAD bound to the owning row) in a **new
reusable module `app/utils/pii_crypto.py`**, so other PII columns can adopt it
later without copying code. This replaces the earlier single symmetric
`PII_ENCRYPTION_KEY` design.

### Scheme (envelope encryption)

- **Data cipher: AES-256-GCM**, unchanged. A 256-bit symmetric key is already
  quantum-resistant: Grover's algorithm at best halves its effective strength
  to about 128 bits, which NIST accepts as secure. Each value gets a fresh
  random 256-bit **data encryption key (DEK)** and a fresh 12-byte nonce.
- **AAD = `death_id.bytes || identifier_type_id.bytes`** on the data
  ciphertext, so a ciphertext copied to another death or another type fails
  to decrypt (a value cannot be moved between rows).
- **DEK wrapping: hybrid PQC KEM, ML-KEM-768 (FIPS 203) combined with
  X25519.** Wrapping a DEK encapsulates to both the ML-KEM-768 public key and
  the X25519 public key; the two shared secrets are joined by a KEM combiner
  (HKDF-SHA256 over both shared secrets, with both KEM ciphertexts / the
  ephemeral X25519 public key and the key id in the `info`), giving a
  key-encryption key that wraps the DEK with AES-256-GCM (AAD = key id and
  algorithm id). The value stays protected while either component holds.
  **ML-KEM-1024** is the stricter option, selectable by algorithm id without a
  schema change.
- **Per-record DEKs** (one per value), so the application needs only the KEM
  **public** keys to write. Unwrapping needs the KEM **private** keys.
- **Crypto-agility:** every stored blob names its algorithm and key id:
  - `value_ciphertext` = `v1:aes256gcm:<urlsafe-base64(nonce || ciphertext+tag)>`;
  - `dek_wrapped` = `v1:aes256gcm+mlkem768x25519:<key_id>:<urlsafe-base64(kem ciphertexts || wrap nonce || wrapped DEK)>`.
  Decrypt dispatches on the prefix; an unknown version, algorithm or key id
  fails with one internal error naming the row id and key id only, never
  ciphertext or plaintext.

### Keys and configuration

- **KEM public keys** (ML-KEM-768 and X25519) and their **key id**: ordinary
  configuration (`PII_KEM_PUBLIC_KEY`, `PII_KEM_KEY_ID`), present in every
  process that writes numbers. Not secret.
- **KEM private keys: held apart from the day-to-day env keys.** They are
  read from a secret file (a Docker secret mounted at a path named by
  `PII_KEM_PRIVATE_KEY_FILE`), kept in the secret store, not in `.env`, and
  mounted **only** into the processes that must read values:
  `minerva_app_service` (authorised page reads and the CSV export) and the
  worker that runs the re-wrap job. `minerva_celery_beat` and any process that
  only writes never receive it. A dedicated decrypt service holding the
  private key, called by the app, is the stricter variant; it is not proposed
  for the first stage because every authorised list page decrypts.
- During a rotation window, `PII_KEM_PREVIOUS_PRIVATE_KEY_FILES` names the
  retired private keys still accepted for unwrapping, never for wrapping.
- **`PII_BLIND_INDEX_KEY`**: a separate 32-byte symmetric key for the blind
  index (below). Never reuse `AUTH_FACTOR_ENCRYPTION_KEY`, `SECRET_KEY` or
  the ODK pepper: each key has one purpose.
- Production (`not app.debug and not app.testing` in `app.create_app`) refuses
  to start without a well-formed public key, key id and
  `PII_BLIND_INDEX_KEY`, as it does for `AUTH_FACTOR_ENCRYPTION_KEY`; a
  process configured to read values also refuses to start without a readable
  private key file. Development and test generate throwaway keys.
- Configuration lands with the code: `config.py`; the app, worker and beat
  `environment` blocks in `docker-compose.yml` (public key, key id and blind
  index key) and a `secrets:` entry for the private key file on the app and
  worker only; `.env.example` (commented, "back it up"); `make ensure-secrets`
  generating the blind index key and, in development, a throwaway KEM key
  pair. Document them where `AUTH_FACTOR_ENCRYPTION_KEY` is documented.
- Keys are never logged, never in the database, never sent to a client.

### Blind index

- `value_blind_index = hex(HMAC-SHA-512(PII_BLIND_INDEX_KEY,
  identifier_type_id.bytes || 0x00 || normalised value))`, 128 hex
  characters. Symmetric and keyed, so not quantum-sensitive. Binding the type
  means the same digits under two types do not correlate.
- Used for the duplicate warning and the exact "find by number" search;
  "has number" and "missing" use the row's existence. No decryption.
- It leaks equality within a type, which is exactly what the duplicate
  warning needs and nothing more. No prefix or partial search.

### Signatures

Not needed for this feature: audit rows and exports are protected by access
control and the append-only audit, not by signatures. If audit or export
integrity signatures are wanted later, **ML-DSA (FIPS 204)** is the option.
Out of scope here.

### Library

Verified on 2026-10-20 in `minerva_app_service`: the installed
`cryptography` is **46.0.5** (`uv.lock`; `pyproject.toml` pins
`cryptography>=42.0.0`), built against **OpenSSL 3.5.5**. Importing
`cryptography.hazmat.primitives.asymmetric.mlkem` fails
(`ModuleNotFoundError`); `x25519` imports. So **ML-KEM is not available in
the installed version.**

Not verified by this document's author, relayed from the coordinator's
reading of the pyca/cryptography CHANGELOG and PyPI: 48.0.0 (2026-05-04) added
ML-KEM and ML-DSA when built with OpenSSL 3.5.0 or later, including in the
published wheels; the latest release is 50.0.2 (2026-09-30).

Decision (owner, relayed): raise the pin to `cryptography>=48` (target
50.0.2) when this feature is built. `liboqs-python` is **not** needed and no
extra native library goes into the images. The ML-KEM and ML-DSA calls are
the ones documented under `hazmat/primitives/asymmetric/mlkem` and `mldsa`;
their exact signatures must be confirmed against the installed version when
implementing. The combiner and AES-GCM use `HKDF` and `AESGCM`, already used
by `totp_service.py`.

The upgrade from 46 to 50 needs a review of the 47 to 50 breaking changes
(48 dropped Python 3.8, irrelevant on 3.13; the 47 to 50 notes are not yet
read), because `cryptography` already backs the ODK credential encryption
(`app/utils/credential_crypto.py`, Fernet and PBKDF2) and TOTP
(`app/services/totp_service.py`, AES-GCM and HKDF). Their existing tests must
pass on the new version.

### Where plaintext exists

- Only in memory, inside a request or job, **after** authorisation has
  decided the caller may see or write that value.
- Write path: normalise -> validate (plaintext) -> blind index -> new DEK ->
  AES-256-GCM encrypt -> wrap DEK with the public keys -> store. Read path:
  authorise -> load ciphertext and wrapped DEK -> unwrap with the private keys
  -> decrypt -> serialise.
- Never in application logs, exception messages, error reports, task
  arguments, audit `reason` or `changes`, notifications, analytics or any
  export other than the audited CSV (decision 9). Celery tasks receive ids,
  never values.

### Audit content

`map_case_transitions.changes` for `identifier:<code>` stores, for `old` and
`new`, a masked trace only: `{"mask": "****0123", "bidx": "<first 16 hex of
the blind index>"}`. The mask shows the last 4 characters only when the value
is at least 8 characters long; shorter values are fully masked (`"****"`).
`null` stands for "no value".

### Performance

- Decrypt only what is rendered: the values on the current page, for viewers
  allowed to see them (decision 14). Badge-only viewers trigger no unwrap or
  decryption.
- Counts, the has / missing filter and tiles use `EXISTS` on
  `map_death_identifier`; the duplicate check and exact search use the blind
  index. None decrypts.
- Each displayed value costs one hybrid decapsulation (ML-KEM-768 plus
  X25519) and one AES-GCM decrypt; a page is bounded by the clamped page size
  and the number of active types. The merge gate times a full page and a
  10 000-row export on staging and records the numbers here; if the page cost
  is material, the fallback is one DEK per key version cached in process,
  which a decision would have to accept (it gives up public-key-only writers).
- Writes cost one encapsulation per changed value.

### Key rotation

1. Generate a new hybrid key pair with a new key id. Install the private key
   in the secret store and mount it; move the old private key to
   `PII_KEM_PREVIOUS_PRIVATE_KEY_FILES`; set the new public key and key id.
   Restart `minerva_app_service`, `minerva_celery_worker` and
   `minerva_celery_beat`. New writes wrap with the new key; reads accept both.
2. Run the **re-wrap job** (a Flask CLI command inside `minerva_app_service`
   or the worker that holds the private keys): select rows whose `key_id` is
   not current, in keyset batches by primary key, unwrap each DEK with the
   old private key and wrap it with the new public key, update `dek_wrapped`
   and `key_id`, commit per batch. **The data ciphertext is not touched.**
   Idempotent and resumable; logs counts only.
3. When the job reports zero rows on old key ids, remove the old private key
   from the mounts and the secret store (after the backup retention below),
   and restart.

Moving to ML-KEM-1024 or a later algorithm is the same procedure with a new
algorithm id. Rotating `PII_BLIND_INDEX_KEY` is a separate, rarer job that
recomputes every `value_blind_index` (unwrap, decrypt, re-HMAC) while writes
are paused, because old and new indexes do not compare.

### Backup and restore

- Database backups hold ciphertext, wrapped DEKs and blind indexes only. A
  backup alone does not disclose numbers.
- The KEM private keys and the blind index key are **backed up separately**
  from the database, in the secret store, and every private key that wrapped
  rows still in a retained backup is kept until those backups expire.
- Restoring a backup needs the private keys for the key ids it contains.
  **Loss of the private keys means loss of the numbers**; there is no
  recovery path. The rows remain (type, has number, audit) but the values
  must be re-entered.
- Restoring into another environment (staging) with different keys makes
  values unreadable there, which is the intended default.

### Migration, dependency and rollout

- The values table is new: no plaintext column to migrate, no backfill. The
  additive migration creates `map_death_identifier` with `value_ciphertext`,
  `dek_wrapped`, `value_blind_index` (`String(128)`) and `key_id`, plus the
  other tables and indexes in "Data model". Downgrade drops them.
- The `cryptography` pin change is made with `uv add` inside
  `minerva_app_service`, then the app, celery worker and celery beat images
  are **rebuilt** and `minerva_app_service`, `minerva_celery_worker` and
  `minerva_celery_beat` restarted (AGENTS.md "Toolchain"). It lands, with
  the ODK credential and TOTP tests green, before the first identifier stage.
- Keys before code: the KEM key pair (private key in the secret store and
  mounted) and `PII_BLIND_INDEX_KEY` exist and are backed up in every
  environment before the first stage deploys, since production refuses to
  start without them.

### Tests for encryption

- **Known-answer tests** for the primitives as used: ML-KEM-768 against the
  FIPS 203 / NIST ACVP vectors where the library exposes deterministic
  inputs, otherwise a pinned vector recorded from the library; X25519
  (RFC 7748 vectors); HMAC-SHA-512 (RFC 4231 vectors); and a fixed-input
  vector for the combiner, so a change in the combiner's `info` layout fails.
- Round trip; a fresh DEK and nonce per write (same value twice gives
  different ciphertext and wrapped DEK, same blind index).
- **Wrong AAD fails:** a ciphertext copied to another `death_id` or another
  type fails to decrypt; a wrapped DEK presented with another key id fails.
- Tampered ciphertext or wrapped DEK, unknown version, algorithm or key id
  fail with the generic error, which contains neither ciphertext nor
  plaintext.
- **Key rotation:** rows on the previous key read during the window; the
  re-wrap job moves every row to the new key id with `value_ciphertext`
  byte-for-byte unchanged; after removing the old private key every row still
  reads.
- A writer configured with only the public key can write; reading without a
  private key fails cleanly.
- Blind index: `mccd/1` and ` MCCD/1 ` give the same index; the same value
  under two types gives different indexes.
- Production start refuses a missing or malformed public key, key id or
  `PII_BLIND_INDEX_KEY`, and a reading process refuses a missing private key
  file.
- No plaintext in the database: after a write, no column of the row and no
  `map_case_transitions.changes` contains the value (assert the row exists
  first). No plaintext in captured logs on a validation failure, a duplicate
  warning and a decrypt failure.

## Personal data and logging

- Registration identifiers are **personal data of the identifier class**
  (`PII_TYPE_IDENTIFIER` in `app/services/pii_field_registry.py`, as
  `abha_number` and `abha_address`): each number links the case to a named
  civil record.
- Values are **never** written to application logs, error messages, audit
  `reason` or `changes`, notifications or analytics. Logs may name the type
  code and the case id only.
- Visibility follows decision 14 and the "See values" rule above, not
  `should_redact_pii` alone. Hidden values are omitted from the payload,
  not blanked.
- Values are not added to the interview payload or the coding views.

## API outline

Names follow `docs/current-state/api-v1.md`. State changes are POST/PATCH/PUT
with `X-CSRFToken` for browser calls.

- **Registration** `POST /api/v1/intake/deaths`: new optional key
  `identifiers`, an object `{<type code>: <text>}`. It is allowed as an
  object (the route today refuses object values for register fields; the
  check is per key, so `identifiers` gets its own parser). Idempotent on
  `client_death_id` like the rest of the registration.
- **Correction before completion** `PATCH /api/v1/intake/deaths/<death_id>`:
  the same `identifiers` key; only listed codes change; `null` or empty
  clears one. Subject to `update_death`'s existing gate.
- **Identifier write, any time**
  `PUT /api/v1/intake/cases/<death_id>/identifiers`: body
  `{"identifiers": {...}, "if_updated_at": ...}`. One endpoint for every role
  in decision 11; the service resolves the writer's right per case (In-charge
  and supervisors by `supervising_grant`, data manager by project scope,
  reporter by `_reporter_reaches`, interviewer by having interviewed the
  case) and applies decision 12 on closed cases. Not gated on completion; one
  `identifiers_set` audit row naming the grant. Supervisor, In-charge and
  data manager writes are browser only.
- **Reads**: the case detail and the list rows (worklist, reported deaths,
  supervision, the shared case list in `case-list-views.md`) carry
  `identifiers: [{code, label, value}]` in `sort_order` for viewers allowed
  to see values, and `[{code, label, present}]` for badge-only viewers;
  loaded in the same query as the row (one aggregated join, no per-row
  lookup), decrypted only for the rows on the page.
- **Configuration**:
  - `GET/POST /api/v1/projects/<project_id>/identifier-types` and
    `PUT /api/v1/projects/<project_id>/identifier-types/<id>` (admin,
    project_pi, data_manager of that project; no DELETE, deactivate instead).
    Saving runs the length, character type, example and pattern checks above
    and writes a `map_identifier_audit` row.
  - Field workers and supervisors read the active types (code, label,
    min_length, max_length, char_type, pattern, example,
    required_at_report) from
    `GET /api/v1/intake/identifier-types?project_id=`, allowed for a project
    where the user may register (`register_death_context`) or supervise.
    Not folded into `/me/access`: access replies are never cached
    (`docs/current-state/expo-client.md`), and the device must cache the
    types for offline registration.

## CSV export

Decision 9.

- The case list export (`GET /api/v1/cases/export.csv`, `case-list-views.md`)
  adds one column per active identifier type of the project, in
  `sort_order`, **only when the exporter has PII access in that project**
  (the "See values" rule: admin, or a live `data_manager`, `project_pi` or
  `site_pi` grant on that project). For any other exporter the columns are
  left out entirely (not blank).
- A multi-project export includes identifier columns only for rows of
  projects where the exporter qualifies; other rows leave those cells empty
  and the header notes it.
- Decrypt path: the export streams in keyset batches; each batch loads its
  ciphertext in the same query as the rows and decrypts in memory; nothing is
  written to a temp file in plaintext.
- Audit: one `map_identifier_audit` row per export with `event =
  'export_with_identifiers'`, the exporter and role, the filter set, the row
  count and the type codes included, written before the response streams.
  No value is recorded. An export without identifier columns writes no row.
- CSV injection: cells beginning with `=`, `+`, `-` or `@` are prefixed with
  `'`, as for every exported text cell.

## UI

- Entry field: one row per active type, label above, **monospaced** input
  (`font-family` monospace, `autocapitalize="characters"`, `autocorrect` and
  `spellcheck` off), the example as hint text below. The field upper-cases
  as the user types (so what they see is what is stored), pre-checks length,
  character type and pattern, and shows the server's message on refusal. A
  required type is marked required.
- A duplicate warning shows inline under the field with **Continue** and
  **Edit** actions (decision 10); it never blocks saving.
- Cards and case detail: for viewers allowed to see values, the numbers in
  monospace, label first; a missing number shows nothing on cards and "Not
  yet issued" on the detail. Badge-only viewers see "Registration number:
  recorded" or "missing" per type.
- An **"Add registration number"** action on a row of the shared case list
  and on the case detail, shown only to users decision 11 and 12 allow for
  that case, opening the same fields.
- Filter on the case list: **has / missing registration number** (any type,
  or one type), applied server-side with `EXISTS` on
  `map_death_identifier`.
- Search by number: exact match through the blind index; the server
  normalises the search text and computes its index for each type; only
  users who may see values can search by number.

## Offline (native app)

- Identifiers entered on a registration made offline travel inside the
  queued registration (in the device's encrypted store) and are covered by
  its `client_death_id` idempotency (field-data-collection.md, "Client
  ids"); a refusal reopens the queued item as for any other register field.
- The identifier type list (`GET /api/v1/intake/identifier-types`) is
  cached in the encrypted store per project and refreshed with the case list. The
  server validates against the types current at upload; a type deactivated
  while the device was offline refuses that value (422) and the item reopens.
- Supervisor, In-charge and data manager writes are web only.

## Rollout and migration

- One additive migration: create the three tables with their constraints
  and indexes. No backfill (no numbers exist yet). Downgrade drops the
  tables. Chain onto a committed revision; run `flask db heads` before and
  after (`migration-chaining.md`).
- Before the first stage: the `cryptography>=48` upgrade with the image
  rebuilds and restarts, and the KEM key pair and `PII_BLIND_INDEX_KEY`
  generated, backed up and installed in every environment (see "Migration,
  dependency and rollout").
- Staged: (1) `app/utils/pii_crypto.py` on the upgraded `cryptography`, keys and config, tables, models,
  type configuration with its audit; (2) registration and correction writes,
  reads on detail and lists; (3) the any-time identifier write, list filter
  and "Add registration number"; (4) native entry and cache; (5) CSV export
  with its audit.
- Update `docs/current-state/data-model.md` and `api-v1.md` with each
  stage, and `pii_field_registry` with the new identifier class.

## Tests

- Type save: `min_length > max_length` refused; example failing length,
  character type or pattern is 400; each `char_type` value accepted and an
  unknown one refused; valid pattern accepted; each refused construct
  (backreference, lookaround, nested quantifier, `{1,1000}`, over-length
  pattern) is 400; duplicate code in a project refused; code change after
  values exist refused; admin, project_pi and data_manager of the project may
  save (assert present), a project_pi of another project gets 404, a coder
  gets 403; each save writes one `map_identifier_audit` row.
- Value: normalisation (whitespace, NFKC, always upper-case: a lower-case
  submission is stored in capitals and the decrypted value matches the
  capitalised pattern); empty clears; under-length and over-length refused
  before the character type and pattern run; each character type accepts its
  set and refuses a character outside it (letters with a digit, digits with a
  hyphen, hyphen/slash allowed only in the fourth type); all rules must pass
  (passes length and character type but fails pattern is refused); inactive
  and unknown code refused; required-at-report missing is 422 on
  registration and accepted on a later write; the refusal message does not
  contain the submitted value.
- Duplicate number: `mccd/1` and `MCCD/1` count as the same number; the
  write succeeds with a warning; the warning carries case id, unit, reporter
  name and designation for a supervisor in reach and only the generic text
  for a writer without reporter-identity rights (assert the detailed form
  first); excluded for confirmed duplicates and cancelled cases; the other
  case appears in `possible_duplicates`.
- Authorization after completion: In-charge, supervisor in scope, data
  manager in project, the reporter on their own death and the interviewer on
  a case they interviewed may write; an interviewer on a case in their unit
  they did not interview is refused; out of scope is 404.
- Closed cases: supervisor and In-charge write on a cancelled and on a
  confirmed-duplicate case; reporter, interviewer and data manager get 409
  `case_closed`.
- Visibility: values present for PII roles and `collaborator_pii` (assert
  present first); coder, reviewer, coding_tester and collaborator get the
  badge with no value field; a coder who also holds a PII grant in another
  project still gets the badge.
- Device credentials are refused for supervisor, In-charge and data manager
  writes.
- Audit: one `identifiers_set` row per write with the grant; `changes` holds
  only the mask and blind index prefix; values absent from `reason`,
  `changes` and captured logs.
- Export: identifier columns present for a data manager with PII access
  (assert present), absent for an exporter without it; one audit row per
  export with identifiers, none without.
- Offline: a resend with the same `client_death_id` stores one set of
  identifiers.
- Lists: identifiers loaded with a constant query count per page; badge-only
  pages perform no decryption.
- Encryption: see "Tests for encryption".

## Non-goals

- No lookup or verification against the civil registration or MCCD systems.
- No identifiers inside the WHO VA interview payload or ODK forms.
- No new role, grant or scope kind.
- No merging of cases that share a number.
- No per-site or per-unit identifier types (project only).
- No partial or fuzzy search on numbers (the blind index supports exact
  match only).

## Contradictions to resolve

- `data-manager-workflow.md` "Export policy" says exports omit direct local
  identifiers from bulk extracts. Decision 9 is a deliberate exception for
  registration numbers; that policy should name it when this baseline is
  accepted.
- `web-intake.md` ("Death register") says register personal data follows
  "admin-only exports". Registration numbers are exported to data managers
  (and project_pi, site_pi) with PII access in the project, audited; that
  line should carve them out.
- `should_redact_pii` (`app/services/viewer_pii_service.py`) lifts
  redaction for coder, coding_tester and reviewer and does not lift it for
  interview_supervisor or death_reporter. Decisions 10 and 14 need the
  opposite for this data, so registration numbers use their own
  per-project visibility check rather than that helper.

## Open questions

1. Add `google-re2` as a second pattern guard, or rely on the safe subset?
2. Should other PII columns (informant phones, ABHA number and address,
   address fields) move to the same `app/utils/pii_crypto.py` helper later?
   Each would need its own blind index decision (phones are searched by
   suffix today, which a blind index does not support) and a staged
   backfill of existing plaintext, re-encrypted under the same PQC
   envelope.
