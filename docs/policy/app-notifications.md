---
title: App Notifications Policy
doc_type: policy
status: active
owner: engineering
last_updated: 2026-10-05
---

# App Notifications Policy

Bead `digitva-hdrv`. The owner decided on 2026-10-04 that the apps learn of
changes by polling a Flask endpoint, not through a third-party push service.

## Rules

1. **Polled, no push.** No FCM, Expo push or other third-party channel. The app
   asks `GET /api/v1/me/notifications` (foreground, about every 60 s while open,
   and a background task on Android), then runs its normal sync. Gunicorn runs a
   single sync worker, so there is no long-poll or SSE: short polls only.
2. **Ids and kinds only.** A notification holds the user it is for, a fixed
   `kind`, the project id and the ids that locate the event (case, draft,
   submission). Never a name, phone number, answer, reason text or free text.
3. **A nudge, not the truth.** Every user-visible state a notification points at
   is also in the synced data. A missed or lost notification costs nothing but
   delay; sync stays the source of truth and the app never acts on a
   notification alone.
4. **Written with the event.** The row is inserted in the transaction of the
   event that causes it, so a rolled-back event leaves no notification. Fan-out
   is bounded (at most 200 recipients per event).
5. **Own rows only.** A request returns the caller's rows, for either
   credential; there is nothing to authorize beyond being signed in.
6. **30-day retention.** A daily Celery beat task deletes older rows in
   batches.
7. **Redis only speeds serving.** Postgres is the truth. Redis keeps the newest
   id per user for 5 minutes so that an empty poll costs no database query; a
   Redis failure falls back to the database.

## Kinds built

| Kind | Fired when | Told |
|---|---|---|
| `revision_requested` | a coder or reviewer sends a submitted interview back, or a supervisor, data manager or admin reopens it for revision | the interviewer of the submission |
| `other_draft_started` | an interviewer starts a new draft on a case where others hold open drafts | those other holders |
| `case_submitted_by_other` | a complete submission closes a case | every other interviewer still holding an open draft on it |
| `case_reopened` | a supervisor reopens a terminal case | the case's starter and open draft holders (not the supervisor) |

Not built: `case_registered_in_my_unit` (there is no cheap, bounded way to list
the interviewers who reach a unit: grants sit at project, site and ancestor-unit
level) and `form_version_available` (form-options `definition_sha256` already
tells the app at every sync). Session revocation needs no notification: any call
answers 401 `session_revoked`.

Current-state detail: `docs/current-state/api-v1.md`,
`docs/current-state/data-model.md`, `docs/current-state/device-collection-api.md`.
