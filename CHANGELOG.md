# Changelog

What landed, newest first. Details live in the commits and the linked docs;
`handoff.md` holds only what is next.

## 2026-10-28

- **Public APKs and matched deployment pins** (`digitva-hs7e.17`): published
  signed arm64 Collect 0.3.13 (67,927,662 bytes) and Collect Plus 0.3.13
  (141,184,458 bytes, prerelease). Fresh public downloads matched their build
  checksums. Pin both APKs and `expo-web-v2026.10.28.2`, whose tests/export/profile
  passed in run `40689771530` from source `9ea377d7b`. Server deployment and
  hosted override population are a separate verified step.
- **Server compatibility and separate APK downloads** (`digitva-hs7e.18`, `.17`):
  public API contract/deployed-build endpoint, manual Settings compatibility
  check scoped to the selected server, separate Collect/Plus update and download
  selection, and actual APK sizes on the download page. Unknown/offline checks
  preserve work. Owner explicitly authorized public Plus alongside Collect;
  written WHO redistribution confirmation remains pending. Local signed 0.3.13
  APKs passed identity/signature and 16 KB checks; normal was installed without
  clearing data. Current mobile: 232 suites/3,329 tests, types and web export pass.
  Backend: 7,015 passed, one non-reproduced query-count failure, six skipped;
  the entire 20-test paging file passed serial and two-worker reruns. Final
  release API tests: eight passed, ten subtests. No coding-list path changed;
  follow-up investigation retains the unexplained full-run failure.
- **Staging deployment** (`digitva-hs7e.17`): deployed server
  `3147fc3a43b8db0e504bd1e8f029395e9a30dab0` after the owner approved image run
  `40679243131`. Verified S3 database backup, migration `b4e7c2a9d6f3` at head,
  healthy app/WHO/DORIS services and public web manifest
  `expo-web-v2026.10.28.1`. Existing public Collect 0.3.10 APK and unrelated
  server settings were preserved. Rollback image: `c8b749f7b88a1a853dcd1e7e83d2070bb76624f4`.
- **Staging web input** (`digitva-hs7e.17`): pin the matched
  `expo-web-v2026.10.28.1` export from `efe8bd636`, verified against its app and
  WHO questionnaire checksums. Release run `40678407080` passed all 3,322 mobile
  tests, types and bundle gates. Android, SmartVA and server ICD image pins stay
  unchanged; server publication/deployment follows separately.
- **Matched web release input** (`digitva-hs7e.17`): fetch the pinned SmartVA
  source before mobile tests so generated symptom checks also work in a clean
  release checkout. No native engine artifact is added to the web release.
- **Bundled native coding** (`digitva-hs7e.3`, `.5`, `.12`, `.13`, `.13.1`):
  Plus includes SmartVA and WHO ICD-11/DORIS code/data in its installed package.
  SmartVA runs after valid local completion, fills missing/stale results on
  coding entry and retains manual regeneration. Frozen options and encrypted,
  answer/version-bound caches preserve provenance. Native libraries support
  16 KB pages; no runtime engine/data download is offered. Policy and runtime:
  `docs/policy/smartva-generation-policy.md`, `docs/current-state/expo-client.md`.
  SmartVA mobile-core source is pinned to `790af12` in the owner fork.
- **Device mode boundaries** (`digitva-hs7e.6`, `.7`, `.11`): explicit server,
  standalone and demo setup, manual password enrolment, project/profile access
  details and persistent mode banners. Standalone needs explicit logout from
  both server slots. Cross-server account-ID collisions fail closed before
  token/store use; serialized sign-in and refresh writes protect those bindings.
  ICD-11/DORIS coding starts disabled and can be enabled in Settings.
- **Consent refusal is a hard stop** (`digitva-hs7e.15`, `.15.1`, `.16`): either
  interview or data-processing refusal permits only broad deceased age/sex and
  essential audit metadata. Save, upload, attachment, identifier and bundle
  ingress enforce the same rule. Fresh-version resume prevents stale answers
  returning after a grant. Registration-only staff have a minimal offline-safe
  refusal receipt. Standalone English/Hindi notices are editable in Settings;
  recorded consent retains its wording. Submitted shared-refusal hold resolution
  remains open as `.15.2`. See `docs/policy/respondent-consent-notice-draft.md`.
- **Coding integrity and local history** (`digitva-hs7e.4.1`–`.4.5`): exact coding
  revision acknowledgements, durable refusal notices, allocation ownership under
  locks, scoped encrypted coded-list cache and bundled VA definitions/mappings.
  SmartVA batch processing rechecks refused/duplicate state under row locks.
- **Phone screens and notices** (`digitva-hs7e.8`–`.10`, `.14`): simpler setup and
  Settings text, actual phone date/time, bundled English/Hindi, offline software
  notices and corrected first-run safe area. The owner-approved screenshot
  allowance covers normal and Plus builds until `2026-11-25T08:12:11Z`.
- **Combined validation**: backend 7,013 passed, 6 skipped, 5,469 subtests;
  mobile 232 suites / 3,322 tests, TypeScript and web export passed. Default
  Rust 10 tests and mobile-core 8 tests passed. Local release APK installed on
  SM-E146B Android 15 and an Android 13 emulator; both passed offline engine
  checks with expected synthetic results. APK 141,185,658 bytes, target API 36,
  all 33 native libraries 16 KB aligned. Phone SmartVA scored the three age
  groups in 245/34/28 ms; DORIS returned expected BA41.Z. These are functional
  checks, not clinical validation. No staging/store publication; remaining
  physical acceptance, signing and WHO/Hindi clearance are in `handoff.md`.

- **Account deletion** (`digitva-et16`, `digitva-kdba`): demo users confirm
  their password to delete their own account on the phone or website; staff
  file a request, reviewed and marked handled on the admin Users page.
  Security/sign-in audit records are retained. New endpoints and additive
  migration `b4e7c2a9d6f3` preserve existing APK contracts.
- **Google Play bundle preparation** (`digitva-6o4b`): Play builds hide hosted
  APK updates, use a higher versionCode and a manual signed AAB artifact
  workflow. This does not publish to Google Play or deploy a server.
- **AI project/site matching** (`digitva-g72d`): the planner receives only
  authorized project/site IDs and names so it can use exact identifiers.
  Organization-unit metadata is excluded from this change.
- **Unified app workflow** (`digitva-6rxf`): shared local profile and local/online
  case navigation, with online coding in the app. Offline coding requires
  self-coding and actual coder access in the same project. Engine startup is
  deferred. Upload/editor leases, exact receipts and snapshot checks retain
  work through retries and concurrent edits.
- **Device controls** (`digitva-65m5`): three live devices per account without
  silent eviction; self, admin and scoped data managers can decommission an
  account/device pair while preserving encrypted unsent work.
