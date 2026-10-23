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
checks via `aws ssm send-command`. Never change staging without asking. Load
test 2026-10-22: 200 users ~26 req/s, p95 1.1–1.4 s; DORIS saturates ~68 req/s;
CPU-bound (2 cores), not memory-bound.

## Ranked next steps

0. **Landing queue** (owner 2026-10-23: land the optimizations; one committer
   session lands them, each after its own targeted tests, one full suite per
   landing): streaming exports and paged ODK sync
   `digitva-lj7u`. Follow-ups: `digitva-mubf` (COD bucket rule mismatch), `digitva-xp9w`
   (EXPLAIN a real staging bucket report before more MV work).
1. Coding allocation follow-ups from the 2026-10-23 security review:
   `digitva-nw4b` (random vs pick lock order can deadlock -> 500 for one user
   firing both at once), `digitva-hbrs` (a failed concurrent index build leaves
   an INVALID index that a re-run keeps).
2. **Releases.** Each web change ships as an Expo web release (`npm run
   vendor:build`, `npm run export:web`, tarball of `dist/` + `.sha256`, tag
   `expo-web-v<date>[.n]`, `gh release create … --latest=false` so Android stays
   Latest), then bump `EXPO_WEB_TAG`/`EXPO_WEB_SHA256`. Android: CI
   `android-release.yml` (publish=true, tag `android-v<version>`, environment
   approval), then pin the arm64 asset (`ANDROID_APK_*`) for
   `/download/android`. Signing key `private/android/` (owner backs it up;
   fingerprint in environment variable `ANDROID_RELEASE_CERT_SHA256`).
   Current: `android-v0.3.0` (Latest) and `expo-web-v2026.10.22.5`, both built
   from `21ccf04dc`.
3. **Public demo deploy** (`digitva-77v5.7`) per the runbook: DNS, DMZ block for
   `demo.causeofdeathindia.com`, S3 `demo/` prefix, demo DB and keys. Then
   `digitva-77v5.9` (seed without the default admin). Owner: review ~40 Hindi
   strings in `mobile/digitva-collect/src/strings/hi.json`; WHO ICD-11 API terms
   for anonymous public use. Proof-of-work timing on a real phone is untested.
4. **Re-measure process memory** on dev after restarting app, worker and beat
   (idle VmRSS from `/proc/<pid>/status`). The figures in
   `runtime-and-operations.md` came from copies started from worktrees, and
   with lazy imports pandas/openpyxl now load per worker, so `--preload` no
   longer shares them.
5. **SmartVA in-process and coalescing** (`digitva-5gsq`, `digitva-96ik`,
   landed): staging deploy and 200-user load re-test requested by the owner;
   expect the SmartVA queue to drain ~100+ tasks/s on one worker; watch the
   worker child RSS against the 300000 KB cap. Known ceilings: the batch claim
   is not atomic above worker concurrency 1; a whole-run failure fails every
   case in the batch. Rollback: `SMARTVA_RS_LIB=""`.
6. Staging `DEVICE_PUBLIC_URL` must be the digitvav3 origin (unchecked).
7. `digitva-342x` revoke unused enrolment codes and enrolled devices from the
   Users page.
8. digitva-collect queue: `0vgh` phone consent, `zkgx` questionnaire languages
   from the server, `jkvl` audio/photo, `jish`, `wh4w`.
9. Staging after deploy: Project Setup → HP0001 → Respondent consent → "Seed
   from draft", approve after legal review, then turn "Require respondent
   consent" on. `flask training-demo setup` if TRN01 is missing.
10. Aakanksha's direct interview (staging `88606c5b`) re-asked name/age at
    completion; deceased section saved only on the second try. Unreproduced:
    need the message, device and tabs. Her empty drafts `5d31cbd0`, `cd39dff7`.
11. Older: `owqc`, `en2g`, `2s6p`, `hs7e` (digitva-coder, deferred), `a6q9`.

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

- After an image rebuild, refresh the shared venv volume `digitva_minerva_venv`
  (stop app/worker/beat, `docker volume rm`, `up -d`).
- `.dockerignore` excludes `desktop/` and `vendor/who-icd11-api/` (6 GB+ images).
- `resource/smartva-phmrc-dataset/` is local research data, git-ignored.
