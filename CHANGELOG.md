# Changelog

What landed, newest first. Details live in the commits and the linked docs;
`handoff.md` holds only what is next.

## 2026-10-23

- **Per-request DB work cut; lost allocation race is 409** (`digitva-lb6b`,
  `digitva-kxit`, migration `c5e7a9b1d3f6`). The unit coding-gate scan returns
  early when no gate exists; the stale-allocation sweep on allocation requests
  runs at most every 30 s (`CODING_STALE_SWEEP_MIN_INTERVAL_SECONDS`); an
  unchanged cookie session is re-saved at most once a minute
  (`SESSION_REFRESH_WINDOW_SECONDS`; idle timeout still 30 min); `area_summary`
  cached 60 s per user. Allocation 39 -> 34 statements, session-store writes
  1 -> 0 per request (`tests/test_request_query_counts.py`). Two coders racing
  for one case: the loser gets 409, not 500.
- **COD snapshot refresh ~2.5x faster** (`digitva-o7a6`, migration
  `b7e2d4f6a8c1`; `docs/current-state/submission-analytics.md`). The 34 payload
  fields come from one `jsonb_to_record` decode instead of 34 detoasts, and
  analytics MV refreshes run with JIT off. Dev REFRESH CONCURRENTLY 3.3 s ->
  1.3 s (staging estimate 7.7 s -> ~3 s); view contents identical. The upgrade
  rebuilds `va_submission_cod_snapshot_mv` WITH DATA (~1-3 s). The ICD-11
  ancestor-chain MV (`digitva-3xko`) was shelved: small gain, see the bead.
- **SmartVA in-process** (`e00cd1249`, `digitva-5gsq`; `docs/current-state/smartva-analysis.md`
  Throughput). The worker calls `libsmartva_rust.so` through ctypes instead of
  a subprocess per run: 8.2 -> 17.7 tasks/s on a real worker, identical stored
  results on all 965 UNSW01 cases. `SMARTVA_RS_LIB=""` falls back to the
  subprocess. Worker cap raised to `--max-memory-per-child=300000` (owner) for
  the child's 236-240 MiB peak.
- **Dev Postgres** memory limit 1 GB in `docker-compose.override.yml`
  (owner); production keeps 756 MiB.
- **Releases** (`441cc7457`): `android-v0.3.0` (CI run 39833431056, Latest) and
  `expo-web-v2026.10.22.5`, both from `21ccf04dc`, pinned in `x-release-pins`.

## 2026-10-22

- **Public demo** (`4178edb00`, epic `digitva-77v5`; policy
  `docs/policy/public-demo.md`, runbook
  `docs/current-state/public-demo-deployment.md`). Off unless
  `PUBLIC_DEMO_ENABLED`. Username sign-up with proof of work (web
  `/vaauth/signup`, app `/api/v1/auth/demo-signup`); phone enrolment without QR
  (`/api/v1/auth/demo-enroll`, 3 phones, a 4th replaces the oldest); own-case
  collection, coding and review; CoD report and own download
  (`/public-demo/cases`); public aggregate dashboard
  (`/public-demo/dashboard`); limits (500 accounts, least-recent idle 7+ days
  evicted, 10 submissions each, per-IP and global caps); 30-day purge, off until
  `PUBLIC_DEMO_PURGE_ENABLED`; `flask public-demo setup|purge`; own Redis
  namespace, Celery queue and beat allowlist; separate compose project
  `docker-compose.demo.yml` on network `digitva_icd`. Migration `b4d6f8a2c9e1`.
- **Process memory** (`be62e5c71`, `digitva-xt4b`, `digitva-345y`; numbers in
  `docs/current-state/runtime-and-operations.md`). pandas, numpy, pyodk and
  openpyxl import on first use (`tests/test_startup_imports.py` guards it);
  gunicorn `--preload` with `gc.freeze` before fork and a post-fork SQLAlchemy
  pool reset; beat boots without blueprints (`DIGITVA_REGISTER_ROUTES=0`);
  worker child replaced past `--max-memory-per-child`.
- **digitva-collect 0.3.0** (`21ccf04dc`): version for the release carrying the
  demo's Try-the-demo enrolment (versionCode 300).
