# DigitVA Collect (Android and browser)

Offline WHO VA 2022 collection app for Path B of
`docs/policy/field-data-collection.md`. Design and API contract:
`.tasks/2026-09-30-android-collection-app.md` (epic `digitva-kmk`).

The client follows `docs/policy/api-v1.md` (epic `digitva-ntct`): one
`/api/v1` contract through `src/api.ts`, using cookie + `X-CSRFToken` on web
and a bearer token on native. Intake uses `/api/v1/intake/*`; user grants,
sites and role-tagged unit trees come from `/api/v1/me/access`. Access data
controls presentation; the server authorizes every request.

Native sign-in uses `/api/v1/auth/sessions*`; sign-in and token refresh
consume the embedded `access` summary. Browser startup reads `/api/v1/me/access`
and its `X-CSRFToken` response header. Common project form options supply intake
mode and instrument version. Form options, intake prefill policy and
translations use the shared endpoints. Missing or malformed settings block
new collection until a complete compatible reference pack is available.

> **Debug builds must not collect real interviews.** A debug APK is signed
> with a well-known key and loads its JavaScript from Metro. Point it at a
> non-production DigitVA only.

## What it does

The browser build is hosted by the Flask server at `/app/`. It uses the
existing secure server sign-in flow, then loads the authorized collection
worklist from the server. A field worker can register a death, start or resume
a WHO VA interview, save sections to a server draft, change the questionnaire
language, and submit after validation. Coding and review navigation will appear
when those workspaces are implemented in Expo.

The reported-deaths list opens case details for follow-up, visit scheduling,
and starting or resuming an interview. Both clients fetch authorized details by
case ID, independently of list pagination, including full informant contacts,
household address and remarks. List summaries contain masked phones.
Case rows and details warn when another interviewer has an open interview,
using the earliest start time without naming the person. On native, the
warning reflects the last successful sync. It does not block an authorized
interviewer from starting with the case's server-provided prefill.
If a teammate submits first, the browser treats its superseded interview
as a successful retained copy and shows a notice on the collection screen.
Native downloaded cases are the active follow-up subset, while unsynced local
registrations retain their entered household and contact details in the encrypted
store. Only a full phone number can open the dialler after an explicit tap.

The app UI currently supports English and Hindi; Hindi text needs review by a
native speaker. During a browser interview, the app chrome follows the selected
questionnaire language so the form and its controls stay together. The
language switcher is available in the shared header on every browser screen,
including the sign-in landing page. New questionnaire language choices are the
project-enabled English/Hindi intersection; other languages remain available only
when resuming saved drafts. An unsupported default prefers enabled English, then
the first supported enabled language. An explicit list with neither blocks new
interviews; legacy settings without a language list retain the English default.
Unavailable translation resources show English questions with a persistent notice
while retaining the requested locale/version. Partial translations use English for
missing text. Authentication failures still stop access.
Browser answers, identifiers, draft IDs, attachments and tokens remain
server-side; only the UI language and theme preferences may be kept in browser
storage. The browser build does not register a service worker.

In-app navigation waits for draft saving and stays on the form if saving fails.
Closing a tab while changes are unsaved prompts a warning; the browser may
terminate an outstanding save if the user proceeds. Wait for the saved status
before closing. A successful JavaScript export does not replace testing the
native app on a device.

Run the web export with `npx expo export --platform web --output-dir dist`.
The Flask host serves the contents of `dist/` from `/app/` by default (or from
the directory configured by `EXPO_CLIENT_DIST`); copy the contents directly so
`index.html` is at the configured directory root. Keep the Android JavaScript
check separate with `npx expo export --platform android --output-dir
dist-native`, otherwise an Android export replaces the web `dist/` contents.
Native Android behaviour and its encrypted offline storage remain the field
collection path.

Birth-date entry supports an exact date, month and year, or year only,
using the WHO form controls. Partial values use `date_of_birth_partial` (`YYYY-MM`
or `YYYY`) rather than an invented exact date. The device contract preserves
that precision in the case detail's interview prefill.
Registration checks required fields, dates, birth/death ordering, age and phone
format before saving. Age above 125 is refused; age above 85 requires explicit
confirmation. Partial dates retain an age range rather than an invented exact
birthday. The backend must enforce the same upper age limit.

