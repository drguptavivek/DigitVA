# Plan: Batch-wise SmartVA processing with shared service

## Context

SmartVA binary gets OOM-killed (SIGKILL -9) when processing forms with hundreds of pending submissions in a single run (e.g., ICMR01ND0101 has 506 pending). The long subprocess also kills the DB connection, and the stale-connection error cascades to subsequent forms because `generate_all_pending` doesn't reconnect after failures.

The existing ODK sync and backfill workflows already batch submissions (size 10 via `ENRICHMENT_SYNC_BATCH_SIZE`). SmartVA needs the same pattern.

## Key findings from investigation

### HIV/Malaria/HCE/Freetext flags
- **SmartVA binary accepts ONLY global flags** per invocation (`--hiv`, `--malaria`, `--hce`, `--freetext`)
- **HIV/Malaria/HCE/Freetext**: All use **form-level only** — ignore per-submission payload values for Id10002/Id10003. Always use `form_smartvahiv`, `form_smartvamalaria`, `form_smartvahce`, `form_smartvafreetext` from `VaForms`.
- This simplifies `_derive_smartva_run_options()` in `va_smartva_02_prepdata.py` — remove the per-submission aggregation logic and always use form defaults directly.
- Also remove the `hiv_overridden`/`malaria_overridden` progress logging in `smartva_service.py` `_generate_batch` since there's no override to report.

### Payload version awareness
- `pending_smartva_sids()` correctly checks `VaSmartvaResults.payload_version_id == VaSubmissions.active_payload_version_id` — only submissions missing SmartVA for their **current** payload version are included. Already correct, no changes needed.

## Approach

### 1. Add `_generate_batch` — core processing function in `smartva_service.py`

New private function extracting the shared logic from `generate_for_form` (lines 772–920) and `generate_for_submission` (lines 966–1089). Takes a form + a set of SIDs (1 to N) and runs one SmartVA binary invocation.

```python
def _generate_batch(
    va_form,
    batch_sids: set[str],
    *,
    trigger_source: str = "form_batch",
    log_progress=None,
) -> int:
```

Logic (extracted from current `generate_for_form` lines 772–920):
1. Create workspace dir
2. Create form run (`_create_smartva_form_run`)
3. Begin nested transaction
4. `va_smartva_prepdata(va_form, workspace_dir, pending_sids=batch_sids)` — already supports SID filtering; now returns form-level HIV/malaria only (no per-submission override)
5. `va_smartva_runsmartva(...)` — runs the binary on the batch CSV
6. Read results (`_read_raw_likelihood_outputs`, `_read_rejected_sids_from_report`, `_read_formatted_results`)
7. Save results per SID, record failures
8. Commit transaction
9. Exception handler: safe rollback (wrapped in try/except for stale connections), record failures

### 2. Rewrite `generate_for_form` to batch pending SIDs

- Compute `pending` as now (lines 708–750) — including protected-state repair and target_sids filtering
- Split `pending` into chunks of `SMARTVA_BATCH_SIZE = 10`
- For each batch, call `_generate_batch`
- Log progress per batch: `"SmartVA {form_id}: batch {i}/{total} ({batch_size} submissions)…"`
- On error in a batch: rollback, `db.session.remove()`, log, continue to next batch
- After each successful batch: commit, `db.session.remove()` to get a fresh connection
- Return aggregated total across all batches

### 3. Rewrite `generate_for_submission` to delegate to `_generate_batch`

Thin wrapper: resolve form from SID, check protected state, then call `_generate_batch(va_form, {va_sid})`. Removes ~100 lines of duplicated logic.

### 4. Fix stale-connection cascade in `generate_all_pending`

After catching exception per form (line 1110):
```python
db.session.rollback()
db.session.remove()  # discard dead connection
```

In `_generate_batch` exception handler: wrap `processing_tx.rollback()` in try/except so stale connection doesn't suppress failure recording:
```python
try:
    processing_tx.rollback()
except Exception:
    db.session.rollback()
```

## Files to modify

| File | Change |
|------|--------|
| `app/services/smartva_service.py` | Add `_generate_batch`, rewrite `generate_for_form` with batching, simplify `generate_for_submission`, fix connection cascade, add `SMARTVA_BATCH_SIZE` constant |
| `app/utils/va_smartva/va_smartva_02_prepdata.py` | Simplify `_derive_smartva_run_options()` to use form-level HIV/malaria only (remove per-submission Id10002/Id10003 aggregation) |
| `app/utils/va_smartva/va_smartva_03_runsmartva.py` | Remove `hiv_overridden`/`malaria_overridden` handling if present |

No changes needed in:
- `app/tasks/sync_tasks.py` — `run_smartva_sync_batch` already calls `generate_for_form(target_sids=...)` with small batches; those calls will now go through `_generate_batch` automatically

## Constants

```python
SMARTVA_BATCH_SIZE = 10  # max submissions per SmartVA binary invocation
```

## Verification

1. Trigger SmartVA-only run via `/admin/api/sync/trigger-smartva` — confirm batches of 10 in Celery logs
2. Confirm OOM kills no longer happen on large forms
3. Confirm stale-connection cascade is fixed — one form/batch failure should not kill the next
4. Run existing tests: `docker compose exec minerva_app_service uv run pytest tests/services/test_smartva_service.py -v`
