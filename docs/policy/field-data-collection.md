---
title: Field Data Collection Policy (paths, device data, encryption)
doc_type: policy
status: draft
owner: engineering
last_updated: 2026-10-27
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

## Permitted paths

Only these three collection paths are permitted: Path A and Path B, and since
2026-10-27 Path C (standalone Collect Plus, below; owner decision, `digitva-5bzf`).
Any further arrangement — in particular a browser client that persists answers
locally — requires this policy to be amended first.

### Path A — online browser intake

- The interviewer fills the questionnaire in a DigitVA page while connected.
- **No questionnaire answer or identifier is persisted on the device, and
  an attachment only in the one case below.** Drafts live server-side (`va_web_intake_drafts` and its section
  rows); the page's `draftStore` writes every save through
  `/api/v1/intake/...`. See [Web Intake Policy](web-intake.md).
- Authentication is the ordinary Flask-Login session cookie with
  `X-CSRFToken` on every state change. No long-lived credential is issued.
- Losing connectivity means losing only answers typed since the last section
  save. That is the accepted trade for holding nothing at rest.

Owner exception, 2026-10-06 (`digitva-ej1`): audio narration, images and
files the interviewer captures may wait in the browser, **encrypted** (WebCrypto
AES-GCM, a non-extractable per-user key), until the network returns and the
server confirms the upload, for at most seven days, and are deleted at
sign-out. The rules are in [Web Intake Policy](web-intake.md), "Attachments".
Nothing else is buffered: no answer, no identifier.

Specifically prohibited on this path:

- a browser-backed `draftStore` (`localStorage`, IndexedDB), including the
  package's deliberately named `createInsecureWhoVaBrowserDefaults()` helper,
  which exists for prototypes and must never be used here (its plaintext
  attachment store included; the encrypted buffer above replaces it);
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
  There is no time ceiling on unsent work (decision C3). This holds for every
  enrolled (non-standalone) account; a Path C standalone phone is the stated
  exception and keeps its records until pushed or removed by the user (owner
  decision 2026-10-27, `digitva-5bzf`; see Path C).
- **Revocable device sessions** (Path B; a Path C standalone phone has no
  server session until enrolled, owner decision 2026-10-27, `digitva-5bzf`).
  A refresh credential is bound to a
  (device, worker) pair, revocable server-side, and revoked automatically
  when the worker no longer holds any grant that opens a device session (see
  "Who may sign in on a device" below). Revocation wipes **that worker's store
  only**, and only when it holds no unsent work (see "Unsent work is never
  purged automatically" below), and refuses further use under that account;
  other accounts on the same handset are untouched.
- **Wipe on logout**, covering that interviewer's database, attachments and
  cached keys. Sign-out states how many items are unsent and, when any are,
  asks a second time; an account that only needs to sign in again is offered
  "Sign in again", which keeps the store.
- **Unsent work is never purged automatically** (owner decision 2026-10-22,
  `digitva-tnr6`). A completed interview not yet acknowledged, an offline
  registration, a queued contact attempt or visit, a queued revision or an
  interview in progress stays on the device until the server acknowledges it
  or the interviewer or a supervisor resolves it. Only rows the server has
  acknowledged, and server copies the device can download again (cases and
  their contacts, settings, form definitions), are deleted automatically.
  - A project that leaves the worker's access (web intake turned off, a site
    form deactivated, a grant paused) keeps its unsent rows. The worklist
    shows "Project paused — N items waiting to send" with the reason; new
    work in that project is blocked; every sync still tries to send the rows
    first, before the access refresh, and a refusal keeps them and is shown.
  - `session_revoked` with unsent work (or while the store is locked, so its
    contents cannot be counted) does not wipe. The tokens are dropped and the
    account is locked into a read-only "access removed — N items not sent;
    contact your supervisor" state: no new work, the encrypted store kept.
    Signing in again (if the server allows it) resumes sending. A later
    unlock that finds nothing unsent completes the wipe.
  - A new death registration being typed in the native app is kept in the
    encrypted store with its client death id (`digitva-3o60`), cleared from
    the screen while the app is hidden and restored on return; only Save or a
    confirmed Discard removes it. The browser registration keeps its
    wipe-on-hide rule.
  - **Security trade-off, accepted by the owner:** after an administrative or
    lost-device revoke, unsent interviews (with names, phone numbers and
    answers) remain on the handset, encrypted under the interviewer's PIN and
    the Keystore-held store secret; five wrong PINs still wipe the store. The
    server can no longer receive the outstanding-work report for that device,
    so the last report before revoke is the record of what it holds.
