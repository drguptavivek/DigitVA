---
title: Field Data Collection Policy (paths, device data, encryption)
doc_type: policy
status: draft
owner: engineering
last_updated: 2026-10-05
---

# Field Data Collection Policy

## Purpose

A verbal autopsy interview is collected with the deceased's name, the
informant's name, the place of death and, for health-system projects, ABHA
identifiers in front of the interviewer. Collection is therefore **unmasked by
necessity**, while coding is **masked**. That asymmetry is the reason this
policy exists: it fixes which collection paths are permitted, and what each one
may keep on the device it runs on.

It governs the WHO VA 2022 questionnaire in every DigitVA-owned client. ODK
Central collection is out of scope — that data is governed by the ODK
deployment and reaches DigitVA only through sync
([ODK Sync Policy](odk-sync-policy.md)).

## Two permitted paths

Only these two collection paths are permitted. Any third arrangement — in
particular a browser client that persists answers locally — requires this
policy to be amended first.

### Path A — online browser intake

- The interviewer fills the questionnaire in a DigitVA page while connected.
- **No questionnaire answer, attachment or identifier is persisted on the
  device.** Drafts live server-side (`va_web_intake_drafts` and its section
  rows); the page's `draftStore` writes every save through
  `/api/v1/intake/...`. See [Web Intake Policy](web-intake.md).
- Authentication is the ordinary Flask-Login session cookie with
  `X-CSRFToken` on every state change. No long-lived credential is issued.
- Losing connectivity means losing only answers typed since the last section
  save. That is the accepted trade for holding nothing at rest.

Specifically prohibited on this path:

- a browser-backed `draftStore` (`localStorage`, IndexedDB), including the
  package's deliberately named `createInsecureWhoVaBrowserDefaults()` helper,
  which exists for prototypes and must never be used here;
- a service worker that caches answers, attachments or API responses carrying
  them;
- personal data in URL paths or query strings, which are logged by proxies and
  kept in browser history.

### Path B — native app with encrypted storage

For offline field work. A native app is required rather than a PWA: browser
storage cannot hold keys in hardware-backed storage, and on iOS it may be
evicted by the operating system while holding the only copy of a completed
interview — a data-loss risk, not only a confidentiality one.

Requirements, all of which must hold before the app collects real data:

- **Encrypted at rest.** Answers *and* attachments are encrypted on the
  device. Audio narration and document images are the bulkiest personal data
  and are covered by this rule, not exempt from it.
- **Keys in hardware-backed storage** (iOS Keychain / Android Keystore), never
  in the application database and never derivable from it alone.
- **One encrypted store per interviewer** (decision C2: phones are shared).
  Each interviewer's answers and attachments are encrypted under a key derived
  from their own PIN, so unlocking as one interviewer never exposes another's
  in-flight interviews. A shared device holds several such stores side by side
  and no shared plaintext index of them: the device may reveal that other
  accounts exist, never what they hold.
- **Unlock gate.** A PIN or biometric unlock; the working key exists only in
  memory while unlocked; automatic lock after inactivity. Repeated failed
  attempts wipe **only the store being unlocked** — never the whole device, or
  one interviewer's forgetfulness would destroy a colleague's unsent work.
- **Push and purge.** The device keeps only in-flight interviews. Once the
  server acknowledges a submission and its attachments, the local copy is
  deleted. The device is not an archive and holds no history of past cases.
  There is no time ceiling on unsent work (decision C3).
- **Revocable device sessions.** A refresh credential is bound to a
  (device, interviewer) pair, revocable server-side, and revoked automatically
  when that interviewer's grant is withdrawn. Revocation wipes **that
  interviewer's store only** and refuses further collection under that account;
  other accounts on the same handset are untouched.
- **Wipe on logout**, covering that interviewer's database, attachments and
  cached keys.
- **Outstanding work is visible server-side.** Each sync reports the device's
  count of unsent interviews and their unique ids. Because there is no
  retention ceiling, this is the only way anyone can tell what a lost phone was
  holding; without it, unsent interviews are invisible to the organization
  until they arrive.

### Path B design (proposed 2026-09-30, pending owner confirmation)

Built to `.tasks/2026-09-30-android-collection-app.md` (epic
`digitva-kmk`). The parts that are policy:

- **Enrolment by one-time QR.** An admin creates an enrolment code for one
  project (default single use, one hour); the QR holds only the server URL,
  the project id and that code. The app accepts a server host only from an
  allowlist compiled into the build (release: the production host), so a
  forged QR cannot send an interviewer's password elsewhere. The device
  secret it receives is used only to open interviewer sessions.
