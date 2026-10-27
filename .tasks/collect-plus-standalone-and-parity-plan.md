# Collect and Collect Plus: standalone mode, post-enrolment push and parity

Status: plan (read-only analysis, nothing implemented)
Priority: P1/P2 (beads `digitva-tb0j`, `digitva-zjqq`, `digitva-r9lk`, `digitva-athy`, `digitva-sxg9`)
Created: 2026-10-27
Owner request: 2026-10-27 (seven items)
Baseline: HEAD `510cbe0e0`, migration head `a9e4c7f2b3d6` (verified: the newest file in `migrations/versions`, nothing chains on it).
Re-run `flask db heads` before every migration slice.

Paths are repo-relative. App root is `mobile/digitva-collect` (written `app/`-free below as `mc/`).
`mc/` = `mobile/digitva-collect/`.

## 0. The finding that reshapes the request

**Standalone mode is not reachable today.** Commit `e59273d7e` ("pure offline coding") built the *parts* (device UUID, offline
profile, `offline_coding` table, on-device DORIS screen) but all of them sit behind a server enrolment and a server account:

1. `mc/src/nativeRoutes/index.tsx:19`: no `device` record redirects to `/enrol`. `mc/src/nativeRoutes/enrol.tsx` offers QR scan or
   "Try the demo" only. There is no "work without a server" choice. `device` is written only by `storeEnrolment`
   (`mc/src/auth.ts:240` `enrolDevice`, `:321` `redeemSignInQr`, demo enrol).
2. `mc/src/nativeRoutes/offlineCoding.native.tsx:42-48` (`useOfflineUserId`) reads `accounts` from `AppState`. `accounts` is written
   only by `storeSession` (`mc/src/auth.ts:337`) after a server sign-in. No account means no `userId`, so no
   `openInterviewerDb` (`mc/src/interviewerDb.ts:56`, store keyed by user id hash `vault.ts:56`), so no offline coding.
3. `mc/src/nativeRoutes/form.tsx:520-640` builds an interview from a `project` taken from the server reference pack
   (`configFromReference(project)`, `project.form_options`), so even the bundled-form fallback
   (`formDefinitionRuntime.ts:136,192`) needs a cached server project.
4. Consent for an interview comes from the cached server config (`mc/src/consentStore.ts:46-83`), with no fallback by design.

What "pure offline" therefore means today is: *an enrolled, signed-in interviewer whose phone happens to be offline can finish an interview
and code it on-device*. The owner's "Collect Plus with no server, an offline profile" needs a new entry flow, a local account/store
key and a project-less (or local-project) interview path. That is slice S4 and it gates items 3 and 4.

Second finding: **nothing on the server accepts an offline-coded case.** `/coding/finalize` requires an allocation and a server-issued
DORIS process token (`app/services/coder_cod_service.py:355-390`, `verify_doris_submission`); the station bundle path
(`app/services/bundle_ingest_service.py:1160-1205`, `_station_doris_fields`) *re-runs DORIS on the server*, which the owner excluded
on 2026-10-26. Item 3 needs a new acceptance contract and a policy decision first.

Third: **the post-enrolment push would lose offline coding** with today's sync. `deleteDraftSnapshot` (`mc/src/drafts.ts:702-710`) deletes
the draft, its consent keys and attachments on server ack, but never the `offline_coding` row, and nothing sends that row. Turning
sync on for an enrolled Plus device today uploads and purges the interview and orphans (or, after a store wipe, destroys) the coding.

## 1. Registered user QR (enrol a registered user or device)

### Already built
- Device-only enrolment QR: payload `{"v":1,"server","enroll","project"}`, parser `mc/src/enrolment.ts:123` (`parseEnrolmentQr`), server
  allow-rule `:79` (`acceptedServerOrigin`), combined parser `:156` (`parseScannedQr`, kinds `enroll` and `sign_in`).
- Registered-user sign-in QR (one scan enrols the device and signs the person in): policy `docs/policy/mobile-sign-in.md` section 8;
  server `app/services/sign_in_qr_service.py`, `app/routes/api/auth.py:180` (`redeem_sign_in_qr`), table `auth_sign_in_tokens`
  (`app/models/auth_devices.py:179`); Users-page issue/status/revoke dialogs `mc/src/web/UsersDialogs.tsx`, `POST /api/v1/users/<id>/sign-in-qr`;
  phone `mc/src/nativeRoutes/enrol.tsx:47-63` + `mc/src/auth.ts:321`. Tests: `tests/routes/test_sign_in_qr.py`,
  `mc/__tests__/enrol-sign-in-qr.test.tsx`, `enrolment.test.ts`.
- Device rows: `AuthDevice` (`app/models/auth_devices.py:50-92`): `project_id` NOT NULL, `enrolled_via`, `enrolled_via_sign_in_token`,
  signing key columns. Enrolment body sends only `code`, `device_name`, `platform`, `app_version` (`auth.ts:245-251`).

### Missing
| Layer | Gap |
|---|---|
| App | Enrol/sign-in redeem must carry the local `device_uuid` (`mc/src/offlineIdentity.ts:58`) on Plus. A "scan a user QR" entry on the Add interviewer path of an already-enrolled device (today only Settings re-enrol, `settings.tsx:119`, reaches `/enrol`). Adoption of a standalone store (S4) at redeem time. Verify multi-project behaviour: redeem on an enrolled device calls `storeEnrolment`, which replaces the single `device` record (`device.project_id` is singular). |
| Backend API | `POST /auth/enroll` and `/auth/sign-in-qr/redeem` accept an optional `client_device_uuid`; store and echo it. Idempotent re-enrol of the same uuid must not create a second device row. |
| Vendor | None. |
| Migration | Yes (S3): nullable `auth_devices.client_device_uuid` UUID, partial unique index where not null; additive, reversible. Chains on `a9e4c7f2b3d6`. |
| Eligibility gap (decision) | The sign-in QR is refused for anyone holding a coder grant (policy section 8 "Who"). A standalone user who also codes will normally hold `coder`/`self-coding` grants, so they get the enrolment QR plus password only. Push of coding (item 3) additionally needs a coding-capable grant. Decide: keep as is, or allow sign-in QR for self-coding grants. Needs a policy edit to `mobile-sign-in.md` section 8 first. |

