# Implementation plan: training session types, phone training, graduation

- Status: plan v2 (2026-11-15), against the settled spec. Supersedes v1 and its Fable review.
- Spec: docs/policy/training-session-types.md (DRAFT; its "Decisions on the review items" section
  overrides anything earlier in it). Current rule until amended: docs/policy/training-demo-project.md.
- Line numbers against HEAD `fcca7b2de`. **(unverified)** = not traced end to end.

## 0. Facts (HEAD fcca7b2de)

Already done by fcca7b2de (do not redo): reviewer_data_manager now gets only a reviewer grant
(training_demo_service.py:158-168); `writer_grants` ignores TRN01 grants; the trainer report
refuses anyone who ever held a coder participation (training_report_service.py:99-121); corpus
order is shuffled per session (`_session_permutation` :413-419); deviceid is scrubbed
(`scrub_device_ids` :783).

- Migration head `a9d3e6b1c4f8` (migrations/versions/a9d3e6b1c4f8_cod_bucket_snapshot_reason_json_import.py).
  The slots check sits in migration f6b2d8a4c1e7_training_session_coder_slots.py:41-42 and in the
  model (app/models/mas_training.py:46, `coder_slots BETWEEN 1 AND 100`). `CODER_SLOTS=20`,
  `CASES_PER_SLOT=10` (:29-31), server_default (:71).
- Other places that assume at least one slot: `_clean_coder_slots` (training_demo_service.py:391-394);
  the API default `payload.get("coder_slots", CODER_SLOTS)` (app/routes/admin_training.py:85-91);
  CLI `IntRange(1, MAX_CODER_SLOTS)` (app/commands/training_demo.py:83-88); panel
  `min="1"` (app/templates/admin/panels/training_sessions.html:32, :284).
- Case copies happen once, at creation: `create_training_session` (:607-747) copies
  `coder_slots*10` cases. `_slot_of` (:387) gives the fixed partition and `_source_order`
  (:397-410) the order. The copy loop is :662-735, `MapTrainingCase.coder_slot` :697-704, and
  attachments are copied in `_copy_attachments` (:531). Corpus list: `_corpus_sids`
  (:429-437, `training_corpus/<form_id>.txt`); `_load_source_rows` (:440) handles one form.
- Grants: `_participant_units` (:1191-1194) puts coders on the slot unit and everyone else on
  the root. `_write_participant` (:1207-1229) writes `_GRANT_ROLES[role]`. The coder language
  check `_require_coder_languages` (:1308-1312) uses the narration languages of the slot's cases
  (`_slot_languages` :1286).
- Close and reopen: `_set_session_status` (:1610-1636) flips every active participant's grants.
  On a phone, a training-only account then gets `grant_withdrawn` (device_auth_service.py:1049)
  and `401 session_revoked`. Its store is kept while unsent work remains (src/auth.ts:88, :865,
  :1078). After that, sign-in is refused with `no_interviewer_grant` (device_auth_service.py:819).
- Areas: `AREA_ROLES` (:1702-1706), `may_use_area` (:1714-1731; ignores session type), and
  `training_scope.resolve` (app/services/training_scope.py:61-84), which runs on every request.
- Graduation: `_GRADUATION_ROLES` (:1520-1526) still maps reviewer_data_manager to
  reviewer + data_manager (bead digitva-xe2x); `graduation_csv` is :1530-1573. Org users import
  (app/services/project_user_import_service.py): `prepare` :329, actions at :521
  (`create_user|grant|retain|reactivate|update_cadre`), `apply` :532 (cadre and reactivation
  writes :581-585), `finalize_apply` :597.
- Self-coding is a project setting (`ProjectSettings.self_coding`, authz/grants.py:160, :419). It
  feeds `self_coding_project_ids` (web_intake_service.py:495-508), `can_code_now` (:511-524),
  `_code_now` (:5211), and access_summary_service.py:78 and :316/:349. Offline coding requires the
  project flag (offline_coding_import_service.py:408). An own interview is excluded by
  `_own_collected_condition` (coder_workflow_service.py:220-234), which `allocate_pick_form`
  (:990-1031, check at :1018-1023) and `allocate_own_case` (:1087-1115, gate at :1107) both apply.