- **Interviewer sign-in** takes the account's email or mobile number
  (unique, from a redeemed code or verified email; mobile-sign-in.md) and its
  password and, when the account has factors, a TOTP or recovery code
  ([Authentication Factors](authentication-factors.md)); a device session
  requires an active `interviewer` grant in at least one project (see
  "Multi-project devices" below), checked again at every refresh.
- **Tokens**: opaque, stored hashed; access 15 minutes; refresh rotated on
  every use and presented with the device secret; reuse of a retired refresh
  token revokes the session. Proposed C1: refresh lifetime 30 days, sliding,
  and (proposed addition) at most 90 days from sign-in, after which the
  interviewer signs in again. Expiry never loses data (the store is keyed by
  the PIN).
- **Only revocation wipes.** The app wipes an interviewer's store only when
  the server answers `session_revoked`, which it sends only for an
  administrative or device revoke (a lost phone must not keep data) or when
  the worker has no active project left (grant withdrawn or last project
  closed). Closing the device's enrolment project alone ends nothing while
  the worker has another project, so moving between phones and projects is
  not hampered. A password or factor reset or a deactivated account answers
  `session_ended`:
  the session is over but a forgotten-password reset must not destroy unsent
  field work. Token reuse (`refresh_reused`, or `refresh_retry_race` when a refresh
  response was lost), expiry and an unrecognised device end the session but
  keep the data: the interviewer signs in again and the unsent interviews are
  still there. A replayed token is a theft signal, not proof the phone is
  lost, and wiping on it would turn a flaky network into data loss.
- **Second factor on the device**: five wrong codes for an account within 15
  minutes lock its device sign-in for the rest of the window
  (`second_factor_lockout` event); every refused sign-in after the password
  step is audited without secrets.
- **Store key**: a random per-store secret in the Android Keystore joined
  with the interviewer's PIN, fed to SQLCipher's key derivation; biometric
  unlock releases the PIN part from a Keystore entry that requires a strong
  biometric. PIN at least 6 digits; 5 wrong PINs in a row wipe that store.
- **Idempotent upload**: each interview carries a client draft id; a resend
  returns the first result. An interview for a case a teammate already
  submitted is kept as a superseded copy, never left on the phone.

**Built, server side** (`digitva-kmk.1`, 2026-09-30): enrolment codes and
QR, device enrolment, interviewer sessions with the second factor and the
grant check, hashed opaque tokens with rotation and reuse revocation,
device revoke, access summary, idempotent upload with the superseded-copy path,
and the outstanding-work report
([Device Collection API](../current-state/device-collection-api.md)).
Hardened (`digitva-kmk.6`): request and answer size bounds, the 90-day
absolute cap (`DEVICE_SESSION_MAX_DAYS`, proposed), device-bound refresh,
reuse codes separate from revocation, the device second-factor lockout,
device units and translations endpoints, outstanding draft ids, and refusal
of a plain-http `DEVICE_PUBLIC_URL` outside development. The refresh
lifetime is the proposed 30 days (C1) behind `DEVICE_REFRESH_TTL_DAYS`, and
enrolment codes are admin-only; both stay owner decisions.

**Built, app phase 2a** (`mobile/digitva-collect`): enrolment, sign-in,
per-interviewer plain SQLite drafts, upload gated on the form's verdict or an
incomplete interview outcome, push and purge, wipe only on `session_revoked`
(other refusals mark the account "sign in again"), units and translations
from the device API.

**Built, app phase 2b** (2026-09-30): each interviewer's drafts are a
SQLCipher database keyed by a random Keystore-held secret joined with a PIN
of 6-16 digits; optional biometric unlock releases the PIN from a Keystore
entry that needs a strong biometric; five wrong PINs in a row wipe that
interviewer's store and end the server session; the app locks after 5 idle
minutes or over a minute in the background, saving the open draft first;
FLAG_SECURE covers every screen. Checked on the emulator (encrypted file,
lock, PIN counter, wipe); biometric enforcement needs a real device. Builds
stay debug-only and must not collect real interviews until C4 is settled.

