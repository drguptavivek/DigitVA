# Handoff

## Start here

Read `AGENTS.md`, `docs/current-state/README.md`, then the policy for the piece
you take. What already landed: `CHANGELOG.md`. Owner focus (bd memory
`focus-2026-10-22`): training, the Expo web app, digitva-collect (Android), and the
experimental **Collect Plus** variant (offline coding, bead `digitva-hs7e`, plan
`.tasks/2026-10-24-collect-plus-offline-coding.md`). The owner owns
`vendor/who-va-2022` and decides commit timing; one committer session lands
everything, workers commit only to their worktree branch.

Working rules the owner set on 2026-10-24/25 (bd memories): **no local APK, Gradle or
Expo web-export builds on the Mac — build only on GitHub Actions**
(`builds-on-ci-only`); Haiku writers, Sonnet reviewer before every merge
(`code-writer-model`); coders' phones have at least 6 GB RAM (`coder-phone-ram`);
DORIS engine stays 1.1.176 on server and phone until WHO ships 1.2.1 in an official
ICD-API image (`doris-engine-version`).

Tests: targeted pytest on a database of your own; one full suite at a time.

## State (2026-10-25)

Migration head `c3f9a1d7e2b4` (dev and staging).

Staging `https://digitvav3.causeofdeathindia.com` (AWS arm64 `i-0b2caee6465bfcac1`,
profile `digitva`, `/data/DigitVA`) runs image `d7f8ac86e`, web
`expo-web-v2026.10.25.1`, and a locally uploaded **APK 0.3.10** (override in
`.env`; preserve `DIGITVA_ANDROID_APK_DIR=/app/private/android-hosted`).
`DORIS_CALL_LOG=1` is still on there (turn off when DORIS debugging ends). The
owner authorized this session's SSM deploy (`digitva-pjc8`). Future staging deploys:
`scripts/deploy-staging.sh <full-sha>` after CI passes; rollback image `73561675ad00fe510ab7237925df86f59509f767`.

CI workflows (main): `server-images.yml`, `android-release.yml`,
`expo-web-release.yml` (new) and `collect-plus-release.yml` (new; pins engine
release `icd11-engine-v2026.10.25.1`, sha256 `975887076aab…0a3`). Both new
workflows passed a non-publishing run (40131082739, 40131601066). Signing runs in
the `android-release` environment: the owner approves each run in GitHub.

## Ranked next steps

1. **Publish Collect Plus** `collect-plus-v0.3.10-plus.1` (prerelease) on the
   owner's go; install on the SM-E146B, confirm warm-up and the engine check.
2. **Collect Plus phase B** (`digitva-hs7e`): in Plus, route DorisPanel search,
   codeinfo and process to the offline engine; native ICD-11 search UI (the picker
   WebView host is server-served); parity check and sync at final save (server
   process token); offline case queue. Then phase C profiling (baseline vs
   `:icd11`), using `scripts/android-profile.sh` and `scripts/android-trace.sh`.
3. **DORIS parity pass 3** (`digitva-knh9`): demo gets dates/manner/surgery/autopsy,
   WHO field labels, pregnancy follow-ups hidden until Yes, search 3 chars/500 ms,
   rule trace behind Details in Expo.
4. **Standard CI across projects**: proposal card "Standard CI: reusable workflows
   + S3 via OIDC" (owner chose GitHub Actions; public `ci-templates` repo and the
   AWS OIDC role need the owner's go).
5. `digitva-om65` (P1): remove the screenshot allowance after 2026-10-30.
6. Open P1s: `digitva-fvbc` (web autosave loops on `csrf_failed`), `digitva-owbz`,
   `digitva-46xk`, `digitva-342x`; mentor view `digitva-oux5` (an early feedback
   model/migration is recovered in `private/worktree-patches/`).
7. Hindi review of the ~240 new keys in `mobile/digitva-collect/src/strings/hi.json`.
8. Older: `digitva-zfsa`, `digitva-yufk` (STT), public demo deploy `digitva-77v5.7`,
   SmartVA `digitva-vv4h`, `cpak`, `zkgx`, `jish`, `wh4w`.

## Open owner decisions

- Collect Plus review findings not yet fixed (low): a readable setup record with a
  malformed `files` entry fails init stickily (`EngineData.acceptedWho`);
  `extractOpenSsl` does not fail on an empty copy; the Plus workflow asks for
  environment approval before its own fast-fail checks.
- 16.8 GB of unattached Docker volumes on the Mac (37 of 41): list and decide.
- `scripts/loadtest/restore.sh` uncommitted change; orientation `.pptx` files in
  `docs/manuscript/` (do not commit the `~$` lock file).
- KEM001: 24 submissions stuck in `attachment_sync_pending`.
- Demo host `digitvademo.causeofdeathindia.com` runbook and deploy; safety
  snapshots `snap-01fa17178686012df`, `snap-0aaaf620a2070b3e7`; unused release
  `expo-web-v2026.10.24.1`.
- Consent history (only the latest decision is sent); enrolment code lifetime;
  web consent gaps; ICD-11 licence inventory (public engine release is the owner's
  call, 2026-10-25).

## Decisions already made (do not reopen)

Engine release and Collect Plus APK are public GitHub release assets; WHO file
downloads only at first setup, on a missing/wrong-size WHO file, or the explicit
"Update WHO files" button; OpenSSL comes from `io.github.ronickg:openssl:3.3.2-1`
(libssl only, libcrypto from expo-sqlite); the engine runs in the `:icd11`
process; Collect Plus keeps our ICD-API 2.6.0 bridge (real WHO search) over the
third-party prototype. Earlier: corrections are submitter-only; respondent consent
required when the project turns it on (notice seeded en + hi, "pending legal
review" until approved); non-admin enrolment codes single use within 60 minutes;
training coder slots per session; reviewers may review their own coding; expired
station configs refused; the WHO ICD container stays on servers; the intake write
path is not batched; no EC2 upsize until measured load calls for it.

## Caveats

- Standalone `deploy-server.sh` dirty-submodule guard: `digitva-22lb`; staging wrapper is guarded.
- Do not push to main while an image build runs. Use full 40-character SHAs for CI refs.
- Quote backticks in `bd create -d "..."`; `bd update --notes` REPLACES notes —
  use `--append-notes`.
- Worktree removal with `--force` deletes untracked files: check
  `git status --porcelain` including untracked before removing.
- Drop `minerva_test_*` databases after model changes.
- `vendor/who-va-2022` `npm ci` fails (lockfile out of sync): symlink or copy
  `dist` into worktrees (`vendor/who-va-2022/dist` and
  `node_modules/@drguptavivek/who-2022-va/dist`).
- The plus JS bundle reads `APP_VARIANT` at Gradle time; `isPlusVariant` also
  detects the engine module.
- A stopped background agent may leave work uncommitted in its worktree: commit it
  as WIP before starting a successor.