- **First-party diagnostics and timelines** (`digitva-yv2n`): enabled minimal
  daily hardware/use/error aggregates, Settings off switch, own-server analytics
  API, 90-day retention and small-cell suppression. Interview/coding timelines
  stay in authorized row-level submission metadata. Native submissions save
  locally before background upload with timeouts.
- **Emulator development** (`digitva-a770`): Plus 0.3.12 debug APK installed on
  arm64 emulator; HMR verified without restarting the app. Helper script keeps
  existing app data and uses Metro port 8082. Releases retain Play AAB and APK
  paths; release/privacy review information is prepared without publication.
- **Worktree reconciliation** (`digitva-vks8`): all seven old worktree directories
  retired; branch refs and verified private source archives/older phonefix APKs
  retained (596 MB). Only the active main checkout remains.
- **Validation** (`1daa556f9`): full backend 6,750 passed, 6 skipped, 5,401 subtests with
  two workers; mobile 207 suites / 3,025 tests and TypeScript passed; real
  emulator HMR and normal pre-commit web export verified. The four-worker
  migration run exceeded PostgreSQL's
  1 GB limit; resource follow-up is `digitva-07lz`. Final audit found no
  material issues after fixes. Final bounded telemetry-reader/logger regression:
  25 tests / 3 subtests passed; diagnostics payloads are not parsed by the request
  logger. Large-backlog paging follow-up: `digitva-uf9j`.

## 2026-10-27

- **Public demo live** at https://digitvademo.causeofdeathindia.com (image
  `c8b749f7b`): own database, S3 user on `demo/`, Let's Encrypt on the proxy.
  First start needed three fixes: the demo compose sets the PII key path
  (`4d1cb7a2e`), the image ships the migration seed folders (`2c11c6365`), and
  the demo mounts `docs/` read-only for boot-time reference data (`9b8c33351`).
  Headers and titles carry `SITE_ENV_LABEL` (DEMO on the demo; set STAGING on
  staging if wanted); the Expo app shows a DEMO badge and title from the
  server origin, and its compiled demo host is now `digitvademo`.
- **Expo web export pinned to `expo-web-v2026.10.27.1`** (from `d011406a7`);
  the image had carried the 25 October export, so staging's `/app/` still
  lacks today's web changes until its next deploy.

- **Staging deployed** at `17e43e4d8` (migration head `f3d9b5c7a2e4`):
  public pages, contact form, AI questions and the rest of the day's set.
  The first attempt failed health checks: the app's `.venv` named volume
  still held the 25 October dependencies (no `pglast`). Fixed forward by
  removing the volume; `scripts/deploy-server.sh` now drops it on every
  deploy. Vertex AI checked from the staging app: `gemini-3.5-flash` in
  `asia-south1` answers through a dedicated service account
  (`digitva-vertex`); `gemini-3.5-flash-lite` returns 429 (no quota yet).
  A Gemini client bug ("client has been closed") is fixed with a
  regression test.

- **Contact us form** (`digitva-gyfj.1`): name, email, topic (general,
  consent, deletion, technical), message. Animal slide-to-slot puzzle with
  the target kept server side, plus the existing proof-of-work check, a
  honeypot and rate limits (per IP, and per inbox with plus-tags and Gmail
  dots folded). Double opt-in: the message waits 24 h in the cache and is
  emailed to `PUBLIC_CONTACT_EMAIL` only after the sender confirms by POST
  from the emailed link; the link carries only a token. The form shows only
  when that address and outgoing mail are configured. Mail logs now mask
  recipients for every email. Security review: no high findings; the
  low ones are fixed or recorded in the policy.
- **APK builds** of `60aef7ee8` (build only, not published): Collect and
  Collect Plus both succeeded.

- **Staging-safe release** (`digitva-weiq`, `digitva-g67f`):
  - The AI questions migration `a9e4c7f2b3d6` no longer needs a superuser.
    Without the privileges it creates the tables, skips the reader role and
    function, and the feature answers 503 `not_configured` until a superuser
    runs `deploy/sql/ai_reader_setup.sql`. Staging's `digitva_app` is not a
    superuser, so the old form would have kept `boot.sh` retrying the upgrade
    and the app down.
  - Maintenance page on the ingress (`deploy/maintenance/`): shown
    automatically on 502/503/504 while the app restarts, and switched on by
    `scripts/deploy-server.sh` for the pull and migrations. API paths get
    JSON 503 `maintenance` with `Retry-After`, which phones treat as transient.
  - Upgrade audit against staging (commit `d7f8ac86`, APK 0.3.10): no data
    loss path. Owner accepted that project-scope grants on tree projects see
    masked PII under the three-tier rule.
- **Owner answers to the Collect Plus defaults** (`digitva-5bzf` notes):
  profile org code may name any level (`.13`, server already routed it);
  enrolled Plus phones get an encrypted backup of unsent work, no CSV
  (`.14`); sign-in QR needs an interviewer or death-reporter grant again
  (`.15`, reverses S8).
- **Public pages** (`digitva-gyfj`, draft pending legal review): `/privacy`
  with a Consent section, `/contact` (Contact us), `/data-requests` (Consent
  and data requests), linked from every footer; organisation details from
  `PUBLIC_*` config. Policy `docs/policy/public-privacy-and-data-requests.md`.
- `AGENTS.md`: staging deploy rules and the web-bundle boundary.

- **KPI refresh: every KPI computed live from workflow events**
  (`digitva-0hul`, `digitva-r5s0`):
  - **Policy:** `docs/policy/kpis.md` rewritten as 18 core panels out of 35
    registered (16 merged, 1 retired), grouped by results-chain stage, with
    analytic views.
  - **Source of truth:** stored daily aggregates are no longer read.
    `bucket_flow_by_day` replays workflow events to end of day in the
    viewer's timezone. `kpi_tasks`, `flask kpi` and the recompute hooks are
    deleted; the table stays.
  - **Bugs fixed:** grid total showing 0; a time-to-code fan-out with
    negative durations; case-sensitive language matching (English coders
    went from 0 to 97); the recode window hard-coded at 24 h; blocked forms
    counting coded cases; the training project leaking to unit data
    managers; deactivated coders counted as available.
  - **New KPIs:** O-UNK, D-QG-09 at WHO bucket level, EQ-01, EQ-02,
    AD-FCOD, AD-COV, D-WF-02 (outcome, equity and critical path).
  - **Registry:** `app/data/kpi_registry.json` with a loader, a drift test,
    the help page rendered from it, a `kpi` search kind and 9 catalog
    entries.
  - **Review fixes:** equity XLSForm spec, chart filters, burndown timezone,
    CSV guard, temp-file sweep, admin booleans.
