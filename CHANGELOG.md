# Changelog

What landed, newest first. Details live in the commits and the linked docs;
`handoff.md` holds only what is next.

## 2026-10-25

- **Builds only on GitHub Actions** (`a57176256`, `16bf80760`, `775da2c0e`): new
  `expo-web-release.yml` and `collect-plus-release.yml`; the ICD-11 engine bundle is the
  public release `icd11-engine-v2026.10.25.1` (`scripts/package-icd11-engine.sh`,
  `scripts/publish-icd11-engine.sh`). Both workflows passed a non-publishing run.
- **Collect Plus "WHO files" and engine hardening** (`digitva-hs7e`; `cf44110b2`,
  `a5c69a71f`): first-setup / missing-file / "Update WHO files" download rule, setup
  record of real WHO file changes, size check with restore from shipped copies,
  priority worker in `:icd11`, progress events, bundled libssl
  (`io.github.ronickg:openssl:3.3.2-1`), atomic writes, Gradle heap via the config plugin.
- **Collect Plus icon** (`f6c5aa3cf`): the DigitVA icon with a "+" badge, plus build only.
- **DORIS parity, Expo coding screen** (`digitva-gfx8`; merge of the gfx8 branch,
  `5afb21ef1`): 422 field errors shown, half-entered interval blocks Process, UCOD
  titles and WHO notes persisted with the saved result, reports behind Details, empty
  Part II dropped, sex 9 "Unknown"; station bundles pass the plain envelope again.
- **DORIS parity, public demo** (`digitva-4m61`; `8e2219a8c`, `1a5744173`,
  `913089896`): "rejected" shows WHO's reason, compact result card, WHO title as
  condition text, 503 shown as unavailable, strict selection check, 8 conditions per
  line, soft warnings, shared result rows.
- **DORIS engine check** (no code change): a third-party 10,010-case DorisEngine 1.2.1
  reference suite matched our server's DORIS (`whoicd/icd-api:2.6.0`, engine 1.1.176)
  on cause, URI, rejection, report and errors for every case. Owner: stay on 1.1.176
  until WHO ships 1.2.1 in ICD-API.

## 2026-10-24 (late)

- **Collect Plus phase A** (`digitva-hs7e`; `18215a8aa`, `ca3a0e64e`, `85f08b5b4`):
  `APP_VARIANT=plus` build with the offline ICD-11/DORIS engine (our ICD-API 2.6.0
  NativeAOT bridge) in a bound `:icd11` service, background warm-up, engine check
  screen, profileable release, Perfetto trace sections; `scripts/android-profile.sh`,
  `scripts/android-trace.sh`. On the SM-E146B: ready about 20 s after launch, search
  35-220 ms, DORIS 7-180 ms, `:icd11` about 530 MB steady.
- **Phone app 0.3.10 offline gate** (`digitva-5u65`, `2aef46bb3`): no server calls while
  the phone has no network; one sync on reconnect. Hosted on staging as a local upload.
- **Coding screen fixes** (web `expo-web-v2026.10.24.10`, deployed at `73561675a`):
  notes panel renders above the header with a Close button, compact SmartVA and DORIS
  cards, associated VA code and case definition under the chosen cause.

## 2026-10-24

- **Death not before birth** (`digitva-08bj`): the year of death `Id10024` cannot be before the year of birth (`Id10021`, `dob_month_year` or `dob_year`; the same year is valid), and the exact death date `Id10023_b` cannot be before a partial birth date (`Id10023_a` already had the check). Definition version `2026081401-7ee547b8e7`; policy in `docs/policy/digitva-who-form-overrides.md`.
- **Native Statistics and Data management screens in the Expo web app** (`digitva-jv14`, `digitva-3f72`): `/statistics` replaces the Flask `/area/` hop (per-unit bars, drill-down, period, causes, staff view; `/area/` redirects; shown to every grant holder), and `/data` holds the data manager Overview (11 counts, URL-driven filters and sort, upstream-change review, panels, exports) and Causes tabs. Pipeline tab follows (`digitva-mmj8`). Design and inventory: `.tasks/2026-10-24-expo-dashboards-dm-mentor-district.md`; policy `docs/policy/area-dashboard.md`, `docs/policy/data-manager-workflow.md`.
- **Data manager API fixes** (`digitva-10fd`, `digitva-208a`, `digitva-4xpd`, `digitva-i347`, `digitva-ujbi`, `digitva-d92d`): redacted viewers cannot sort by coder; bad dates, schemes and day counts are 400 not 500; list rows carry `has_smartva_failed`; admin reaches the list, counts, exports and sync APIs; sync runs filter by scope before the 25-row cap; sync POSTs are rate limited; empty dates sort last; the gender filter ignores case; the area cause rows carry `suppressed`.
- **Address hints on free-text place questions** (`digitva-xrqv`): `Id10054`, `Id10055`, `Id10057`, `Id10072` gain an en + hi hint saying an address or place name is wanted, not a category. Definition version `2026081401-5a091ba784`; policy `docs/policy/digitva-who-form-overrides.md`.
- **Date of registration check** (`digitva-y5te`): `Id10071` cannot be in the future or before the date of death (year only when the day is unknown). Definition version `2026081401-0e105c1d52`; policy in `docs/policy/digitva-who-form-overrides.md`.
- **Phone app 0.3.3** (`3c2131d03`): release of everything below. CI run
  `android-v0.3.3` awaits approval; until it is pinned, staging serves a
  locally built 0.3.3 (`docs/current-state/android-release-builds.md`).
