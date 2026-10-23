---
title: "Staging load tests and memory/CPU optimizations, October 2026"
doc_type: kb
status: active
owner: engineering
last_updated: 2026-10-23
---

# Staging load tests and memory/CPU optimizations, October 2026

What was measured on staging (`digitvav3`) on 2026-10-22 and 2026-10-23, what
was changed because of it, and what was tried and dropped. Numbers are from
the runs described here; reuse them as a baseline, not as a capacity promise.

## Box and setup

- Staging app host `DIGITVA-v3`: EC2 t4g.medium (2 vCPU Graviton, 4 GB, no
  swap, `unlimited` CPU credits). Postgres on its own t4g.small. App runs
  gunicorn 2 workers x 4 threads, one Celery worker (`--concurrency=1`),
  Celery beat, Redis, nginx ingress, the WHO ICD API container and the
  public DORIS service.
- Load came from a temporary t4g.small in the same subnet, hitting the
  ingress on the app host's private address, port 8000, directly with `Host: digitvav3...`. The
  public hostname goes through the t2.small proxy that production and ODK
  Central also use, so load was never sent through it.
- Harness (scratch; to move into `scripts/loadtest/` later): `lt_setup.py`
  creates `lt+i<n>`/`lt+c<n>@digitva.com` users on TRN01 (interviewer and
  `coding_tester` grants) and mints device bearer tokens server-side, which
  skips the 10/min sign-in limits. `lt_run.py` (stdlib + requests) runs:
  - `mix`: 100 interviewers loop `POST /api/v1/intake/submissions`; 100
    coders loop available -> allocate -> workspace -> categories -> DORIS
    terms/process -> finalize. `coding_tester` finals return the case to
    the pool.
  - `doris`: an open loop of DORIS `terms`/`process` at a target rate.
- Every run: a verified backup first, a memory sampler and a
  "free memory < 300 MB" abort watchdog during, then a restore from the
  backup and teardown of the temporary instance and security-group rule.

## Baseline, 2026-10-22 (before the changes)

200 users, 10 minutes (`--ramp 120 --think 10`):

| | Value |
|---|---|
| Throughput | 26.4 req/s; 5,043 interviews, 1,243 coding cycles |
| Latency p50/p95 | intake 604/1439 ms; coding 282-370/1078-1186 ms; DORIS 239-249/1080-1103 ms |
| Errors | 4 HTTP 500 on allocation (two coders picked the same case; `WorkflowTransitionError`) |
| SmartVA queue | grew to ~3,300 tasks; the worker drained ~2/s (~28 min backlog) |
| Memory | app 350 -> 410 MB, worker 244, beat 170, ICD 606 -> 710; host never below 1.47 GB free |
| CPU | app 130-180% of 2 cores, load average up to 7.9 |

DORIS at a target of 100 req/s: all 18,001 requests returned 200, but the box
completed only ~68/s; p95 climbed from 3.5 to 11.7 s as requests queued.

Conclusion: memory was never the limit (always >= 1.39 GB free); CPU was.

## What changed, with measured effect

| Change | Commit | Measured effect |
|---|---|---|
| Lazy-import pandas, numpy, pyodk, openpyxl; gunicorn `--preload` with `gc.freeze`; beat boots without blueprints | `be62e5c71` | per process ~-60 MB; gunicorn total Pss 381 -> 261 MB; staging idle app 350 -> 264, worker 229 -> 196, beat 170 -> 114 MB (-175 MB) |
| Warm smartva-rs in the worker (ctypes, cached tariff models) | `e00cd1249` | 8.2 -> 17.7 SmartVA tasks/s; one task 110 -> 53 ms; results identical on 965 cases |
| Coalesce queued per-case SmartVA tasks into one engine run; recycle the worker child mainly on memory (1000-task backstop) | `bc05006e9` | dev backlog drained from the worker log: UNSW01 20.2 -> 195.5 tasks/s; ICMR01 (6,932 cases) 11.6 -> 135.7 tasks/s, 6,932 -> 143 engine runs; results identical on all 7,897 cases |
| smartva-rust v3.0.2 (panic-safe C ABI, version export, parameterised warm-up) | `5fc804e89`, `f05091920` | robustness; no speed change |
| COD snapshot view decodes payload JSON once (`jsonb_to_record`) and refreshes with JIT off | `757b2e1fb` | refresh 7.7 s -> 2.6 s on staging (measured); was ~90% of all DB time |
| Per-request trim: skip org-unit scan without gates, sweep off the request path, session expiry not written every request, area summary cache, skip-locked pick | `d42ae7166` | allocation 39 -> 34 statements; session writes 1 -> 0 per request; allocation race answers 409, not 500 |
| Allocation lock order (workflow row before allocation insert) and deadlock -> 409 | `d120dae27` | removes a same-user random/pick deadlock |
| Concurrent index re-run guard in `c5e7a9b1d3f6` | `5ae70679b` | a failed build no longer leaves an INVALID index kept by the re-run |
| Streamed data-manager CSV exports; paged ODK sync | `44338faf3`, `0214610ef`, `1a539de38` | export peak memory +501 -> +60 MB on a 7k-row clone; byte-identical output |
| SmartVA worker container `cpu_shares: 128` | `f23339810` | see the A/B below |

## The worker CPU A/B, 2026-10-23

After warm and batched SmartVA, the worker kept up (queue 0-6 instead of
~3,300), but request latency rose 40-60%. Identical 4-minute runs, 200 users
(`--duration 240 --ramp 60 --think 10`), p50/p95 ms:

| Endpoint | Worker paused | Running, normal | Running, `nice -n 10` | Running, live `--cpu-shares 128` | **Running, compose `cpu_shares: 128`** |
|---|---|---|---|---|---|
| intake.submit | 388/913 | 909/2102 | 975/2312 | 542/1423 | **461/1000** |
| coding.available | 142/630 | 551/1843 | 592/1972 | 252/1092 | **179/738** |
| coding.allocate | 129/653 | 529/1644 | 607/2013 | 227/1081 | **182/767** |
| va.workspace | 164/681 | 633/1880 | 581/1934 | 257/1147 | **208/760** |
| doris.process | 101/551 | 547/1886 | 631/1671 | 195/945 | **176/714** |
| req/s | 27.1 | 25.6 | 24.9 | 26.5 | **26.8** |

All runs had 0 HTTP 5xx. With compose `cpu_shares` the worker used ~16% CPU
and the SmartVA queue stayed at 11 or below.

How the cause was found: a read-only sampler of `pg_stat_activity` (165
samples) showed 92% of busy backends "idle in transaction / ClientRead" and
no lock waits at all, so requests were slow in Python, not in Postgres. Both
containers had cgroup `cpu.weight` 100. `nice` only ranks processes inside
one cgroup, so it could not give gunicorn priority over another container.
`cpu_shares: 128` gives the worker container `cpu.weight` 21 against the
app's 100.

Check on a host: `cat /sys/fs/cgroup/system.slice/docker-<id>.scope/cpu.weight`.
`docker update --cpu-shares 0` does not reset a live change; recreate the
container from compose instead.

## What did not work, or was dropped

| Idea | Outcome | Why |
|---|---|---|
| Move Python modules to Rust to cut memory | Rejected | Memory was Python plus imported libraries; a Rust extension runs inside the same process and removes none of it. Lazy imports did. |
| Replace Celery and beat with a Rust scheduler | Rejected | Importing Celery costs ~0 MB; tasks are Python, so a Python worker stays. Beat's schedules are DB-driven and edited in admin. |
| Embed beat in the worker (`-B`) | Rejected (owner) | Saves ~150 MB, but breaks decision 13 in `docs/policy/death-registration-identifiers.md`: beat must never receive the PII private key. Beat now boots without blueprints instead. |
| Worker under `nice -n 10` alone | No effect | Niceness does not cross container cgroups (A/B above). Kept, harmless; `cpu_shares` is the fix. |
| Cache SmartVA tariff models in Redis | Rejected | In-process cache hits are free; fetching and deserialising a blob per run costs more than the one-time ~85 ms build. Redis is 64 MB and holds the queue. |
| Keep 30-40 warm SmartVA scenarios | Unnecessary | The cache key is (age group, hce, free_text, short_form). WHO 2022 input is always short_form; all forms use hce and free text, so 3 models. Country, HIV and malaria apply per run. |
| `smartva_warm_cache()` at worker start | Wrong models | It warmed PHMRC-full (`short_form=false`). v3.0.2 adds `smartva_warm_cache_for(hce, free_text, short_form)`; startup warming is not wired in. |
| Side table of extracted payload fields for the COD view | Rejected | `jsonb_to_record` inside the view got most of the win; a table saved only ~230 ms more for a write path, backfill and second copy. |
| ICD-11 ancestor-chain materialized view (`digitva-3xko`) | Shelved | Proven identical, but saved ~11 ms per refresh and ~4 ms per report lookup. The 160-412 ms `icd11_report_chain` entries in `pg_stat_statements` are whole report queries labelled by their first CTE. Patch kept in the session notes. |
| Nightly DuckDB/Parquet for the COD buckets, data-management and area pages | Rejected | Those pages are cheap (data-management grid 11 ms mean) or live (sync state, current counts); a nightly copy would be stale, add DuckDB memory in gunicorn and a second copy of the data. Parquet suits offline research exports only. |
| 100 DORIS req/s through the public DORIS service | Not possible as asked | It is limited to 120/min per IP and one gunicorn worker. Tested through the signed-in `/api/v1/doris-clinical` routes instead. |

## Harness pitfalls (fixed or worked around)

- Refresh tokens rotate and are not written back. A second run on the same
  token file fails with 401 and revokes those sessions; mint fresh tokens
  before every run.
- Access tokens last 15 minutes and refresh is limited to 30/min per IP. A
  run started long after minting trickles in at 25 users/min; mint right
  before starting.
- `pgrep -f "<pattern>"` inside an SSM command matches the SSM shell itself.
- Unquoted backticks in a shell argument run as commands. Once this applied
  a stray `docker update` to the local dev worker; it was recreated.
- Restoring staging (stop, `pg_restore --single-transaction`, start) needs
  the `pg_stat_statements` extension excluded from the restore list. The
  app's DB role cannot drop a superuser-owned extension, and the
  single-transaction restore then rolls back cleanly.

## Open follow-ups

- `digitva-mubf`: the COD snapshot view and the reports resolve ICD-11
  buckets against different map rows.
- `digitva-p2cr`: help pages do not explain how codes reach VA causes.
- `digitva-ekpt`: test the `flask cod-buckets` generator end to end.
- `digitva-xp9w`: profile one real staging report query before optimising reports.
- `digitva-f0ys`: a spelling test fails only under xdist.
- Load-test harness into `scripts/loadtest/` with tokens and hostnames in env vars.
- The proxy/ODK Central t2.small (2 GB): check memory before any change; do not downsize.