- **Bug fixes:**
  - `digitva-fvbc`: a dead session gets 401 before CSRF; the client pauses
    autosave and shows a sign-in prompt.
  - `digitva-x928`: no session save on unmodified API GETs.
  - `digitva-783d`: SmartVA export header order is deterministic.
  - `digitva-mubf`: the COD report and snapshot use the same mapping rows.
  - `digitva-8dzk`: `allocation_exists` answers 409.
  - `digitva-p6fs.27`: advertised and downloadable translations agree.
  - `digitva-fb5` (partly): label-code audit and fix CLI; 16 rows still
    need a speaker.
  - `digitva-46xk`, `digitva-jish`, `digitva-wh4w`: Collect revise layout,
    stuck uploads and low-end performance.
  - `digitva-owbz` (partly); `digitva-e1t9` race fix plus retry (still open).
  - `digitva-ke83.8`: the corpus parity test now compares real values;
    `digitva-ke83.7` was already fixed.
  - `digitva-l945`, `digitva-yeg3.26`: DM cards equal lists; `org_unit`,
    `visit_note` and date-of-death filters; pending is 6 states; org-unit
    picker.
- **Collect Plus standalone** (epic `digitva-5bzf`; slices S0 to S8):
  - S0 policy baseline; S1 equity layer (migration `b4f8d2e6a1c3`); S2
    offline allowability pack; S3 device UUID binding (`c7a3e9d1f5b8`); S4
    standalone onboarding; S6 export and passphrase-encrypted backup; S7
    bundled consent; S8 coder sign-in QR; S5a server import
    (`f3d9b5c7a2e4`).
  - New web-bundle guard test keeps native-only code out of the web export.
  - S5b app push after enrolment (`digitva-5bzf.7`): a separate push queue
    from the standalone store; a record is deleted only after the server
    acknowledges it; coding whose answers changed is not sent. Deleting a
    sent draft now removes its offline-coding row for every account. Audio
    on tree projects can stall at the file step until the draft endpoint
    accepts no unit. Tested with a mocked network only.
- **More policies recorded:** Collect correction loop (`digitva-ydnl`),
  interview support and its edge model (`digitva-fixy`, `.1`), EAVA and
  InterVA5 (`digitva-13gs`), document vision-language model
  (`digitva-sxg9.1`); the earlier narrative AI, geography, equity, DHS,
  BYOK, `digitva-lep4` and DuckDB entries are below.
- **AI questions for data managers** (`digitva-qwvt`, `digitva-qwvt.1`):
  - **Asking:** data managers and admins ask in plain language at
    `/data-management/ai-questions`. Claude Sonnet (default) or Gemini,
    chosen per question from the enabled providers, writes SQL over
    per-request temp tables built with the caller's scope. The provider
    never sees result rows (owner decision: aggregates only,
    `docs/policy/ai-analytics-questions.md`).
  - **What questions can read:**
    - `ai_cube`: case counts with language, org-unit names, consent mode
      and final-saved week;
    - `ai_org_levels`;
    - `ai_staff`: staff counts, with no names;
    - `ai_coder`: named coder results, for data managers and admins only.
  - **How answers come back:** comparative where possible, with a peer
    reference line. Questions needing data DigitVA does not hold get "This
    data is not captured in DigitVA: …" and run no SQL.
  - **How the SQL runs:** through `digitva_ai_run`, a SECURITY DEFINER
    function owned by `digitva_ai_reader` (migration `a9e4c7f2b3d6`), after
    a pglast allowlist check. Time, memory, temp files, output and joins
    are capped, and advisory locks are released after each run. `SET ROLE`
    alone was rejected because the reader could switch back to the session
    user.
  - **Without the model:** 12 built-in reports, 94 catalog questions and
    saved queries run with no model call or quota.
  - **Search:** Typesense (192 MB, internal only) gives typo-tolerant search
    over catalog questions, the user's saved queries, role-filtered help
    pages and VA definitions, with an in-process fallback.
  - **Live test:** checked live with Claude on dev. Prompt caching is
    working, at about 0.5 cents a question.
  - **Not yet:** not deployed (staging freeze).
- **Policies recorded, built later** (owner 2026-10-27):
  - narrative AI on a local workstation, with PII detection and
    de-identification (`digitva-sxg9`, `docs/policy/narrative-ai-processing.md`);
  - consent item 7 and purpose `narrative_automated_processing`, added to
    the default consent seed (English and Hindi; legal review pending);
  - country-neutral geography codes, rural/urban area type, facility ids
    and boundary-pack maps (`digitva-v1oi`);
  - an `equity` form extension with DHS-aligned choices (`digitva-r9lk`);
  - DHS Program data links (`digitva-1835`);
  - per-project AI keys stored with the post-quantum envelope
    (`digitva-6383`);
  - ODK credentials moved off Fernet to the post-quantum envelope
    (`digitva-lep4`);
  - a DuckDB store for all reports, in the next version (`digitva-2476`).

- **ICD-10 annex-only vs ICD-11 widened, recorded as a decision**
  (`digitva-7pl2`): ICD-10 projects have no DORIS, so the WHO annex list stays
  their check that a final is a WHO VA cause code; ICD-11 is wider because
  DORIS may return any real cause. Age tables are DigitVA decisions (WHO
  publishes sex lists only); ICD-10 keeps refusing age conflicts. Docs only.

- **ICD-11 allowability follows WHO** (`digitva-kmm2`, `digitva-443q`,
  `digitva-oh7j`, `digitva-xmpx`): chapter 22 injury-nature codes are no
  longer a final COD and `KD3B.Z` is selectable again (migration
  `b8d4f2a6c1e9`, which also drops the "Draft: " note prefix). A `/`
  cluster's allowability, VA cause, training report and definition use the
  causing condition WHO codeinfo names (`FB80.B/2F9Z` counts as `2F9Z`);
  migration `c5e8a2f4b7d1` rebuilds the COD snapshot and detail views so
  reports follow it. Sex conflicts still refuse; age conflicts at the final
  and the masked DORIS Step 1 ask for confirmation, recorded in
  `icd11_provenance` with DORIS's plausibility warning. The picker offers
  "Causing condition not known" on a required causing-condition axis.
  Station rejections stay `final_blocked`. Also: the reviewer page's own
  saves, the DORIS editor flag and definition lookup, and two React Native
  Web warnings (Notes tab text node, `textDecoration`). Full suite 6,392
  passed (one old test updated to the new rule); mobile jest 2,767; code and
  security reviews; checked on dev with a 3-year-old training case.

## 2026-10-26

- **ICD-11 allowability decisions recorded** (`digitva-oh7j`, `digitva-xmpx`;
  follow-ups `digitva-kmm2`, `digitva-443q`, `digitva-7pl2`): the selection
  principles separate allowability, VA cause mapping and expression building,
  each with its basis. Owner decisions, not yet implemented: sex conflicts
  block and age conflicts warn for the final COD (DORIS only warns on both;
  WHO has no age table), and a required-axis stem may stand alone when the
  causing condition is not known (WHO RG 2.7.2.1). Review found chapter 22
  accepted as a final COD and `KD3B.Z` refused, against WHO; dev holds no
  such finals. Docs and beads only.

