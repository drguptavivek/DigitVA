---
title: SmartVA Generation Policy
doc_type: policy
status: draft
owner: engineering
last_updated: 2026-03-19
---

# SmartVA Generation Policy

## Purpose

This policy defines when SmartVA cause-of-death analysis should run, how it interacts with the workflow state machine, and what protections exist for finalized submissions.

## Core Principle

SmartVA is an **advisory tool** that provides automated COD suggestions to coders. It must respect the workflow state machine and **not regenerate results for finalized submissions** unless explicitly authorized.

## Workflow State Guards

### Protected States

SmartVA generation is **blocked** for these states (unless forced):

- `coder_finalized` — Final COD is authoritative, SmartVA should not change
- `revoked_va_data_changed` — Pending review, no new SmartVA until resolved
- `closed` — Terminal state, no further changes

### Allowed States

SmartVA runs normally for these states:

- `screening_pending`
- `ready_for_coding`
- `coding_in_progress`
- `partial_coding_saved`
- `coder_step1_saved`
- `not_codeable_by_coder`
- `not_codeable_by_data_manager`

## Generation Operations

### Single Submission (`generate_single`)

```
generate_single(va_sid, force=False)
```

| Workflow State | Has Active Result | force=False | force=True |
|---|---|---|---|
| Allowed | No | Run SmartVA | Run SmartVA |
| Allowed | Yes | Skip (result exists) | Regenerate |
| Protected | * | **SKIP** — return reason | Run SmartVA |

**Authorization for `force=True`:** Admin only

### Form-Level Pending (`generate_pending`)

```
generate_pending(form_id)
```

Finds submissions for the form that:
1. Have NO active SmartVA result
2. Are in an **allowed** workflow state

Protected submissions are excluded from the pending set.

### Bulk Pending (`generate_all_pending`)

Same behavior as form-level, applied across all active forms.

## Trigger Sources

SmartVA can be triggered from:

| Source | Behavior |
|---|---|
| Full sync (Phase 2) | Runs for `pending_sids ∪ amended_sids`, excludes protected |
| Single form sync | Runs for `pending_sids ∪ amended_sids`, excludes protected |
| Single submission refresh | Runs only if state is allowed, otherwise skip |
| "Gen SmartVA" button | Runs `generate_pending()` for all forms |
| Manual API call | Respects `force` parameter |

## Result Lifecycle

### Active vs Inactive Results

- **Active**: `va_smartva_status = 'active'` — current result shown to coders
- **Inactive**: `va_smartva_status = 'deactive'` — superseded by newer result

### When Results Are Regenerated

| Condition | Action |
|---|---|
| New submission (no result) | Create new active result |
| ODK data changed + allowed state | Deactivate old, create new active |
| ODK data changed + protected state | **DO NOT regenerate** |
| Manual force regenerate | Deactivate old, create new active |

### Audit Trail

Every SmartVA result change creates `VaSubmissionsAuditlog` entries:

- `va_smartva_creation_during_datasync` — new result created
- `va_smartva_deletion_during_datasync` — old result deactivated

## Service Architecture

```
SmartVAService
├── generate_single(va_sid, force=False) -> SmartVAResult
├── generate_pending(form_id) -> FormSmartVAResult
├── generate_all_pending() -> BulkSmartVAResult
├── get_active_result(va_sid) -> VaSmartvaResults | None
└── has_active_result(va_sid) -> bool

SmartVAResult:
├── status: "generated" | "skipped_protected" | "skipped_exists" | "error"
├── reason: str (when skipped)
├── result: VaSmartvaResults (when generated)
└── audit_entries: list[VaSubmissionsAuditlog]
```

## Integration with ODK Sync

SmartVA runs **after** ODK sync (Phase 2), but only for submissions that:

1. Were added or updated in Phase 1, AND
2. Are in an allowed workflow state

```
Phase 1: ODK Sync
├── fetch_submissions()
├── upsert_submissions()
│   ├── Non-protected: normal upsert
│   └── Protected + changed: mark revoked_va_data_changed
└── sync_attachments()

Phase 2: SmartVA
├── get_pending_sids() — excludes protected
├── prep_input_csv()
├── run_smartva_binary()
└── save_results()
```

## Protected Submission Handling

When a submission is in `coder_finalized` or `revoked_va_data_changed`:

1. **Do NOT regenerate SmartVA** during sync
2. **Do NOT modify existing SmartVA result**
3. **Log skip reason** in sync progress
4. **Return skip status** to caller

If an admin forces regeneration:
1. Deactivate existing result (audit logged)
2. Run SmartVA
3. Create new active result (audit logged)
4. Do NOT change workflow state

## Authorization Matrix

| Operation | Coder | Data Manager | Admin |
|---|---|---|---|
| View SmartVA results | Yes (assigned) | Yes (scoped) | Yes |
| Generate pending (form) | No | Yes | Yes |
| Generate pending (all) | No | No | Yes |
| Force regenerate (protected) | No | No | Yes |

## Performance Considerations

- SmartVA is CPU-intensive and runs in the Celery worker container
- Form-level runs process submissions in batches
- Large forms may take several minutes
- Progress is logged to `va_sync_runs.progress_log`

## Related Documents

- [Coding Workflow State Machine Policy](coding-workflow-state-machine.md)
- [ODK Sync Policy](odk-sync-policy.md)
- [SmartVA Analysis Current State](../current-state/smartva-analysis.md)