- Pool: `_available_submission_filters` (:237-266) applies language, scope, own and training
  filters. Gates: `_coding_gate_filters` (:562), `_get_excluded_sites_for_coding` (:342).
  Random pick :918 and :1440. `get_coder_ready_stats._count_ready` (:148-155) omits the gate
  filters (existing mismatch). Language: `_narration_language_filter` (:115-119) filters only
  when the coder has languages; pick refuses a mismatch (:1025-1031).
- Interview unit comes from the payload org fields (`route_submission`, web_intake_service.py:2972);
  TRN01 has no ODK fallback.
- Client scope: every training call carries `csrf.training`, e.g. src/client/revisionList.ts:13-15
  and src/web/interviewAttachments.ts:60, :177. On native, `TrainingScope` renders nothing
  (src/AppState.tsx); web AppState.web.tsx sets it. Native project choice:
  src/ui/ProjectSelect.tsx, src/nativeRoutes/worklistParts.tsx. `/me/access` puts TRN01 under
  `training.project` (access_summary_service.py:119-155). Additive keys are safe for old APKs
  (src/api.ts, src/workspace/contracts.ts).
- `NATIVE_DEVICE_ROLES` (authz/grants.py:88) has no interview_supervisor, so supervisors are web
  only, as the spec now says.
- Profile: there is no self-service language edit (app/routes/api/profile.py has only PATCH
  timezone, job-title and interviewer). Admin writers are routes/admin.py and data_management.py.
- Maestro flows: mobile/digitva-collect/.maestro/flows (70-interview-send, 82/83 coding,
  90 profile; 96/97/98 are free).

## Phase 0: policy baselines and bead (docs only; lands first)

1. docs/policy/training-demo-project.md: add a pointer to the session-types spec.
   - Amend "No generated accounts" (:45): an admin-run session import creates accounts through
     the org users import rules.
   - Amend "English forms only" (:21): any interview language. Supervisors are web only.
   - Graduation (:323): the screen, coder and interviewer only.
   - Trainer report (:335): admin-only for typed sessions; legacy sessions unchanged.
   - Close: grants stop, practice interviews are kept, sync before close.
2. docs/policy/coding-workflow-state-machine.md:
   - New "Coder coding languages" baseline: who sets them (admin, manager, and the coder in
     their profile), and that the setting narrows pool and pick.
   - "Forms pending coding": the allocation predicate without the language filter, counts
     only.
   - Self-coding (:814): add the per-session training grant route.
3. Promote training-session-types.md from DRAFT once the owner signs. Keep bead digitva-xe2x
   open for phase 3.

## Phase 1: session type and per-coder copies (server and migration; old APKs unaffected)

Migration (down_revision `a9d3e6b1c4f8`):
- Add `mas_training_sessions.session_type VARCHAR(16) NULL`, with check
  `IN ('interviewer','coder','self_coding')`. NULL means legacy mixed (S001, S002), unchanged.
- Replace the slots check with `coder_slots BETWEEN 0 AND 100 AND (coder_slots = 0) =
  (session_type IS NOT DISTINCT FROM 'interviewer')`. Downgrade is refused while a typed row
  exists.
- Mirror the check in mas_training.py:46.

Service:
- `create_training_session(..., session_type)` requires a type for new sessions (`type_required`).
  - The CLI gets `--type`, and `IntRange(0, MAX)` with a cross-check.
  - The route takes `session_type`; the slots default is applied per type (interviewer 0,
    otherwise `CODER_SLOTS`).
  - `_clean_coder_slots` takes the type.
  - Typed sessions copy nothing at creation: they create the root, plus slot units for
    coder/self_coding. Legacy creation stays callable only for tests (no type means refused at
    the route).