- **ICD-11 axes load when WHO lists an uncoded window root** (`digitva-cth7`):
  `_axes` now skips scale roots with no code and no children (WHO "window"
  entities such as FB80.B's "Neoplasms of the musculoskeletal system") instead
  of failing the whole axis panel with "WHO ICD-11 guidance is unavailable";
  they stay in the axis search scope. New
  `docs/policy/icd11-code-selection-principles.md` grounds the code, axis,
  extension, first-stem and allowability rules in the WHO ICD-11 Reference
  Guide and marks each DigitVA narrowing with its owner decision. The
  `/app/` reload allowlist gains Collect Plus's `offline-coding` and
  `offline-profile` routes (full suite had failed on them after `e59273d7e`).
  `docs/policy/icd11-local-api-runtime.md`
  `docs/policy/icd11-local-api-runtime.md` records WHO's reply on offline use
  (not written permission; servers stay on the official image). Full suite:
  6,356 passed, 1 failed (the allowlist, fixed and rerun: 3 passed).

- **Collect Plus pure offline coding** (`digitva-zjqq`): entirely offline mode
  for the Plus variant — install without a server, record interviews, and code
  them via the on-device DORIS engine. Local device identity minted at first
  run and an offline coder/facility profile (including the SmartVA
  HIV/malaria inputs) captured in Settings; coding saves to a new encrypted
  `offline_coding` table with device/profile provenance. Nothing syncs while
  unenrolled and no masking applies (collector and coder are the same person);
  enrolled sync with org-match routing is `digitva-tb0j`, and the server does
  not re-run DORIS on offline results. Mobile jest 185 suites / 2,760 tests
  and `make check-web` pass (screens are platform-split after the new routes
  briefly broke the web export via expo-sqlite).

- **Three-Tier PII boundary hardening and security audit remediation**
  (`digitva-2yo5`, `digitva-0v8f`, `digitva-9qoq`): enforce strict Tier 1 and
  Tier 2 Non-PII redaction in `ResolvedGrants.is_pii_grant` and
  `pii_visible_user_ids` (removing the `collaborator_pii`/`interviewer` early
  short-circuit on organization-tree projects), remove `collaborator_pii` from
  `MENTOR_ROLES` and `project_mentoring_overview`, and prevent Mentoring
  Institute `site_pi` unit grants from expanding via `ResolvedGrants.oversees`
  into Tier 3 `data_manager`/`interview_supervisor` powers. Remediate the
  `run-1` security audit findings: reject incapable worker `home_cadre_id`
  substitutions and enforce active-user, active-pair, and mentor-grant guards
  in `bulk_apply_project_users_grid`; cap offline station `bundle_seq` gaps
  against `MAX_BUNDLE_SEQ_GAP` (`10000`) before `generate_series`; scope
  `project_mentoring_overview` scientist PII to project-linked institutes;
  enforce `SUBMISSION_MAX_BYTES` and `check_device_answers` on `save_draft` and
  `submit_draft`; enforce `training_scope` isolation across intake attachment,
  prefill-policy, coding, and DORIS clinical routes; return trimmed
  `_identifier_reply` on `PATCH /api/v1/intake/deaths/<death_id>` and gate
  `case_prefill` on `interviewer_reaches`; and require manageable-user scope and
  unit-writer contact redaction in `PUT /data-management/api/users/<id>`. Full
  pytest suite 6,356 passed.

- **Three-tier Inside vs Outside health-system PII boundary, 7-level hierarchy,
  and parent-unit deactivation choice** (`digitva-ewa5`): codify and enforce the
  three-tier PII boundary on organization-tree projects across
  `docs/policy/access-control-model.md`, `docs/policy/district-reference-model.md`,
  `docs/policy/organization-model.md`, `docs/policy/case-list-views.md`, and
  `docs/current-state/health-system-organization-model.md` — Tier 1 (Project
  level: `project_pi`, `data_manager@project`, and project-scoped coding/viewer
  roles) and Tier 2 (Mentoring Institute lead and scientists) sit outside the
  health system and are Non-PII (blinded), while Tier 3 (Health-system unit
  grants at `org_unit` scope for non-mentoring-institute staff, including
  `In-charge`, unit `data_manager`, `interview_supervisor`, `interviewer`, and
  in-system doctors) is PII across within-tree and cross-tree scope, with
  exceptional PII granted via `data_manager` at the attached District unit.
  Expand `DEFAULT_LEVEL_TEMPLATE` to 7 levels (`state` optional at depth 1 above
  `district`, `taluka`, `chc`, `phc`, `subcentre`, `village`) with optional-root
  depth handling across `organization_service`, `mentor_institute_service`, and
  `/api/v1/organization/<project_id>/units`. Require an explicit operator choice
  (`reparent_children_to_org_unit_id` with subtree `ltree` path rewrite or
  `cascade_deactivate_children=True`) when deactivating a unit that has active
  child units, add level-change and optional-to-required tree-integrity guards,
  and surface the Three-Tier PII banner, `In-charge` terminology, and deactivation
  modal in `organization.html`, `project_setup.html`, and `access_grants.html`.
  Full pytest suite 6,353 passed.

## 2026-10-25

- **Training interview collection parity and consent panel layout**
  (`digitva-eiym`): reuse `CollectionPanel` on `/training/interview` when the
  participant holds the `interviewer` role so training matches real project
  collection (`Report a death`, `Direct VA interview`, refresh control, and
  `My interviews (N)` | `Reported deaths (M)` tabs routing to
  `/training/reporting` and `/training/interview/form`), scope
  `getIntakeContext`, `getDrafts`, and `getSubmittedRevisions` automatically
  when `csrf.training` is set, and deduplicate `org_units` in
  `interviewer_context` when a participant holds both `interviewer` and
  `death_reporter` on the same unit. Redesign `RespondentConsentPanel` and
  `StationConsentPanel` with a bordered notice box, readable language buttons
  (`English`, `हिन्दी`), `Select all` / `Clear all`, and left-aligned
  `ConsentCheckboxRow` items with required/optional pills. Jest 180/2713,
  `make check-web`, and training pytest 111 passed.

- **Interview welcome card, live case summary strip, and TRN01 DPDP consent**
  (`digitva-ydgv`, `digitva-idvp`): render the project welcome note (`Before
  you begin` / `intake_note` when `intake_screen` is enabled) before mounting
  the questionnaire on new Expo web and native phone drafts, and keep
  `ServerDraftStore.load()` pin-only writes from prematurely stamping
  `initialData` or `current_section` onto unstarted server drafts. Render the
  `Case id <unique_id> · <unit or project/site>`, save state (`Saved HH:MM:SS
  (N sections)` / `Not saved yet`), and live `Name / DOD / Age / Sex` summary
  strip on Expo web `InterviewScreen` for both direct and registered-death
  interviews. Configure `TRN01` (`setup_training_project`) to use the standard
  welcome default (`web_intake_intake_note = NULL`) and require respondent DPDP
  consent using the seeded English and Hindi draft notices pending legal review
  while preserving existing notices, retention, contacts, and single-stage
  settings (`docs/policy/training-demo-project.md`). Jest 180/2711,
  `make check-web`, and full pytest 6346 passed.

- **Published matched web release** (`digitva-9f8n`):
  `expo-web-v2026.10.25.2` from `1892f085d`, publication run40200511607.
  WHO/app builds and publish passed; both downloaded archive checksums, matching
  source/component metadata and strict web profile verified. Compose pins and
  staging remain unchanged; server image/deployment are separate steps.

- **Web acceptance and deployment handoff** (`digitva-3yaw`; implementation
  `3eaaf3b0c`): record measured performance, recovery checks and remaining vendor
  test limitations. Document matched WHO/app publishing, verified app pins,
  protected server-image build, SSM deployment and rollback. Close completed
  `digitva-k2s1`, `digitva-k2s1.1` and `digitva-bc56`; retain queued work in the
  rewritten handoff. No release publication or deployment during closeout.

- **Matched WHO and DigitVA builds** (`digitva-k2s1.1`, `digitva-k2s1`,
  `digitva-bc56`): build WHO as a verified package artifact before the app job,
  record its version/commit/hashes in the asset manifest, and publish both as one
  matched release. Preserve the complete web archive hosting contract. Correct
  Metro's web-control adapter resolution so native WHO code stays out of startup;
  local Docker export passes the strict gate (about 30% less initial gzip JS).
  Direct interview links return to their explicit training/collection list after
  saving. App Jest180/2706, typecheck, Node33 and artifact round trip passed;
  paired CI40198746587 passed; both downloaded artifacts and the final strict
  bundle profile verified. Three-trial poor-network home startup improved
  6.269 to 4.990 s; the owner accepted 1.492 s slower cold direct interviews.
  WHO download retry and offline-save/reconnect/reload passed in Chrome.
  See docs/current-state/expo-connectivity-profile.md. No staging deployment.

- **WHO preloaded web package entry** (`digitva-k2s1`): add an explicit
  `/web/preloaded` namespace using the canonical instrument and shared renderer.
  Preserve ordinary WHO root/web/native loading and exports. CI40191960858
  correctly rejected the first split because its nested instrument import put
  the form JSON into initial common code; keep that placement gate enforced.

- **WHO interview loading and training routes** (`digitva-k2s1`, `digitva-bc56`):
  isolate the WHO core and renderer behind one asynchronous browser boundary,
  keep coding/registration controls lightweight, and warm only verified public
  interview assets after eligible login. Add CI checks for all initial scripts
  and canonical instrument placement. Keep training flows under
  `/training/interview`, `/training/coding`, `/training/reporting` and
  `/training/reviewing`, with legacy redirects and consistent scoped API reads,
  saves and configuration. Jest180/2705, typecheck, Node18 and backend519/125
  subtests passed; live HMR training form opened and saved. CI-only production
  export and connectivity acceptance follow this commit; no staging deploy.

- **Web startup and local navigation** (`a14f6fa24`; `digitva-grmg`, `digitva-cklz`): paint
  the saved/system theme before React starts and keep navigation/loading status
  visible while deferred screens load. Route the local HMR legacy home links
  `/vaindex` and `/index` to Flask so Admin's logo returns to the app. CI export
  `40185993778` passed; final archive startup HTML and SHA-256 verified.

- **Web coding recovery and delivery** (`b133babc1`; `digitva-akbt`, `digitva-k2s1`,
  `digitva-55zu`, `digitva-dmcl`, `digitva-26h6`): recover permitted COD fields,
  remarks and pending notes after reload; reset to interview prefill; show VA
  references inline and refresh SmartVA independently of its drawer. Add opt-in
  Docker HMR, deferred interviewer loading and release-versioned public-asset
  caches. Non-publishing CI export `40185207054` passed; connectivity profiling
  remains open. This code change does not deploy a new staging version.

- **Shared SSM helper** (`digitva-gxvx`): move to `scripts/ssm.sh` so deployment
  and load-test watchdog commands use the same helper outside the load-test folder.
- **Web parity release** (`digitva-pjc8`): publish and pin
  `expo-web-v2026.10.25.1` (CI run `40160961967`, source `3ad5cefdb`), so the
  next server image includes the DORIS parity fixes; archive checksum verified
  against the published checksum asset and GitHub asset digest.
- **Digitvav3 parity deployment** (`digitva-pjc8`; image `d7f8ac86e`, CI
  `40161375783`): verified database backup before SSM deployment, healthy
  services, migration head unchanged, live web entry matches the release bytes,
  hosted APK 0.3.10 preserved. Reusable Mac wrapper `scripts/deploy-staging.sh`
  replaces the scratchpad procedure; usage in the split deployment runbook.
  Independent review and nine shell checks passed; command dispatch keeps child
  processes from consuming the script source through standard input.
- **Builds only on GitHub Actions** (`a57176256`, `16bf80760`, `775da2c0e`): new
  `expo-web-release.yml` and `collect-plus-release.yml`; the ICD-11 engine bundle is the
  public release `icd11-engine-v2026.10.25.1` (`scripts/package-icd11-engine.sh`,
  `scripts/publish-icd11-engine.sh`). Both workflows passed a non-publishing run.
- **Collect Plus "WHO files" and engine hardening** (`digitva-hs7e`; `cf44110b2`,
  `a5c69a71f`): first-setup / missing-file / "Update WHO files" download rule, setup
  record of real WHO file changes, size check with restore from shipped copies,
  priority worker in `:icd11`, progress events, bundled libssl
  (`io.github.ronickg:openssl:3.3.2-1`), atomic writes, Gradle heap via the config plugin.
- **Collect Plus icon** (`f6c5aa3cf`): the DigitVA icon with a "+" badge, plus build only.
- **DORIS parity, Expo coding screen** (`digitva-gfx8`; merge of the gfx8 branch,
  `5afb21ef1`): 422 field errors shown, half-entered interval blocks Process, UCOD
  titles and WHO notes persisted with the saved result, reports behind Details, empty
  Part II dropped, sex 9 "Unknown"; station bundles pass the plain envelope again.
- **DORIS parity, public demo** (`digitva-4m61`; `8e2219a8c`, `1a5744173`,
  `913089896`): "rejected" shows WHO's reason, compact result card, WHO title as
  condition text, 503 shown as unavailable, strict selection check, 8 conditions per
  line, soft warnings, shared result rows.
- **DORIS engine check** (no code change): a third-party 10,010-case DorisEngine 1.2.1
  reference suite matched our server's DORIS (`whoicd/icd-api:2.6.0`, engine 1.1.176)
  on cause, URI, rejection, report and errors for every case. Owner: stay on 1.1.176
  until WHO ships 1.2.1 in ICD-API.

## 2026-10-24 (late)

- **Collect Plus phase A** (`digitva-hs7e`; `18215a8aa`, `ca3a0e64e`, `85f08b5b4`):
  `APP_VARIANT=plus` build with the offline ICD-11/DORIS engine (our ICD-API 2.6.0
  NativeAOT bridge) in a bound `:icd11` service, background warm-up, engine check
  screen, profileable release, Perfetto trace sections; `scripts/android-profile.sh`,
  `scripts/android-trace.sh`. On the SM-E146B: ready about 20 s after launch, search
  35-220 ms, DORIS 7-180 ms, `:icd11` about 530 MB steady.
- **Phone app 0.3.10 offline gate** (`digitva-5u65`, `2aef46bb3`): no server calls while
  the phone has no network; one sync on reconnect. Hosted on staging as a local upload.
- **Coding screen fixes** (web `expo-web-v2026.10.24.10`, deployed at `73561675a`):
  notes panel renders above the header with a Close button, compact SmartVA and DORIS
  cards, associated VA code and case definition under the chosen cause.

## 2026-10-24

- **Death not before birth** (`digitva-08bj`): the year of death `Id10024` cannot be before the year of birth (`Id10021`, `dob_month_year` or `dob_year`; the same year is valid), and the exact death date `Id10023_b` cannot be before a partial birth date (`Id10023_a` already had the check). Definition version `2026081401-7ee547b8e7`; policy in `docs/policy/digitva-who-form-overrides.md`.
- **Native Statistics and Data management screens in the Expo web app** (`digitva-jv14`, `digitva-3f72`): `/statistics` replaces the Flask `/area/` hop (per-unit bars, drill-down, period, causes, staff view; `/area/` redirects; shown to every grant holder), and `/data` holds the data manager Overview (11 counts, URL-driven filters and sort, upstream-change review, panels, exports) and Causes tabs. Pipeline tab follows (`digitva-mmj8`). Design and inventory: `.tasks/2026-10-24-expo-dashboards-dm-mentor-district.md`; policy `docs/policy/area-dashboard.md`, `docs/policy/data-manager-workflow.md`.
- **Data manager API fixes** (`digitva-10fd`, `digitva-208a`, `digitva-4xpd`, `digitva-i347`, `digitva-ujbi`, `digitva-d92d`): redacted viewers cannot sort by coder; bad dates, schemes and day counts are 400 not 500; list rows carry `has_smartva_failed`; admin reaches the list, counts, exports and sync APIs; sync runs filter by scope before the 25-row cap; sync POSTs are rate limited; empty dates sort last; the gender filter ignores case; the area cause rows carry `suppressed`.
- **Address hints on free-text place questions** (`digitva-xrqv`): `Id10054`, `Id10055`, `Id10057`, `Id10072` gain an en + hi hint saying an address or place name is wanted, not a category. Definition version `2026081401-5a091ba784`; policy `docs/policy/digitva-who-form-overrides.md`.
- **Date of registration check** (`digitva-y5te`): `Id10071` cannot be in the future or before the date of death (year only when the day is unknown). Definition version `2026081401-0e105c1d52`; policy in `docs/policy/digitva-who-form-overrides.md`.
- **Phone app 0.3.3** (`3c2131d03`): release of everything below. CI run
  `android-v0.3.3` awaits approval; until it is pinned, staging serves a
  locally built 0.3.3 (`docs/current-state/android-release-builds.md`).
- **Consent chip and delete a never-sent draft** (`digitva-wy90`, `0a32821c0`):
  the interview shows its consent decision and lets the interviewer change it;
  an unsent draft can be deleted. The previous decision is not kept: the
  server rejects `supersedes` for unsent consents, so only the latest decision
  is sent.
- **Demo purge and station fixture** (`1f7289d3f`): the demo purge covers
  `auth_sign_in_tokens`; the station fixture is regenerated; the UI string
  source check is named once.
- **Celery beat crash loop fixed** (`44bfe72be`): a circular import of the UI
  string service crash-looped beat on staging between the first pull-only
  deploy and this fix.
- **Android `android-v0.3.2` hosted on servers** (`ec1b2d34f`): CI-built APK
  pinned in `x-release-pins`; staging deployed at `ec1b2d34f`.
- **Screenshots allowed in release APKs until 2026-10-30** (`a68e92a2d`,
  `digitva-om65`): `EXPO_PUBLIC_ALLOW_SCREENSHOTS_UNTIL`; remove afterwards.
- **Expo web `expo-web-v2026.10.24.2` to `.4`** (`.4` from `b907cd7d5`,
  pinned in `1b3760ae4`, `073490e15`, `1a429aeab`): the pins for the changes
  below. `.1` was never used.
- **Form colours follow the app theme** (`digitva-klzc`, `f273c99c7`): a
  `FormTheme` prop replaces the engine's hard-coded greens.
- **Form usability pass** (`digitva-e49e`, `digitva-man7`, `digitva-12ks`,
  `digitva-v5zz`, `digitva-kkdb` step 1, `92da1f8e7`): a problems popup whose
  rows jump to each field (Go), age assists, narration language taken from the
  script, a compact footer, a year control, safe insets, a revision reason and
  a dictation tip.
- **In-app confirm dialog and submit banner** (`digitva-8ehe`, `digitva-0d3a`,
  `00da8d2a2`): releases are confirmed in an app dialog, web submits in a
  banner, instead of the browser's.
- **Interviewer FAQ and daily update check** (`digitva-zgl2`, `digitva-2vrs`,
  `a9bfd29fe`, `c77dba3e6`): the Help sheet carries the FAQ; the phone checks
  once a day for a newer APK and offers it only when its link is https.
  `c502a2bc0`: the server tells the phone which APK version it offers.
- **Attachments in phone interviews** (`3a19c7aad`, `061360ca4`,
  `50cafaf56`): audio recording, photos and PDFs; interviews started without a
  case can carry them; narrative recordings pause and resume.
- **Phone clock check** (`digitva-ltqg`, `57adf7bbc`, `05d3b3a7e`): the server
  records each upload's clock offset and flags a wrong clock; the phone warns
  above 5 minutes and blocks data entry above 4 hours, measured from the
  server `Date` header and saved with the check.
- **Azure machine translation of missing UI strings** (`digitva-cqw9`,
  `9dd2440d3`): drafts in the Indian languages saved as candidates an admin
  reviews, never live; migration `q7c2n5x9d4b8`; `1f7289d3f` fixes a
  constraint name with `89f755b1156c`. Azure Translator is configured and
  verified on staging (2 Punjabi drafts).
- **Users screen redesign** (`digitva-9npt`, `f454c601d`): fly-out filters,
  quick chips, one line per user, a Status popup and the sign-in QR dialog.
  `6140258b6`: the users list filters on the server and returns a status
  summary per user.
- **Sign-in QR for data collectors and death reporters** (`digitva-3g19`,
  `digitva-mhjg`): policy `55df618f1`; server `a62b78a70` (migration
  `f3c8a1d5b7e2`); phone `e6e56b254` (redeem, six-box PIN, optional long-PIN
  field) and `9b397cc4d` (PIN longer than six digits, fingerprint or phone
  screen-lock unlock, the screen-lock weakness stated plainly). Security
  review done.
- **Phone consent parity and owner form defaults** (`99b340c5c`): the phone
  asks for respondent consent, explains refused uploads, defaults `Id10051`
  yes and `Id10053` "-", and prefills residence `Id10055`.
- **Phone app polish** (`c96197359`): only work that can be sent counts as
  unsent ("unsent" means ready to send), the phone says why anything stays,
  and the language switch sits in the header.
- **Names on coding screens** (`9ee184c5c`): shown to coders cleared for
  personal data and to the submitter in a self-coding project.
- **Phone shell** (`2ea4f8d5a`, `e6f60fa81`, `80be9f235`): one toast system,
  full-height forms, a header, bottom tabs, account menu, Settings, Help and
  an exportable error log; a Home dashboard, a searchable Interviews list and
  site picker, deceased names on rows, empty, loading and offline states.
- **CI builds the server image** (`7e2174a14`, `server-images.yml`): pushes
  `ghcr.io/drguptavivek/digitva-app:<sha>` (public package); servers only pull
  (`docker-compose.images.yml`, `make prod-pull`, `scripts/deploy-server.sh
  <sha>`). Staging adopted it 2026-10-24: first pull-only deploy `1a429aeab`,
  then `1b3760ae4`, `44bfe72be`, `ec1b2d34f` (migrations `e7b2c4d8f1a3`,
  `f3c8a1d5b7e2`, `q7c2n5x9d4b8`, `89f755b1156c`; analytics MV refreshed;
  build cache pruned).
- **Full suite**: 6226 passed on 2026-10-24, then the 2 failures were fixed. An
  earlier 252-failure run came from stale test databases (`create_all` never
  adds columns): drop `minerva_test_*` after schema changes.

## 2026-10-23

- **`finalAgeInYears` on web and app submissions** (`digitva-wsab`): set by
  the ND01 rule (ageInYears, else ageInYears2, else "000") so `va_deceased_age`
  is no longer 0 ("Age: 0" on coding cards); migration `e7b2c4d8f1a3` backfills
  existing web/device payloads in place, reversibly. Refresh the analytics MV
  after it runs. `docs/policy/who-2022-age-derivation.md`.
- **Expo web `expo-web-v2026.10.23.3`** (from `d31d1ef8d`: Training menu and screens) pinned in `x-release-pins`.
- **Training in the Expo app** (`digitva-r2pf`, `digitva-rcwt`): a Training
  menu (Interview, Coding, Review by training role) and `/app/training`;
  every request excludes the training project by default (Flask and API),
  `?training=1` widens to it only for an active participant, trainer tools opt
  out; one active allocation per coder/reviewer per side (migration
  `d6a1f3b8c2e4`). `docs/policy/training-demo-project.md`.
- **Phone app 0.3.2** (`digitva-zm9w`, `digitva-2cy0`): transactions stay on
  the keyed SQLCipher connection (expo-sqlite's exclusive transaction opened
  an unkeyed one) and `busy_timeout` 5 s; background refresh never redraws an
  open form, failures are a toast with the Ref line and back off; Refresh
  spinner; the Ref line keeps native function names and the cause; emblem
  icon; `.dev` debug variant; screenshots allowed in builds that set
  `EXPO_PUBLIC_ALLOW_SCREENSHOTS_UNTIL` (temporary, until 2026-10-30,
  `digitva-om65`).
- **Android `android-v0.3.1`** (CI run 39938767176 from `8da64237c`, Ref line
  under generic errors) published and pinned for `/download/android`.
- **Expo web `expo-web-v2026.10.23.2`** (from `a531ba664`: Ref line, server
  reason and Fix line on refused submits) pinned in `x-release-pins`.
- **Unknown exact date of death** (owner 2026-10-23): when `Id10022` is not
  yes and `Id10024` holds the year, the case gets 1 July of that year (capped
  at today), never replacing a date on file; web submit, revision and ODK case
  creation. A direct start with only the year no longer fails at submit.
  `docs/policy/web-intake.md`.
- **Identity refusals name the questions**: the 422 "Record the name, date of
  death and sex" carries `fields` (Id10017/18, Id10019, Id10022 + Id10024 or
  Id10023_a/_b), and the web page shows them as "Fix: Section › Question".
