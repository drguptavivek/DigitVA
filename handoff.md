# Handoff

## Start here

Read `AGENTS.md`, `docs/current-state/README.md`, then the policy for the piece
you take. Owner focus (bd memory `focus-2026-10-22`): the station app is paused;
work on training (TRN01), the Expo web app and digitva-collect (Android, data
collection only). digitva-coder will be a new Expo project in its own folder.
Stage explicit paths (`grep -Ev` filters, check the staged list), never stash,
one full parallel run (`-n 4`) on a database of your own, one test database per
concurrent agent. **The owner decides commit timing: hold commits until the
owner says go, then one commit.** The owner owns `vendor/who-va-2022`.
Owners may edit accounts and translations: reread live state.

## State (2026-10-22, night)

`main` = `origin/main`. Migration head: `c8e4a2f6b1d3 → d4a7c9e2f5b1` (consent
notice approval) `→ f6b2d8a4c1e7` (training coder slots); dev is at the head.
Hosts never compile: `smartva-rs` and the Expo web export are pinned GitHub
releases downloaded and SHA-checked in Docker stages (pins in `x-release-pins`,
`docker-compose.yml`). Dev serves the working tree's export
(`EXPO_CLIENT_DIST=/app/mobile/digitva-collect/dist` in the override).

Staging: `https://digitvav3.causeofdeathindia.com`, AWS arm64
`i-0b2caee6465bfcac1` (ap-south-1, profile `digitva`, `/data/DigitVA`); read-only
checks via `aws ssm send-command` (the DB is external: query through
`minerva_app_service` with `DATABASE_URL`). Never change staging without asking.

## Ranked next steps

1. Publish a new Expo web release (`npm run vendor:build`, `npm run
   export:web`, tarball + `.sha256` as `expo-web-v<date>` on DigitVA) and bump
   `EXPO_WEB_TAG`/`EXPO_WEB_SHA256` in `x-release-pins`. The pinned
   `expo-web-v2026.10.22` predates the consent, case-view, Users and Hindi fixes.
2. `digitva-k4jt` digitva-collect: the QR may name any https server under
   `causeofdeathindia.com` (owner decision; today a release build accepts only
   `digitva.`, so staging cannot enrol); Settings shows the server read-only,
   change = re-enrol, refused while anything is unsynced. Staging's
   `DEVICE_PUBLIC_URL` must be the digitvav3 origin (unchecked).
3. `digitva-342x` revoke unused enrolment codes and enrolled devices from the
   Users page.
4. digitva-collect queue: `0vgh` phone consent (always required, like the
   station), `cpx5` collection-only build, release key, per-ABI APK, GitHub
   release link (the 19 Oct `android-v0.1.0` APK is stale), `zkgx`
   questionnaire languages from the server (UI English + Hindi only), `jkvl`
   audio/photo on the phone, `jish`, `wh4w`.
5. Staging after deploy: Project Setup → HP0001 → Respondent consent → "Seed
   from draft", approve when legal review is done, then switch "Require
   respondent consent" on. `flask training-demo setup` if TRN01 is missing.
6. Aakanksha's direct interview (staging, `88606c5b`, submitted fine at 06:58
   UTC) was asked again for name/age at completion; the deceased section was
   saved only at the second attempt. Unreproduced: need the exact message,
   phone or browser, tabs. Two empty direct drafts of hers (`5d31cbd0`,
   `cd39dff7`) sit at "Details pending".
7. Older: `owqc`, `en2g`, `2s6p` (Fable review), `hs7e` ICD-11 on Android
   (digitva-coder, deferred), `a6q9` KPI cards in UTC.

## Open owner decisions

- Staging draft `84e711b0` (empty, Test Admin, created by opening a start link):
  discard?
- Enrolment email code lifetime (24 h, single use) and whether PIs may send it.
- Users page: device sessions and activity counts are shown across the viewed
  user's projects / whole project, not only the viewer's subtree.
- Hindi strings of the Users page are the writer's translations: review.
- Web consent gaps: server accepts a submission with no consent decision when
  no covered answer is filled; a refusal while editing a registration is not
  sent; withdrawal.
- ICD-11 licence inventory (`docs/kb/icd11-licence-inventory.md`); bulk import
  `created_via: import` vs audit `project_import`.

## Decisions already made (do not reopen)

Corrections are submitter-only; respondent consent is required when the project
turns it on, notice seeded from the draft (en + hi), editable, "pending legal
review" until an admin approves; Deaths menu hidden for direct-only
interviewers, supervisors keep it; Add worker suggests all accounts and emails
the enrolment QR + APK link to data collectors only; non-admin enrolment codes
are single use within 60 minutes; training coder slots are chosen per session
(1–100, cases repeat across slots); reviewers may review their own coding;
expired station configs are refused; every account records its creator; the
WHO ICD container stays on servers (Rust ICD licensing unresolved).

## Caveats

- Shared Python venv volume `digitva_minerva_venv` must be refreshed after an
  image rebuild (stop app/worker/beat, `docker volume rm`, `up -d`).
- `.dockerignore` excludes `desktop/` and `vendor/who-icd11-api/` (they made
  images 6 GB+).
- `resource/smartva-phmrc-dataset/` and `docs/from-server/` are untracked and
  not part of this work.
