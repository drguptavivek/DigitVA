# Coding and review workspace API (digitva-xl43)

- Status: phases 1-3 done 2026-10-05 (`eeec15eb`, `f98617f3`, phase 3 3a `digitva-xl43.4` + 3b `digitva-xl43.5`); left: `digitva-xl43.3` DORIS prefill, a read-only view mode when the app needs one
- Priority: P1
- Created: 2026-10-05

## Goal

The coding and review workspace under `/api/v1` for every client, so the
Expo app can code and review (`digitva-p6fs.4`). Owner 2026-10-05: option A,
one source of truth. Logic moves out of `va_form.renderpartial` into
services; the new routes and the existing web partials both call them; the
web screens do not change.

## Phases (one commit each)

1. Coder COD steps: `coder_cod_service` (Step 1, final COD, not codeable),
   mirroring `reviewer_coding_service`; `renderpartial` POST branches call it;
   `POST /api/v1/coding/initial|finalize|not-codeable/<va_sid>`. Fix
   `digitva-sndk` (neonate other-conditions list) on the way.
2. Case content: one service for nav, category data (PII redaction and the
   Redis section cache included), case meta, step state, saved assessments,
   SmartVA result, other-conditions options; `GET /api/v1/va/<sid>/...`;
   `renderpartial` GET branches render from it.
3. Media over `/api/v1` (bearer-capable, same `can_access_submission_attachment`
   check) and `{error, code}` on the reviewing, NQA and social-autopsy routes.
   Owner 2026-10-05 adds: reviewer queue (available cases, stats, history,
   as `/coding/available|stats|history`), reviewer release of a started
   review, and the private user note (`vausernote`) for coder and reviewer.

## Already JSON (reuse)

Allocation, release, recode, send-back, SmartVA run, NQA
(`/api/v1/va/<sid>/narrative-qa`), social autopsy (`.../social-autopsy`),
reviewer initial/final, ICD-10/ICD-11/DORIS search, workflow events.

## Done

- `digitva-xl43.1` app sign-in for coders and reviewers (owner yes,
  2026-10-05), commit `4d20ccb3`.

- `digitva-xl43.2` case content (phase 2): `app/services/case_content_service.py`
  (section data with PII redaction and the Redis cache, saved artifacts and
  step state, Step 1 prefill, SmartVA summary, blockers) with `renderpartial`
  GET rendering from it, and `GET /api/v1/va/<sid>/workspace|categories/<code>`
  (`app/routes/api/va_case.py`, `?mode=coding|reviewing`; no read-only view
  mode yet, DORIS fields deferred to `digitva-xl43.3`). The section cache key
  fixed two latent bugs: it had no role bucket (coder/reviewer legacy mapping
  versus the DB mapping of data managers and viewers shared one entry) and no
  payload version (an interviewer revision was served the old answers for 30
  minutes; `_invalidate_section_data_cache` had no callers). Key is now
  `form_data:<sid>:<payload_version_id>:<role>:<category>[:nopii]`.

## Phase 3 design (built 2026-10-05; see docs/current-state/api-v1.md for the shipped contract)

### 3a `digitva-xl43.4`: media and the private note

- Bearer works only under `/api/v1/` (`device_auth_service.request_bearer_token`),
  so media needs `/api/v1` routes. The renderer emits them for every client
  (one URL family): `_resolve_attachment_url`
  (`app/utils/va_render/va_render_06_processcategorydata.py`) is the only
  producer. Token rows: `GET /api/v1/attachments/<storage_name>`; legacy rows
  with `storage_name` NULL (1,440 of 17,142 in dev): `GET
  /api/v1/attachments/legacy/<va_form_id>/<va_filename>`. URLs keep ending in
  the original extension (templates sniff image/audio by it). New blueprint
  `app/routes/api/attachments.py`, same role list as `va_form.serve_attachment`.
