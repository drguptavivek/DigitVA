---
title: ODK Sync Policy
doc_type: policy
status: active
owner: engineering
last_updated: 2026-04-02
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

## Submission Identity Baseline

DigitVA submission identity is anchored on the stable ODK submission `KEY`
(`__id` in OData), not on ODK `instanceID`.

Current rule:

- normalized ODK fetch sets `KEY` from `__id`
- normalized ODK fetch computes `sid` as `{KEY}-{form_id.lower()}`
- `instanceID` is treated as operational metadata that may vary across edited
  versions of the same ODK submission
- `va_uniqueid` / displayed `VA Form ID` is a business identifier for users and
  must not be treated as the canonical technical sync identity

Policy implications:

- sync matching and local submission identity must remain anchored to `KEY`
- `instanceID` changes alone do not imply a new DigitVA submission
- reviewer-facing upstream-change diffs should not treat `instanceID` churn as a
  substantive data change when the underlying ODK `KEY` is unchanged

### Changed vs unchanged payload

A submission is considered unchanged only when the normalized synced payload is
semantically identical to the current active payload version.

This should be determined by a canonical payload fingerprint or equivalent
versioning rule, not only by ODK timestamps.

Practical implication:

- the current agreed rule is to fingerprint the full canonical normalized ODK
  payload JSON
- volatile metadata and derived helper fields do not count as substantive
  business-payload change; examples include `updatedAt`, attachment counters,
  ODK review comments, device metadata, and derived age-band helper fields
- numeric and string-equivalent scalar values compare equal after
  normalization; for example `10.0` and `"10"` must not create a new logical
  payload version on their own
- materially different normalized payload should be treated as a new payload
  version even if workflow routing happens later

### Canonical payload enrichment

The canonical stored submission payload remains OData-first, but selected
operational metadata is now enriched before persistence so payload versions and
upstream-change review use one stable contract.

Current required canonical stored fields include:

- OData form-answer payload
- `FormVersion`
- `DeviceID`
- `SubmitterID`
- `instanceID`
- `ReviewState`
- `instanceName`
- `AttachmentsExpected`
- `AttachmentsPresent`

Current source precedence:

- OData:
  canonical form-answer payload plus mirrored ODK fields such as
  `ReviewState` and `instanceName`
- submission XML:
  `FormVersion`, `DeviceID`
- submission metadata endpoint:
  `SubmitterID`, `instanceID`, and fallback review metadata
- attachments endpoint:
  `AttachmentsExpected`, `AttachmentsPresent`

Policy boundary:

- this enrichment is part of the canonical stored payload for sync writes and
  payload-version lineage
- this does not replace OData as the primary payload source
- attachment inventory details such as `audit.csv` presence may be used
  operationally, but are not required as coder-facing canonical payload fields

## How To Identify The Current Artifact For A SID

Use these rules when a submission has history across syncs, recodes, or
protected upstream review.

### Current VA data payload

- read `va_submissions.active_payload_version_id`
- then read the matching row in `va_submission_payload_versions`
- that payload row is the current accepted ODK data for the `va_sid`

### Current SmartVA payload

- find the active `va_smartva_results` row for the `va_sid`
- it must have `payload_version_id = va_submissions.active_payload_version_id`
- if it does not, the SmartVA projection is stale and needs repair

### Current finalized ICD10/COD

- authoritative ICD/COD comes from final-COD authority resolution
- coder final COD and reviewer final COD rows are both payload-version aware
- only rows linked to the current active payload should be treated as current

### Current reviewer-owned artifacts

- reviewer artifacts are downstream authority-chain artifacts
- if reviewer-owned final COD or other reviewer-owned payload-bound artifacts
  exist, they follow the same preserve/deactivate decision as coder-owned
  authoritative artifacts for the same SID
- `Accept And Recode` deactivates both coder and reviewer authoritative
  artifacts because the accepted upstream payload invalidates the existing
  coding conclusion chain
- `Keep Current ICD Decision` preserves both coder and reviewer authoritative
  artifacts, if present, because the explicit policy decision is that the
  existing ICD/COD conclusion remains valid for the promoted payload

### Current coder NQA

- find the active row in `va_narrative_assessments`
- it must match both the coder and the submission's
  `active_payload_version_id`

### Current Social Autopsy

- find the active row in `va_social_autopsy_analyses`
- it must match both the coder and the submission's
  `active_payload_version_id`

## Simple Upstream Review Examples

