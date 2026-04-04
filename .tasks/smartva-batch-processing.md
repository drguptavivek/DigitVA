# SmartVA Optimization — Completed

## What was done (2026-04-04)

### Phase 1: Batch processing
- Split SmartVA generation into batches of 10 (`SMARTVA_BATCH_SIZE = 10`)
- Added `_generate_batch()` core function; `generate_for_form()` and `generate_for_submission()` delegate to it
- HIV/malaria flags use form-level only (`form_smartvahiv`/`form_smartvamalaria`), no per-submission aggregation
- Fixed stale-connection cascade with `db.session.remove()` after error rollback

### Phase 2: Source-based execution (replaces PyInstaller binary)
- Replaced `resource/smartva` PyInstaller `--onefile` binary with `python -m smartva.va_cli`
- SmartVA-Analyze installed from `vendor/smartva-analyze` git submodule via `uv pip install --no-deps`
- CLI deps in `pyproject.toml`: `progressbar2`, `stemming`, `python-dateutil`, `xlsxwriter`, `matplotlib`
- Removed `_cleanup_smartva_tmp()` — no more `/tmp/_MEI*` orphan dirs
- Memory savings: ~150-300MB per invocation (no PyInstaller extraction overhead)

## Files changed

| File | Change |
|------|--------|
| `app/services/smartva_service.py` | Batch processing, `_generate_batch()`, stale-connection fixes |
| `app/utils/va_smartva/va_smartva_02_prepdata.py` | Form-level HIV/malaria only |
| `app/utils/va_smartva/va_smartva_03_runsmartva.py` | Python module invocation, removed binary cleanup |
| `app/services/va_data_sync/va_data_sync_01_odkcentral.py` | Stale-connection retry on post-attachment commit |
| `Dockerfile` | Install smartva from vendor submodule |
| `pyproject.toml` | Added CLI deps + matplotlib |
| `docker-compose.yml` | Memory limit 1536m for celery worker |
| `.dockerignore` | Exclude data/, output/, private/ |