- One shared authorization in `attachment_service` (the regex, record
  lookup, `can_access_submission_attachment`, the denial log) called by the
  old `/vaform/attachment` and `/vaform/media` routes (unchanged behaviour,
  kept for already-rendered pages) and the new ones; delivery stays
  `attachment_service.deliver` / `deliver_legacy_media` (local `send_file`
  with Range, S3 302 presigned, `private, no-store`, nosniff).
- New routes answer JSON `{error, code}`: 404 `not_found`, 403 `forbidden`,
  and catch `HTTPException` from delivery: 502 `upstream_error`, 503
  `unavailable` (copy `Retry-After`), all `private, no-store`.
- Bump the section cache key prefix (`form_data:` to `form_data2:` in
  `case_content_service`) so cached cookie URLs are not served after deploy.
- Device risk to check on hardware (`digitva-p6fs.5`): a native player that
  forwards `Authorization` to the S3 presigned redirect is refused by S3.
- Note: `GET/PUT /api/v1/va/<sid>/note?mode=coding|reviewing` in
  `va_case.py`; split the cheap first half of `_authorize` (mode, role,
  `require_coding_session` / `require_reviewing_session`) into
  `_authorize_session` so a note does not render every category. Own
  allocation only (the web also allows notes on its view page; widen when an
  API view mode lands). GET `{va_sid, content, updated_at}`; PUT `{content}`
  upsert, empty or not text 400 `invalid_request`, body cap 64 KB by
  `Content-Length` (413 `too_large`), 20,000 characters (422). New
  `app/services/user_note_service.py` (`get_active_note`, `save_note`) used by
  the web `vausernote` branch and the COD panel read in `va_form.py`. One
  note per user per case, shared by their coding and reviewing sessions.

### 3b `digitva-xl43.5`: reviewing errors, reviewer queue, reviewer release

- Flat `{error, code, processing?}` on `app/routes/api/reviewing.py` (today
  `_error` nests `{schema_version, error: {code, message}}` when a code is
  given), `nqa.py`, `so.py` and `va_permission_11_require_coding_access`.
  Codes at the `ReviewerCodingError` raise sites in
  `reviewer_coding_service` (keep every HTTP status): `not_found`,
  `forbidden`, `no_allocation`, `wrong_state`, `conflict`,
  `allocation_exists`, `invalid_cod`, `invalid_request`, `final_blocked`,
  `who_not_configured`, `who_unavailable`, `invalid_doris`, the `DORIS_*`
  conflicts. The web COD panel script
  (`_va_cod_assessment_panel.html`, the two DORIS-conflict readers) reads
  `data.code` and `data.error`. `nqa.py` / `so.py`: `get_json(force=True,
  silent=True)`, non-object 400 `invalid_request`.
- Reviewer queue: no service today (inline in `app/routes/reviewing.py`
  `dashboard()`). New `app/services/reviewer_dashboard_service.py`; the web
  dashboard calls it unchanged. `GET /api/v1/reviewing/stats`
  `{in_scope, completed, available, allocation}`, `/available` (exactly what
  `start_reviewer_coding` accepts: `reviewer_eligible`, REVIEW scope,
  narration language in the profile, in ODK, not a confirmed duplicate,
  active project-site) and `/history` (own active reviewer finals, VIEW
  scope, newest first), both paged `limit` (default 50, max 200) / `offset`
  with `has_more`; one query each, index-backed.
- Reviewer release: `POST /api/v1/reviewing/allocation/release`, no body,
  200 `{va_sid, workflow_state}`, 409 `no_allocation` / `wrong_state`.
  Reuses `coding_allocation_service._release_reviewer_allocation` with an
  `actor` parameter (audit carries the reviewer), and
  `reset_incomplete_reviewer_session` accepts a reviewer actor. Owner
  2026-10-05: the reviewer's saved Step 1 is kept (as on timeout); reviewer
  NQA/review and Social Autopsy analysis are cleared. Policy first:
  "Reviewer release" in `docs/policy/coding-allocation-timeouts.md`, and the
  reviewer-session text corrected (Step 1 is kept).
