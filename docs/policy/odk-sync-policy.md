---
title: ODK Sync Policy
doc_type: policy
status: active
owner: engineering
last_updated: 2026-03-24
---

# ODK Sync Policy

## Purpose

This policy defines how ODK data synchronization interacts with the coding workflow state machine. The core principle is that **finalized COD decisions must be protected from inadvertent data changes** while still allowing authorized overrides.

## Core Principles

ODK is the source of truth for submission content. All submissions present in ODK are stored in DigitVA — including those with refused or missing consent. This ensures complete auditability and allows consent corrections made in ODK to be picked up automatically on the next sync.

**Coder-finalized submissions have protected status** that prevents automatic destructive refresh without explicit authorization.

**Consent determines workflow routing, not storage.** Submissions without valid explicit consent are stored but never enter the coding workflow.

## Payload Versioning Baseline

The sync model must distinguish the current live submission row from the
specific normalized ODK payload version that produced it.

Canonical terms:

- `source submission`:
  the ODK submission identified by `va_sid`
- `payload version`:
  one concrete normalized ODK payload for that `va_sid`
- `active payload version`:
  the payload version currently accepted as the live basis for workflow,
  SmartVA, and human coding
- `pending upstream payload version`:
  a newer changed ODK payload detected while the submission is in a protected
  finalized state; it is not active until an authorized accept action
- `superseded payload version`:
  an older payload version that was previously active but has been replaced

Policy intent:

- unchanged syncs do not create a new logical payload version
- changed syncs do create a new logical payload version
- SmartVA and human COD artifacts should attach to a payload version, not only
  to `va_sid`
- `va_submissions` may remain the current active summary row, but payload
  lineage should be preserved explicitly

### Changed vs unchanged payload

A submission is considered unchanged only when the normalized synced payload is
semantically identical to the current active payload version.

This should be determined by a canonical payload fingerprint or equivalent
versioning rule, not only by ODK timestamps.

Practical implication:

- the current agreed rule is to fingerprint the full canonical normalized ODK
  payload JSON
- if `updatedAt` changes and that change is present in the normalized payload,
  the payload is treated as changed
- materially different normalized payload should be treated as a new payload
  version even if workflow routing happens later

## Consent Routing

Consent is evaluated on every upsert (insert and update). The `Id10013` field is the consent field.

### Consent validity

Consent is considered **valid** when:
- the field is present and non-empty, **and**
- the value is not `"no"`

Examples: `"yes"`, `"telephonic_consent"` → valid. `"no"`, `""`, null → refused.

### Workflow state assignment

| Condition | Workflow state set |
|---|---|
| Consent valid | `smartva_pending` in current runtime for newly synced or payload-changed submissions; target state remains `smartva_pending` until SmartVA is generated, regenerated, or explicitly failed-and-recorded |
| Consent = `"no"` | `consent_refused` |
| Consent missing / empty | `consent_refused` |

### `consent_refused` state

- Submissions are stored in full — ODK data, attachments, and metadata are all synced normally.
- The submission never enters the coding queue.
- SmartVA is not run on `consent_refused` submissions.
- If consent is corrected in ODK Central, the next sync automatically re-evaluates and transitions the submission into the coding-eligibility path.
  Current runtime: `smartva_pending` before `ready_for_coding`
  Desired target: `smartva_pending` before `ready_for_coding`
- Data managers can see and filter `consent_refused` submissions and view their count on the dashboard.

## Workflow State Guards

### Protected States

The following workflow states are **protected** from automatic ODK data refresh:

- `coder_finalized` — Final COD has been submitted and is authoritative
- `finalized_upstream_changed` — Current state key for finalized cases whose ODK data changed after finalization
- `reviewer_eligible` — Post-24-hour resting state before any optional reviewer coding
- `reviewer_coding_in_progress` — Reviewer has an active mid-session allocation;
  automatic re-routing would orphan the allocation; requires DM accept/reject
- `reviewer_finalized` — Reviewer-owned final COD is now authoritative
- `closed` — Legacy compatibility state only; if such rows exist they remain protected

Current naming:

- current persisted key: `finalized_upstream_changed`
- legacy migrated key: `revoked_va_data_changed`
- UI label: `Finalized - ODK Data Changed`

Current implementation note:

- runtime now writes `reviewer_eligible` instead of `closed` after coder
  recode-window expiry
- sync should still treat `closed` as protected if such legacy rows exist

`consent_refused` is **not** protected — ODK updates flow through freely so that consent corrections are picked up automatically.

### Non-Protected States

These states allow normal ODK sync behavior (consent re-evaluated on each update):

- `consent_refused` — ODK updates flow freely; consent corrections automatically
  re-route the submission into `smartva_pending`
- `screening_pending`
- `smartva_pending`
- `ready_for_coding`
- `coding_in_progress`
- `partial_coding_saved`
- `coder_step1_saved`
- `not_codeable_by_coder` — ODK data change deactivates the exclusion artifact
  and re-routes to `smartva_pending`; coder may re-exclude after review
- `not_codeable_by_data_manager` — ODK data change deactivates the DM exclusion
  artifact and re-routes to `smartva_pending`; DM may re-exclude after review

## Sync Operations

### Single Submission Refresh (`fetch_single`)

```
fetch_single(va_sid, force=False)
```

| Workflow State | force=False | force=True |
|---|---|---|
| Non-protected | Fetch from ODK, upsert | Fetch from ODK, upsert |
| Protected | **SKIP** — return reason | Fetch from ODK, upsert |

**Authorization for `force=True`:** Admin only

### Form-Level Sync (`fetch_form_submissions`)

```
fetch_form_submissions(form_id, force=False)
```

For each submission in the form:

| Workflow State | ODK Data Changed | force=False | force=True |
|---|---|---|---|
| Non-protected | Yes | Fetch, upsert, run SmartVA | Fetch, upsert, run SmartVA |
| Non-protected | No | Skip (no change) | Skip (no change) |
| Protected | Yes | **Mark as `finalized_upstream_changed`**, preserve workflow artifacts, require manual resolution | Admin-only explicit override path required |
| Protected | No | Skip | Skip |

### Bulk Sync (`fetch_all`)

Same behavior as form-level sync, applied across all active forms.

## Upstream Data Change Handling

When ODK data changes for a `coder_finalized` submission:

### Current Implemented Baseline

The current runtime behavior is partially aligned with this policy:

1. Protected submissions are **not** auto-reset to `ready_for_coding`
2. Existing coding artifacts are **not** destroyed on protected-state ODK update
3. The submission transitions to `finalized_upstream_changed`
4. Audit logging is written for the state transition
5. Durable upstream-change records preserve prior and incoming payload
   snapshots for the accept/reject decision path

### Remaining Gaps

The current implementation does **not yet** complete the full target behavior:

1. Runtime sync now writes active and pending payload versions, and protected
   upstream accept/reject now promotes or rejects those payload versions as the
   authoritative path
2. Historical COD is not yet uniformly linked to a specific payload version
3. SmartVA runs are not yet documented or persisted as payload-version-bound
   artifacts
4. Legacy rows using `revoked_va_data_changed` are migrated to
   `finalized_upstream_changed`

### Required Behavior

When upstream data changes for a finalized submission:

1. **Do NOT destroy workflow artifacts**
2. **Do NOT reset workflow state automatically**
3. **Transition to the finalized-upstream-change state**
   Current key: `finalized_upstream_changed`
   Legacy migrated key: `revoked_va_data_changed`
4. **Preserve historical COD** and its authority linkage relative to the
   current active payload version
5. **Preserve historical VA data** and incoming VA data as distinct payload
   versions or version-equivalent snapshots
6. **Create notification** for data managers/admins
7. **Log audit trail** with reason `upstream_data_changed`
8. **Do not activate the new payload version automatically** while the case is
   awaiting accept/reject resolution

### State Transition

```
coder_finalized --[ODK data changed]--> finalized_upstream_changed
```

This state indicates:
- The submission was previously finalized
- Upstream ODK data has changed since finalization
- The previous active payload version and authoritative COD are preserved but
  may need review
- A newer upstream payload version has been detected but is not yet the active
  coding basis