- **Enrol**: scan the one-time QR from the project's Setup home, Devices
  (or paste its JSON in a debug build). The server must be on the allowlist
  compiled into `src/enrolment.ts`: release builds accept
  `https://digitva.causeofdeathindia.com` only; debug builds also accept
  `http://10.0.2.2:8051` (emulator to host) and `http://localhost:8051`
  (device with `adb reverse tcp:8051 tcp:8051`).
- **Interviewers**: several may sign in on one phone. The home screen shows
  display names only. Tokens live in SecureStore per interviewer; the access
  token refreshes with rotation (the refresh also carries the device id and
  secret), one refresh in flight per interviewer.
- **Native sign-in**: choose email or mobile. Mobile entry uses a fixed +91
  prefix and ten Indian mobile digits; the identifier is sent through the
  auth API's existing `email` field. Accounts may have a null email.
  Code redemption and forgotten passwords open the enrolled server's pages.
  Pending terms are accepted in the app through `POST /api/v1/me/terms`;
  collection stays blocked until acceptance succeeds. The app does not offer
  chosen passwords.
- **Offline project settings**: after sign-in and store unlock, download
  reference packs for every authorized interviewer project in `me/access`: intake mode, sites/units,
  questionnaire options and enabled translations. Automatic refresh is at most
  once every 24 hours on ordinary focus; app foreground resume, Sync and Refresh
  force an access/settings attempt. A complete stale pack
  stays usable during a network failure. Authorization refusals block the
  affected workflow; factor and maintenance gates preserve unsent encrypted work.
  Projects removed by a successful access refresh are purged even if later downloads fail. New collection waits
  for a complete compatible pack. Project modes allow registration first,
  direct interviews, both, or neither; existing drafts remain resumable.
  Settings, units, translations and queued work carry their project ID. The
  enrolment project is the device's admin home, not a collection default.
  A project removed from interviewer access loses all its local settings, cases,
  contacts, registrations, actions and drafts. Sync refreshes authorization
  before sending queued work. Direct starts use the project's interviewer
  and selected-unit prefill; registered cases use their detail's locked prefill.
- **Offline registration and interview**: Save and start stores the death
  locally and opens a bound WHO interview without a network request. Drafts
  remain in the encrypted store. Sync registers the death first, replaces its
  local binding with the server death ID, and then uploads the completed
  interview. The reference pack records attempted English/Hindi translation
  availability; missing packs use English with a notice and are retried on the
  next normal refresh or a forced refresh. Missing packs do not overwrite the
  versioned translation cache.
  Each saved draft retains its questionnaire language, enabled modules, instrument
  code and translation version in encrypted metadata. Legacy drafts without a
  reliable configuration are blocked rather than reopened with a different form.
- **PIN and encryption** (phase 2b): after an interviewer's first sign-in on
  the device they set a PIN (6 to 16 digits, confirmed). A random 32-byte
  store secret goes into SecureStore; the SQLCipher passphrase is
  `hex(secret) + ":" + PIN` (`src/vault.ts`), applied with `PRAGMA key` and
  proved with a read. Phase-2a plaintext files are deleted at PIN setup (no
  real data existed). Optional biometric unlock keeps the PIN in a SecureStore
  entry with `requireAuthentication` under its own Keystore alias; a new
  biometric enrolment invalidates it and the PIN takes over. The PIN always
  works.
- **Failed PINs**: counted in SecureStore before each try, cleared on
  success; a warning from the third, and the fifth in a row deletes that
  interviewer's database, keys and tokens and ends their server session.
  Other interviewers are untouched.
- **Lock**: unlocked handles live only in memory (`src/interviewerDb.ts`).
  Auto-lock after 5 idle minutes or on return after over 1 minute in the
  background (`src/autoLock.ts`); **Lock now** on the worklist. Locking saves
  the open form's draft, closes every database and returns home, which shows
  each account's name and Locked/Unlocked only.
