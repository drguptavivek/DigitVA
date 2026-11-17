# Architecture Summary (`DigitVA` — Run 7, Scoped `3603ca6..e6a1791`)

## 1. Product, Principals, Normal Authority, and Protected Resources
DigitVA is a verbal autopsy (VA) platform comprising a Flask web application, Celery worker/beat services, an Expo/React Native mobile and web client (`DigitVA Collect` and `DigitVA Collect Plus`), native offline WHO ICD-11/DORIS and SmartVA engines, and an offline Rust PHC desktop station.

Principals (lowest to highest trust):
- **Unauthenticated / Public Caller**: Accesses login (`/auth/login*`), passkey assertion, password/factor reset, email verification, mobile sign-in code redemption (`/auth/verify-code`, `/api/v1/auth/code-sessions`), QR redemption (`/api/v1/auth/qr-sessions`), device enrolment, public DORIS training endpoints (`/help/doris-demo`, `/api/v1/doris-demo/*`), and (when `PUBLIC_DEMO_ENABLED=1`) demo signup (`/auth/demo-signup`, `/api/v1/auth/demo-signup`).
- **Public-Demo Account (`is_public_demo=True`)**: Confined by `_guard_public_demo_grants` (`app/services/authz/grant_cache.py:316-343`) to `{interviewer, coder, reviewer}` on `PUBLIC_DEMO_PROJECT_ID` (`PUB01`) and restricted by `_own_cases` (`app/services/authz/predicates.py:120-138`) to its own submitted drafts.
- **Project Member (`MapProjectMember` only)**: Listed on a project roster (`app/models/map_project_members.py:14-39`) with zero data or grant authority until an operator assigns a role grant.
- **Trainee (`interviewer`, `coder`, `self_coding` session on `TRN01`)**: Confined by `training_scope.resolve` (`app/services/training_scope.py:60-85`) and `AREA_RULES` (`app/services/training_demo_service.py:2402-2452`) to `TRN01` training cases; excluded from `writer_grants` (`app/services/authz/grant_writes.py:114`) and trainer answer keys.
- **Trainer (`reviewer_data_manager` on `TRN01`)**: Views concordance and session reports (`app/routes/dm_training.py:23-64`) via `training_report_service.authorized_session`, with answer keys redacted if the viewer ever held a `coder` participant row in that session (`app/services/training_report_service.py:141-151`).
- **Field & Clinical Roles (`death_reporter`, `interviewer`, `interview_supervisor`, `coder`, `coding_tester`, `reviewer`, `collaborator`, `collaborator_pii`)**: Scoped by project, site (`project_site`), or `ltree` organization unit (`org_unit`) (`app/services/authz/predicates.py:165-601`). Native bearer tokens (`g.bearer_auth`) project only `NATIVE_DEVICE_ROLES` (`interviewer`, `death_reporter`, `coder`, `coding_tester`, `reviewer`) and strip `is_admin` (`app/services/authz/grants.py:505-532`).
- **Mentoring Institute Member / Admin (`MapMentorInstituteUser`)**: Restricted by `check_mentor_grant` (`app/services/mentor_institute_service.py:682-713`) to attached district subtrees and denied Tier 3 PII except with an explicit `data_manager` unit grant (`app/services/authz/grants.py:263-290`).
- **Data Manager (`data_manager`), In-Charge (`site_pi @ org_unit`), and Project PI (`project_pi`)**: Manage triage, ODK sync, routing, supervision, and scoped grant writes (`can_grant`, `app/services/authz/grant_writes.py:141-196`). Project-scope DMs and PIs manage the project roster, bulk user grid, worker placement, and sign-in code issuance (`app/routes/admin_organization.py:1358-1861`).
- **Platform Admin (`admin @ global_scope`)**: Full platform configuration, training session creation and graduation (`app/routes/admin_training.py:39-298`), user activation/deactivation, and DB backup/restore.

Protected resources: VA submissions and narratives, hybrid-KEM-sealed PII (`va_death_identifier`, `map_payload_version_pii`, `va_death_register.pii_sealed`), DPDP consent artefacts, audio/image/PDF attachments, training answer keys (`MasTrainingCase`), user credentials/sessions/passkeys, SQLCipher mobile databases, and ODK Central credentials.

## 2. Comparable-Software Baseline
DigitVA integrates with ODK Central (`pyodk==1.2.1`), WHO ICD-11/DORIS 1.2.0 (`whoicd/icd-api:2.6.0` and NativeAOT `libdigitva_icd11`), SmartVA Tariff 2.0 (`smartva-rs`), and FIDO2 WebAuthn (`webauthn>=2.8.0`). Like ODK Central, form/site/unit hierarchy and offline sync reconciliation are critical boundaries where stale state, attachment rebinding, or scope drift can cause cross-unit disclosure or data loss.

## 3. Tech Stack, Deployment Paths, and Offline Execution Limits
- **Backend**: Python 3.13, Flask, SQLAlchemy, PostgreSQL (`ltree`), Redis, Celery, Gunicorn (`app/__init__.py`, `docker-compose.yml`, `docker-compose.demo.yml`).
- **Client & Native**: TypeScript, Expo SDK 57 / React Native (`mobile/digitva-collect`), C JNI (`shim.c`), Kotlin (`DigitvaIcd11Module.kt`, `Icd11Service.kt`, `DigitvaSmartvaModule.kt`, `SmartvaService.kt`), Swift (`DigitvaIcd11Module.swift`, `DigitvaSmartvaModule.swift`).
- **Sandbox / Local Execution Limits**: On this VM, container seccomp blocks `unshare --net` and `unshare --mount` (`ENOSYS`), cgroup v2 controllers are read-only, and Docker, PostgreSQL, Redis, `.venv` (Python 3.13), and `node_modules` are absent. Target-controlled code execution is therefore blocked by missing OS sandbox and runtime dependencies; source-grounded leads requiring runtime verification are recorded as `needs_validation`.

