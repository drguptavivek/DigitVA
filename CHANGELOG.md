# Changelog

What landed, newest first. Details live in the commits and the linked docs;
`handoff.md` holds only what is next.

## 2026-10-23

- **On-screen error reference** (`digitva-l3r8`): the Expo app's generic
  "Something went wrong" (and web "server could not complete") messages now
  carry a `Ref:` line with HTTP status, code, method and masked route (or the
  local error class), UTC time and app version, so a field screenshot is
  enough to find the failing request. No tokens, server text or answers.
- **Staging at `f23339810`**, confirmed: with the worker at `cpu_shares` 128,
  request p50 is within ~30-75 ms of the worker-paused baseline at full
  SmartVA throughput, 0 5xx. Runbook: `git submodule sync` before the update.
- **SmartVA worker CPU weight** (`digitva-g8iu`): worker containers run with
  `cpu_shares` 128 (demo worker 128 against its app's 256), so gunicorn keeps
  the CPU under load. Staging p50 coding.available 252 ms vs ~580 with `nice`
  alone (it cannot cross container cgroups) and 142 with the worker paused.
- **Expo web `expo-web-v2026.10.23.1`** (from `19c05ba07`, carries the DORIS
  remark) pinned in `x-release-pins`.
- **Staging A/B on `d120dae27`**: `nice -n 10` on the workers did not lower
  request latency; `cpu_shares` 128 did (`digitva-g8iu`).
- **Sync master data and single-form resync** (`digitva-tn21`,
  `digitva-jvgp`; `docs/current-state/odk-sync.md`). The sync upsert reads
  form type and category config once per call instead of 3 queries per
  record; the single-form force-resync fetches page by page and still commits
  once. On failure it now rolls back before recording the error, so that
  run's sync-issue ("missing in ODK") flags are not saved, as in the main sync.
- **DORIS remark in the Expo app** (`6848a6f8b`, `digitva-p9j0`): the final
  cause-of-death step sends the coder's or reviewer's remark, as the web form
  does. Needs an Expo web release and pin.
- **Deploy runbook**: `git submodule update --init vendor/smartva-analyze`
  after the pull and in rollback.
- **Celery workers under `nice -n 10`** (`digitva-295w`): main and demo
  workers yield CPU to gunicorn (demo worker also gets
  `--max-memory-per-child=300000`). Staging A/B re-test pending.
- **Allocation lock order** (`digitva-nw4b`): every coding allocation locks the
  case's workflow row before inserting the allocation; a remaining deadlock
  answers 409 `conflict`, not 500. Migration `c5e7a9b1d3f6` drops an INVALID
  leftover of its concurrent index before rebuilding it (`digitva-hbrs`; no
  new revision, a no-op where it already applied).
- **Streaming exports and paged ODK sync** (`digitva-lj7u`;
  `docs/current-state/data-manager-dashboard.md`, `odk-sync.md`). The
  data-manager submissions and SmartVA-input CSV exports stream rows through a
  server-side cursor into a temporary file: peak memory ~+60 MB at any size
  (was ~+500 MB for 7k rows), byte-identical output. The main ODK sync fetches
  and upserts 250 records at a time with one commit per form, batches its
  per-record lookups (5 -> 3 queries per record) and reads only the columns it
  needs for sync-issue marking and repair planning (+131 -> +38 MB per form).
- **Staging deployed at `f05091920`** and load-tested (200 users): 0
  allocation 500s, SmartVA queue ≤6, Python services −175 MB idle, COD refresh
  7.7 -> 2.6 s; request latency doubles while the SmartVA worker runs
  (CPU-bound, `digitva-295w`).
- **smartva-rust 3.0.2** (`digitva-kyxr`): a Rust panic in the library fails
  that one SmartVA run instead of ending the worker child; runs record the
  library's own version (`smartva_version`). Pinned in `x-release-pins`;
  `vendor/smartva-analyze` at `cb89e05`, now on SmartVA-Analyze main.
- **SmartVA backlog ~10x faster** (`digitva-96ik`;
  `docs/current-state/smartva-analysis.md` Throughput). A starting completion
  run takes up to 49 other queued completion runs of its form (same trigger,
  Redis flag `smartva-plain:<sid>`) into one engine run; their own tasks skip.
  Run-button and regenerate requests stay per case. Worker children recycle
  mainly on memory (`worker_max_memory_per_child` 300000 KB) with a 1000-task
  backstop (was 100). Dev backlog: UNSW01 20 -> 195 tasks/s, ICMR01 (6,932
  cases) 11.6 -> 136 tasks/s; stored results identical on all 7,897 cases.
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
