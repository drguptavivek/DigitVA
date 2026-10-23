# Handoff

## Start here

Read `AGENTS.md`, `docs/current-state/README.md`, then the policy for the piece
you take. What already landed: `CHANGELOG.md`. Owner focus (bd memory
`focus-2026-10-22`): station app paused; training (TRN01), the Expo web app and
digitva-collect (Android, collection only). digitva-coder will be a new Expo
project in its own folder. The owner owns `vendor/who-va-2022` and decides
commit timing. With parallel sessions, one committer session lands everything;
the others commit only to their own worktree branch.

Tests: one full suite at a time, `-n 2` (~15-19 min) on a database of your own,
and not while other sessions benchmark against dev Postgres: concurrent load
OOM-killed it twice on 2026-10-22 and made a full suite drop ~90 tests. Dev
`minerva_db` is now capped at 1 GB (override); `-n 4` can still overflow the
lock table during schema setup.

## State (2026-10-23)

Migration head `b4d6f8a2c9e1`; dev is at the head. Hosts never compile:
`smartva-rs` and the Expo web export are pinned GitHub releases, SHA-checked in
Docker stages (`x-release-pins` in `docker-compose.yml`). Dev serves the working
tree's export (`EXPO_CLIENT_DIST` in the override).

Staging: `https://digitvav3.causeofdeathindia.com`, AWS arm64
`i-0b2caee6465bfcac1` (ap-south-1, profile `digitva`, `/data/DigitVA`); read-only
checks via `aws ssm send-command`. Never change staging without asking.
Staging runs `f23339810` (head `c5e7a9b1d3f6`, smartva-rust 3.0.2,
`expo-web-v2026.10.23.1`). Load test 2026-10-23, 200 users, worker running at
`cpu_shares` 128: 26.8 req/s, 0 5xx, request p50 within ~30-75 ms of the
worker-paused baseline (intake 461 vs 388 ms, allocate 182 vs 129), SmartVA
queue ≤11, Python services −175 MB idle vs 2026-10-22, COD refresh 7.7 -> 2.6 s.
DORIS saturates ~68 req/s.

## Ranked next steps

1. **Request path is CPU-bound in Python** (2 cores; 92% of busy backends idle
   in transaction during load, no lock waits). Next lever: profile the slowest
   endpoints (intake p95 ~1 s), or 4 vCPU. Load-test harness to
   `scripts/loadtest/` (agreed, small change through the committer).
2. **Releases.** Each web change ships as an Expo web release (`npm run
   vendor:build`, `npm run export:web`, tarball of `dist/` + `.sha256`, tag
   `expo-web-v<date>[.n]`, `gh release create … --latest=false` so Android stays
   Latest), then bump `EXPO_WEB_TAG`/`EXPO_WEB_SHA256`. Android: CI
   `android-release.yml` (publish=true, tag `android-v<version>`, environment
   approval), then pin the arm64 asset (`ANDROID_APK_*`) for
   `/download/android`. Signing key `private/android/` (owner backs it up;
   fingerprint in environment variable `ANDROID_RELEASE_CERT_SHA256`).
   Current: `android-v0.3.0` (Latest, from `21ccf04dc`) and
   `expo-web-v2026.10.23.1` (from `19c05ba07`).
3. **Public demo deploy** (`digitva-77v5.7`) per the runbook: DNS, DMZ block for
   `demo.causeofdeathindia.com`, S3 `demo/` prefix, demo DB and keys. Then
   `digitva-77v5.9` (seed without the default admin). Owner: review ~40 Hindi
   strings in `mobile/digitva-collect/src/strings/hi.json`; WHO ICD-11 API terms
   for anonymous public use. Proof-of-work timing on a real phone is untested.
4. SmartVA known ceilings (`digitva-96ik`): the batch claim is not atomic
   above worker concurrency 1; a whole-run failure fails every case in the
   batch. Rollback for the in-process engine: `SMARTVA_RS_LIB=""`.
5. Staging `DEVICE_PUBLIC_URL` must be the digitvav3 origin (unchecked).
6. `digitva-342x` revoke unused enrolment codes and enrolled devices from the
   Users page.
7. digitva-collect queue: `0vgh` phone consent, `zkgx` questionnaire languages
   from the server, `jkvl` audio/photo, `jish`, `wh4w`.
8. Staging after deploy: Project Setup → HP0001 → Respondent consent → "Seed
   from draft", approve after legal review, then turn "Require respondent
   consent" on. `flask training-demo setup` if TRN01 is missing.
9. Aakanksha's direct interview (staging `88606c5b`) re-asked name/age at
    completion; deceased section saved only on the second try. Unreproduced:
    need the message, device and tabs. Her empty drafts `5d31cbd0`, `cd39dff7`.
10. Older: `owqc`, `en2g`, `2s6p`, `hs7e` (digitva-coder, deferred), `a6q9`.
   Also: `mubf` (COD bucket rule mismatch), `xp9w` (EXPLAIN a staging bucket
   report before more MV work), `8dzk` (allocation_exists 403 vs 409), `f0ys`
   (spelling-fold tests flaky under xdist), `783d` (SmartVA export header order).

## Open owner decisions

- Staging draft `84e711b0` (empty, Test Admin): discard?
- Enrolment email code lifetime (24 h, single use) and whether PIs may send it.
- Users page: device sessions and activity counts span the viewed user's
  projects, not only the viewer's subtree. Its Hindi strings need review.
- Web consent gaps: a submission with no consent decision is accepted when no
  covered answer is filled; a refusal while editing a registration is not sent;
  withdrawal.
- ICD-11 licence inventory (`docs/kb/icd11-licence-inventory.md`); bulk import
  `created_via: import` vs audit `project_import`.

## Decisions already made (do not reopen)

Corrections are submitter-only; respondent consent is required when the project
turns it on, notice seeded from the draft (en + hi), editable, "pending legal
review" until an admin approves; Deaths menu hidden for direct-only
interviewers; Add worker emails the enrolment QR + APK link to data collectors
only; non-admin enrolment codes are single use within 60 minutes; training
coder slots are per session (1–100); reviewers may review their own coding;
expired station configs are refused; every account records its creator; the WHO
ICD container stays on servers.

## Caveats

- Quote backticks in `bd create -d "..."` descriptions: the shell runs them
  (2026-10-23 a stray `docker update` hit the dev worker this way).
- ODK sync (`digitva-lj7u`): a form syncs in one transaction, so row locks from
  its first page are held through later ODK fetches; a coder saving a case a
  large, slow delta sync updates waits until the form commits.
- SmartVA input export header order follows row order (no ORDER BY;
  `digitva-783d`); harmless for consumers that read columns by name.
- After an image rebuild, refresh the shared venv volume `digitva_minerva_venv`
  (stop app/worker/beat, `docker volume rm`, `up -d`).
- `.dockerignore` excludes `desktop/` and `vendor/who-icd11-api/` (6 GB+ images).
- `resource/smartva-phmrc-dataset/` is local research data, git-ignored.
