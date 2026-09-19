---
title: Field Data Collection Policy (paths, device data, encryption)
doc_type: policy
status: draft
owner: engineering
last_updated: 2026-09-18
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
| C1 | Device credential lifetime and refresh-rotation interval | **Open.** Sharpened by C2: the credential is per (device, interviewer), so a lifetime long enough for a multi-day offline circuit sits on a handset other people also use |
| C2 | One device per interviewer, or shared? | **Decided 2026-09-18:** shared, with one encrypted store per interviewer |
| C3 | Retention ceiling for an unsent interview | **Decided 2026-09-18:** no ceiling; purge only after a confirmed push. Accepted risk recorded above |
| C4 | Distribution and signing-key custody | **Deferred 2026-09-18:** unsigned development builds for now; must be settled before the app collects real interviews |

## References

- [Web Intake Policy](web-intake.md)
- [Organization Model Policy](organization-model.md)
- [Access Control Model](access-control-model.md)
- [Attachment Storage Policy](attachment-storage.md)
- `docs/planning/who-va-2022-web-intake-plan.md`
