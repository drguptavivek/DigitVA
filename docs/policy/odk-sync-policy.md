---
title: ODK Sync Policy
doc_type: policy
status: active
owner: engineering
last_updated: 2026-03-20
---

# ODK Sync Policy

## Purpose

This policy defines how ODK data synchronization interacts with the coding workflow state machine. The core principle is that **finalized COD decisions must be protected from inadvertent data changes** while still allowing authorized overrides.

## Core Principles

ODK is the source of truth for submission content. All submissions present in ODK are stored in DigitVA — including those with refused or missing consent. This ensures complete auditability and allows consent corrections made in ODK to be picked up automatically on the next sync.

**Coder-finalized submissions have protected status** that prevents automatic destructive refresh without explicit authorization.

**Consent determines workflow routing, not storage.** Submissions without valid explicit consent are stored but never enter the coding workflow.

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
| Consent valid | `ready_for_coding` |
| Consent = `"no"` | `consent_refused` |
| Consent missing / empty | `consent_refused` |

### `consent_refused` state

- Submissions are stored in full — ODK data, attachments, and metadata are all synced normally.
- The submission never enters the coding queue.
- SmartVA is not run on `consent_refused` submissions.
- If consent is corrected in ODK Central, the next sync automatically re-evaluates and transitions the submission to `ready_for_coding`.
- Data managers can see and filter `consent_refused` submissions and view their count on the dashboard.

## Workflow State Guards

### Protected States

The following workflow states are **protected** from automatic ODK data refresh:

- `coder_finalized` — Final COD has been submitted and is authoritative
- `revoked_va_data_changed` — Current implemented state key for finalized cases whose ODK data changed after finalization
- `closed` — Terminal state, no further changes permitted

Target naming cleanup:

- preferred future state key: `finalized_upstream_changed`
- preferred UI label: `Finalized - ODK Data Changed`

`consent_refused` is **not** protected — ODK updates flow through freely so that consent corrections are picked up automatically.

### Non-Protected States

These states allow normal ODK sync behavior (consent re-evaluated on each update):

- `screening_pending`
- `ready_for_coding`
- `coding_in_progress`
- `partial_coding_saved`
- `coder_step1_saved`
- `not_codeable_by_coder`
- `not_codeable_by_data_manager`
- `consent_refused`

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
| Protected | Yes | **Mark as `revoked_va_data_changed`**, preserve workflow artifacts, require manual resolution | Admin-only explicit override path required |
| Protected | No | Skip | Skip |

### Bulk Sync (`fetch_all`)

Same behavior as form-level sync, applied across all active forms.

## Upstream Data Change Handling

When ODK data changes for a `coder_finalized` submission:

### Current Implemented Baseline

The current runtime behavior is partially aligned with this policy:

1. Protected submissions are **not** auto-reset to `ready_for_coding`
2. Existing coding artifacts are **not** destroyed on protected-state ODK update
3. The submission transitions to `revoked_va_data_changed`
4. Audit logging is written for the state transition

### Remaining Gaps

The current implementation does **not yet** complete the full target behavior:

1. Historical COD is not explicitly preserved through a dedicated upstream-change linkage like `base_final_assessment`
2. The prior ODK payload is not snapshotted before `va_submissions.va_data` is overwritten
3. No explicit notification artifact is created for data managers/admins
4. The state key remains `revoked_va_data_changed`; the preferred future name is `finalized_upstream_changed`
5. Authorization is not yet aligned with the admin-only policy target for accept/reject resolution

### Required Behavior

When upstream data changes for a finalized submission:

1. **Do NOT destroy workflow artifacts**
2. **Do NOT reset workflow state automatically**
3. **Transition to the finalized-upstream-change state**
   Current implemented key: `revoked_va_data_changed`
   Preferred target key: `finalized_upstream_changed`
4. **Preserve historical COD** as `base_final_assessment` (like recode does)
5. **Preserve historical VA data** snapshot
6. **Create notification** for data managers/admins
7. **Log audit trail** with reason `upstream_data_changed`

### State Transition

```
coder_finalized --[ODK data changed]--> revoked_va_data_changed

Target naming cleanup:

coder_finalized --[ODK data changed]--> finalized_upstream_changed
```

This state indicates:
- The submission was previously finalized
- Upstream ODK data has changed since finalization
- The previous COD is preserved but may need review
- Manual intervention required to either:
  - Accept the change and recode
  - Reject the change and restore `coder_finalized`

## Historical Data Preservation

When transitioning to the finalized-upstream-change state:

| What | How |
|---|---|
| Final COD | Preserve explicit linkage to the previously authoritative final assessment; current code only preserves final COD implicitly by leaving active rows in place |
| VA data snapshot | Stored before ODK update, referenceable; current code does not yet store a dedicated pre-update snapshot |
| Audit trail | `VaSubmissionsAuditlog` entries with full context |
| Notification | Created for data managers and admins; current code does not yet create a durable notification artifact |

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
| Accept upstream change | No | Current implementation: Yes | Policy target: Yes (Admin only) |
| Reject upstream change (restore finalized) | No | Current implementation: Yes | Policy target: Yes (Admin only) |

## Current Authorization Gap

The current runtime/API implementation still allows data managers to resolve
`revoked_va_data_changed` submissions.

That is a known gap relative to the policy target above. Until resolved:

- treat data-manager resolution as transitional behavior
- do not assume the admin-only authorization matrix is fully enforced in code

## Desired State Snapshot

```text
coder_finalized -- ODK data changed during sync --> finalized_upstream_changed
                                                  UI: Finalized - ODK Data Changed

finalized_upstream_changed -- admin accepts upstream change --> ready_for_coding
finalized_upstream_changed -- admin rejects upstream change --> coder_finalized

coder_finalized -- recode window expires automatically --> closed
coder_finalized -- admin override final COD -----------> ready_for_coding
```

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