- Per-coder copies: when a coder participation first takes a slot in a coder or self_coding
  session, the case-copy loop (:662-735) is factored out as `_copy_cases(session_row, slot,
  source_rows, actor, created_objects)`.
  - It copies 10 draws from the 200 into that slot. Draw with
    `random.Random(f"{session_id}:{slot}").sample(range(n), 10)`; copies are numbered
    `max(case_number)+1...`.
  - Attachments are copied the same way. All of this happens in the add transaction, and objects
    are removed on rollback.
  - Re-adding the same coder keeps the slot and the copies (as today). `_slot_of` and
    `_source_order` stay for legacy only.
- Corpus: `training_corpus/english_v1.txt` holds `<va_form_id>,<va_sid>` lines (multi-form).
  - `_load_source_rows` and `_copy_attachments` work per row's form.
  - `check-source --corpus english_v1`.
  - Until the owner supplies the list, typed coder/self_coding sessions are refused with
    `corpus_missing`. Tests use a fixture corpus.
- Grant roles by (type, role) replace `_GRANT_ROLES[role]`:
  | type | roles accepted | grants written |
  | --- | --- | --- |
  | interviewer | interviewer; interview_supervisor (single add only, open item) | interviewer or supervisor on root |
  | coder | coder | coder on slot unit |
  | self_coding | coder | coder + interviewer on slot unit (`grant_ids` already a list) |
  | NULL | as today | as today |
  - Refuse others with `role_not_in_session_type` in add_participant (:1246) and
    bulk_add_participants (:1349). death_reporter and reviewer_data_manager are refused in
    typed sessions.
  - The self-coding interviewer grant on the slot unit keeps own interviews inside the coder's
    slot scope; the trainee cadre allows it (confirmed in v1 review).
- `_session_fields` (:910), list/get, `/training/me`, and `/me/access` `training.session_types`
  all gain `session_type` as an additive key.
- `may_use_area` and `areas_of` join on session type:
  - interview: interviewer/supervisor in NULL or interviewer; coder in self_coding.
  - coding: coder in any.
  - review: NULL only.
- Trainer report: `authorized_session` (:99) and `sessions_for_viewer` admit non-admins only
  when `session_type IS NULL`. Typed sessions are admin-only. Legacy reviewer_data_manager
  participations keep their current access on S001/S002 and lose nothing.
- Panel (training_sessions.html): a type select at create, slots hidden for interviewer,
  `min` 0/1 per type, and the type shown in the list and summary.

## Phase 2: self-coding per session and queues (server; enforced before any client shows it)

- TRN01 `self_coding_enabled` stays off. Add `training_self_coding_ids(user)`: the slot unit ids
  of the user's active coder participations in active self_coding sessions, memoised on `g`.
  - `_own_collected_condition` exempts TRN01 drafts whose case sits on one of those units.
  - `allocate_own_case` (:1107) also allows that case.
  - `self_coding_project_ids` adds TRN01 for such a user, which drives `can_code_now`,
    `_code_now` and access summary code-now.
  - Offline coding stays off (offline_coding_import_service.py:408 unchanged).
- Queues on the training side only (scope ONLY):
  - `_available_submission_filters(..., queue="standard"|"own")`, default `standard`.
  - standard = `va_sid IN (map_training_cases for the user's active coder slots)`.
  - own = the user's submitted TRN01 draft AND NOT IN map_training_cases AND on their
    self-coding unit.
  - Every pool, count, random allocation (:918, :1440) and pick list defaults to standard.
  - `GET /api/v1/coding/available?queue=own|standard` and `/coding/stats?queue=`; any other
    value gives 400. A coder session asking for own gets 403.
- Pick enforcement: `allocate_pick_form` in TRN01 refuses (403 `not_in_your_training_set`) a sid
  that is neither in the user's map_training_cases nor their own self-coding draft. The own case
  goes through `own_case` or `queue=own`.
  - This also closes the legacy leak: an S001 root interviewer's case could land in any slot
    pool.