- **Outstanding work is visible server-side.** Each sync reports the device's
  count of unsent interviews and their unique ids. Because there is no
  retention ceiling, this is the only way anyone can tell what a lost phone was
  holding; without it, unsent interviews are invisible to the organization
  until they arrive.

### Path B design (updated 2026-10-11)

Built to `.tasks/2026-09-30-android-collection-app.md` (epic
`digitva-kmk`). The parts that are policy:

- **Enrolment by one-time QR.** An admin creates an enrolment code for one
  project (default single use, one hour); the QR holds only the server URL,
  the project id and that code. The app accepts only a server that passes
  the rule compiled into the build (an https host under
  `causeofdeathindia.com`; mobile-sign-in.md section 7) and shows that host
  before redeeming the code, so a forged QR cannot send an interviewer's
  password elsewhere. The device
  secret it receives is used only to open interviewer sessions.
- **Interviewer sign-in** takes the account's email or mobile number
  (unique, from a redeemed code or verified email; mobile-sign-in.md) and its
  password. Native passkey sign-in is deferred. A device session requires an
  active grant that opens its gate for `interviewer`, `coder`,
  `coding_tester` or `reviewer` in at least one project (or a `death_reporter`
  grant in a project that keeps a death register) (see "Who may sign
  in on a device" and "Multi-project devices" below), checked again at every
  refresh.
- **Tokens**: opaque, stored hashed; access 15 minutes; refresh rotated on
  every use and presented with the device secret; reuse of a retired refresh
  token revokes the session. Proposed C1: refresh lifetime 30 days, sliding,
  and (proposed addition) at most 90 days from sign-in, after which the
  interviewer signs in again. Expiry never loses data (the store is keyed by
  the PIN).
- **Only revocation wipes**, and then only a store with no unsent work (see
  "Unsent work is never purged automatically" above). The app wipes an
  interviewer's store only when the server answers `session_revoked`, which it sends only for an
  administrative or device revoke (a lost phone must not keep data) or when
  the worker has no access left (every interviewer, coder, coding_tester and
  reviewer grant withdrawn, or their last project closed). Closing the device's enrolment project alone ends nothing while
  the worker has another project, so moving between phones and projects is
  not hampered. A password or security reset or a deactivated account answers
  `session_ended`:
  the session is over but a forgotten-password reset must not destroy unsent
  field work. Token reuse (`refresh_reused`, or `refresh_retry_race` when a refresh
  response was lost), expiry and an unrecognised device end the session but
  keep the data: the interviewer signs in again and the unsent interviews are
  still there. A replayed token is a theft signal, not proof the phone is
  lost, and wiping on it would turn a flaky network into data loss.
- **Local unlock on the device**: after server sign-in, the encrypted store is
  opened with the interviewer's PIN or optional device biometric. This local
  unlock is not a server factor and does not add permissions.
- **Store key**: a random per-store secret in the Android Keystore joined
  with the interviewer's PIN, fed to SQLCipher's key derivation; biometric
  unlock releases the PIN part from a Keystore entry that requires a strong
  biometric. PIN at least 6 digits; 5 wrong PINs in a row wipe that store.
- **Idempotent upload**: each interview carries a client draft id; a resend
  returns the first result. An interview for a case a teammate already
  submitted is kept as a superseded copy, never left on the phone.

**Built, server side** (`digitva-kmk.1`, 2026-09-30): enrolment codes and
QR, device enrolment, interviewer sessions with password and the grant check,
hashed opaque tokens with rotation and reuse revocation,
device revoke, access summary, idempotent upload with the superseded-copy path,
and the outstanding-work report
([Device Collection API](../current-state/device-collection-api.md)).
Hardened (`digitva-kmk.6`): request and answer size bounds, the 90-day
absolute cap (`DEVICE_SESSION_MAX_DAYS`, proposed), device-bound refresh,
reuse codes separate from revocation, device units and translations endpoints,
outstanding draft ids, and refusal
of a plain-http `DEVICE_PUBLIC_URL` outside development. The refresh
lifetime is the proposed 30 days (C1) behind `DEVICE_REFRESH_TTL_DAYS`, and
enrolment codes are admin-only; both stay owner decisions.

**Built, app phase 2a** (`mobile/digitva-collect`): enrolment, password sign-in,
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

**Deleting an unsent interview draft on the phone** (owner 2026-10-24,
`digitva-wy90`). "Delete draft" is in the interview's ⋮ menu and on a draft
row of the Interviews list, only for a draft that was never sent: not
completed (not queued, ready to send or sending), no server draft id, no
upload issue, no stored send refusal and no attachment the server confirmed.
A draft that was sent once and reopened is not offered. A danger
confirmation precedes it; the delete then removes, in one transaction, the
draft row, its consent record, its attachments, its stored form choices and
its send-error note, then returns to the worklist with "Draft deleted".
Nothing is deleted on the server (a never-sent draft has no server copy).
Registration and revision discards are unchanged.

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
replaces the earlier "phones stay hidden on the device". An authorized native
worker may download the full contact details of an **active** case in their
scope (waiting for a visit, refused, or in progress; the app decides from the
case's `state`) into their encrypted per-interviewer store: the informant's
name, both full phone numbers, the household address fields (address, house
or street, village or ward, landmark) and the remarks. They come only from the
single-case detail call, never from a list. They are kept exactly like
drafts: deleted when the case leaves the active states, on logout, and on
`session_revoked` (device or administrative revoke, withdrawn grant); a case's
contact copy is a server copy, so it goes even when unsent drafts are kept. ABHA
number and address and the father's and mother's names are never in the
detail's own fields (the case prefill keeps what it already carried). Cases
in other states may be listed online without phone digits; the app does not
keep their contact details, so the device still holds no history of past
cases.

**Who may sign in on a device** (owner, 2026-10-05). Coders, coding testers
and reviewers may sign in to the app without any interviewer grant. Device
sign-in and refresh need at least one of: an interviewer grant that reaches a
project whose web intake is not off (so an interview can start), or an active
`coder`, `coding_tester` or `reviewer` grant whose gate is open (the same
"opens its gate" rule the web app applies). Demo-training grants never
count. A user holding only other roles (collaborator, data manager,
supervisor, site or project PI) is still refused with 403
`no_interviewer_grant`; the code keeps its name because the app matches on
it, only the message changed. The session carries no authority of its own:
every route still checks its own role, action and scope, so a worker who only
codes can use only the coding routes and the interview and intake routes
remain interviewer-only. The automatic revocation above applies when the
user holds none of these any more, and a worker with an interviewer grant in
a web-intake-off project but a coder grant elsewhere keeps the session. The
per-worker encrypted store and its wipe rules are unchanged; for a worker who
only codes the store holds no collected interviews, so a wipe loses nothing
that was not already on the server. A data manager or admin may use the app
only when they also hold an allowed collection or coding grant; the app has no
data-manager or administrator functions, and the bearer token cannot reach
those web routes. A device refresh token lasts up to 30 days (90 at most),
longer than a 30-minute web session; a lost phone is handled by revoking the
device.

**The Android app collects data only** (owner, 2026-10-22, `digitva-cpx5`).
DigitVA Collect (package `com.causeofdeathindia.digitvacollect`) offers
enrolment, sign-in, PIN, consent, death registration, interviews, drafts,
attachments, sync and settings. Coding and review are not reachable on the
phone: the coding, reviewing and workspace routes and every Code now or queue
entry are removed from the native build, and an account that only codes or
reviews sees "Coding and review are done in the DigitVA web app" after
sign-in. The same Expo project builds the web app, where coding and review are
unchanged. The server still admits a coder-only device session under the rule
above; whether it should refuse one for this app is an open owner question. A
separate coding app, if built, will use package
`com.causeofdeathindia.digitvacoder`.

**Multi-project devices** (owner, 2026-10-03; no older apps in the field,
so no compatibility path, 2026-10-04). A native device may hold data for
every project the signed-in worker is an interviewer in (the intake
context), with no admin step. Every project-scoped request names its
project, which must be one of those; the enrolment project is not a default
and does not limit access (it stays the device's admin home: listed and
revoked there, and its closure ends the device). The session lasts while the
worker holds at least one grant that opens a device session (an interviewer
project, or a coder, coding_tester or reviewer grant elsewhere) and is revoked
(`session_revoked`) when none remains. When a project drops out of the
access summary's project list the app deletes that project's server copies
(cases, contact details, settings, form definitions) but keeps its unsent
work (drafts, registrations, queued actions and revisions) as a paused
project until it is sent or resolved (owner decision 2026-10-22). The
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
  cached until every draft on it has uploaded. Exception (2026-10-22,
  digitva-oxvt): a draft saved without a definition pin (an earlier build)
  whose form cannot be recovered exactly moves to the project's current form
  with a visible notice and is pinned to it; answers to questions that form
  no longer asks stay in the draft (section `_other`) but are not part of the
  submission.
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

### Path C: standalone Collect Plus (owner decision 2026-10-27, `digitva-5bzf`)

Status: policy baseline, nothing built. Implementation slices S1 to S8 of
`.tasks/collect-plus-standalone-and-parity-plan.md` follow this text. Every
rule below carries the owner decision of 2026-10-27 (`digitva-5bzf`).

Path C is Collect Plus (see "Collect Plus (experimental)") used **without a
server**: an unenrolled phone that collects interviews and codes them on the
device, and pushes both later, once the phone is enrolled. It is a third
arrangement, so this section is the amendment this policy demands for one.
Path A and Path B are unchanged for every enrolled, non-standalone use.

- **Who and where (owner decision 2026-10-27, `digitva-5bzf`).** Owner-controlled
  pilot phones only. A standalone phone is never handed to an interviewer;
  the person holding it is the owner's named pilot user. The plain build
  never offers Path C (it is Collect Plus only, and Android only like the
  device identity below).
- **Entry flow (owner decision 2026-10-27, `digitva-5bzf`).** The first-run
  screen offers "Use without a server" beside enrolment. It creates, on the
  phone alone: an **offline profile** (name and country required; the other
  profile fields as the app defines them), a **local account** with its own
  PIN and its own encrypted store under the Path B rules (SQLCipher, Keystore
  secret plus PIN, auto-lock, five wrong PINs wipe that store only), and a
  **project-less form path**: the interview runs from the instrument bundled in
  the app, with the DigitVA extension set the user picks in setup (default
  none; the equity layer available once it ships). The local account is not
  a server account: it holds no grants, never calls the server, and is
  skipped by token refresh, notification polling and sync until enrolment.
  Informant details are saved only after the standalone consent below.
- **Device identity (owner decision 2026-10-27, `digitva-5bzf`).** On first run
  the phone mints a device UUID, kept in the Keystore-backed secure store,
  never regenerated, and stamped on every standalone interview and coding
  result. It is provenance, not authentication: when the phone is later
  enrolled the server records it as the optional `client_device_uuid` of the
  device row (one device row per UUID; an idempotent re-enrol never makes a
  second), and the bearer token stays the only credential.
- **Retention (owner decision 2026-10-27, `digitva-5bzf`).** No hard ceiling,
  consistent with decision C3: unsent work is never purged automatically.
  Because a standalone phone has no server record of what it holds and no
  remote revoke or wipe, the app shows a visible **age warning** on any
  standalone interview or coding result that has not been pushed or backed up
  for longer than a stated number of days, and **backup reminders** (days since
  the last backup, count of records not in any backup). The thresholds are
  set in the implementation slice (open point 1 below).
- **Accepted risks (owner decision 2026-10-27, `digitva-5bzf`).** The
  "Outstanding work is visible server-side" control of Path B does not exist
  before enrolment: the server cannot tell what a lost standalone phone
  holds. Accepted, with these mitigations: per-store encryption, the PIN, the
  five-failure wipe, screen-capture blocking, and the backup reminders. There is no
  remote wipe, and a wiped or uninstalled phone destroys the only copy
  (OS backup is off), which is why the backup rules below are part of this
  policy. A phone that has never synced is not judged by the phone-clock
  check, so a standalone phone shows a standing "check Date & time" notice
  and its interview times are the phone's own until the first sync measures
  an offset.
- **Masking.** Coding on a standalone phone is not masked (accepted
  2026-10-26): the same person collects and codes. After enrolment the case
  reaches the server as an imported, coded result with its provenance, not as
  a masked coding (see [Offline API Contract](offline-api-contract.md)
  section 17).
- **Enrolment later (owner decision 2026-10-27, `digitva-5bzf`).** Enrolling
  the phone (enrolment QR or sign-in QR,
  [Sign-in by Mobile Number](mobile-sign-in.md) section 8) binds the device
  UUID to the server device row and moves the standalone records under the
  redeemed account only through an explicit, PIN-confirmed adoption step that
  shows how many interviews and coding results will be sent; adoption is never
  silent, because whoever redeems first would otherwise inherit the data.
  The offline profile carries an **optional org code**, a single code at one
  organisation level of the project tree (which level: open point 2). The
  app stamps it into the interview as the matching `org_<level>_code` answer
  so the server's normal routing applies. The code is a claim, validated
  against the project tree like any payload; free text such as the facility
  name never routes. A record whose code is absent, unknown or does not
  match goes to the project's **unrouted queue** for a data manager to
  place or pin, never guessed (see [Organization Model](organization-model.md),
  routing and the unrouted queue). What is pushed and how it is accepted:
  [Offline API Contract](offline-api-contract.md) section 17. Once the
  server acknowledges a record, the Path B push-and-purge rule applies to
  that record (open point 3).
- **Consent.** A standalone interview uses a notice bundled in the app,
  generated from the server seed, with the text snapshot sent on push:
  [Respondent Consent Notice](respondent-consent-notice-draft.md) "Standalone
  notice". A missing or unusable bundled notice behaves like no notice:
  covered fields stay locked empty, never "consent off".
- **SmartVA offline is out of scope for now (owner decision 2026-10-27,
  `digitva-5bzf`).** No SmartVA runs on a standalone phone, and the app says
  so. The profile's HIV and malaria mortality levels are collected for a later
  SmartVA build and are unused until then.
- **Plus-only.** Everything here requires the Plus variant on Android
  (arm64); the plain build is unchanged.

#### Export and backup (owner decision 2026-10-27, `digitva-5bzf`)

These two acts are allowed on a standalone account. On an enrolled,
non-standalone account they are off (so "the device is not an archive" stays
true for Path B) unless a later decision lets a project enable them (open
point 4). Neither is automatic, neither goes to a cloud service by the app,
and each is recorded in the on-device log as a kind and a count, never content.

**Export of your own records.** The user exports their own records as **CSV
or JSON**, one record or a chosen set, through the share sheet.

- *Included:* the interview answers, the consent record (decision, purposes,
  notice version and hash, mode, time), the offline coding result with its
  provenance (device UUID, pack and engine versions, process token), and the
  profile snapshot used at the time.
- *Excluded:* audio and document images (they are in the backup only), the
  PIN, the store secret and any key, the backup passphrase, and any other
  account's data. Aadhaar and VID are already reduced at capture and never
  re-expanded.
- *Identifiers:* the user may choose "omit identifiers", which strips the
  personal-field registry fields (`app/services/pii_field_registry.py`) and
  the consent notice's covered fields. Whether that option is on by default is
  open point 5.
- *Handling:* an export is plaintext by nature, like a printout. The app
  confirms with a message naming the personal data it contains, writes the file
  only to its private cache, deletes it when the share ends, and never
  writes to shared storage on its own.

**Encrypted backup.** One file holding the whole store (interviews,
attachments, coding results, consent records, profile).

- *Passphrase:* a **user-chosen** passphrase of at least 12 characters, not
  the PIN, set at each backup. **There is no recovery**: the app, the owner
  and the server cannot open a backup whose passphrase is lost.
- *Format:* the store re-keyed under that passphrase with SQLCipher's own key
  derivation at a high iteration count (so no new format or KDF dependency).
  A copied live database file is useless on another phone, because its key is
  Keystore-bound; the backup is not. The exact export call is confirmed by
  an early spike (plan section 10) before the slice is built.
- *Saved* through the **share sheet** only. The app does not pick a folder
  and never uploads.
- *Restore* works on the same or a new Collect Plus phone, into an unlocked
  store, in one transaction: it needs the passphrase, imports rows whose ids do
  not already exist (existing ids are skipped, never overwritten) and marks
  each restored row with the backup's device UUID so the server can detect the
  same interview arriving from two phones. A restore never deletes anything.
  The app offers "back up only what is not yet sent" and says that restoring
  already-acknowledged cases is pointless.
- *Warning shown before every export and backup:* "This file contains
  names, phone numbers, addresses and the stories of real people. Anyone who
  has the file and (for a backup) the passphrase can read it. Save it only
  where you control access. Do not send it by WhatsApp, e-mail or any chat
  app. If you lose the passphrase, nothing can recover the backup. The wipe
  after five wrong PINs does not protect a file you have already saved."

#### Path C open points

1. Number of days for the standalone age warning and the backup reminder.
2. Which organisation level the profile's optional org code names.
3. Whether a standalone user may keep acknowledged records instead of the
   Path B purge.
4. Whether a project may enable export and backup for enrolled accounts.
5. Whether "omit identifiers" is on by default for an export.

### Pre-release builds

Until decision C4 is settled the app is built unsigned, for development only.
A debug-signed build is signed with a well-known shared key, so any party can
produce an update that replaces it. **Debug builds must not be used to collect
real interviews**, and must be pointed at a non-production DigitVA.

## Phone clock

Owner decision 2026-10-23 (digitva-ltqg). A wrong phone date breaks
date checks ("not in the future", the 1 July rule, age from dates), the
interview start and end times and session expiry, so the phone checks its
clock against the server.

- **Measuring.** On each sync the phone compares its clock with the `Date`
  header of a server response (every response carries one) and keeps the
  difference, phone minus server. Offline it uses the last measured
  difference; a phone that has never synced is not judged.
- **5 minutes to 4 hours off:** a persistent warning with a button to the
  phone's Date & time settings ("set to automatic").
- **More than 4 hours off: no data entry.** No new registration or
  interview and no editing of drafts or revisions until the clock is fixed and
  a re-check passes. Viewing, Send now / Refresh (which re-measures),
  Settings and Export errors still work. If this is detected while a form is
  open, what was typed is saved first; nothing is lost.
- **On the server.** Uploads may carry `draft.clockOffsetSeconds` (integer,
  phone minus server; clamped to ±366 days, a non-integer is refused). The
  server stores it in the draft meta and marks the upload `clockSuspect` when
  the offset exceeds 4 hours or `startedAt` / `completedAt` is more than
  10 minutes ahead of the server. Such uploads are kept, never refused;
  coders and supervisors see `device_clock_offset_seconds` and
  `device_clock_suspect` with the submission.

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

## Collect Plus (experimental)

"DigitVA Collect Plus" (`APP_VARIANT=plus`, Android package
`com.causeofdeathindia.digitvacollect.plus`, versionName `<version>-plus`) is a
build variant of the collect app that also enables the native Coding, Review and
case-workspace screens and carries the offline WHO ICD-11 / DORIS engine from the
owner's private spike (`private/icd11-offline-spike`, never committed). It exists
to profile coding on a phone (bead digitva-hs7e).

- **Experimental, not for interviewers.** (Unchanged by Path C: a standalone
  phone is an owner-controlled pilot phone, owner decision 2026-10-27,
  `digitva-5bzf`.) It is never uploaded to `/download/android`,
  never pinned in `docker-compose.yml`, and never handed to interviewers. Since the
  owner's decision of 2026-10-25 it may be published as a public GitHub prerelease
  (`collect-plus-release.yml`, arm64 only) and its engine as a release asset
  (`icd11-engine-<version>`); the ICD-11 licence ruling (2026-10-21) and its
  obligations are in `docs/policy/icd11-local-api-runtime.md`. Builds run only on
  GitHub Actions.
- It installs beside the plain app and shares nothing with it: another package,
  another encrypted store, another URL scheme (`digitvacollectplus`).
- The plain build is unchanged: it has no engine, no engine assets and no module
  code, and its coding routes still explain that coding is done on the web.
- Connected (enrolled) coding screens still call the server for DORIS; the
  offline engine is exercised by the hidden Settings > "Offline engine check"
  screen and, on a standalone phone (Path C), by on-device coding with the
  same ICD-11 allowability rules as the server
  ([DORIS COD Workflow Policy](doris-cod-workflow.md) "Collect Plus offline
  parity"). Amended 2026-10-27 (`digitva-5bzf`): this replaces "Phase A coding
  screens still call the server for DORIS". The masking rules above apply
  unchanged to the connected coding screens.

## Phone numbers

Informant phones (`informant_phone`, optional `informant_phone_2`) are exactly
10 digits with no country code and no restriction on the first digit, shown
3-3-4 ("987 654 3210") and stored and sent as the plain 10 digits; a leading
`+91`, `91` or `0` is dropped from a pasted number when 10 digits remain. The
server is authoritative (the same validation error as the other
registration fields, no new error code) and validates a phone on an edit only when the edit changes it, so an older
non-conforming stored value never blocks an unrelated correction.

Age information (owner, 2026-10-20). A registration carries a date of birth
(exact date, month and year, or year only) or, when "Date of birth unknown" is
chosen, an estimated `age_years`. Both clients mark the field required (Date of
birth *, or Estimated age * under unknown) and block the save with an inline
message; the server is authoritative with the same validation error as the other
registration fields, on create and on edit. An edit is checked only when it
changes `date_of_birth`, `date_of_birth_partial` or `age_years`, so an older row
holding none of them (or an ODK-sourced or direct-start case) stays editable while
they are untouched; clearing them on a row that had one is refused.

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
| C5 | Standalone Collect Plus (Path C) | **Decided 2026-10-27** (`digitva-5bzf`): owner-controlled pilot phones only; no retention ceiling with age warning and backup reminders; SmartVA offline out of scope. Open points listed under Path C |

## References

- [Web Intake Policy](web-intake.md)
- [Interview Revisions Policy](interview-revisions.md)
- [Organization Model Policy](organization-model.md)
- [Offline API Contract](offline-api-contract.md) (standalone push, section 17)
- [Respondent Consent Notice](respondent-consent-notice-draft.md) (standalone notice)
- [DORIS COD Workflow Policy](doris-cod-workflow.md) (offline parity)
- [Access Control Model](access-control-model.md)
- [Attachment Storage Policy](attachment-storage.md)
- `docs/planning/who-va-2022-web-intake-plan.md`
