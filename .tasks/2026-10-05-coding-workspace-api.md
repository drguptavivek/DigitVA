# Coding and review workspace API (digitva-xl43)

- Status: phases 1 and 2 done 2026-10-05 (phase 2 uncommitted until the main session lands it); phase 3 next
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