- Language in self_coding: an own interview is coded in its interview language. The own queue,
  and an own-case pick, skip the coder-language filter and refusal (:1025) only for that case.
  The standard set stays English.
- "X of Y" counts: `/coding/stats` gains `training_queues: {own:{coded,total}|null,
  standard:{coded,total}}`. coded = active final per training_report_service.py (:194-207);
  own total = the user's submitted drafts in the session.
- Prepared-case delay (verify): with no attachments, SmartVA is queued after commit
  (web_intake_service.py:2997-3002, 30 s sweep in sync_tasks.py:2360). With attachments it waits
  in `attachment_sync_pending`. If the mover is hourly, add an after-commit repair. The client
  retries `not_ready` (src/workspace/CodeNowButton.tsx:12, :83).

## Phase 3: admin import and graduation (server and admin panel; admin-only)

- `import_trainees(session_ref, rows, kind, actor, dry_run)`; route
  `POST /admin/api/training/sessions/<ref>/import`, admin only (`_require_admin` :182).
  - Rows: email or phone, plus name. A username column is refused. The file is parsed by
    `tabular_import_service.parse_table`.
  - `kind`: interviewer session gives interviewer; coder session gives coder; self_coding gives
    both (one coder participation, which carries both grants).
  - Create missing accounts through the org users import (`prepare`/`apply`/`finalize_apply`,
    :329/:532/:597): same identity rules, email invite, one-time mobile code shown once
    (no-store response), QR as today. Then `bulk_add_participants`. One transaction, all or
    nothing.
  - New coders get `vacode_language=["english"]`. For existing coders, "english" is added only
    if missing (it never removes a language; show the change in the preview).
- Graduation:
  - `GET .../sessions/<ref>/trainees` returns each trainee with their role (coder, interviewer,
    or both for self_coding).
  - `POST .../sessions/<ref>/graduate {project_id, rows:[{user_id, org_unit_code, cadre_code,
    language_codes}], dry_run, confirm:[user_id]}`.
  - Refuse a TRN01 or demo project (`is_demo`/training flag) with `target_not_allowed`.
  - Grants coder and/or interviewer only, built as org import rows; per-row refusal reasons
    come from refactored `prepare` output.
  - `update_cadre` and `reactivate` rows (:521, :581-585) are listed separately in the preview
    and applied only if the user_id is in `confirm`.
  - `retain` means a row already granted; saving again changes nothing. Languages are written
    with the admin.py validation.
  - Save per row = the same call with one row. Save all applies accepted rows and leaves
    refused ones listed.
  - Unit tree and cadres come from `/admin/api/organization/<pid>/units|cadres|level-cadres`
    (admin_organization.py:179, :469, :508).
- Panel: replace the graduation block with:
  - a project select;
  - a top cadre, overridable per row;
  - a searchable unit datalist per row and a languages multi-select;
  - Preview, Save, Save all, and a confirm list.
- Fix digitva-xe2x: `_GRADUATION_ROLES` emits coder and interviewer only (reviewer_data_manager,
  supervisor and death_reporter give no row). Keep `graduation.csv` for one release, then remove
  it.
- Close checklist: the close dialog lists per trainee their open server drafts and last sync,
  plus "graduated" status, and needs a ticked "every trainee has synced" box.
  `_set_session_status` is unchanged: grants are deactivated. Non-graduated training-only
  phones get `session_revoked`, and unsent drafts stay on the phone (auth.ts:88). No discard,
  no `training_ended`.

## Phase 4: "Your languages" and "Forms pending coding" (every project)

- `pending_by_language(user, project_id)`: one grouped query, `_available_submission_filters(...,
  languages=False)` plus `_coding_gate_filters`, `GROUP BY lower(trim(va_narration_language))`,
  with NULL or '' put in an `unrecorded` bucket. Only non-zero buckets are returned. In training
  scope it honours the standard queue.