### Policy status
Covered for user and device QR (`mobile-sign-in.md` sections 7-8). Not covered: binding a pre-existing local device identity to the server row, and the
coder exclusion for a Plus phone. Baseline needed in `docs/policy/mobile-sign-in.md` (new section 8.x) and `docs/policy/field-data-collection.md` (Collect Plus).

### Risks
- A stranger redeeming an unredeemed user QR first inherits the **standalone data** if adoption is automatic. Adoption must be an explicit, PIN-confirmed step that shows counts, never silent.
- Binding the uuid is an identity claim by the client; the server must treat it as provenance, not authentication (the bearer remains the credential).
- Re-enrol on an enrolled device today asks for confirmation (`reEnrolConfirm.ts`) and may wipe; make sure it cannot wipe a standalone store with unsent work (the existing unsent-work guard `interviewerDb.ts:69` counts drafts but not `offline_coding` rows).

## 2. Standalone mode onboarding (Collect Plus, no server, offline profile)

### Already built
- Device identity: `mc/src/offlineIdentity.ts:58-74` (Plus + Android gate, single-flight mint, SecureStore `offline_device_identity`). Test `__tests__/offlineIdentity.test.ts`.
- Offline profile: `mc/src/offlineProfile.ts:14-30` (fields), `:80` (`getOfflineProfile`), `:97` (`saveOfflineProfile`, name and country required); screen
  `mc/src/nativeRoutes/offlineProfile.native.tsx` with `.web` twin; Settings entry `settings.tsx:213`. Test `offline-profile.test.ts`.
- `offline_coding` table + accessors: `mc/src/drafts.ts:380-398` (DDL), `:856-927` (save/list/get/delete/case readers).
- On-device DORIS screen: `offlineCoding.native.tsx` (list, case, `offlineWorkspaceApi` that refuses every server call, `:64-72` save context), `mc/src/workspace/offlineDoris.ts`
  (editor, search/codeinfo mapping `:165-194`, certificate seed `:345-387`). Engine: `mc/src/offlineEngine.ts`, `mc/modules/digitva-icd11`.
- Per-interviewer SQLCipher store, PIN, lock, wipe: `mc/src/interviewerDb.ts`, `mc/src/vault.ts`.
- Bundled WHO form fallback: `formDefinitionRuntime.ts:136,192`, `form.tsx:577` `createWhoVa2022Instrument(extensions)`.

### Missing
| Layer | Gap |
|---|---|
| App: entry | A "Use without a server" choice on `/enrol` (Plus only; plain build must not show it). First-run setup: profile (name, country, org), PIN, store creation. |
| App: local account | A synthetic local account (id derived from the device uuid, `kind: "standalone"`) so `accounts`, `openInterviewerDb`, unlock, PIN, auto-lock, biometric all work unchanged. `Account` (`auth.ts:44`) needs a `standalone` flag; `refreshAccessSummary`, token refresh, notification poll and `syncAccount` must skip it. |
| App: local project | A synthetic "standalone project" reference pack: sites/units (one local site, optional unit from profile), `form_options` with the extension set the standalone user picked (default none; equity optional), `narration_languages`, `requires_death_register=false` (direct interviews only), consent block (below), prefill policy defaults. `form.tsx:520-640` and `reference` loading (`sync.ts:988-1110`) must read it instead of the server. |
| App: gates | Plus-only everywhere. The Home redirect `index.tsx:19`, the clock check (`phoneClock.ts`, measures against server `Date`; a never-synced phone "is not judged", so a wrong phone clock silently writes wrong interview times offline: add a standalone warning). |
| App: SmartVA | On-device SmartVA does not exist (the Rust `desktop/crates/digitva-smartva` is desktop-only, no Android build). The profile collects HIV and malaria levels (`offlineProfile.ts:25-26`) for nothing yet. Say so in the UI, or plan a JNI build as a separate project (out of this plan). |
| Backend API | None for onboarding itself. |
| Vendor | None for core. The bundled instrument has no server-composed DigitVA geography/consent/outcome items; confirm which `ALL_DIGITVA_EXTENSIONS` subset the standalone form uses and that `interview_outcome`/consent-gate questions (server-injected today per `digitva-c48`) exist in the bundled composition. |
| Migration | None (the on-device store gets an additive `migrate()` step in `drafts.ts`). |

### Policy status
**Policy baseline needed first.** `docs/policy/field-data-collection.md` "Collect Plus (experimental)" (line ~628) still says "Phase A coding screens still call the server for DORIS" and
"never handed to interviewers". Path B says "the device keeps only in-flight interviews ... is not an archive" and "revocable device sessions". Standalone mode is a third arrangement:
an unenrolled device that keeps interviews and codings indefinitely, with no server revocation. The file itself says any third arrangement requires the policy to be amended first.
Add a "Path C: standalone Collect Plus" section covering: who may install (owner-controlled pilot only?), retention (no ceiling vs a user-visible reminder), data at rest
(same SQLCipher per user), no remote wipe, device-loss accepted risk, no masking offline (already decided 2026-10-26), profile contents, local clock risk. Also update
`docs/current-state/expo-client.md` "Pure offline mode" and `docs/policy/offline-api-contract.md` section 10 ("Station modes and data protection") with a pointer.

### Risks
- **No revocation, no outstanding report.** Server cannot know what a lost standalone phone holds. Accept explicitly in policy; mitigate with a PIN wipe after N failures (already `WIPE_AFTER_FAILURES=5`), FLAG_SECURE (exists), and an export/backup reminder.
- **Data loss on uninstall/clear data.** `allowBackup:false` and a Keystore-bound store secret mean an uninstall destroys the only copy. This is why item 4 is part of the safety case, not a convenience.
- `drafts.ts:371-374` deletes `cases WHERE project_id IS NULL` at every store open; harmless for `drafts`, but the standalone project must have a non-null project id or any case-like standalone rows would be deleted.
- Profile is PII (coder name, age, sex, facility) kept in SecureStore (`offline_profile`); it is not in the SQLCipher store, so a store export would not carry it, and SecureStore has a ~2 KB value limit. Keep the profile small or move it into `meta`.
- Plus is arm64-only, a ~800 MB engine process (`expo-client.md` Collect Plus), CI-built, debug-signed locally: standalone cannot target the plain build.
- Pilot gating: the plan assumes owner-controlled devices because Plus is "never handed to interviewers" (policy).