**Built, phase 3 offline cases** (`digitva-kmk.4`, 2026-09-30; one case
list since `digitva-p6fs.24`): the device's case list is the browser
worklist of one project. The app downloads the cases in active states
(waiting for a visit, refused, in progress) with that list and then each
case's detail (with its prefill, which the server sends only for a case the
worker may start or resume) into the encrypted store, and replaces them
on every refresh, so a case that leaves the active states leaves the phone:
no history is kept. Deaths
registered, contact attempts logged and visit dates set offline are queued
with client ids, sent registrations first, and deleted on acknowledgement;
pending registrations are part of the outstanding-work report.
Attachments are not built yet.

**Offline contact details** (owner, 2026-10-03, `digitva-p6fs.24`). This
replaces the earlier "phones stay masked on the device". An authorized native
worker may download the full contact details of an **active** case in their
scope (waiting for a visit, refused, or in progress; the app decides from the
case's `state`) into their encrypted per-interviewer store: the informant's
name, both full phone numbers, the household address fields (address, house
or street, village or ward, landmark) and the remarks. They come only from the
single-case detail call, never from a list. They are kept exactly like
drafts: deleted when the case leaves the active states, on logout, and on
`session_revoked` (device or administrative revoke, withdrawn grant). ABHA
number and address and the father's and mother's names are never in the
detail's own fields (the case prefill keeps what it already carried). Cases
in other states may be listed online with masked phones; the app does not
keep their contact details, so the device still holds no history of past
cases.

**Multi-project devices** (owner, 2026-10-03; no older apps in the field,
so no compatibility path, 2026-10-04). A native device may hold data for
every project the signed-in worker is an interviewer in (the intake
context), with no admin step. Every project-scoped request names its
project, which must be one of those; the enrolment project is not a default
and does not limit access (it stays the device's admin home: listed and
revoked there, and its closure ends the device). The session lasts while the
worker has at least one authorized project and is revoked
(`session_revoked`) when none remains. When a project drops out of the
access summary's project list the app deletes that project's local data (drafts,
cases, contact details), as it deletes a store on `session_revoked`. The
browser (Path A, PWA included) is unchanged: no multi-project persistence
and no offline storage.

**Which cases a worker sees** (owner, 2026-10-03), on the device as in the
browser ([Web Intake](web-intake.md), "Who sees which cases"): the death list
and its contacts are shared by every worker of a unit; a worker granted on
several units, in one project or several, sees each granted unit's subtree in
its own project; a site grant sees that whole project-site and a project
grant the whole project, and where a wider grant overlaps a unit grant the
wider wins. Interview forms stay the worker's own: the submission id
(`va_sid`) appears in a case's list row and detail only for the worker who
started its interview.

### Interview times (owner, 2026-10-04, `digitva-latk`)

Every interview, from the browser or the app, records three times:

- **Interview start**: the device or browser time the interview was opened.
- **Interview completion**: the device time it was marked complete.
  Marking it complete again updates this time.
- **Upload (receipt)**: the server time the interview arrived.

**Clock skew** is one stored number: the difference between the device's
clock at upload and the server's receipt time. It is for audit and for the
two-device conflict rule ([Web Intake Policy](web-intake.md), "Parallel
interviews"). It does not change the interview times.

The submission payload's `start` and `end` come from the start and completion
times; `SubmissionDate` stays the server receipt time.

The server's re-check of relevance and constraints evaluates `today()` at the
device's raw completion time, whatever the device considered local, not the
upload time and not skew-corrected. An interview finished offline days earlier
is not refused for it.

Built server-side (`digitva-latk`; detail in
[Device Collection API](../current-state/device-collection-api.md)):

- The device envelope carries `startedAt`, `completedAt` and `deviceClockAt`
  (ISO 8601 with a UTC offset); a malformed or offset-less one is refused
  422 `invalid_interview`. Start and completion are stored in the draft's
  meta, and `deviceClockAt` yields the stored clock skew.
- Payload `start` and `end` are `startedAt` and `completedAt` when present
  (else the draft's open time and the server submit time, as before);
  `SubmissionDate` is the server receipt time.
- The re-check evaluates `today()` at `completedAt` in its own offset when
  present, else at the server submit time as before.

Still the app's (`digitva-latk`, `mobile/`): `markCompleted`
(`mobile/digitva-collect/src/drafts.ts`) sets only a flag and records no
completion time. It must record `completedAt`, update it when completion is
sent again, and send `startedAt`, `completedAt` and `deviceClockAt` in the
envelope. Until then an app upload has no times and the server falls back to
the old behaviour. The browser keeps the draft's `createdAt` as start and the
submit time as completion, with no skew.

### Upload integrity under connection drops (owner, 2026-10-04, `digitva-2bxa`)

Owner concern: another app saw dropped connections corrupt data and create
duplicate uploads. The rules:

- **Client ids.** Every offline write carries one: `client_death_id` for a
  registration, `client_attempt_id` for a contact attempt, `client_draft_id`
  for an interview. A resend returns the first result, never a second record.
- **One transaction.** The server commits the whole interview in one
  transaction before it replies.
- **Delete after a matching acknowledgement.** The device deletes its copy
  only after an acknowledgement that matches what it sent.
- **Exact text and hash.** The app sends the answers as one exact JSON text
  string (`answers_json`) plus `answers_sha256`, the SHA-256 of that exact
  string. The server hashes the bytes it received and compares. A mismatch is
  refused 422 and nothing is stored. Only then does it parse. Neither side
  re-serialises the answers, so JavaScript and Python number formatting
  cannot differ.
- **What the server stores.** It stores that hash, computed over what was
  sent, before locked answers are overwritten and irrelevant answers
  stripped. It echoes the hash in the acknowledgement. The app verifies the
  echoed hash and the death id before it deletes its copy.
- **Resend with the same `client_draft_id`, or a later upload of the same
  interview** (owner, 2026-10-05, `digitva-xpqm`). There is no hash conflict:
  `hash_mismatch` is gone. The same hash is 200 with the stored result. Other
  answers are a later version of the interviewer's own interview, and the
  last completed version wins by completion time
  ([Web Intake Policy](web-intake.md), "Parallel interviews"): a newer one
  becomes the coder's version through the revision path, an older one, or any
  one after coding is final, is stored as history. The reply always says
  which: `kept: "incoming"` (the coder has the answers just sent) or
  `kept: "server"` (the coder keeps a newer version; the sent answers are
  history), `locked` (coding is final or the case closed), and
  `received_sha256`, the hash of the answers the server received, while
  `answers_sha256` stays the coder version's hash. The server answers the
  app's old shape (answers only in `draft.data`) with 422
  `answers_hash_required`, so the app side ships with it.
- **Acknowledgement rule.** The app deletes its copy when `received_sha256`
  equals the hash it sent (and the case id matches), whatever `kept` says:
  `kept: "server"` is an acknowledgement, the server has the answers. It
  never deletes on `answers_sha256` alone. On `kept: "server"` with `locked`,
  the app tells the interviewer a newer completed version is already with the
  coder, and that a send-back or reopen is the way to change it.
- **Timeouts.** Every app request has a timeout, so a dead connection fails
  the run with everything kept instead of hanging.
- **Case list refresh.** The app writes the replacement case list in one
  local transaction, so a kill mid-write leaves the old list.

This closes a data-loss path that exists today: the upload succeeds, the reply
is lost, the interviewer edits the completed draft, and the resend returns the
old stored result, so the app deletes the edited copy.

Built, server half (`digitva-2bxa`, `digitva-xpqm`): `answers_json`,
`answers_sha256`, the 422 (`answers_hash_required`, `answers_hash_invalid`),
the stored hash, and the `kept` / `received_sha256` / `locked` reply (see
[Device Collection API](../current-state/device-collection-api.md), "Uploads").
Still to build in the app: dropping its `hash_mismatch` handling, deleting on
`received_sha256`, the notice for `kept: "server"`, request timeouts (none
today) and the transactional case list write.
Client-id idempotent resend is built (see "Idempotent upload" above).

### Form version (owner, 2026-10-04, `digitva-xuf9`)

The form is compiled into the app. A question or logic change needs a new app
build. The server records the phone's form version (envelope
`instrumentVersion`, stored as payload `FormVersion`) but never compares it,
and it re-checks answers against its own server instrument. So an older phone's
answers can be stripped by rules it never showed.

Rule:

- The server publishes its form version in form-options: the server
  instrument's own version, not the web bundle's file time.
- An app whose bundled version is older blocks **new** interviews with "update
  the app". It never blocks an upload.
- The server never refuses an upload on version. It flags
  `FormVersion` != current for QA.
- The app's version is refreshed at each sign-in.
- Owner, 2026-10-04: the server publishes the current form version and its
  history at `GET /api/v1/instruments/<code>/versions`: each version and the
  date-time it became active on this server, newest first. The server records
  a version the first time it serves it, so no deploy step is needed.

Built (server half, `digitva-xuf9`, 2026-10-05):

- `GET /api/v1/instruments/<code>/versions` and `mas_instrument_versions`
  (instrument code, version, `activated_at`, and the full composed definition;
  unique on code + version). A version is recorded the first time this server
  serves it, once per process, `INSERT ... ON CONFLICT DO NOTHING`.
- form-options `instrument_version` is the composed version string
  (`<WHO version>-<first 10 hex of the composed definition's SHA-256>`, e.g.
  `2026081401-3833e95fb5`), and `definition_sha256` fingerprints the project's
  slice so an app with it cached skips the fetch.
- Re-check by version (owner, 2026-10-04): `derive_validation_errors` and
  `strip_irrelevant_answers` in `app/services/web_form_relevance_service.py`
  take an optional `version`; a recorded version is judged by its stored
  definition, an unknown one by the current server instrument.
  `form_version_of(meta)` reads it from the envelope; submit and revision
  pass it. A version this server never served (the browser's bundled form)
  is judged by the reduced server instrument, as before.

Built server-side (`digitva-xuf9`, 2026-10-05): the versions endpoint and
`mas_instrument_versions`; form-options `instrument_version` is the composed
version; an upload is re-checked against the version it names when this
server served it (else the current rules); the payload carries
`form_version_outdated` (true for a served version older than the current
one; never a refusal); `auth_devices.app_version` is refreshed from an
optional `app_version` on `POST /auth/sessions` and `/auth/sessions/refresh`.

The app half (send `app_version` at sign-in and refresh, compare versions,
block new interviews on an outdated form) is built by the Expo session
(`digitva-6pwq.1`, closed).

### Form definition from the server (owner, 2026-10-04, `digitva-6pwq`)

The form is already data: a JSON definition (sections, questions, choices,
relevance, constraints, calculations) run by a generic engine
(`vendor/who-va-2022/src/generated/who-va-2022.instrument.json`,
`src/engine/`; the controls in `src/ui/question-controls.tsx` name no
question). Today it is bundled into the app at build time, and DigitVA's
extensions are added to it in code (`src/digitva-extension.ts`).

Rule:

- The server builds each project's complete form (the WHO definition plus
  that project's enabled extensions, with the package's own composer) and
  serves it as JSON, with its version, a SHA-256 fingerprint and an ETag.
  The server re-checks answers against that same definition.
- JSON only. No XForm XML (it would need a second engine) and no YAML.
- The app downloads the definition, checks the fingerprint, caches it per
  version and renders it. Question, label, choice, relevance, constraint and
  order changes need no app build.
- A draft stays on the version it started with. The app keeps a version
  cached until every draft on it has uploaded.
- The definition names the engine version it needs. An app whose engine is
  older refuses it and asks for an update: new control types, expression
  functions or engine changes still need an app build.
- The bundled form stays as the fallback until the first download. With a
  served definition, "older version" in the rule above means the app has no
  current definition its engine can run; it then blocks new interviews,
  never uploads.

Built (server half, `digitva-6pwq`, 2026-10-05):

- `tooling/who-va-2022/build-composed-instrument.mjs` (`npm run
  build:composed-instrument`) composes the package's
  `createWhoVa2022Instrument(ALL_DIGITVA_EXTENSIONS)` (the form the app
  renders), keeps the full definition and tags every section and question a
  conditional extension (`social_autopsy`, `narration_language`,
  `death_summary`, `medical_records`, `abha`) contributes with
  `extensions: [..]`. It fails unless, for all 32 subsets, the tagged items
  filtered by the subset equal the package's own composition for it (names and
  order, every item deep-equal). `order` numbers may differ because a subset
  that omits a layer renumbers the layers after it; the check requires the
  relative order, ties included, to be identical. Output
  `app/data/who-va-2022.composed.json`, deterministic, with top-level
  `version` and `engineVersion: 1`.
- `app/services/served_form_service.py` loads the file once and serves
  `GET /api/v1/instruments/<code>/definition?project_id=`: the file minus the
  items whose tags are all disabled for the project, serialized once per
  distinct set of enabled extensions; ETag `"<sha256>"` and
  `X-Definition-SHA256`, `Cache-Control: private, no-cache`, 304 on
  `If-None-Match`. The SHA-256 is not in the body.
- Slice identity and historical fetch (`digitva-6pwq.2`). `version` names the
  composed (all-extensions) definition, so one version has up to 32 project
  slices. Every body therefore carries a top-level `extensions`: the sorted
  conditional extensions it contains. A slice is identified by
  (`version`, `extensions`) and verified by its SHA-256. The same route takes
  `?version=<v>&extensions=a,b` (both or neither; empty `extensions` = none)
  and serves that exact slice from the full definition recorded for `v` in
  `mas_instrument_versions`, with the same body shape, headers, gzip and 304.
  404 `version_unknown` (never recorded here), 422 `invalid_extensions` (names
  outside that version's tags), 400 when only one param is given. The
  authorization is the project access check alone: the project need not enable
  those extensions today, since its settings may have changed since the draft
  was filled. The current version with extensions equal to the project's
  returns the same bytes as the default call. The draft envelope stores
  `instrumentVersion`, `definitionSha256` and `definitionExtensions`
  (`web_intake_service._ENVELOPE_META_KEYS`; validated: 64 lowercase hex, at
  most 16 names of `[a-z][a-z0-9_]{0,31}`; 422 otherwise) and the server
  echoes them in the draft envelope. After cache loss the app fetches by
  version and extensions, verifies the SHA-256 and never substitutes the
  current or bundled form; if the fetch fails the interview is preserved and
  the app fails visibly.

Built in the app (`digitva-6pwq.1`, closed): download, SHA-256 check,
per-version cache, rendering the served definition, drafts pinned to their
version, the `engineVersion` constant and refusal of a higher one.

Not decided:

- Switching the server's re-check default from the reduced server instrument
  to the stored composed definition.

Narration languages are not narrowed in the served definition: `narr_language`
carries the composer's full choice list, and the client keeps narrowing it to
the project's form-options `narration_languages`, as the web form does today.

### Accepted risk: no retention ceiling

Decision C3 permits an interview to remain on a device indefinitely until it
syncs, so that a CHO on a multi-day circuit with no connectivity is never
blocked from working. The accepted consequence is that a handset lost after a
long offline spell holds every interview taken in that spell. The compensating
controls are per-interviewer encryption, the PIN gate, and the server-side
record of outstanding work above. This trade should be revisited if devices are
lost in practice.

### Pre-release builds

Until decision C4 is settled the app is built unsigned, for development only.
A debug-signed build is signed with a well-known shared key, so any party can
produce an update that replaces it. **Debug builds must not be used to collect
real interviews**, and must be pointed at a non-production DigitVA.

## Coding is masked; collection is not

- The coding screen renders only fields carrying a mapped
  `subcategory_code`. Identifier questions are not mapped, so they are not
  rendered — the exclusion is structural, not a per-role filter.
- `mas_field_display_config.is_pii` redacts payload keys from the
  data-manager CSV export. The set is declared in
  `app/services/pii_field_registry.py` so it survives a mapping reseed and a
  fresh install; see
  [Field Mapping System](../current-state/field-mapping-system.md).
- Any new DigitVA extension field that carries a name, an identifier, free-text
  location or contact details **must be added to that registry in the same
  change that introduces it**. The registry is an allowlist of known-personal
  fields, so an unlisted new field defaults to exportable.

## Data minimization

- The collector requests only what the questionnaire and routing need. Host
  identifiers (draft UUIDs, grant ids) stay outside the WHO answer payload.
- Structured geography (`survey_state`, `survey_district`,
  `org_<level>_code`) is operational and not treated as personal data.
  Free-text location (`Id10055`, `Id10057`) is.
- Personal data is never written to application logs, including on the device.
  Logged identifiers are the submission id, the draft id and the unit code.

## Open decisions

| # | Question | Status |
|---|---|---|
| C1 | Device credential lifetime and refresh-rotation interval | ~~Open.~~ Sharpened by C2: the credential is per (device, interviewer), so a lifetime long enough for a multi-day offline circuit sits on a handset other people also use. **Deferred 2026-09-19:** with the native app, not open; decided when that work starts. Proposed and built behind config: 30 days sliding, 90-day absolute cap |
| C2 | One device per interviewer, or shared? | **Decided 2026-09-18:** shared, with one encrypted store per interviewer |
| C3 | Retention ceiling for an unsent interview | **Decided 2026-09-18:** no ceiling; purge only after a confirmed push. Accepted risk recorded above |
| C4 | Distribution and signing-key custody | ~~Deferred 2026-09-18: unsigned development builds for now; must be settled before the app collects real interviews~~ **Deferred 2026-09-19:** with the native app, not open; decided when that work starts |

## References

- [Web Intake Policy](web-intake.md)
- [Interview Revisions Policy](interview-revisions.md)
- [Organization Model Policy](organization-model.md)
- [Access Control Model](access-control-model.md)
- [Attachment Storage Policy](attachment-storage.md)
- `docs/planning/who-va-2022-web-intake-plan.md`