- Fix `_count_ready` (:148-155) to apply the gates. This changes dashboard numbers; note it in
  the release notes.
- `/coding/stats` gains `languages: {mine:[...], pending:[{language,count}]}` (additive).
- `PATCH /api/v1/profile/languages` (CSRF for cookie sessions; validation as admin.py) lands
  only after the phase 0 coding-policy baseline is approved.

## Phase 5: Expo web (one bundle; web users only)

- src/workspace/QueueScreen.tsx (shared): a languages line with an edit link to settings, and
  the pending line ("Hindi 42 · Tamil 5").
  - In training: two buttons (Code from my interviews / Code from standard training set) for
    self_coding, the standard one only for coder, with "X of Y" per queue.
  - `createWorkspaceApi` (src/workspace/api.ts) passes `queue`.
- src/web/TrainingScreen.tsx and TrainingChecklist.tsx: per-type areas, no reviewing for typed
  sessions. src/web/SettingsScreen.tsx: a language editor behind the policy.
- src/ui.tsx: map `role_not_in_session_type`, `not_in_your_training_set`, `corpus_missing`.
  src/client/revisionList.ts and src/web/interviewAttachments.ts already carry `csrf.training`;
  check them under the new per-project scope.

## Phase 6: native training mode (DigitVA Collect, Android; new APK only)

- `scopeFor(access, projectId)` in src/training.ts: training=1 exactly when the selected project
  is `training.project`. src/AppState.tsx native `TrainingScope` sets `csrf.training` from the
  selected project.
- Call sites to check: sync.ts, draftSync.ts, cases.ts, attachmentUpload.ts, consent.ts,
  client/revisionList.ts, web/interviewAttachments.ts (full list unverified; grep
  `csrf.training`).
- src/ui/ProjectSelect.tsx and worklistParts.tsx: the post-PIN choice includes the training
  project while the session is active. While it is selected, show only training work and a
  "Training mode" banner. After close it disappears from `/me/access`.
- auth.ts collection access includes `training.project`, and reference data is loaded for TRN01.
- Onboarding notice, then bearer `/training/me/start` (bearer needs no special case,
  app/utils/bearer_session.py:33-41).