## 3. Posting standalone submissions after onboarding (`digitva-tb0j`)

### Already built
- Idempotent interview upload on `client_draft_id`: `POST /api/v1/intake/submissions` (`app/routes/api/intake.py:1030`), sender `mc/src/sync.ts:396-516`, contract
  `docs/current-state/device-collection-api.md` "Uploads", including answers hash (`answers_sha256`), later-version-wins, `superseded`, `kept`, definition identity fields.
- Direct-start drafts and attachments: `device-collection-api.md` "Direct start with attachments" (`POST /intake/drafts`, `PUT .../attachments/<id>`).
- Routing: `docs/policy/organization-model.md:838-886`: routing is by `org_<level>_code` in the payload, else the form mapping fallback, else the project's **unrouted queue**
  (data managers see it and may pin); `va_submissions.org_unit_resolution`. So the "unrouted group" already exists; no new server concept.
- Consent on upload: `consent` object on `/submissions` (offline-api-contract.md section 5.3; server checks `consent_required`, `consent_invalid`).
- Provenance fields on the phone: `offline_coding.device_uuid`, `coder_profile_updated_at`, `process_token local-<uuid>` (`drafts.ts:380-398`).

### Missing
| Layer | Gap |
|---|---|
| App | (a) Post-enrol *adoption*: map the standalone local account to the redeemed server account (re-key `drafts`/`offline_coding`/`attachments` rows to the account's store, or send from the standalone store as the account). (b) Assign project/site/unit: the QR names the project; choose site and unit (picker) or derive from profile org code. (c) Stamp `org_<level>_code` answers from that choice so server routing applies. (d) New sender for offline coding rows. (e) **Ack-ordering fix**: send coding before or with the interview and delete the `offline_coding` row with the draft in `deleteDraftSnapshot` (`drafts.ts:702`). (f) Count `offline_coding` in `unsentWork`/`countUnsentWork` so sign-out and re-enrol warn. (g) Bind `answers_sha256` to the coding row (the table has none, `drafts.ts:380`): reopening or editing a coded draft (`reopenDraft` `drafts.ts:622`) must mark the coding stale, or a stale DORIS result is posted for changed answers. (h) Profile org code field (see below). |
| Backend API | New contract (proposal, to be fixed in policy first): `POST /api/v1/intake/submissions` gains an optional `offline_coding` object (same call, so interview and coding commit atomically and idempotently on `client_draft_id`), or a sibling `POST /api/v1/coding/offline-results`. Server stores the result as an **imported** final with `coding_origin = collect_plus_offline`, `device_uuid`, `coder_profile` snapshot (name, designation, facility, country), `process_token` as opaque provenance, **no DORIS re-run**. Server still applies the cheap, deterministic allowability rules (chapter 22 block, sex block, age flag, primary stem, bucket mapping) because reports (`submission_analytics_mv.py`, migration `c5e8a2f4b7d1`) assume them; a rejected offline code lands as "needs coder review", never dropped. Workflow state after import is a policy decision (coded and skip review? coded pending reviewer?). Enrolment must record the claim (`client_device_uuid`, S3). |
| Vendor | None. |
| Migration | Yes (S5): provenance on the coded result (e.g. `coding_origin`, `client_device_uuid`, `coder_profile` JSONB) on the final-assessment table or a `map_offline_coding_import` table keyed by `va_sid`; unique `(client_device_uuid, client_draft_id)`; additive. Chains after S3's revision. Also possibly an "unrouted standalone" tag column for the DM queue filter. |

### Policy status
**Policy baseline needed first**, in `docs/policy/offline-api-contract.md` (new section "Standalone push", status proposed) and `docs/policy/coding-workflow-state-machine.md`
(imported final: state, who may recode, reviewer sampling, KPIs `digitva-r5s0`). `docs/policy/interview-revisions.md` also needs one rule: a later resend with changed answers after an offline-coded import is
history-only (it already is for finished coding: "Coding finished ... history only, `kept: server`, `locked: true`"). Routing rule needs no change; only a statement that standalone
org codes are claims, validated against the project tree like any payload. The bead's two statements ("org-match routing" and "unrouted group") map to existing behaviour; record that.

### Risks (duplicates, PII, integrity)
- **Duplicate submissions.** Same interview posted twice (retry, two phones restored from backup, a re-import). Idempotency key is `client_draft_id` plus the answers hash: keep it, and add `client_device_uuid` to the server uniqueness. A restored backup on a *second* phone reuses draft ids: the server must treat same `client_draft_id` + different `client_device_uuid` as a conflict (409), not a new case.
- **Duplicate deaths.** Standalone interviews have no death register; the same death may already be on the server (registered by a death reporter, or interviewed by another phone). Rely on the existing duplicate machinery (`va_duplicate`, possible-duplicates by identifiers); do not auto-merge. Standalone interviews must carry the identifier fields the matcher uses.
- **Locked prefill overwrites.** The server overwrites interviewer identity, area presets and ABHA from its prefill policy (`device-collection-api.md` "Locked answers"). A standalone interview filled under a *different* identity loses that attribution; keep the profile snapshot in provenance.
- **Stale coding.** See (g) above; also verify `coded_answers_sha256` on the server against the stored answers (`offline-bundle-and-transfer.md` 5.5 uses the same idea).
- **Org code trust.** A free-text facility cannot route. The profile needs an optional org code (new field, not the free-text `facility_name`); an unmatched code goes to the unrouted queue, never guessed.
- **Consent attached to the interview.** See item 6; a consent referencing an unknown notice version fails the whole interview with `consent_invalid` (422) and the phone `reopenDraft`s it (`sync.ts` 422 branch), looping the user. Make the failure terminal and visible instead.
- **Bulk upload load.** A standalone phone may hold hundreds of interviews and audio; keep one interview per request, resumable, with backoff (the existing per-draft loop already does this); attachments ride the existing per-file PUT.
- **Engine versions.** The result records `engine`/WHO file hashes (`who-files.json`) so a future audit can explain parity differences; server DORIS 1.1.176 and phone must match (handoff, `digitva-hs7e` progress).

## 4. Exports and database backups in standalone mode

### Already built
- Only the error-log export: `mc/src/errorExport.ts` (React Native `Share` of a text body; no file, no zip package). Policy `docs/policy/expo-client.md:217-260`.
- Encrypted store: `interviewerDb.ts`, `vault.ts` (SQLCipher key = Keystore secret + PIN; attachments are BLOB rows in the same DB, `attachmentStore.ts:1-8`, so one DB file holds everything).
- `allowBackup:false` and `fullBackupContent`/`dataExtractionRules` (`mc/app.json:67`, generated manifest). Policy `docs/policy/phone-attachments.md:72`.
- Server-side export policies for comparison: `docs/policy/data-management-cod-snapshot-export.md`, de-identified research export `digitva-fx2c`.
- Dependencies available: `expo-file-system`, `expo-document-picker`, `expo-crypto` (digest/random only). **Not** installed: `expo-sharing`, any zip or KDF (PBKDF2/Argon2) library.

### Missing
| Layer | Gap |
|---|---|
| App | (1) *Per-record export*: one interview (answers, consent record, DORIS result) as JSON/CSV/PDF. (2) *Backup*: a portable encrypted archive of the whole store (drafts, attachments, `offline_coding`, consent keys, profile). (3) *Restore* from a backup on the same or a new phone, with duplicate-id handling. (4) Delivery: share sheet vs user-picked folder (SAF) vs USB (`adb`). (5) Reminder UX (days since last backup, count unbacked). |
| Backend API | None required (restore is local). A server-side "backup received" is explicitly not planned. |
| Vendor | None. |
| Migration | None server-side. On-device store version bump if a `last_backup_at` meta key is added (meta, no DDL). |

### Design constraints (proposal)
- **A copied `.db` file is useless on another phone.** The SQLCipher key is `store_secret:PIN` and the secret is Keystore-bound (`THIS_DEVICE_ONLY`). A backup therefore re-keys: `ATTACH DATABASE <file> AS bak KEY '<backup passphrase>'; SELECT sqlcipher_export('bak')`, producing a SQLCipher file under a **user-chosen backup passphrase** (strong, 12+ chars, not the PIN), with SQLCipher's own PBKDF2 (no new KDF dependency; set `cipher_kdf_iter` high). A restore `ATTACH`es it with the passphrase and imports rows into the unlocked store inside a transaction. This reuses the code path that is already tested for SQLCipher, avoids inventing a file format, and keeps attachments inside.
- Per-record export is **plaintext by nature** (PDF/CSV). Treat it like a printout: confirm dialog naming PII, optional "omit identifiers" (strip `INFORMANT_PII_FIELDS` and covered fields), no auto-share, file written to app cache and deleted after the share, never to shared storage without the user choosing a destination.
- No new native module is required for `Share` of text, but sharing a **file** on Android needs one (`expo-sharing`, or SAF via `expo-file-system`). That is an APK rebuild on CI, and `make check-web` must still pass (web twin must no-op).

### Policy status
**Policy baseline needed first.** `field-data-collection.md` forbids a device archive ("not an archive", "push and purge") and `phone-attachments.md` says backups are off. Add to the Path C section: backup is user-initiated only,
passphrase-encrypted, never to cloud by the app; per-record export is an authorised act of the interviewer on their own data; retention of exported files is the user's; logging of export events (count, kind, no content) in the on-device error/audit log; export is disabled on enrolled, non-standalone accounts unless the project allows it (so the "device is not an archive" rule stays true for enrolled use).
Also decide with the DPDP/consent text: informant PII leaving the app via export needs the notice to say so (`respondent-consent-notice-draft.md`, covered fields / purposes).

### Risks
- **PII in exports and backups** is the main exposure: names, phones, addresses, narratives, audio, images. Passphrase loss means total loss (no recovery by design). Weak passphrase means brute-forceable archive: enforce length and rely on high KDF iterations.
- Backup to a shared/Downloads location is readable by other apps and the Files UI; prefer SAF folder chosen by the user or the share sheet to a trusted target. Warn about WhatsApp/email attachments (retention outside any control).
- Restore creates **duplicates** if the source phone is also alive or already pushed. Rows carry draft ids; on restore skip ids that exist; mark restored rows `restored_from` with the backup's device uuid so the push contract (item 3) can detect cross-device conflicts.
- A backup taken *after* a push is stale data of already-acknowledged cases; offer "back up only unsent" and warn that restoring acknowledged cases is pointless.
- Wipe-after-5-failures protects the live store but not an exported backup: say so in the UI.
- `adb` backup is off; USB pull of the app-private DB fails by design; keep that.

## 5. DigitVA form extensions (`digitva-r9lk` and others)

### Status of each extension bead
| Bead | State | Notes for the apps |
|---|---|---|
| `digitva-r9lk` equity layer | **Policy complete, zero code.** `docs/policy/digitva-who-form-overrides.md:89-282` (residence_type, social_group, vulnerable_group, health_coverage, refusal profile, DHS alignment, placement and own gate); `va-web-form-options.md:43,182-184`; `va-form-project-configuration.md:388`. No `equity` in `ALL_DIGITVA_EXTENSIONS` (`vendor/who-va-2022/src/digitva-extension.ts:34-54`), no `web_intake_equity_enabled` in `app/` or `migrations/`, no `residence_type` anywhere in code. | Served to Collect by definition, **no app build needed** if no new control type is required (confirm `select_multiple` with exclusive `none/dk/ref` choices in the engine; otherwise an engine change and app build). Plus standalone needs the layer in its **bundled** instrument. |
| `digitva-rou1` project country | Landed (`9850711d4`), bead still open. | Equity's country choice sets (India NFHS vs default) depend on it. Standalone has only the free-text profile country; map to ISO3 (needed for SmartVA too). |
| `digitva-v1oi` geography/area_type | Open, policy in `organization-model.md`. | Equity reports fall back to unit `area_type`; not an app change. |
| `digitva-1835` DHS links, `digitva-6383`, `digitva-lep4` | Open, backend only. | No app work. |
| `digitva-bx43` DORIS preflight hints | Open, discuss first. | Would add on-device hint logic only after owner agrees. |
| `digitva-sxg9` narrative AI | Policy draft awaiting owner sign-off; consent item 7 adopted. | Touches consent (item 6) only. |
| `digitva-zfsa` | Open P3: desktop crate `digitva-db` pins served-definition sha after 2026-10-24 form changes. | Adding `equity` changes the composed hash again: the desktop station pins break too. Add to the equity slice's checklist. |
| `digitva-fb5` translation label bugs | Open P1 (served now to Odia/Kannada). | Equity adds EN+HI strings; fb5 is a reminder that new labels must be checked per language before activation. |
| `digitva-zkgx` | Open: questionnaire locales filtered to UI_LOCALES (`mc/src/i18n.ts`). | Equity and any new question appear only in en/hi until this is fixed. |

### Missing for r9lk (split)
| Layer | Gap |
|---|---|
| Vendor form package | Add `equity` to the extension tuples (`:34-54`); emit `residence_type`, `social_group`, `vulnerable_group`, `health_coverage` after `Id10055`/`Id10053`/`Id10066`, the refusal profile after `Id10013 = no`, own gate (layer on and consented, **not** `Id10051`), age/sex filters via `isNeonatal/isChild/isAdult/Id10019` (or split to yes/no items if choice filtering is unsupported), EN+HI strings, `uiTranslations`; regenerate `src/generated`. Vitest in the package. |
| Backend API | `tooling/who-va-2022/build-composed-instrument.mjs` (32-subset check becomes 64), regenerate `app/data/who-va-2022.composed.json`; `served_form_service.py` tag set; `form_options.enabled_extensions` derivation from `web_intake_equity_enabled` (`app/models/va_project_master.py`, `web_intake_service.py`, `app/routes/admin.py`, `api/organization.py`, `public_demo_service.py`, `training_demo_service.py`, as `medical_records` does); Project Setup toggle `app/templates/admin/panels/projects.html`; analytics cube dims (refusal age group and sex; `<5` suppression); PII registry check (`app/services/pii_field_registry.py`: none of these are personal, state that); ODK form export (`digitva-aek`); country choice-set table (project country dependent); project label overrides. |
| App | Collect renders the served definition unchanged. Needs: bundled instrument rebuilt with the package; prefill of `refusal_age_group`/`refusal_sex` from the registered death (`mc/src/prefill.ts`, `registrationAgeText.ts`) for Collect's death-register path; Hindi strings only if any UI chrome is added; jest for the prefill. |
| Migration | Yes (S1): `va_project_master.web_intake_equity_enabled` boolean default false, and later `social_group` choice-set storage. Chains on `a9e4c7f2b3d6`. Must run `flask db heads` before and after. Dev serves the working tree, so the writer finishes with the dev upgrade (house rule). |

### Policy status
Equity: **policy exists** (owner decisions 2026-10-27, three sections). Open policy items inside it: legal basis for the refusal profile is flagged (`digitva-athy`), `social_group` list pending owner confirmation (bead note), `religion` excluded. Standalone adds one question not yet covered: which extensions a standalone user may enable (project switch does not exist offline). Record "standalone form = bundled instrument with extension set chosen in setup; default off; equity available" in the Path C section.

### Risks
- Changing the composed definition changes `definitionSha256` for every project slice: drafts stay pinned to their version (policy), but **a standalone draft pinned to the bundled version** must be resolvable by the server at push time (`mas_instrument_versions`, `GET /instruments/<code>/definition?version=&extensions=` serves historical slices). If the app is built from a package commit the server never recorded, the server cannot re-check the answers: add a CI check that the bundled version is registered, and make push fail visibly.
- Equity adds sensitive characteristics of the deceased (caste group, custody, gender minority). Optional, no free text, aggregate-only reporting is policy; in standalone the answers sit on a PIN-protected device and in exports, so exports must be able to omit them.
- Engine support for exclusive choices and per-choice relevance in `select_multiple` is unverified; check before building.

## 6. Consent (server changes, default seed item 7, standalone)

### Already built
- Server seed: `app/services/consent_notice_seed.py:83,92` (purpose `narrative_automated_processing`, EN/HI item 7, `required: False`); policy `docs/policy/respondent-consent-notice-draft.md:96-140,259` and `narrative-ai-processing.md:155-179`; commit `510cbe0e0`. Tests `tests/services/test_consent_notice_seed.py` (keeps seed equal to the draft).
- Consent config to the phone: `GET /api/v1/intake/consent-config` (`app/routes/api/intake.py:267`), contract `offline-api-contract.md` section 5; phone cache `mc/src/consentStore.ts:46-83`, gate `interviewConsentGate:78`, registration gate `:86`, panel `RespondentConsentPanel`, purpose parsing/normalising `mc/src/consent.ts:611` (generic over purpose codes, so item 7 renders without app code once the project's notice is re-seeded).
- Sandbox notice: `mc/src/consent.ts:268-376` (`sandboxProjectConsentConfig`, project `"1"` only; contract 5.6 forbids hardcoded config for provisioned projects). **`isSandboxProject`/`defaultProjectConsentConfig` have no caller outside `consent.ts`**; nothing in the screens uses the sandbox config.

### Missing
| Layer | Gap |
|---|---|
| App | (a) Enrolled phones: no code change, but verify that a notice version with 7 purposes and a `required:false` purpose the respondent refuses still yields `decision: granted` and that the per-purpose choices (including `narrative_automated_processing: false`) travel in `purposes` (jest on `buildSortedPurposeChoices`, `consent.ts:411`). (b) Standalone: a bundled notice, shown and hashed on the phone, recorded in a consent record. The existing sandbox notice has 5 purposes and **two codes that differ from the server seed** (`sms_whatsapp_messages` vs `messages`; `statistical_reports` vs `statistics_reports`) and no item 7. (c) `[ORGANISATION]`, `[PROJECT NAME]`, retention, DPO and contacts placeholders: the seed leaves them for the project (`consent_notice_seed.py` header), so a bundled text needs profile-fed fills, which changes the hash per deployment. |
| Backend API | A way to accept a standalone consent: either (A) server accepts a consent whose `notice_version_id` is a **registered platform standalone notice** (allowlist table of text hashes, platform-level `mas_*`), or (B) the push carries the **full notice text snapshot** and the server stores it as a new, source-flagged notice version (`standalone-<sha>`) scoped to the project, append-only. Today either fails with `consent_invalid` (unknown version, hash, purposes; offline-api-contract 5.3). Recommend (B) with an allowlist check of the template hash so unknown text is flagged, not silently trusted. Also: withdrawal for a pushed standalone consent works through the existing data-manager path; the phone cannot be told (no server link before enrolment). |
| Vendor | None. |
| Migration | Likely yes (S7/S5): notice-version `source` column (`project|standalone`) and a text snapshot path; additive. |

### Policy status
Server seed: **covered and adopted** (owner 2026-10-27; still needs legal and language review per the draft header). Narrative-AI withdrawal and leasing rules covered in `narrative-ai-processing.md`.
**Not covered: consent in standalone mode.** `offline-api-contract.md` 5.6 ("No silent fallback to hardcoded defaults", strict capture) contradicts a bundled notice. Needs a baseline in
`docs/policy/respondent-consent-notice-draft.md` (new "Standalone notice" section: who supplies the text, placeholder fills, language set, the seed hash, whether item 7 is offered in a standalone context where no server processing exists yet) and an amendment to `offline-api-contract.md` 5.6 stating the exception and the push-time validation. Legal review (`digitva-athy`) must cover: a notice that names an organisation and contacts who may not yet be reachable by the respondent, and whether narrative processing consent can be asked before a server exists (recommend: ask it, store it, default **no** when the standalone user is not yet enrolled to an organisation that runs the pipeline).

### Risks
- **Offline consent validity** is the largest legal risk of the whole plan: consent taken offline against text that the server never published cannot be re-collected from the respondent later. Store the exact text shown, its hash, language, mode, witness flag, time, device uuid and profile snapshot, and never edit it (append-only, supersede only).
- Purpose-code drift between the bundled notice and the seed makes server checks fail only at push time, months later. Generate the bundled notice **from** `consent_notice_seed.py` (a script plus a drift test), not by hand.
- A notice that says "Programs on systems controlled by [ORGANISATION] in India" must not claim processing that standalone data never receives until pushed; the text needs a standalone variant, or the purpose is hidden until enrolled (then it cannot be consented to retroactively). Owner/legal decision; record it, do not guess.
- Informant PII on the device before consent: the phone locks covered fields empty until consent (`unavailable` gate, `consentStore.ts:78`). In standalone, a missing bundled notice must behave the same (locked empty), never as "consent off".

## 7. SmartVA Step 1-2 display and DORIS fixes: parity in the apps, including the on-device engine

### What the server changed (commit `92f220c2f`)
Server rule code: `app/services/icd_coding_policy.py` (age/sex clauses `:92-129`, `AgeRestrictionConfirmationRequired:22`), `icd_coding_value.py` (`check_causing_condition_unknown:194`, `record_final_cod_flags:209`, `icd11_primary_stem_of:248`),
`icd11_mms_service.py`, `coder_cod_service.py` (age confirmation `:549-608`), `reviewer_coding_service.py`, data tables `mas_icd11_mms.is_coding_selectable/age_group_selectable/sex_selectable`
(policy artifact `resource/icd11_mms_2026_01_policy_signoff_2026_09_29.json`, 16,387 selectable items) changed by migrations `b8d4f2a6c1e9` (chapter 22 out, `KD3B.Z` in) and `c5e8a2f4b7d1` (bucket by primary stem of a `/` cluster). Web JS: `doris_clinical.js`, `doris_final_cod.js`, `digitva_icd11_picker.js?v=5`, `causing_condition_unknown` hidden field, `digitvaAgeRetry`.

### Already built in the apps
- Connected Expo coding (Plus, enrolled): `mc/src/workspace/doris/DorisPanel.tsx` now has `ageConfirm` dialog (`AGE_RESTRICTION_CONFIRMATION_REQUIRED`), `finalFlags` (`causing_condition_unknown`, `age_restriction_confirmed`), picker `causingConditionUnknown`, strings `ageRestriction*`/`ageGroup_*` in en/hi. Test `__tests__/workspace-doris.test.tsx`, `workspace-doris-picker.test.ts`. These work **only against the server**, which supplies the refusal and the allowability data.
- SmartVA display in connected Expo: `workspace/SmartVaReference.tsx`, `SmartvaStatusPanel.tsx`, `useSmartvaLifecycle.ts`, result card `645fd8527`. The ICD-10 to ICD-11 mapping beside SmartVA codes (`docs/policy/smartva-icd11-display.md`) is a server crosswalk.

### Missing (on-device path)
| Layer | Gap |
|---|---|
| App | Offline coding saves through `offlineWorkspaceApi.saveFinal` and the editor in `mc/src/workspace/offlineDoris.ts` with **none** of the allowability rules (no match for chapter, KD3B, sex or age logic in the file). Needed on device: (1) allowability data pack (code to selectable, sex, age group) loaded from a versioned asset; (2) chapter 22 and non-selectable rejection in search and save; (3) `KD3B.Z` allowed per policy; (4) sex block (refusal) and age block (confirm dialog, store who/when/DORIS warning in `offline_coding`); (5) primary-stem judgement of `/` clusters via on-device `codeinfo`, so the stored bucket stem equals the server's; (6) "Causing condition not known" in the picker bridge; (7) the DORIS-warning text the server records. A shared pure TS module `mc/src/workspace/icdAllowability.ts` with jest vectors generated from the server tests (`tests/services/test_masked_doris_coding.py`, `test_migrate_icd11_chapter_22_kd3b_z.py`, `tests/routes/test_coding_cod_api.py`). |
| Data | An export script (server side, read-only SELECT of the policy columns) that writes `mc/assets/icd11-allowability-<release>.json(.gz)` with a content hash and the migration revision; a pytest drift test asserts the committed pack equals the DB state at head (so a future policy migration cannot ship without a refreshed pack). Size must be measured (16k rows ~ hundreds of KB gzipped). The pack is part of the engine release asset or the app bundle: decide. |
| Backend API | The offline import (item 3) must re-apply the same rules (cheap, no WHO call) and record any disagreement; ingest service function reusing `icd_coding_policy` and `icd_coding_value`. |
| Vendor | None. |
| Migration | None for parity; the pack records the head revision it was generated from. |
| SmartVA | **No on-device SmartVA exists**; "Step 1-2" SmartVA display parity applies only to connected Collect Plus (already via the shared panel). For standalone, either show "SmartVA not available offline" or open a separate project to cross-compile `desktop/crates/digitva-smartva` for Android (+ WHO to PHMRC transform, tariff data, size). Not part of this plan; record it as a decision. The profile fields `hiv_mortality`/`malaria_mortality` are collected but unused until then. |

### Policy status
Server rules: **covered** (`who-2022-icd11-coding-allowability.md`, `icd11-code-selection-principles.md`, `icd11-cod-bucket-schemes.md`, `doris-cod-workflow.md`, updated in `92f220c2f`). Not covered: that the **offline engine must apply the same policy pack**, how drift is detected, and that offline results are re-checked on import. Add to `docs/policy/doris-cod-workflow.md` a "Collect Plus offline parity" section and a drift-test rule. `docs/current-state/expo-client.md` "Limits, accepted" (subtree search returns the flat list) must be revised once the pack exists, since the flat list is the case where chapter 22 shows up.

### Risks
- Engine drift: phone DORIS 1.1.176 vs server (handoff pins 1.1.176; move both together). Record the engine/WHO file hashes with each saved result.
- Local digests are integrity markers, not WHO canonical digests (accepted); keep them out of any server verification.
- Offline search returning the flat MMS list (`expo-client.md` accepted limit) could surface non-selectable codes; the pack filters results client-side.
- Forgetting to regenerate the pack after a future policy migration: the pytest drift test is the guard.

## 8. Slice plan

Order respects: policy baseline before code; APK/web exports on CI only; migrations chained on committed heads (`a9e4c7f2b3d6`); one test runner; Opus `code-writer` for risky multi-file, Sonnet for narrow.
Mobile slices run `make check-web` (the web export must still build; native-only modules need `.native`/`.web` twins as in `e59273d7e`). Backend slices run targeted pytest only; one full suite before each commit.
Each slice is independently shippable; none changes behaviour for the plain build or enrolled non-standalone users unless stated.

| # | Slice | Files (main) | Tests | check-web | Migration | Depends on |
|---|---|---|---|---|---|---|
| **S0** | **Policy baseline** (docs only, one commit): Path C standalone (field-data-collection.md, incl. Collect Plus section fix), standalone push contract (offline-api-contract.md new section + 5.6 exception), imported-final workflow state (coding-workflow-state-machine.md), standalone consent notice (respondent-consent-notice-draft.md), export/backup rules, doris-cod-workflow.md offline parity, mobile-sign-in.md section 8.x, expo-client.md current-state. Front matter and `last_updated` on each. | `docs/policy/*`, `docs/current-state/expo-client.md` | none | no | no | owner decisions in section 9 |
| **S1** | Equity layer: vendor module + composed instrument + `web_intake_equity_enabled` + Project Setup toggle + served definition + analytics dims; EN/HI strings. | `vendor/who-va-2022/src/digitva-extension.ts`, `src/generated`, `tooling/who-va-2022/build-composed-instrument.mjs`, `app/data/who-va-2022.composed.json`, `app/models/va_project_master.py`, `app/services/web_intake_service.py`, `app/routes/admin.py`, `app/routes/api/organization.py`, `app/templates/admin/panels/projects.html`, `app/services/served_form_service.py`, new migration | vitest in vendor; pytest `tests/test_admin_project_setup.py`, composed-instrument tests, served-form and `form_options` tests; jest for prefill if touched | **yes** | **yes** (after `flask db heads`) | none (policy exists); `digitva-zfsa` follow-up |
| **S2** | Offline allowability port: pure module + data pack + drift test + offline save wiring + age-confirm dialog and unknown-cause in the offline editor. | `mc/src/workspace/icdAllowability.ts`, `offlineDoris.ts`, `offlineCoding.native.tsx`, `mc/assets/`, server export script under `scripts/`, `tests/services/test_icd11_allowability_pack.py` | jest (vectors); pytest (pack drift) | **yes** | no | S0 (doris-cod-workflow section) |
| **S3** | Device uuid binding at enrolment and sign-in-QR redeem. | `app/models/auth_devices.py`, `app/services/device_auth_service.py`, `app/services/sign_in_qr_service.py`, `app/routes/api/auth.py`, `mc/src/auth.ts`, `mc/src/nativeRoutes/enrol.tsx`, new migration | pytest `tests/routes/test_device_api.py`, `test_sign_in_qr.py`; jest `enrol-sign-in-qr.test.tsx` | yes | **yes** | S0 |
| **S4** | Standalone onboarding: "Use without a server" entry, local account and store, synthetic project and reference pack, bundled form path, consent gate for the bundled notice (read-only first: notice shown, recorded locally), local-account guards in sync/notification/auth refresh, unsent-work count includes `offline_coding`, Plus-only gates, clock warning. | `mc/src/nativeRoutes/enrol.tsx`, `index.tsx`, new `mc/src/standalone/*`, `auth.ts`, `AppState.tsx`, `form.tsx`, `sync.ts`, `drafts.ts` (additive migrate), `unsentWork.ts`, `consent.ts`/`consentStore.ts`, `settings.tsx`, strings en/hi | jest: new suites (onboarding flow, local account guards, project-less form load, consent gate unavailable behaviour); update `offline-gate.test.ts` | yes | no (on-device additive only) | S0, S7 (notice source) |
| **S5** | Post-enrolment push: server import contract + routing + provenance; app adoption, ack-ordering fix, stale-coding binding (`answers_sha256` on `offline_coding`), org-code in profile, project/site/unit pick. Split S5a server (migration, ingest, tests) and S5b app so two writers do not touch the same files. | S5a: `app/routes/api/intake.py`, new `app/services/offline_coding_import_service.py`, `coder_cod_service.py` (reuse), `submission_analytics_mv.py` as needed, new migration, `tests/routes/test_offline_coding_import_api.py`. S5b: `mc/src/sync.ts`, `drafts.ts`, `offlineProfile.ts`, `offlineCoding.native.tsx`, `standalone/adopt.ts`, strings | pytest (idempotency, duplicate device, consent_invalid path, unrouted, stale hash, rules re-applied); jest (ack order, adoption, orphan prevention) | yes (S5b) | **yes** (S5a, chained after S3's revision) | S0, S2 (rules), S3, S4, S7 |
| **S6** | Export and backup: per-record export, passphrase-encrypted store backup via `sqlcipher_export`, restore with dedupe, reminders, event log. File delivery module. | new `mc/src/export/*`, `interviewerDb.ts` (attach/export helpers), `errorExport.ts` (reuse), `settings.tsx`, `package.json` (`expo-sharing` or SAF), strings | jest (round trip on in-memory sqlite mock, dedupe, passphrase rules, PII-strip option); manual device verification noted (CI APK) | yes | no | S0, S4 |
| **S7** | Consent alignment: generate the bundled notice from `consent_notice_seed.py` (script + drift test), standalone notice variant, server acceptance of standalone notice (allowlist/snapshot), `consent-config` unchanged. Include the enrolled-phone check for item 7 (7 purposes, optional refused). | `scripts/` generator, `mc/src/consent.ts`, `consentStore.ts`, `app/services/consent_*`, `app/routes/api/intake_consent.py`, new migration if `source` column | pytest `tests/services/test_consent_notice_seed.py` + new; jest `consent-store.test.ts`, `respondent-consent-panel.test.tsx` | yes | likely yes (merge into S5a's migration if sequenced together to keep one head) | S0 |
| **S8** | Registered-user QR polish: scan user QR from Add interviewer on an enrolled device; coder eligibility change (if the owner decides it); adoption prompt entry point. | `mc/src/nativeRoutes/index.tsx`, `sign-in.tsx`, `enrol.tsx`, `sign_in_qr_service.py` | jest + `test_sign_in_qr.py` | yes | no | S3, S4 |
| S9 | Residual (separate, already queued): `digitva-zkgx` questionnaire locales, `digitva-jish`, `digitva-owbz`/`46xk` (block `ydnl.1`), `digitva-ydnl` loop. Not on the critical path of this request; do not mix into the slices above. | | | | | |

### Dependency graph
```
S0 (policy) ──┬─ S1 (equity, independent after S0 optional)
              ├─ S2 (allowability) ───────────────┐
              ├─ S3 (uuid binding) ───────────────┤
              ├─ S7 (consent) ───┐                ├─ S5 (push: S5a server → S5b app)
              └─ S4 (onboarding) ┴─ S6 (export)   │
                          └────────────────────────┘
S8 after S3 + S4.
```
S1 needs no S0 (its policy exists) and may start now. S2 needs only the doris-cod-workflow paragraph from S0.

### What can run in parallel (no two writers on the same files)
- Wave 1 (parallel): **S0** (docs), **S1** (vendor + server + migration; the one migration writer), **S2** (mobile workspace files + `scripts/` + pack). S1 and S2 do not share files. Only S1 adds a migration this wave.
- Wave 2 (parallel): **S3** (server auth + migration chained after S1's revision; one small `auth.ts`/`enrol.tsx` edit), **S7** (consent files; if it needs a migration, fold it into S5a or sequence after S3 to keep a single head). S3 and S7 share `consent`-free files, but both touch `mc/src/auth.ts`/`consent.ts` separately; keep S7 off `auth.ts`.
- Wave 3 (serialize): **S4** then **S5b** touch `drafts.ts`, `sync.ts`, `offlineProfile.ts`: never concurrently. **S5a** (server) can run in parallel with **S4**.
- Wave 4 (parallel): **S6** and **S8** (S6: `export/*`, `interviewerDb.ts`, `settings.tsx`; S8: `index.tsx`, `sign-in.tsx`, `enrol.tsx`). `settings.tsx` is shared with S4: keep S4 merged first.
- Migration discipline: exactly one writer adds a migration at a time; each runs `flask db heads` before and after. Order: S1 then S3 then S5a (and S7 folded in).
- Test runner: one read-only runner at a time; each writer gets its own `minerva_test_<name>`; one full suite after the whole list, per the memory rule.
- APK/web: none built locally. Plus APK for device acceptance of S2/S4/S5/S6 comes from `collect-plus-release.yml`; device acceptance (engine on phone, Samsung SM-E146B) is manual and must be recorded as such, not claimed from jest.

## 9. Owner decisions needed before S0 (do not guess)

1. Is standalone Collect Plus for **owner-controlled pilot phones only** (policy today: never handed to interviewers)?
2. Retention on a standalone phone: no ceiling plus backup reminders, or a visible age warning?
3. State after an imported offline final: coded (counts as the coder's final), coded plus reviewer sample, or "needs coder confirmation"? Does the server re-apply allowability rules and flag disagreements (recommended) or accept as is?
4. Consent in standalone: bundled platform notice (generated from the seed) with text snapshot on push, and whether item 7 (`narrative_automated_processing`) is offered before enrolment (recommend default "no").
5. Sign-in QR for users holding coder/self-coding grants (needed for Plus coders), or enrolment QR plus password only.
6. Backup passphrase model (user-chosen, no recovery) and where backups may be saved (share sheet vs SAF folder).
7. SmartVA offline: out of scope for now (recommended), or open an Android build project for `digitva-smartva`.
8. Org matching: add an optional org code field (and which level) to the offline profile, or route everything standalone to the unrouted queue for a data manager.

## 10. Verification and honesty notes

- Verified by reading code: standalone unreachability (items 0.1-0.4), the ack-ordering orphan (`drafts.ts:702-710`), missing answers hash on `offline_coding`, absence of allowability in `offlineDoris.ts`, the sandbox consent mismatch and its zero callers, absence of `equity` in code, migration head file.
- Not run: jest, pytest, `flask db heads` (read-only brief; head taken from the committed migration files and the brief), device behaviour, dev DB queries.
- Unverified assumptions to check inside the slices: engine support for exclusive `select_multiple` choices (S1); SAF versus share-sheet behaviour on Android 14+ with `expo-file-system` 57 (S6); `sqlcipher_export` availability through `expo-sqlite` 57 with `useSQLCipher` (S6, spike first, one hour); how `storeEnrolment` treats an already-enrolled device with a different project (S3/S8).