- **Consent chip and delete a never-sent draft** (`digitva-wy90`, `0a32821c0`):
  the interview shows its consent decision and lets the interviewer change it;
  an unsent draft can be deleted. The previous decision is not kept: the
  server rejects `supersedes` for unsent consents, so only the latest decision
  is sent.
- **Demo purge and station fixture** (`1f7289d3f`): the demo purge covers
  `auth_sign_in_tokens`; the station fixture is regenerated; the UI string
  source check is named once.
- **Celery beat crash loop fixed** (`44bfe72be`): a circular import of the UI
  string service crash-looped beat on staging between the first pull-only
  deploy and this fix.
- **Android `android-v0.3.2` hosted on servers** (`ec1b2d34f`): CI-built APK
  pinned in `x-release-pins`; staging deployed at `ec1b2d34f`.
- **Screenshots allowed in release APKs until 2026-10-30** (`a68e92a2d`,
  `digitva-om65`): `EXPO_PUBLIC_ALLOW_SCREENSHOTS_UNTIL`; remove afterwards.
- **Expo web `expo-web-v2026.10.24.2` to `.4`** (`.4` from `b907cd7d5`,
  pinned in `1b3760ae4`, `073490e15`, `1a429aeab`): the pins for the changes
  below. `.1` was never used.
- **Form colours follow the app theme** (`digitva-klzc`, `f273c99c7`): a
  `FormTheme` prop replaces the engine's hard-coded greens.
- **Form usability pass** (`digitva-e49e`, `digitva-man7`, `digitva-12ks`,
  `digitva-v5zz`, `digitva-kkdb` step 1, `92da1f8e7`): a problems popup whose
  rows jump to each field (Go), age assists, narration language taken from the
  script, a compact footer, a year control, safe insets, a revision reason and
  a dictation tip.
- **In-app confirm dialog and submit banner** (`digitva-8ehe`, `digitva-0d3a`,
  `00da8d2a2`): releases are confirmed in an app dialog, web submits in a
  banner, instead of the browser's.
- **Interviewer FAQ and daily update check** (`digitva-zgl2`, `digitva-2vrs`,
  `a9bfd29fe`, `c77dba3e6`): the Help sheet carries the FAQ; the phone checks
  once a day for a newer APK and offers it only when its link is https.
  `c502a2bc0`: the server tells the phone which APK version it offers.
- **Attachments in phone interviews** (`3a19c7aad`, `061360ca4`,
  `50cafaf56`): audio recording, photos and PDFs; interviews started without a
  case can carry them; narrative recordings pause and resume.
- **Phone clock check** (`digitva-ltqg`, `57adf7bbc`, `05d3b3a7e`): the server
  records each upload's clock offset and flags a wrong clock; the phone warns
  above 5 minutes and blocks data entry above 4 hours, measured from the
  server `Date` header and saved with the check.
- **Azure machine translation of missing UI strings** (`digitva-cqw9`,
  `9dd2440d3`): drafts in the Indian languages saved as candidates an admin
  reviews, never live; migration `q7c2n5x9d4b8`; `1f7289d3f` fixes a
  constraint name with `89f755b1156c`. Azure Translator is configured and
  verified on staging (2 Punjabi drafts).
- **Users screen redesign** (`digitva-9npt`, `f454c601d`): fly-out filters,
  quick chips, one line per user, a Status popup and the sign-in QR dialog.
  `6140258b6`: the users list filters on the server and returns a status
  summary per user.
- **Sign-in QR for data collectors and death reporters** (`digitva-3g19`,
  `digitva-mhjg`): policy `55df618f1`; server `a62b78a70` (migration
  `f3c8a1d5b7e2`); phone `e6e56b254` (redeem, six-box PIN, optional long-PIN
  field) and `9b397cc4d` (PIN longer than six digits, fingerprint or phone
  screen-lock unlock, the screen-lock weakness stated plainly). Security
  review done.
- **Phone consent parity and owner form defaults** (`99b340c5c`): the phone
  asks for respondent consent, explains refused uploads, defaults `Id10051`
  yes and `Id10053` "-", and prefills residence `Id10055`.
- **Phone app polish** (`c96197359`): only work that can be sent counts as
  unsent ("unsent" means ready to send), the phone says why anything stays,
  and the language switch sits in the header.