- Coding reuses QueueScreen through src/nativeRoutes/plusWorkspace.tsx. The app/training/*
  native redirects are replaced by native routes.
- Old APKs: they ignore `training.project`. An imported training-only account on an old APK
  signs in to an empty app. Mitigation: the training script states the minimum version, and
  sign-in refuses `app_update_required` when the user's only grants are TRN01 and the client
  version header is below the minimum (verify the header exists).
- Supervisors: web only (no change to `NATIVE_DEVICE_ROLES`).

## Strings (English and Hindi, owner-approved; list for the string files)

- Session type names: Interviewer, Coder, Self-coding.
- "Training mode" banner; "Practice: use made-up details only" plus onboarding body.
- "Code from my interviews" / "Code from standard training set".
- "My interviews coded: {x} of {y}" / "Standard training set coded: {x} of {y}".
- "Your languages" / "none set" / "Forms pending coding" / "Unrecorded".
- Errors: not in your training set; role not allowed in this session type; update app to train.
- Panel (English only): import kind, close checklist, graduation preview, confirm cadre change,
  confirm reactivation.

## Tests

- pytest:
  - type and slot constraints, plus migration up/down refusal;
  - `type_required`, `role_not_in_session_type`;
  - interviewer session copies nothing;
  - coder add copies 10 own cases, overlapping draws are separate copies, re-add copies
    nothing, rollback removes objects;
  - self_coding writes 2 grants that flip on close and reopen;
  - `may_use_area` per type;
  - queue default standard everywhere (pool, random, pick list, stats); `queue=own` only in
    self_coding; pick refuses out-of-set sids;
  - own interview excluded elsewhere and codeable here; own-queue language exemption;
  - legacy S001 unchanged; report admin-only for typed and RDM still works for NULL;
  - import creates and enrols in one transaction, English default, username refused, kind per
    type;
  - graduate: only coder/interviewer, TRN01/demo refused, cadre/reactivate need confirm,
    idempotent;
  - `_GRADUATION_ROLES` fix;
  - `pending_by_language` equals pool counts with gates, trim/case/NULL buckets; `_count_ready`
    gates;
  - `/me/access` keeps old keys;
  - multi-form corpus attachments.
- Jest: `scopeFor` exact id; training-only account collection access; QueueScreen buttons and
  counts per type; error mapping; web-bundle-boundary; then `make check-web`.
- Maestro:
  - 96-training-interview-send (pick training project, banner, send);
  - 97-training-self-code (code own interview and standard set, counts);
  - 98-training-close-keeps-drafts (close with an unsent draft: session_revoked, draft kept).
  - Rerun 70, 82, 83, 90.

## Risks

- A `scopeFor` bug could send a real draft with training=1: 409, kept, not lost. Covered by
  Jest and 96.
- Copying at add makes adding a coder heavy (10 payloads plus attachments, S3). Bulk-add of 50
  is about 500 copies, the same as S001 creation; time it on staging.
- Graduation grants are immediate; project gates must limit new users (verify).
- `_count_ready` fix changes dashboard numbers.
- A training-only account on an old APK sees an empty app (mitigated above).
- Self-set languages change a manager control everywhere; this is behind the baseline.

## Remaining verification items

1. The corpus list of 200 English cases (owner), and a sample read to confirm the narratives are
   English, not Romanised Hindi.
2. A just-sent interview becomes codeable without waiting for an hourly sweep (attachment mover
   cadence).
3. The interview org fields prefill to the trainee's slot unit (`prefill_policy`,
   web_intake_service.py:527).
4. Project coding and interview gates limit a newly graduated user.
5. Whether a client version header exists for `app_update_required`.
6. How supervisors join interviewer sessions (single web add proposed).
7. Full `csrf.training` call-site list on native.

## Fable review of v2 (2026-11-15) and decisions taken (engineering, owner asleep)

Verdict: phases 0-2 can start with corrections; phases 3 and 6 need the redesign below.
Decisions folded into implementation:
- N1 import transaction: extract account creation and identity validation from
  `project_user_import_service.apply` (:545-563) / `prepare` into helpers that write no grant;
  split `bulk_add_participants` into a non-committing core + committing wrapper; `issue_code`
  flush-only on this path; the importer owns commit/rollback/_remove_objects.
- N2 new imported accounts get `vacode_language=["english"]` (coders and interviewers); verify
  "english" is an active MasLanguages code.
- N3 typed sessions check the coder's languages against the corpus language (english) before
  copying, in add and bulk dry-run; dry-run also runs corpus checks.
- N4 draw indices first and load/unseal only the 10 drawn sids; cap bulk add (50) and copy within
  the lock but with no long idle gaps; time it on staging later.
- N5 `allocate_pick_form` set check from data, independent of `own_case`.
- N6 baseline states the standard-queue filter changes what legacy coders can pick; code-now
  unit-aware; decide `case_list_service.py:1338` and `web_intake_readiness_service.py:455`.
- N7 target refusal: TRN01 (`DIGITVA_TRAINING_PROJECT_ID`) and `demo_training_enabled` projects
  (+ the public-demo project predicate from public_demo_service).
- N8 add nullable `graduated_at` on `map_training_participants` in the phase 1 migration.
- N9 graduated trainee with an unsent training draft after close: keep it, show "training closed,
  ask the trainer to reopen"; test.
- N10 phase 6 scope per draft `project_id` (`scopeFor(access, item.project_id)`), never the
  selected project; read native 404 handling first; Jest mixed-outbox test.
- N11 `app_update_required` from the sign-in body `app_version`; missing value = allow.
- N12 counts from rows, not slots*10; panel/messages updated.
- N13 service keeps `session_type=None` legacy; route and CLI require a type.