- **Secure screens**: `FLAG_SECURE` on the whole app. A debug build started
  with `EXPO_PUBLIC_ALLOW_SCREENSHOTS=1 npx expo start` skips it for emulator
  screenshots; release builds always set it.
- **Drafts**: each interviewer has their own SQLCipher file (`iv_<sha256>.db`),
  opened in `src/interviewerDb.ts`; the form writes through a `draftStore`
  over it (`src/drafts.ts`). Attachments are disabled. New-interview choices
  come from role-filtered `/api/v1/me/access` units and form languages from
  `/api/v1/instruments/<code>/translations/<locale>`, both cached in
  the interviewer's database (`src/sync.ts`). A registered case has one draft
  per interviewer across phone and browser: sync uploads unfinished phone
  drafts after registrations and case actions, before completed interviews.
  When both devices edited the same draft, the newer save wins and the other
  copy stays in server history. Opening the case reconciles its latest server
  draft into the existing phone UUID; a closed-case refusal keeps the phone
  copy for a later superseded submission.
- **Finish**: the form's own completion (valid) marks a draft ready with
  `completion: {valid: true}`; **Finish as incomplete** is allowed only when
  the interview outcome is partially completed or respondent unavailable.
  Only such drafts are uploaded.
- **Send**: ready interviews go to `POST /api/v1/intake/submissions`
  with the stored `project_id`, `client_draft_id` = the draft UUID and `completion`.
  Answers are sent as one exact JSON string plus its SHA-256. The local copy
  is deleted only when the server echoes the matching hash and case ID, and
  the stored envelope still matches the uploaded snapshot. Edits made during
  an upload stay on the phone.
  A `hash_mismatch` keeps the interview, stops automatic retries, and shows
  the stored case ID with a notice that later edits were not applied. An
  invalid hash is recomputed from the same string and retried once; a second
  refusal keeps the draft editable with a needs-attention notice. Superseded
  interviews show that a teammate submitted first and the server kept this copy.
  A 422 (the interview as it stands is refused) puts the draft back in
  progress with its answers, so the interviewer can correct it; other
  refusals keep it ready for the next send.
  Requests time out after 30 seconds, or 120 seconds for interview uploads;
  a timeout stops sync without deleting unacknowledged work.
  Native drafts record interview start and completion with the device's
  local UTC offset. Completing again updates the completion time; each
  upload attempt adds a fresh device clock reading for the server's skew
  audit. Legacy completed drafts without a recorded completion time use
  the server fallback rather than a guessed time.
  The remaining count and draft ids are then reported to `/outstanding`.