### Example: accept and recode

1. Current payload is `P1`
2. Protected sync creates pending payload `P2`
3. Data manager chooses `Accept And Recode`
4. DigitVA promotes `P2`
5. Coder final COD, reviewer final COD if present, current NQA, current Social
   Autopsy, and current SmartVA are no longer treated as current artifacts for
   coding
6. SmartVA reruns and coding starts again on `P2`

### Example: keep current ICD decision

1. Current payload is `P1`
2. Protected sync creates pending payload `P2`
3. Data manager chooses `Keep Current ICD Decision`
4. DigitVA promotes `P2`
5. Coder final COD remains authoritative, and reviewer final COD remains
   authoritative too if a reviewer-owned final COD exists
6. SmartVA, coder NQA, and Social Autopsy are rebound to `P2` instead of being
   regenerated

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
   snapshots for the upstream-review decision path
6. Data-manager and admin review surfaces expose a structured changed-fields
   diff derived from the normalized payload, not raw JSON inequality

### Review Surface Baseline

Pending upstream-change review must be available through one shared backend
contract.

Required surfaces:

- JSON API:
  `/api/v1/data-management/submissions/<va_sid>/upstream-change-details`
- data-manager detail-page `View Changes` modal on
  `/data-management/view/<va_sid>`
- dashboard `View Changes` modal for `finalized_upstream_changed` rows

The changed-fields presentation must:

- separate data changes from metadata changes
- separate formatting-only changes from substantive data changes
- show field labels when form mapping metadata exists
- keep stable `field_id` values in the payload even when no label mapping exists

Current terminology:

- `Data Changes`
- `Metadata Changes`
- `Formatting-Only Changes`

### Implementation Status

All items below are fully implemented as of 2026-04-01:

1. Runtime sync writes active and pending payload versions; protected upstream
   review outcomes now promote the pending payload version on both branches
2. Coder and reviewer final COD are each linked to the `payload_version_id`
   that was active when they were submitted
3. SmartVA runs are bound to payload version via `VaSmartvaFormRun`/`VaSmartvaRun`
   linkage
4. Legacy `revoked_va_data_changed` rows migrated to `finalized_upstream_changed`

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
   awaiting upstream-review resolution

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
  - Accept and recode: activate the new payload version for SmartVA/coding
  - Keep current ICD decision: activate the new payload version while
    preserving the current authoritative COD

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
| Changed sync on non-protected state | Create new active payload version | Route to `smartva_pending` and regenerate SmartVA for the new payload |
| Changed sync on protected finalized state | Create pending upstream payload version | Route to `finalized_upstream_changed` |
| Accept And Recode | Promote pending payload version to active and update `va_submissions` from it | Route to `smartva_pending` and regenerate SmartVA for the new payload |
| Keep Current ICD Decision | Promote pending payload version to active and update `va_submissions` from it | Return to prior finalized path while preserving COD artifacts and rebinding the preserved SmartVA projection to the new payload |

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
| Accept And Recode | No | Yes | Yes |
| Keep Current ICD Decision | No | Yes | Yes |

## Desired State Snapshot

```text
coder_finalized -- ODK data changed during sync --> finalized_upstream_changed
                                                  UI: Finalized - ODK Data Changed

finalized_upstream_changed -- data manager or admin accepts upstream change --> smartva_pending
smartva_pending ----------- SmartVA generated / regenerated / recorded failure --> ready_for_coding
finalized_upstream_changed -- data manager or admin keeps current ICD decision --> prior finalized state

coder_finalized -- recode window expires automatically --> reviewer_eligible
coder_finalized -- admin override final COD -----------> ready_for_coding
```

SmartVA gate note:

- in the desired target model, any path that introduces a new or changed
  payload into the coding queue must first pass through `smartva_pending`
- that includes initial sync eligibility and accept-upstream-change
- same-payload returns such as timeout cleanup, demo cleanup, or admin override
  do not require a SmartVA rerun
- active SmartVA projection rows must always match the submission's current
  active payload version
- prior SmartVA runs and likelihood rows remain durable history even after the
  projection row is superseded

## Service Architecture

```
ODKSyncService
├── fetch_single(va_sid, force=False) -> SyncResult
├── fetch_form_submissions(form_id, force=False) -> FormSyncResult
├── fetch_all(project_id=None, force=False) -> BulkSyncResult
├── accept_upstream_change(va_sid) -> AcceptResult
└── reject_upstream_change(va_sid) -> KeepCurrentIcdResult

SyncResult:
├── status: "synced" | "skipped_protected" | "error"
├── reason: str (when skipped)
├── submission: VaSubmissions (when synced)
└── audit_entries: list[VaSubmissionsAuditlog]
```

