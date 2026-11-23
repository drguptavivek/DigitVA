# Supervisor corrections: death report and interview

- Status: in progress
- Priority: P1
- Created: 2026-11-23
- Beads: digitva-6dh9 (server), digitva-5izv (supervision UI), digitva-76de (death edit + village)
- Policy: docs/policy/interview-revisions.md "Supervisor correction";
  docs/policy/web-intake.md "Supervisors"

## Goal

A supervisor of a cadre ticked "Can edit interviews" corrects a submitted
interview in their reach until the coder finalises; any supervisor corrects
the death report until an interview is completed; supervision rows show the
village and "Last edited by". Simplest, frictionless; reuse existing screens
and endpoints, no new screens.

## Facts that shape it

- Supervision UI is web-only (Expo web export): native `app/supervision.tsx`
  redirects to the worklist. No native work: native supervision does not exist.
- Web interview revision already exists: `/interview` with `revisionDraftId,
  revisionProjectId, revisionSiteId, revisionVaSid`; loads `GET
  /intake/drafts/<id>` (owner-only), posts `POST
  /intake/submissions/<va_sid>/revisions` (interviewer-only, via
  `find_own_submission`).
- Web death edit already exists: `/death-registration?deathId=<id>` loads
  `GET /intake/cases/<id>` (interviewer-only) and PATCHes `/deaths/<id>`
  (supervisors already allowed by the service). The screen is read-only once
  submitted/completed, matching the server's `case_completed` rule.
- `case_transition_service.supervising_grant(user, case)` returns
  `(grant_id, cadre_id)`.
- `address_village_ward` is a sealed PII column: it opens per row like
  `deceased_name` but cannot be filtered in SQL.

## Server (one writer)

1. `map_org_level_cadre.can_edit_interviews` boolean, default false, additive
   migration on head `f4c2a8e6b1d9`. Only settable while
   `can_supervise_interviews` (unset it when that is unset). Plumb like
   `can_report_deaths`: `list_level_cadres`, `upsert_level_cadre`, admin PUT
   `/level-cadres`, `level_cadres` workbook sheet (export + import), grid
   checkbox and table cell in `admin/panels/organization.html`, help text.
2. `may_supervisor_edit(user, death) -> bool`: `supervising_grant` gives the
   grant; its cadre at the grant unit's level has `can_edit_interviews` on an
   active grid row. Grant role must be `interview_supervisor` (not data
   manager / In-charge / PI / admin).
3. Reuse the interviewer endpoints, no new routes:
   - `GET /intake/drafts/<id>`: also served to a supervisor-editor for a
     *submitted* draft of a case they may edit (same reply shape).
   - `POST /intake/submissions/<va_sid>/revisions`: add `interview_supervisor`
     to the role gate; `revise_submission` finds the draft by owner OR by
     supervisor-editor. Supervisor must send `reason_code
     = supervisor_correction` (422 otherwise; interviewers may not send it).
     Same window, locks and refusals as the interviewer. Payload version
     `created_by` = supervisor; release/reopen/route audit source
     `supervisor_revision`. `va_data_collector` unchanged. Last update wins.
   - `GET /intake/cases/<id>` (death edit prefill): also served to a
     supervisor of the case, as `update_death` already falls back.
4. Supervision rows (`serialize_supervised_row` / `_supervised_rows`):
   `village_ward` (PII-gated like the name), `last_edited_by_name` +
   `last_edited_at` from the active payload version when it is a revision
   (batched, no N+1). Case detail (`GET /supervision/cases/<id>`) adds
   `edit_interview`: `{draft_id, va_sid, project_id, site_id}` when
   `may_supervisor_edit` and the submission is revisable now, else null; and
   `can_edit_death` (edit open: not completed, not details_pending, not
   closed).
5. No village filter: the column is sealed. Policy updated to say so.

## Expo web (one writer, after the API contract above)

1. `SupervisedCase` type: `village_ward`, `last_edited_by_name`,
   `last_edited_at`, `edit_interview`, `can_edit_death`.
2. `CaseSummary`: village next to unit; "Last edited by {name}, {date}" line.
3. `SupervisionCaseDetail`: "Edit interview" button when `edit_interview`
   -> `router.push("/interview", {revision params, revisionBy: "supervisor"})`;
   "Edit death report" when `can_edit_death` -> `/death-registration?deathId=`.
4. `InterviewScreen` with `revisionBy=supervisor`: no reason picker, sends
   `supervisor_correction`; otherwise unchanged. Return to supervision after.
5. Strings in en.json and hi.json.

## Tests

Server: tick off -> 404; tick on in reach -> new version, release, created_by
supervisor; out of reach -> 404; protected state -> 409 revision_locked;
interviewer sending supervisor_correction -> 422; draft GET for supervisor;
case GET for supervisor; rows carry village/last edited; grid flag plumbing
and the supervise-unset rule; migration up/down.
Expo: supervision-screen tests for the two buttons and the row lines; the
interview screen's supervisor mode; i18n checks; `make check-web`.

## Code guidance from the spaghetti audit (digitva-r8nh), apply in review and later briefs

Server:
- Authz predicate `edits_interviews` lives in `app/services/authz/supervision.py`
  beside `supervising_grant` (one EXISTS query). No authz in
  web_intake_service / case_transition_service; no inline grant queries in routes.
- New small module `app/services/intake_revision_access.py`:
  `find_revisable_submission(user, va_sid) -> (draft, editor)` ("owner" |
  "supervisor"), `check_revision_reason(editor, reason_code)`,
  `draft_reachable_by(user, draft)` used by both get_draft and case_detail.
  `revise_submission` calls it at its one lookup point; no new branch inside it.
  Reason rule in the service only, not the route.
- Rows: one batched last-edited query per page; `should_redact_pii` once per
  request; village_ward via the deceased_name PII path.
- `supervisor_revision` defined once beside the other release sources;
  dm_kpi SQL imports the constant.
- organization_service mirrors can_report_deaths; no inline growth of
  bulk_apply_project_users_grid.
- Errors via request_helpers.error, bodies via parse_body / optional_object_body.

Phone auth:
- Add interview_supervisor to `NATIVE_DEVICE_ROLES` (authz/grants.py), the single
  source; no new g.bearer_auth reads. `edits_interviews` returns False under
  bearer (~supervision.py 227) and dm_shaped_grant None: decide per predicate in
  one explicit authz rule (e.g. a device_ok set). has_device_access: one clause
  `resolved.of((interview_supervisor,), virtual=False)` with opens_gate.
- data_manager on the phone is NOT included: owner decision + policy first.

Expo:
- Move src/web/Supervision* to a neutral src/supervision/ first (pure move),
  then import from web and native.
- API calls in src/supervision/api.ts style; nothing added to src/api.ts.
- Native revision/register supervisor mode as a prop + small hook; shared
  rules in registrationRules.ts; no raw SQL in components (drafts.ts helper);
  strings via t() with hi.json; error codes as constants.
- r8nh.1 (audit session) is rewriting mobile src/revisions.ts in a worktree:
  build the native revision step on top of it once merged.
