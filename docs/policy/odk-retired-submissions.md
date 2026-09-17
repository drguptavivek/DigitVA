---
title: ODK Retired Submissions Policy
doc_type: policy
status: active
owner: engineering
last_updated: 2026-09-17
---

# ODK Retired Submissions Policy

## Rule

A submission whose `va_submissions.va_sync_issue_code` is `missing_in_odk` is
**retired from ODK**: it exists locally but was absent from the active
submission list of its mapped ODK form on the last sync. Retired submissions
are **never deleted** and all their history is kept, but by default they are
**not codeable and not counted**.

ODK Central is the source of truth for whether a submission exists. Sync sets
the flag when a submission disappears and clears it automatically if the
submission reappears, at which point the submission resumes normally.

The flag is **orthogonal to workflow state**. No workflow state is added or
changed when a submission is retired; whatever state it holds is kept, so a
submission that reappears continues from where it was.

## Single definition

Every surface below uses the one predicate in
[`app/services/odk_retirement_service.py`](../../app/services/odk_retirement_service.py)
(`submission_is_in_odk()` / `is_submission_retired()`), never a locally
re-derived comparison on `va_sync_issue_code`.

## Coding

Retired submissions are excluded from:

- the coder random pool and the pick-and-choose list;
- the demo/training pool;
- the reviewer-eligible pool;
- every "start"/"pick" entry validator. A direct URL to start or pick a
  retired submission is refused with a clear "no longer in ODK" message.
- recode: a recode creates a new coding allocation, so a retired submission
  is not offered for recode and a recode request is refused.

Active allocations are **not** released when a submission becomes retired:
they run to the normal allocation timeout. Resuming an existing active
allocation on a retired submission is therefore still permitted; only new
allocations are blocked. Coding already completed on a retired submission is
kept unchanged.

## Counting and reporting

Retired submissions are excluded **by default** from:

- the data-manager submission list (default filter is *in sync*; the filter
  still offers *Missing in ODK* and *All*);
- data-manager KPIs and the KPI daily grid;
- analytics materialized-view consumers (dashboards, COD bucket reporting,
  site-PI reporting);
- exports.

They remain **explicitly visible**:

- the data-manager dashboard shows a "Missing in ODK" count so a gap between
  DigitVA and Central is self-explaining;
- the data-manager list can be filtered to show them;
- the admin/data-manager read-only submission view stays available.

Mechanically the core analytics MV carries an `odk_missing` boolean so
consumers can filter without losing the explicit count; retired rows are not
removed from the MV.

## Attachments and the Central-backed attachment plan

Central purges a deleted submission's attachments after its trash window, so a
retired submission usually has **no remote source**. Therefore:

- attachment copies (originals and MP3 derivatives) of retired submissions are
  **never deleted**; they are the archival copy. The rule is about *deleting*,
  not about which DigitVA store holds them: a retired submission's attachments
  are uploaded into the DigitVA S3 store like any other, and that object then
  *is* the archive;
- moving the now-redundant local file aside is therefore permitted but is not
  the default. `flask attachments local-quarantine` skips
  `local_fallback_state='retained'` rows unless `--include-retained` is given,
  and it moves files into `media/.s3-uploaded/` rather than removing them;
- the attachment service distinguishes source state `retired` from
  `missing`: `missing` means Central reports not-found and repair may be
  queued; `retired` means the submission is gone from ODK — do not probe, do
  not repair, serve the local copy if present, otherwise show unavailable.

See [ODK Central S3 Attachment Integration Plan](../planning/s3-attachment-plan.md).

## Non-goals

- No automatic deletion or archival of retired submissions.
- No new workflow state.
- No change to how sync detects absence (see
  [ODK Sync Policy](odk-sync-policy.md)).