## Connection Guard and Pacing

All outbound ODK Central calls pass through a shared connection guard
(`app/services/odk_connection_guard_service.py`). The guard enforces
per-connection pacing and cooldown using state persisted in `mas_odk_connections`.

### Pacing

Every ODK call reserves a slot via `reserve_odk_request_slot()`, which uses a
DB row-level lock on the connection row to enforce a minimum interval between
consecutive calls.

| Config key | Default | Meaning |
|---|---|---|
| `ODK_CONNECTION_MIN_REQUEST_INTERVAL_SECONDS` | `0.5` | Minimum seconds between consecutive calls on the same connection. Set to `0` to disable pacing. |

If a call arrives before the interval has elapsed, the caller sleeps the
remaining wait before proceeding.

### Failure tracking and cooldown

Each retryable ODK failure increments `consecutive_failure_count` on the
connection row. When the count reaches the threshold, `cooldown_until` is set
to `now + cooldown_seconds`. While cooldown is active, any `guarded_odk_call`
for that connection raises `OdkConnectionCooldownError` immediately without
touching ODK.

A single successful ODK call resets `consecutive_failure_count` to zero and
clears `cooldown_until`.

| Config key | Default | Meaning |
|---|---|---|
| `ODK_CONNECTION_FAILURE_THRESHOLD` | `3` | Consecutive retryable failures before cooldown activates |
| `ODK_CONNECTION_FAILURE_COOLDOWN_SECONDS` | `300` | Cooldown duration in seconds (5 minutes) |

### Retryable errors

The following are treated as retryable connectivity failures that count toward
the threshold:

- `requests.exceptions.ConnectTimeout`
- `requests.exceptions.ConnectionError`
- `requests.exceptions.Timeout`
- HTTP 401 or 403 responses (auth failure / token expiry)
- Exceptions whose string representation contains any of: `ConnectTimeout`,
  `ConnectionError`, `Max retries exceeded`, `timed out`, `HTTPSConnectionPool`,
  `Unauthorized`, `Forbidden`, `token`, `expired`, `auth`

`OdkConnectionCooldownError` itself is **not** retryable — it is a guard signal,
not a connectivity error, and must propagate immediately.

### Sync loop behaviour on cooldown

When `OdkConnectionCooldownError` is raised during a form's sync:

1. The form is logged as **SKIPPED** at `WARNING` level (not `ERROR`)
2. The connection ID is added to `connections_in_cooldown` for this run
3. All subsequent forms sharing the same connection are **preemptively skipped**
   at the top of the loop without making any ODK calls
4. Forms on other connections are **unaffected** and continue running
5. Cooldown-skipped forms are reported separately in the Phase 1 summary
   (`cooldown_skipped_forms`) and are **not** counted as failures

A non-cooldown exception (data error, transient HTTP failure below threshold)
continues to go to the `FAILED` path with full error logging and does not
preemptively skip other forms.

### Operator visibility

Connection guard state is surfaced in the admin dashboard at three points:

- **Sync dashboard** — shows cooldown status and remaining cooldown time for
  each connection involved in the current or most recent sync run
- **ODK Connections panel** — shows `consecutive_failure_count`, active cooldown
  flag, and last failure message per connection
- **Project forms panel** — shows a cooldown warning banner when a live ODK
  action is attempted and the connection is in cooldown

The `serialize_connection_guard_state()` helper in the guard service produces
the UI-safe dict consumed by all three.

### Comments and `updatedAt`

Adding a comment or changing `reviewState` on a submission via
`client.submissions.review()` does **not** change `__system/updatedAt` in ODK
Central. ODK only bumps `updatedAt` for data-XML edits. This means:

- DigitVA's writeback calls (`mark_submission_needs_revision`,
  `post_dm_rejection_comment`) are invisible to the delta check
  `(submissionDate gt T or updatedAt gt T)`
- No spurious re-syncs are triggered by our own review state writes

## Related Documents

- [Coding Workflow State Machine Policy](coding-workflow-state-machine.md)
- [SmartVA Generation Policy](smartva-generation-policy.md)
- [ODK Sync Current State](../current-state/odk-sync.md)
- [Final COD Authority Policy](final-cod-authority.md)