- **Web submit refusals show the server's reason** (`digitva-l3r8`): a 422 on
  interview submit shows the server's rule text (consent, Id10013, identity)
  with the `Ref:` line, and web 400/422/5xx messages carry the `Ref:` line,
  instead of "Check the highlighted fields" with nothing highlighted.
- **SmartVA batch failure split** (`digitva-vv4h`): a multi-case whole-run
  failure reruns each case alone, so one bad case no longer fails the batch.
- **Intake device submit CPU** (`digitva-9m11`, `digitva-anzv`): section
  relevance evaluated once per pass; interviewer context and locked death
  built once per submit. ~11% less CPU, 75 -> 68 SQL statements per submit.
- **Slow-request log** (`digitva-cpak`): `logs/slow_requests.log` with
  `SLOW_REQUEST_LOG_MS`; `docs/current-state/runtime-and-operations.md`.
- **Load-test harness** in `scripts/loadtest/`;
  `docs/kb/load-test-and-optimizations-2026-10.md`.
- **On-screen error reference** (`digitva-l3r8`): the Expo app's generic
  "Something went wrong" (and web "server could not complete") messages now
  carry a `Ref:` line with HTTP status, code, method and masked route (or the
  local error class), UTC time and app version, so a field screenshot is
  enough to find the failing request. No tokens, server text or answers.
