# Handoff

## Start here

Read `AGENTS.md`, `docs/current-state/README.md`, then the policy for the piece
you take. What already landed: `CHANGELOG.md`. Load tests, measured
optimizations and dropped ideas (Oct 2026): `docs/kb/load-test-and-optimizations-2026-10.md`. Owner focus (bd memory
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

## State (2026-10-24)

Migration head `89f755b1156c`; dev is at the head. Hosts never compile:
`smartva-rs` and the Expo web export are pinned GitHub releases, SHA-checked in
Docker stages (`x-release-pins` in `docker-compose.yml`). CI builds the server
image (`server-images.yml`, `ghcr.io/drguptavivek/digitva-app:<sha>`); servers
only pull (`make prod-pull`, `scripts/deploy-server.sh <sha>`). Dev serves the
working tree's export (`EXPO_CLIENT_DIST` in the override).

Staging: `https://digitvav3.causeofdeathindia.com`, AWS arm64
`i-0b2caee6465bfcac1` (ap-south-1, profile `digitva`, `/data/DigitVA`); read-only
checks via `aws ssm send-command`. Never change staging without asking. The
owner runs the deploy scripts (agent SSM writes are blocked); keep pull output out
of SSM output (24 KB cap). Staging runs `ec1b2d34f` (pull-only deploy),
`expo-web-v2026.10.24.4`, Azure Translator configured. Staging serves a
locally built 0.3.3 APK through `DIGITVA_ANDROID_APK_DIR=/app/private/android-hosted`
in its `.env` (file in `/data/DigitVA/private/android-hosted`). CI
`android-v0.3.3` is published and pinned in `9b64ec372` (image run 40023434115);
deploying that image removes the override
(`sed -i '/^DIGITVA_ANDROID_APK_DIR=/d' .env`).

## Ranked next steps

1. **Deploy `9b64ec372`** (CI 0.3.3 pinned): the owner deploys; the APK
   override comes off staging. Releases: Expo
   web `npm run vendor:build`, `npm run export:web`, tarball + `.sha256`, tag
   `expo-web-v<date>[.n]`, `gh release create … --latest=false`, bump
   `EXPO_WEB_TAG`/`EXPO_WEB_SHA256`. Signing key `private/android/` (owner backs
   it up; fingerprint in `ANDROID_RELEASE_CERT_SHA256`).
2. **Owner field testing on 0.3.3**: audio and camera, consent chip, delete
   draft, sign-in QR / PIN / unlock, errors popup, age assists, colours, clock
   warning and block.
3. **Staging setup**: Project Setup → HP0001 → Respondent consent → "Seed from
   draft", approve after legal review, turn "Require respondent consent" on.
   Press the machine-translate button, then review the drafts.
   `flask training-demo setup` if TRN01 is missing.
4. **Hindi review**: about 200 new keys landed 2026-10-24 in
   `mobile/digitva-collect/src/strings/hi.json` (plus the ~40 earlier).
5. `digitva-om65` (P1): remove the screenshot allowance after 2026-10-30.
6. **Open P1 bugs**: `digitva-fvbc` (web autosave loops on `csrf_failed`),
   `digitva-owbz` and `digitva-46xk` (revise a submitted interview; verify
   whether `92da1f8e7` fixed them before work), `digitva-342x` (revoke unused
   enrolment codes and devices from the Users page).
7. `digitva-zfsa` (P3): desktop crate served-definition sha pins after the
   2026-10-24 form changes.
8. **Speech to text**: in-app on-device STT needs owner approval; spike
   `digitva-yufk`.
9. **Public demo deploy** (`digitva-77v5.7`, then `.9`) per the runbook; WHO
   ICD-11 API terms for anonymous use; proof-of-work timing on a phone untested.
10. SmartVA `digitva-vv4h` (coalescing not atomic above concurrency 1; rollback
    `SMARTVA_RS_LIB=""`); digitva-collect `zkgx`, `jish`, `wh4w`; request path
    CPU-bound, act only if the slow log (`digitva-cpak`) points at intake.
11. Older: `owqc`, `en2g`, `2s6p`, `hs7e`, `a6q9`, `mubf`, `xp9w`, `8dzk`,
    `f0ys`, `783d`; Aakanksha's unreproduced re-asked name/age (`88606c5b`).

## Open owner decisions

- `scripts/loadtest/restore.sh` has an uncommitted change from the autosave
  session: commit or drop?
- Consent change history: only the latest decision is sent (the server rejects
  `supersedes` for unsent consents). Keep, or build a history?
- Leftover release `expo-web-v2026.10.24.1` (unused) and the old waiting image
  run 40018081998: delete?
- Staging draft `84e711b0` (empty, Test Admin): discard? Users page: device
  sessions and activity counts span the viewed user's projects, not only the
  viewer's subtree.
- Enrolment email code lifetime (24 h, single use) and whether PIs may send it.
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
ICD container stays on servers; the intake write path (payload version, PII,
transitions, audit) is not batched, consistency first; no EC2 upsize until
measured real load (slow-request log, `digitva-cpak`) calls for it.

## Caveats

- Quote backticks in `bd create -d "..."` descriptions: the shell runs them.
- Drop `minerva_test_*` databases after model changes: `create_all` never adds
  columns, stale ones caused a 252-failure run.
- `vendor/who-va-2022` `npm ci` fails (lockfile out of sync): symlink
  `node_modules`.
- Worktree writers append strings at the end of `en.json`/`hi.json`: expect
  union merges.
- Local signed APK build recipe: `docs/current-state/android-release-builds.md`,
  with `DIGITVA_ANDROID_VERSION_CODE=<major*10000+minor*100+patch>` and
  `EXPO_PUBLIC_ALLOW_SCREENSHOTS_UNTIL`.
- GitHub release creation and staging writes are owner-run (permissions).
- After an image rebuild, refresh the shared venv volume `digitva_minerva_venv`
  (stop app/worker/beat, `docker volume rm`, `up -d`).
- `resource/smartva-phmrc-dataset/` is local research data, git-ignored.
