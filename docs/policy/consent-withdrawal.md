---
title: Respondent Consent Withdrawal on a Submitted Case
doc_type: policy
status: draft
owner: engineering
last_updated: 2026-11-20
---

# Respondent consent withdrawal on a submitted case

Owner decision 2026-11-20, tracked in `digitva-4gu7` (DPDP Act s6(4) and
s6(6)). A respondent (informant) may withdraw consent after the interview was
submitted. Staff record the withdrawal on the case; from then on the case is
no longer used anywhere. The data is kept but sealed; erasure is a separate,
explicit admin step and is not part of this policy. The ODK source is never
touched. De-identified data already shared before the withdrawal is out of
scope (the privacy page says so).

## 1. Who records it

An admin, or a data manager, In-charge (`site_pi` at a unit) or project PI
whose grant covers the case: the data-manager shaped grants of
`authz.supervision.dm_shaped_grant`, the same rule as confirming an already
coded duplicate. A data manager at any scope (unit, project-site or whole
project) is covered, on tree and non-tree projects alike (owner, 2026-11-20:
a project-level data manager may record too); the project PI and the
In-charge keep the rules of that grant. Coders, reviewers, interviewers and interview supervisors
without such a grant cannot. A case outside the caller's reach answers 404.
Only a case in state `submitted` takes a withdrawal (409 otherwise); a second
withdrawal on the same case is refused (409).

## 2. What is recorded

Table `va_consent_withdrawals` (one active row per case):

| Field | Rule |
| --- | --- |
| `requested_by` | Required, at most 200 characters, e.g. "informant's son". The only person text; never logged, never in an audit reason. |
| `requested_on` | Required date, not in the future. |
| `channel` | `contact_form`, `phone`, `in_person`, `email` or `other`. |
| `contact_reference` | Optional, at most 100 characters. Contact-form messages are not stored by the app (section 7 of [public-privacy-and-data-requests.md](public-privacy-and-data-requests.md)), so this is a pointer such as the message date, never the sender's address. |
| `note` | Optional, at most 2000 characters. |
| `recorded_by`, `recorded_at` | The staff member and server time. |

It is not a `va_consent_records` event: those rows need a notice version and
the interview's consent mode, are append-only, and carry no informant text.

Audit: each record, undo and admin view of a withdrawn case writes one
`map_case_transitions` row (state unchanged): `consent_withdrawn` (reason:
the channel code), `consent_withdrawal_undone` (reason: the admin's reason),
`consent_withdrawn_case_viewed`.

## 3. Effect: excluded everywhere

Recording sets `va_death_register.consent_withdrawn_at`. The shared exclusion
rule (`app/services/duplicate_exclusion.py`, the one that keeps confirmed
duplicates out) reads that column in the same subquery, so the case's
submission leaves every coding reader at once: coding and review pools,
allocation and pick, direct coding open, KPIs and dashboards, the public home
statistics, analytics over the materialized views (applied at query time, so
no view is rebuilt), exports and research datasets, the mentor view and the
interviewer's own counts. Case-level readers that filter the register's
status directly (area dashboard, DM KPI outcomes, case list, supervision
list, user home) add `not_withdrawn_case_condition`.

In-progress work stops: an active coding or review allocation is released as
on a timed-out allocation; finished coding is kept, sealed with the case. A
coder or reviewer acting on the case gets the existing refusal (409,
`conflict`) with the message that the respondent withdrew consent; no new
error code, so older apps show it as any refusal.

## 4. Sealed

The case and its content are visible to admins only. Everyone else gets the
existing not-found answer on the supervision case and its actions, and the
case leaves every list. An admin opening the case writes an audit row.

Enforcement is in the authz layer: for a non-admin, `scope_filter` ANDs
`duplicate_exclusion.not_withdrawn_submission_condition` (a correlated
`NOT EXISTS` on `va_death_register.va_sid`, index
`ix_va_death_register_va_sid`) into every submission action except `CODE`,
`RECODE` and `REVIEW`, so `can` and `require` refuse too, as not found (404).
That covers the read-only workspace (`?mode=view`, categories, note), the
coding and reviewing view pages and their partials, attachments, workflow
events, data-manager triage and sync, pin, the unrouted queue and the
`LIST_DATA` lists. `CODE`, `RECODE` and `REVIEW` keep the workflow's 409
`conflict` of section 3 so older apps show the refusal they show today.
Confirmed duplicates are not sealed in authz. Outside authz: the
interviewer's own draft routes (`web_intake_service.get_draft` and
`list_drafts`: draft, answers and attachment bytes answer 404, and the
draft leaves the list), `may_read_submitted_answers` (interviewer and
supervisor `?mode=view`), and an offline coding pushed or applied for the
case (refused `not_available`, a receipt as for any unavailable case; the
interview itself is kept). The server sends no case to a phone for coding
(offline coding is the interviewer's own interview), and ODK re-sync never
writes `consent_withdrawn_at`.

## 5. Undo

An admin may undo a mistaken record with a required reason (at most 200
characters). The row keeps `undone_by`, `undone_at`, `undo_reason`; the
case's column is cleared and the case returns everywhere in the workflow
state it kept (a released allocation stays released).

## 6. API and screens

`POST /api/v1/intake/supervision/cases/<death_id>/consent-withdrawal` and
`.../consent-withdrawal/undo` ([api-v1.md](../current-state/api-v1.md)).
Both are browser-session routes with `X-CSRFToken`. The Expo web supervision
case row shows "Record consent withdrawal" (with a confirmation) where
`can_record_consent_withdrawal` is true; an admin sees a withdrawn banner and
"Undo".

### Withdrawn cases page (admin)

The Expo web page "Withdrawn cases" (`/withdrawn-cases`, in More for an
admin only) lists the cases with a withdrawal, newest recorded first: case
id (`unique_id`), project, date asked (`requested_on`), recorded at, channel,
recorded by (staff name) and whether it was undone (undone records are
hidden unless "Include undone records" is on). It can filter by project id
and pages 100 at a time. The list never carries `requested_by`, the note or
the contact reference (person text); a row opens the sealed case detail,
which shows them with the banner and "Undo withdrawal". Data:
`GET /api/v1/admin/consent-withdrawals` ([api-v1.md](../current-state/api-v1.md)).