- **Staging at `f23339810`**, confirmed: with the worker at `cpu_shares` 128,
  request p50 is within ~30-75 ms of the worker-paused baseline at full
  SmartVA throughput, 0 5xx. Runbook: `git submodule sync` before the update.
- **SmartVA worker CPU weight** (`digitva-g8iu`): worker containers run with
  `cpu_shares` 128 (demo worker 128 against its app's 256), so gunicorn keeps
  the CPU under load. Staging p50 coding.available 252 ms vs ~580 with `nice`
  alone (it cannot cross container cgroups) and 142 with the worker paused.
- **Expo web `expo-web-v2026.10.23.1`** (from `19c05ba07`, carries the DORIS
  remark) pinned in `x-release-pins`.
- **Staging A/B on `d120dae27`**: `nice -n 10` on the workers did not lower
  request latency; `cpu_shares` 128 did (`digitva-g8iu`).
- **Sync master data and single-form resync** (`digitva-tn21`,
  `digitva-jvgp`; `docs/current-state/odk-sync.md`). The sync upsert reads
  form type and category config once per call instead of 3 queries per
  record; the single-form force-resync fetches page by page and still commits
  once. On failure it now rolls back before recording the error, so that
  run's sync-issue ("missing in ODK") flags are not saved, as in the main sync.
- **DORIS remark in the Expo app** (`6848a6f8b`, `digitva-p9j0`): the final
  cause-of-death step sends the coder's or reviewer's remark, as the web form
  does. Needs an Expo web release and pin.
- **Deploy runbook**: `git submodule update --init vendor/smartva-analyze`
  after the pull and in rollback.
- **Celery workers under `nice -n 10`** (`digitva-295w`): main and demo
  workers yield CPU to gunicorn (demo worker also gets
  `--max-memory-per-child=300000`). Staging A/B re-test pending.
- **Allocation lock order** (`digitva-nw4b`): every coding allocation locks the
  case's workflow row before inserting the allocation; a remaining deadlock
  answers 409 `conflict`, not 500. Migration `c5e7a9b1d3f6` drops an INVALID
  leftover of its concurrent index before rebuilding it (`digitva-hbrs`; no
  new revision, a no-op where it already applied).
- **Streaming exports and paged ODK sync** (`digitva-lj7u`;
  `docs/current-state/data-manager-dashboard.md`, `odk-sync.md`). The
  data-manager submissions and SmartVA-input CSV exports stream rows through a
  server-side cursor into a temporary file: peak memory ~+60 MB at any size
  (was ~+500 MB for 7k rows), byte-identical output. The main ODK sync fetches
  and upserts 250 records at a time with one commit per form, batches its
  per-record lookups (5 -> 3 queries per record) and reads only the columns it
  needs for sync-issue marking and repair planning (+131 -> +38 MB per form).
- **Staging deployed at `f05091920`** and load-tested (200 users): 0
  allocation 500s, SmartVA queue ≤6, Python services −175 MB idle, COD refresh
  7.7 -> 2.6 s; request latency doubles while the SmartVA worker runs
  (CPU-bound, `digitva-295w`).
- **smartva-rust 3.0.2** (`digitva-kyxr`): a Rust panic in the library fails
  that one SmartVA run instead of ending the worker child; runs record the
  library's own version (`smartva_version`). Pinned in `x-release-pins`;
  `vendor/smartva-analyze` at `cb89e05`, now on SmartVA-Analyze main.
- **SmartVA backlog ~10x faster** (`digitva-96ik`;
  `docs/current-state/smartva-analysis.md` Throughput). A starting completion
  run takes up to 49 other queued completion runs of its form (same trigger,
  Redis flag `smartva-plain:<sid>`) into one engine run; their own tasks skip.
  Run-button and regenerate requests stay per case. Worker children recycle
  mainly on memory (`worker_max_memory_per_child` 300000 KB) with a 1000-task
  backstop (was 100). Dev backlog: UNSW01 20 -> 195 tasks/s, ICMR01 (6,932
  cases) 11.6 -> 136 tasks/s; stored results identical on all 7,897 cases.
- **Per-request DB work cut; lost allocation race is 409** (`digitva-lb6b`,
  `digitva-kxit`, migration `c5e7a9b1d3f6`). The unit coding-gate scan returns
  early when no gate exists; the stale-allocation sweep on allocation requests
  runs at most every 30 s (`CODING_STALE_SWEEP_MIN_INTERVAL_SECONDS`); an
  unchanged cookie session is re-saved at most once a minute
  (`SESSION_REFRESH_WINDOW_SECONDS`; idle timeout still 30 min); `area_summary`
  cached 60 s per user. Allocation 39 -> 34 statements, session-store writes
  1 -> 0 per request (`tests/test_request_query_counts.py`). Two coders racing
  for one case: the loser gets 409, not 500.
- **COD snapshot refresh ~2.5x faster** (`digitva-o7a6`, migration
  `b7e2d4f6a8c1`; `docs/current-state/submission-analytics.md`). The 34 payload
  fields come from one `jsonb_to_record` decode instead of 34 detoasts, and
  analytics MV refreshes run with JIT off. Dev REFRESH CONCURRENTLY 3.3 s ->
  1.3 s (staging estimate 7.7 s -> ~3 s); view contents identical. The upgrade
  rebuilds `va_submission_cod_snapshot_mv` WITH DATA (~1-3 s). The ICD-11
  ancestor-chain MV (`digitva-3xko`) was shelved: small gain, see the bead.
- **SmartVA in-process** (`e00cd1249`, `digitva-5gsq`; `docs/current-state/smartva-analysis.md`
  Throughput). The worker calls `libsmartva_rust.so` through ctypes instead of
  a subprocess per run: 8.2 -> 17.7 tasks/s on a real worker, identical stored
  results on all 965 UNSW01 cases. `SMARTVA_RS_LIB=""` falls back to the
  subprocess. Worker cap raised to `--max-memory-per-child=300000` (owner) for
  the child's 236-240 MiB peak.
- **Dev Postgres** memory limit 1 GB in `docker-compose.override.yml`
  (owner); production keeps 756 MiB.
- **Releases** (`441cc7457`): `android-v0.3.0` (CI run 39833431056, Latest) and
  `expo-web-v2026.10.22.5`, both from `21ccf04dc`, pinned in `x-release-pins`.

## 2026-10-22

- **Public demo** (`4178edb00`, epic `digitva-77v5`; policy
  `docs/policy/public-demo.md`, runbook
  `docs/current-state/public-demo-deployment.md`). Off unless
  `PUBLIC_DEMO_ENABLED`. Username sign-up with proof of work (web
  `/vaauth/signup`, app `/api/v1/auth/demo-signup`); phone enrolment without QR
  (`/api/v1/auth/demo-enroll`, 3 phones, a 4th replaces the oldest); own-case
  collection, coding and review; CoD report and own download
  (`/public-demo/cases`); public aggregate dashboard
  (`/public-demo/dashboard`); limits (500 accounts, least-recent idle 7+ days
  evicted, 10 submissions each, per-IP and global caps); 30-day purge, off until
  `PUBLIC_DEMO_PURGE_ENABLED`; `flask public-demo setup|purge`; own Redis
  namespace, Celery queue and beat allowlist; separate compose project
  `docker-compose.demo.yml` on network `digitva_icd`. Migration `b4d6f8a2c9e1`.
- **Process memory** (`be62e5c71`, `digitva-xt4b`, `digitva-345y`; numbers in
  `docs/current-state/runtime-and-operations.md`). pandas, numpy, pyodk and
  openpyxl import on first use (`tests/test_startup_imports.py` guards it);
  gunicorn `--preload` with `gc.freeze` before fork and a post-fork SQLAlchemy
  pool reset; beat boots without blueprints (`DIGITVA_REGISTER_ROUTES=0`);
  worker child replaced past `--max-memory-per-child`.
- **digitva-collect 0.3.0** (`21ccf04dc`): version for the release carrying the
  demo's Try-the-demo enrolment (versionCode 300).