- Manual intervention required to either:
  - Accept the change and activate the new payload version for SmartVA/coding
  - Reject the change and keep the current active payload version plus current
    authoritative COD

## Historical Data Preservation

When transitioning to the finalized-upstream-change state:

| What | How |
|---|---|
| Final COD | Preserve explicit linkage to the previously authoritative final assessment for the current active payload version |
| VA data snapshot | Preserve both prior active payload and incoming changed payload; current code does this through upstream-change snapshots, while additive payload-version schema now exists for the planned general lineage cutover |
| Audit trail | `VaSubmissionsAuditlog` entries with full context |
| Notification | Created for data managers and admins |

## Payload-Version Routing Rules

Target routing rules:

| Situation | Payload version action | Workflow action |
|---|---|---|
| First sync | Create initial active payload version | Route by consent to `consent_refused` or `smartva_pending` |
| Unchanged sync | No new payload version | No SmartVA rerun; preserve current workflow unless other sync-issue handling applies |
| Changed sync on non-protected state | Create new active payload version | Route to `smartva_pending` |
| Changed sync on protected finalized state | Create pending upstream payload version | Route to `finalized_upstream_changed` |
| Accept upstream change | Promote pending payload version to active and update `va_submissions` from it | Route to `smartva_pending` |
| Reject upstream change | Mark pending payload version rejected and keep current active payload version | Return to prior finalized path |

## Notification Requirements

When a finalized submission's upstream data changes:

1. **Immediate notification** to:
   - Data managers for the project/site
   - System admins

2. **Notification content**:
   - Submission identifier (va_sid, instance name)
   - Project/site/form information
   - Timestamp of change detection
   - Previous workflow state
   - Action required (review and decide)

3. **Dashboard visibility**:
   - Submissions in the finalized-upstream-change state appear in a dedicated queue
   - Count shown on data manager dashboard
   - Filterable in submission lists

## Authorization Matrix

| Operation | Coder | Data Manager | Admin |
|---|---|---|---|
| Single submission refresh (non-protected) | No | Yes | Yes |
| Single submission refresh (protected, force) | No | No | Yes |
| Form sync | No | Yes | Yes |
| Form sync (force on protected) | No | No | Yes |
| Bulk sync | No | No | Yes |
| Accept upstream change | No | Yes | Yes |
| Reject upstream change (restore finalized) | No | Yes | Yes |

## Desired State Snapshot

```text
coder_finalized -- ODK data changed during sync --> finalized_upstream_changed
                                                  UI: Finalized - ODK Data Changed

finalized_upstream_changed -- data manager or admin accepts upstream change --> smartva_pending
smartva_pending ----------- SmartVA generated / regenerated / recorded failure --> ready_for_coding
finalized_upstream_changed -- data manager or admin rejects upstream change --> prior finalized state

coder_finalized -- recode window expires automatically --> reviewer_eligible
coder_finalized -- admin override final COD -----------> ready_for_coding
```

SmartVA gate note:

- in the desired target model, any path that introduces a new or changed
  payload into the coding queue must first pass through `smartva_pending`
- that includes initial sync eligibility and accept-upstream-change
- same-payload returns such as timeout cleanup, demo cleanup, or admin override
  do not require a SmartVA rerun
- future SmartVA run history should bind each run to the active payload
  version that triggered it

## Service Architecture

```
ODKSyncService
├── fetch_single(va_sid, force=False) -> SyncResult
├── fetch_form_submissions(form_id, force=False) -> FormSyncResult
├── fetch_all(project_id=None, force=False) -> BulkSyncResult
├── accept_upstream_change(va_sid) -> AcceptResult
└── reject_upstream_change(va_sid) -> RejectResult

SyncResult:
├── status: "synced" | "skipped_protected" | "error"
├── reason: str (when skipped)
├── submission: VaSubmissions (when synced)
└── audit_entries: list[VaSubmissionsAuditlog]
```

## Related Documents

- [Coding Workflow State Machine Policy](coding-workflow-state-machine.md)
- [SmartVA Generation Policy](smartva-generation-policy.md)
- [ODK Sync Current State](../current-state/odk-sync.md)
- [Final COD Authority Policy](final-cod-authority.md)