- **Names on coding screens** (`9ee184c5c`): shown to coders cleared for
  personal data and to the submitter in a self-coding project.
- **Phone shell** (`2ea4f8d5a`, `e6f60fa81`, `80be9f235`): one toast system,
  full-height forms, a header, bottom tabs, account menu, Settings, Help and
  an exportable error log; a Home dashboard, a searchable Interviews list and
  site picker, deceased names on rows, empty, loading and offline states.
- **CI builds the server image** (`7e2174a14`, `server-images.yml`): pushes
  `ghcr.io/drguptavivek/digitva-app:<sha>` (public package); servers only pull
  (`docker-compose.images.yml`, `make prod-pull`, `scripts/deploy-server.sh
  <sha>`). Staging adopted it 2026-10-24: first pull-only deploy `1a429aeab`,
  then `1b3760ae4`, `44bfe72be`, `ec1b2d34f` (migrations `e7b2c4d8f1a3`,
  `f3c8a1d5b7e2`, `q7c2n5x9d4b8`, `89f755b1156c`; analytics MV refreshed;
  build cache pruned).
- **Full suite**: 6226 passed on 2026-10-24, then the 2 failures were fixed. An
  earlier 252-failure run came from stale test databases (`create_all` never
  adds columns): drop `minerva_test_*` after schema changes.

## 2026-10-23

- **`finalAgeInYears` on web and app submissions** (`digitva-wsab`): set by
  the ND01 rule (ageInYears, else ageInYears2, else "000") so `va_deceased_age`
  is no longer 0 ("Age: 0" on coding cards); migration `e7b2c4d8f1a3` backfills
  existing web/device payloads in place, reversibly. Refresh the analytics MV
  after it runs. `docs/policy/who-2022-age-derivation.md`.
- **Expo web `expo-web-v2026.10.23.3`** (from `d31d1ef8d`: Training menu and screens) pinned in `x-release-pins`.
- **Training in the Expo app** (`digitva-r2pf`, `digitva-rcwt`): a Training
  menu (Interview, Coding, Review by training role) and `/app/training`;
  every request excludes the training project by default (Flask and API),
  `?training=1` widens to it only for an active participant, trainer tools opt
  out; one active allocation per coder/reviewer per side (migration
  `d6a1f3b8c2e4`). `docs/policy/training-demo-project.md`.
- **Phone app 0.3.2** (`digitva-zm9w`, `digitva-2cy0`): transactions stay on
  the keyed SQLCipher connection (expo-sqlite's exclusive transaction opened
  an unkeyed one) and `busy_timeout` 5 s; background refresh never redraws an
  open form, failures are a toast with the Ref line and back off; Refresh
  spinner; the Ref line keeps native function names and the cause; emblem
  icon; `.dev` debug variant; screenshots allowed in builds that set
  `EXPO_PUBLIC_ALLOW_SCREENSHOTS_UNTIL` (temporary, until 2026-10-30,
  `digitva-om65`).
- **Android `android-v0.3.1`** (CI run 39938767176 from `8da64237c`, Ref line
  under generic errors) published and pinned for `/download/android`.
- **Expo web `expo-web-v2026.10.23.2`** (from `a531ba664`: Ref line, server
  reason and Fix line on refused submits) pinned in `x-release-pins`.
- **Unknown exact date of death** (owner 2026-10-23): when `Id10022` is not
  yes and `Id10024` holds the year, the case gets 1 July of that year (capped
  at today), never replacing a date on file; web submit, revision and ODK case
  creation. A direct start with only the year no longer fails at submit.
  `docs/policy/web-intake.md`.
- **Identity refusals name the questions**: the 422 "Record the name, date of
  death and sex" carries `fields` (Id10017/18, Id10019, Id10022 + Id10024 or
  Id10023_a/_b), and the web page shows them as "Fix: Section › Question".
- **Web submit refusals show the server's reason** (`digitva-l3r8`): a 422 on
  interview submit shows the server's rule text (consent, Id10013, identity)
  with the `Ref:` line, and web 400/422/5xx messages carry the `Ref:` line,
  instead of "Check the highlighted fields" with nothing highlighted.
- **SmartVA batch failure split** (`digitva-vv4h`): a multi-case whole-run
  failure reruns each case alone, so one bad case no longer fails the batch.
- **Intake device submit CPU** (`digitva-9m11`, `digitva-anzv`): section
  relevance evaluated once per pass; interviewer context and locked death
  built once per submit. ~11% less CPU, 75 -> 68 SQL statements per submit.
- **Slow-request log** (`digitva-cpak`): `logs/slow_requests.log` with
  `SLOW_REQUEST_LOG_MS`; `docs/current-state/runtime-and-operations.md`.
- **Load-test harness** in `scripts/loadtest/`;
  `docs/kb/load-test-and-optimizations-2026-10.md`.
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
