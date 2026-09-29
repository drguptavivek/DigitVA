---
title: Field Data Collection Policy (paths, device data, encryption)
doc_type: policy
status: draft
owner: engineering
last_updated: 2026-09-30
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
  `/intake/api/...`. See [Web Intake Policy](web-intake.md).
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
- **Interviewer sign-in** uses the account's password and, when the account
  has factors, a TOTP or recovery code
  ([Authentication Factors](authentication-factors.md)); a device session
  requires an active `interviewer` grant in the enrolled project, checked
  again at every refresh.
- **Tokens**: opaque, stored hashed; access 15 minutes; refresh rotated on
  every use and presented with the device secret; reuse of a retired refresh
  token revokes the session. Proposed C1: refresh lifetime 30 days, sliding,
  and (proposed addition) at most 90 days from sign-in, after which the
  interviewer signs in again. Expiry never loses data (the store is keyed by
  the PIN).
- **Only revocation wipes.** The app wipes an interviewer's store only when
  the server answers `session_revoked`, which it sends only for an
  administrative or device revoke or a withdrawn grant. A password or factor
  reset, a deactivated account or a closed project answers `session_ended`:
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
device revoke, bootstrap, idempotent upload with the superseded-copy path,
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
from the device API. **Not built** (phase 2b): encryption at rest, PIN,
biometric, auto-lock, secure screens, failed-PIN wipe; until then debug
builds must not collect real interviews.

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
- [Organization Model Policy](organization-model.md)
- [Access Control Model](access-control-model.md)
- [Attachment Storage Policy](attachment-storage.md)
- `docs/planning/who-va-2022-web-intake-plan.md`