## 4. Entry Surfaces and Source-to-Sink Paths (`3603ca6..HEAD`)
1. **Project Roster, Bulk Grid, Worker Placement & Member Imports**: `app/routes/admin_organization.py`, `app/services/organization_service.py`, `app/services/project_user_import_service.py`, `app/static/js/admin/project_person.js`, `app/static/js/admin/users_panel.js`.
2. **One-Time Mobile Sign-In Codes, QR Redemption & Device Limit Eviction**: `app/services/mobile_sign_in_service.py`, `app/services/sign_in_qr_service.py`, `app/services/device_auth_service.py`, `app/routes/api/auth.py`, `app/routes/va_auth.py`, `app/routes/data_management.py`.
3. **Training Session Types (`interviewer`, `coder`, `self_coding`), Pseudonymiser, Reports & Graduation**: `app/routes/admin_training.py`, `app/routes/dm_training.py`, `app/services/training_demo_service.py`, `app/services/training_scope.py`, `app/services/training_report_service.py`, `app/services/training_pseudonymiser.py`.
4. **Clinical DORIS, Public Demo DORIS, Coding, Social Autopsy & Attachments**: `app/routes/api/doris_clinical.py`, `app/public_doris/routes.py`, `docker-compose.demo.yml`, `app/routes/api/coding.py`, `app/routes/api/so.py`, `app/routes/api/attachments.py`, `app/services/coder_workflow_service.py`, `app/services/public_demo_purge_service.py`.
5. **Mobile Auth, PIN Lockout/Recovery, Profile Deletion & Workspace**: `mobile/digitva-collect/src/auth.ts`, `DeviceLimitChoice.tsx`, `offlineProfile.ts`, `pinResetGrant.ts`, `sync.ts`, `draftSync.ts`, `workspace/*`.
6. **Native ICD-11 & SmartVA Bridges and Restore/Parity Scripts**: `mobile/digitva-collect/modules/digitva-icd11/*`, `modules/digitva-smartva/*`, `scripts/manual-db-restore.sh`, `scripts/icd11-parity/*`, `scripts/smartva-parity/*`.

## 5. Trust Boundaries and Strongest Source-Visible Controls
- **Authentication & Session / Device Binding**: `load_user` checks `auth_session_version`; `authenticate_bearer_request` validates hashed device bearer tokens and projects `NATIVE_DEVICE_ROLES`; `check_device_slot` locks user rows `FOR UPDATE` on 3-device eviction.
- **Grant Write & Roster Takeover Boundary**: `can_grant` (`app/services/authz/grant_writes.py`), `require_on_project_roster` (`app/services/organization_service.py:3973`), and `_roster_rule` / `may_issue_code*` / `may_edit_account` (`app/services/mobile_sign_in_service.py:118-320`).
- **Training (`TRN01`) & Answer-Key Isolation**: `training_scope.resolve` (`app/services/training_scope.py:60-85`), `AREA_RULES`, and `_viewer_was_coder_in_session` (`app/services/training_report_service.py:141-151`).
- **Client DOM & Native IPC Boundary**: `esc()` in admin templates/JS, `piiBoundary.ts` before native engine calls, and isolated Android `:icd11` / `:smartva` service processes with size caps (`MAX_TEXT_CHARS`, `MAX_REQUEST_BYTES`).

## 6. Prior-Run Context
Raw `run-6` JSON artifacts (`~/security-audit-skill/DigitVA/run-6`) are not present on this ephemeral VM; Run-6 (`digitva-9xn9`, closed at `3603ca6`) and the 2026-11-14 training audit (`digitva-q3iu`, open for item 7 session resize/reassign) are tracked in `.beads/issues.jsonl`. All units in this scoped run initialize with `prior_status: "none"`.

## 7. Selected Companion Files
- `WEB-PROTOCOL-AND-AUTH.md`: Mobile sign-in codes, QR tokens, device limit eviction, CSRF, and session invalidation.
- `DATA-ISOLATION-AND-LIFECYCLE.md`: Project roster isolation, training scope (`TRN01`), PII redaction, and demo purge/restore.
- `DESKTOP-MOBILE-AND-LOCAL-IPC.md`: Mobile vault/PIN recovery, profile deletion, and Android/iOS native engine IPC.
- `CLIENT-SIDE.md`: Admin roster/users panel DOM rendering (`innerHTML`) and browser `sessionStorage` drafts.
- `MEMORY-SAFETY-AND-BINARY.md`: C JNI shim (`shim.c`) and native FFI boundaries for ICD-11 and SmartVA.
- `CLOUD-AND-DEPLOYMENT.md`: `docker-compose.yml`, `docker-compose.demo.yml`, and `scripts/manual-db-restore.sh`.
- `RESOURCE-EXHAUSTION-AND-AVAILABILITY.md`: Unbounded inputs, CSV/XLSX imports, native engine IPC payloads, and DORIS endpoints.
