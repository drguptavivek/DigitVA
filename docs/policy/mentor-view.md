---
title: Mentor View Policy
doc_type: policy
status: draft
owner: engineering
last_updated: 2026-10-24
---

# Mentor View Policy

Bead `digitva-oux5` (native client: `digitva-3vj8`). Owner decisions of
2026-10-24, confirmed. Nothing here is built yet. Design notes:
`.tasks/2026-10-24-expo-dashboards-dm-mentor-district.md`, "Mentor view".

## Purpose

A mentoring institute, the district data manager and the In-charge (`site_pi`
at a unit) need to see how each coder in one district is doing, and to tell a
coder what to improve on a specific case. The area dashboard deliberately
cannot do this (next section), so this is a separate view with its own
audience, audit and data rules.

## Why the area dashboard cannot carry it

The area dashboard shows counts only, no case lists and staff names only to
viewers `should_redact_pii` allows (`docs/policy/area-dashboard.md:54-57`). Its
per-coder throughput table was cut on 2026-10-22 as not decision-useful to a
district officer or a mentor (`docs/policy/area-dashboard.md:80-92`), and
"Coder 1" pseudonyms were rejected because one coder's throughput still singles
out one person to anyone who knows the team (`docs/policy/area-dashboard.md:236-246`).
The data manager's coder statistics keep per-coder rows
(`app/routes/api/dm_kpi/dm_kpi_coders.py:53-365`, data-manager and admin only;
the page that shows them excludes viewers "because several panels name
coders", `app/routes/data_management.py:339`).

This policy answers those concerns, it does not reverse them:

1. The area dashboard stays as it is. Per-coder rows live only in the Mentor
   view, behind its own grant test, never on `/api/v1/area/*`.
2. The audience is people whose job is supervising coders. It is not a
   general viewer: a plain `collaborator` gets nothing (see "Who sees it").
3. Names are shown, not pseudonyms, because pseudonyms do not work and
   mentoring is meaningless without knowing whom to mentor. The test is still
   `should_redact_pii` (`app/services/viewer_pii_service.py:62`), so the
   decision stays in one place.
4. A coder is not ranked against others. Rows sort by name, there is no
   league table, no total row across coders and no "best/worst" marker.
5. Every open of a coder's case list is audited, so the exposure is traceable.

## Who sees it

A user sees the Mentor view for one district (a depth-1 org unit) when any
of these holds, and only for that district:

- **Mentoring-institute staff**: an active `map_mentor_institute_user` row of
  an active `mas_mentor_institute` attached by an active
  `map_mentor_institute_org_unit` row to the district
  (`app/models/mas_mentor_institute.py:44-95`;
  `app/services/mentor_institute_service.py:577-608` for the membership test,
  and `mentors_for_unit` at `:652` for the district-covers-unit join).
- **District data manager**: a `data_manager` grant whose unit covers the
  district (at or above it; `app/services/authz/grants.py:95` `covers_unit`).
- **In-charge**: a `site_pi` grant at `org_unit` scope covering the district
  (`app/services/authz/actions.py:123`, "site_pi counts only at org_unit scope").

Further rules:

- **Staff must also pass `should_redact_pii`.** A mentor whose only grant is
  plain `collaborator` is redacted by design
  (`docs/policy/organization-model.md:586-590`;
  `app/services/viewer_pii_service.py:49-59`). The view needs names, so such a
  user is refused with 403 and a message that a different grant is needed. A
  mentor with `collaborator_pii`, `coder` or `reviewer` passes. Data manager
  and `site_pi` always pass (`viewer_pii_service.py:49-59`). Open question 1.
- **Coders never see other coders.** A user whose only relevant role is
  `coder` (or `coding_tester`) gets 403. A coder who is also, say, a mentor
  staff member is judged on the other path.
- **Server-side only.** Each request re-derives the district test; the client
  list of districts is a convenience. A district outside the user's reach is
  404, as for the area API (`app/routes/api/area.py:7`), not 403. A viewer
  covering several districts picks one in a `district` parameter; the server
  never merges districts.
- **Viewing scope, never coding scope.** The view grants no right to code,
  review or recode, as in `docs/policy/area-dashboard.md:50-52`. Mentor
  institute membership gives no access beyond this view; mentor access to
  cases still comes from ordinary unit grants
  (`docs/policy/organization-model.md:576-596`).
- A viewer sees the coders holding an active `coder` grant that covers the
  district. Mentoring-institute staff who themselves code are not rows
  (`docs/policy/organization-model.md:631-633` counts them separately).
- `admin` sees every district, whole. An inactive institute, link, district
  or membership ends access on the next request (no caching beyond the
  grant cache, `app/services/authz/grant_cache.py`).

## What the view shows

Per coder, for the selected district and the period filter:

| Column | Definition |
| --- | --- |
| Ready for them | Count of submissions in `ready_for_coding` in the coder's reach, current state, not period-filtered. |
| Coded | Submissions for which the coder has an active `va_final_assessments` row with `va_finassess_createdat` in the period. |
| Reviewed, agreed | Of those, cases with an active `va_reviewer_final_assessments` row whose `va_conclusive_cod` equals the coder's. |
| Reviewed, changed | Same, with a different `va_conclusive_cod`. |
| Not codeable | Active `va_coder_review` rows by the coder (`app/models/va_coder_review.py`, not `is_tester`) created in the period. |
| Recodes | See "Definitions". |
| Last active | Most recent coding action of the coder in the district (see "Definitions"). |

Everything excludes retired submissions and confirmed duplicates
(`docs/policy/coding-workflow-state-machine.md:32-70`;
`app/services/duplicate_exclusion.py`), demo projects and `coding_tester`
output (`app/models/va_coder_review.py:30-34`;
`docs/policy/coding-workflow-state-machine.md:179-190`).

**Drill-down.** Selecting a coder lists that coder's coded cases: case id
(`va_sid`), coded date, final COD summary, review outcome (not reviewed,
reviewer agreed, reviewer changed). Each row opens the existing read-only
coded-case view (`mode=view`, authorized by `Action.VIEW` alone,
`app/routes/api/va_case.py:8-11`). Rows are only cases that viewer passes
`authz.can(user, Action.VIEW, sid)` for (`app/services/authz/predicates.py:484`);
the list filter is `scope_filter(user, Action.VIEW)` (`:430`), never a role test.

**Not shown.** Subject identity, narrative, answers and attachments are not in
this view or its API; only the read-only case view shows them, and it applies
the viewer's own redaction (`should_redact_pii`) and scope. No coder
contact details, no phone, no email, no grants. No comparison across coders.
Final COD summary follows the authority rule: reviewer COD if present, else
coder COD, never the initial COD or a draft recode
(`docs/policy/final-cod-authority.md:43-52,109-118`).

## Definitions

- **Coded**: the coder's active final COD, per
  `docs/policy/final-cod-authority.md:43-60`. Period timestamp:
  `va_final_assessments.va_finassess_createdat` of the active row
  (`app/models/va_final_assessments.py:87`). After a recode the replacement
  row is the active one, so a recoded case counts in the period of the recode
  and counts once.
- **Period**: the same four choices as the area dashboard, last 30 days,
  last 90 days, last 12 months, all time (default)
  (`docs/policy/area-dashboard.md:98-107`), applied to the timestamps in the
  table above. "Ready for them" is current state and never filtered.
- **Reviewed**: the submission has an active `va_reviewer_final_assessments`
  row, which is how reviewer secondary coding completes (state
  `reviewer_finalized`, `docs/policy/coding-workflow-state-machine.md:335-350`;
  reviewer final COD supersedes the coder's,
  `docs/policy/final-cod-authority.md:69-81`). Reviewer coding opens only
  after the recode window, in `reviewer_eligible`
  (`docs/policy/coding-workflow-state-machine.md:885-905`). Review is
  sample-based, so most coded cases are "not reviewed": that is not a
  failure and the view must not present it as one.
- **Agreed vs changed**: compare `va_conclusive_cod` of the coder's final row
  and the reviewer's, as the data manager's disagreement KPI does
  (`app/routes/api/dm_kpi/dm_kpi_coders.py:316-365`). Equal is agreed. A
  reviewer final row only exists when the reviewer submitted their own final
  COD, so there is no third "rejected" outcome
  (`docs/policy/final-cod-authority.md:63-68`: reviewer is not an
  accept/reject overlay).
- **Recode**: a `va_coding_episodes` row with `episode_type = 'recode'` and
  `started_by` the coder (`app/models/va_coding_episodes.py:12-50`), started in
  the period. Only the original coder may recode, once, within the project's
  recode window (`docs/policy/coding-workflow-state-machine.md:885-905`).
  Abandoned episodes count as recodes started. Open question 4.
- **Not codeable** by a data manager (`not_codeable_by_data_manager`) is not a
  coder outcome and is excluded
  (`docs/policy/coding-workflow-state-machine.md:299`, "data-manager triage
  does not masquerade as coder activity", `:20`).
- **Last active**: latest of the coder's final-assessment, not-codeable and
  recode-start timestamps in the district. There is no login timestamp on the
  user to use. Open question 3.

## Feedback notes (v1)

- A viewer who can see a coder's case in the Mentor view may add a note on
  that coder's specific coded case. Text, 1 to 2000 characters; the UI warns
  "Do not enter names, places, phone numbers or anything that identifies the
  person who died or the family". The server cannot detect PII, so the
  warning is the control; notes are not exported by default.
- **Append-only.** A note is never edited. The author may retract it: soft
  delete (`retracted_at`, `retracted_by`), the text stays in the table for
  audit but is no longer returned to anyone but admins. Nobody else may
  retract. Data manager and admin retraction of others' notes: open question 6.
- **The coder sees** notes on their own case (in the existing case view for
  the coder) and a "Feedback from mentors" list on the Home/coding screen
  (`GET /api/v1/feedback/mine`), newest first, with unread count. The coder may mark
  a note read (one-way). The coder sees the author's name and institute or
  role. Nobody else's notes are visible to a coder.
- A note can only target a case where the author passes the drill-down test
  above and the coder named in the note is the case's active final coder. If
  a recode or reviewer change later moves the case, the note stays attached to
  the case and its coder at the time.
- **Table**: `va_coder_feedback_notes`. Name: the other tables that hold
  per-case coding artefacts are `va_*` (`va_final_assessments`,
  `va_coder_review`, `va_coding_episodes`); `mas_`, `map_` and `auth_` are for
  masters, mappings and authorization (`AGENTS.md`, "Engineering rules"), and a
  note is none of these. Columns: `note_id` uuid PK; `va_sid` FK to
  `va_submissions` (ON DELETE CASCADE, as `va_submission_workflow` does,
  `app/models/va_submission_workflow.py:26`); `coder_user_id` FK `va_users`;
  `author_user_id` FK `va_users`; `project_id`; `org_unit_id` (the district at
  write time); `body` text; `created_at` tz-aware; `read_at` nullable;
  `retracted_at`, `retracted_by` nullable. Indexes: `(coder_user_id,
  created_at)` for the coder's list, `(va_sid)` for the case. `read_at` is the
  one in-place update besides retraction; it sits on the row because there is
  one reader. Additive, reversible migration chained on the committed head
  (`flask db heads` before and after).
- **Notification.** The existing mechanism is `notify()` writing
  `map_user_notifications` rows, polled by `GET /api/v1/me/notifications`
  (`app/services/notification_service.py:79`;
  `app/models/map_user_notifications.py:11-37`;
  `docs/policy/app-notifications.md:14-35`). Add a kind `mentor_feedback`
  (fits `String(32)`) for the coder, with `project_id` and `va_sid` only,
  written in the note's transaction. It never carries the text or author
  (`app-notifications.md:20-21`), it is a nudge, and the truth is the notes list
  and its unread count (`:22-24`), so no separate badge is needed beyond that
  count. Rows purge after 30 days (`:30`); the notes themselves do not.

## Surface and API

Web-only, cookie session, like `/api/v1/area/*`: a `before_request` of
`browser_session_only` refuses device bearer tokens with
`cookie_session_required` (`app/routes/api/request_helpers.py:56-69`;
`app/routes/api/area.py:24-28`). Native clients do not call these routes.
Client polls send `X-DigitVA-Background: 1` so they do not extend the idle
session (`app/utils/idle_session.py:5-8,26`).

Blueprint under `/api/v1/mentor` (registered beside `area`,
`app/routes/api/__init__.py:60`):

| Method and path | Purpose |
| --- | --- |
| `GET /districts` | Districts the caller may view (id, name, project). |
| `GET /coders?district=&period=` | The per-coder table. |
| `GET /coders/<coder_id>/cases?district=&period=&after=` | Drill-down, paged (at most 100 rows). Audited. |
| `POST /cases/<sid>/notes` | Create a note. JSON `{body}`. |
| `POST /notes/<note_id>/retract` | Author retracts. |
| `GET /feedback/mine`, `POST /feedback/<note_id>/read` | The coder's list and read mark; own rows only. |

Reads are `GET` with `login_required`, errors via `api_error`. State changes
(`POST`) require `X-CSRFToken` in the header, JSON included
(`docs/policy/access-control-model.md:1008`; `AGENTS.md`). Unknown or
out-of-reach district, coder or case is 404, not 403, apart from the
coder-only and plain-collaborator refusals above, which are 403.

**Rate limits** (Flask-Limiter, per user, `app/__init__.py:99-103` default 900
per hour; area endpoints use `120 per minute`, `app/routes/api/area.py:50`):
reads `120 per minute`; note creation `30 per hour` per user; retract and
read-mark `120 per minute`.

**Queries** are scoped by district in SQL, grouped per coder in one pass, and
capped at 500 coders and 100 case rows per page, as the area staff lists are
(`docs/policy/area-dashboard.md:248`). Per-user response cache of 60 seconds
at most, like `area_summary`; notes are never cached.

## Audit

- **Opening a coder's case list** is audited: actor, district, coder, period,
  row count, timestamp, written to a dedicated log line (`log_mentor_institute_action`
  style, `app/logging/va_logger.py:253-261`, key=value, no PII, no case
  text) because the event has no single submission. Listing the coders table
  is not audited per row; a list call is logged at request level only.
- **Note create and retract**: a row in `va_submissions_auditlog` for the
  case (`va_sid`, actor, role, action `mentor_note_created` or
  `mentor_note_retracted`, `va_audit_entityid` = note id;
  `app/models/va_submissions_auditlog.py:10-37`). The note text is never in
  the audit row or in logs.
- Opening the read-only case view is audited as that view already is, unchanged.

## Retention

Notes are kept as long as the case is. Retraction hides, it does not delete.
They follow the submission's lifecycle (cascade on delete) and are not part of
demo cleanup because demo projects have no Mentor view. No bulk deletion
path. Whether notes should expire is open question 7.

## Not in scope

Ranking, scores, targets or alerts; messaging between mentor and coder beyond
the one-way note; replies; mentor-edited COD; exports of the per-coder table
(the area CSV rule of "never names or ids", `app/routes/api/area.py:10-11`,
applies); native Expo screens (`digitva-3vj8`) until the web contract is
accepted.

## Owner decisions (2026-10-24)

These answer the draft's open questions and override any earlier section that
says otherwise. Items 1, 3, 4 and 6 are the owner's answers; items 2, 5, 7, 8
and 9 are the recommended defaults, pending owner review of this draft.

1. **Plain `collaborator` mentors** get the view with coder names hidden:
   coders are labelled "Coder 1", "Coder 2" (stable within one response, never
   a user id), and there is no drill-down to cases. Mentors with
   `collaborator_pii` or a coder/reviewer grant see names and the drill-down.
2. **Mentor name on the coder's side:** shown (author name and institute).
3. **"Last active"** is a real last-seen time: add login tracking (a
   `last_active_at` timestamp updated on sign-in and on authenticated use, at
   most once per few minutes per user), in an additive migration. Shown as a
   date, never a session log.
4. **Recodes:** count completed recodes only; open ones count under in progress.
5. **"Ready for them":** cases in `ready_for_coding` reachable by that coder's
   coding grant in the district (the project pool for random allocation).
6. **Retraction:** the author, an admin, or a data manager whose grant covers
   the district may retract a note. Soft delete, audited with who retracted it.
7. **Retention:** notes live as long as the case; a coder's deactivation does
   not delete them.
8. **Counts and drill-down use the same scope:** a coder's counts are computed
   over the cases the viewer may VIEW, so the list never shows fewer than the
   count.
9. **Cross-project institutes:** one picker per project and district pair.