- **Offline cases** (phase 3, `src/cases.ts`, `app/case.tsx`,
  `app/register.tsx`): **Send and refresh** runs, in order, offline
  registrations (`POST /deaths`, `project_id`, `client_death_id`), queued contact attempts
  and visit dates (`client_attempt_id`), unfinished registered-case drafts
  (`POST /drafts/sync`), completed interviews (with the case's `death_id`),
  the outstanding report (draft ids, case ids, pending
  registration ids), then downloads every page of `GET /cases?project_id=&state=`
  for registered, scheduled, in-progress, paused, not-reachable and refused cases.
  Each case's detail supplies full contacts for encrypted storage; prefill is
  optional and withheld when the caller cannot start or resume its interview.
  Each project's replacement list is written in one local transaction, so
  an interrupted refresh leaves its previous list intact.
  New offline case interviews require prefill; saved drafts retain their own.
  A case that leaves these active states or returns 404 is removed. Other states
  are shown only in an online, paginated list and never stored. Drafts keep their own
  case binding and prefill. **Start interview** on a case opens a draft
  prefilled from the case (as the web form) and bound to it; an interview on
  a registration not yet sent waits for it. A 422 marks a registration,
  attempt or visit "Not accepted" for editing or discarding; a 404/409 on an attempt
  does the same.
- **Sign out** warns about unsent interviews, then deletes that
  interviewer's database, store secret, PIN counter, biometric entry and tokens. A `401 session_revoked` does the same
  without asking. Any other refused refresh (`refresh_reused`,
  `409 refresh_retry_race`, `session_expired`, `refresh_invalid`,
  `device_invalid`) only marks the account "sign in again" and keeps its
  interviews. Nobody else's data is touched.
- UI strings in `src/strings/{en,hi}.json`; `hi` needs native-speaker review.

## Setup

```sh
cd mobile/digitva-collect
npm run vendor:build   # builds vendor/who-va-2022/dist and installs a copy of it
npm install
```

The WHO VA package is installed from `file:../../vendor/who-va-2022` as a
packed copy (`.npmrc` `install-links=true`), so Metro never sees the vendor's
own `react-native`. After changing or rebuilding the vendor package, run
`npm run vendor:build` again.

## Run against the dev server

1. Start DigitVA (`docker compose up -d` at the repo root; it serves
   `http://localhost:8051`).
2. As an admin, open the project's Setup home, **Devices**, and create an
   enrolment code. For the emulator the QR's server must be
   `http://10.0.2.2:8051`; if the page shows another host, copy the JSON and
   change `server` before pasting it into the app.
3. `npm run android` (or build the APK below, install it, and `npx expo start`
   with `adb reverse tcp:8081 tcp:8081`). A debug APK loads its JavaScript from
   Metro; it does not run without it.
4. Sign in with an interviewer account (see `AGENTS.md` for test accounts).

## Build the debug APK

```sh
npx expo prebuild --platform android
cd android
ANDROID_HOME=~/Library/Android/sdk ./gradlew assembleDebug -PreactNativeArchitectures=x86_64,arm64-v8a
# -> android/app/build/outputs/apk/debug/app-debug.apk
```

`android/` is generated and not committed. The Android package id
(`org.digitva.collect`, owner decision pending) lives only in `app.json`.

## Checks

```sh
npx tsc --noEmit
npx jest
```

## Enrolment code from a shell (dev)

```sh
docker compose exec -T -e DEVICE_PUBLIC_URL=http://10.0.2.2:8051 minerva_app_service \
  uv run --no-sync flask devices create-enrolment-code --project <id> --actor <admin email>
```

Prints the QR payload JSON to paste into the debug enrol box.

## Server-served questionnaires

Current project definitions are verified against the exact response SHA-256
and the app's supported engine version before rendering. Native definitions
remain in the unlocked interviewer's SQLCipher database; browser definitions
remain in account-scoped memory. Drafts and revisions keep their original
version, hash and extension list. Cache loss recovers that exact historical
slice; a failed recovery keeps the answers and blocks editing.

An unpinned browser draft without saved extension provenance also keeps its
server answers and cannot be opened using today's project settings. Historical
native forms use their original English labels when an exact translation cannot
be established. Failed current-definition refresh does not block queued uploads.

After vendor changes, rebuild the package and refresh the installed package
copy before exporting the app. Web and Android JavaScript exports do not install
or validate a physical Android build.

## Notification polling

The inbox prompts an authoritative sync; notification rows never change case
status directly. Foreground clients poll about once a minute and refresh normal
data at least every 15 minutes, even when the inbox is empty. Browser cursors
stay in account-scoped memory. Native cursors and pending-sync flags use
account-scoped SecureStore metadata and are cleared on account reset.

Android uses `expo-background-task` with a minimum 15-minute interval. Android
chooses the actual schedule. A locked task only records notification metadata;
interview data sync waits for unlock. iOS polls in the foreground. No FCM, Expo
push service or OS notification permission is required. Background registration
failure emits one generic diagnostic; foreground polling continues.

These native modules require a rebuilt Android app. JavaScript export,
autolinking and isolated prebuild have been checked; APK compilation and real
device WorkManager scheduling still require Android build/device acceptance.

## Needs a real device

Biometric enforcement: emulators do not require the biometric to release a
`requireAuthentication` entry, and `canUseBiometricAuthentication()` is false
on a stock emulator, so the biometric offer never shows there.
