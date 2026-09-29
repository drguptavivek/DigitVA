# DigitVA Collect (Android)

Offline WHO VA 2022 collection app for Path B of
`docs/policy/field-data-collection.md`. Design and API contract:
`.tasks/2026-09-30-android-collection-app.md` (epic `digitva-kmk`).

> **Debug builds must not collect real interviews.** A debug APK is signed
> with a well-known key and loads its JavaScript from Metro. Point it at a
> non-production DigitVA only.

## What it does

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
  come from `/api/v1/device/units` and form languages from
  `/api/v1/device/instruments/<code>/translations/<locale>`, both cached in
  the interviewer's database (`src/sync.ts`).
- **Finish**: the form's own completion (valid) marks a draft ready with
  `completion: {valid: true}`; **Finish as incomplete** is allowed only when
  the interview outcome is partially completed or respondent unavailable.
  Only such drafts are uploaded.
- **Send**: ready interviews go to `POST /api/v1/device/submissions`
  with `client_draft_id` = the draft UUID and the stored `completion`; the
  local copy is deleted when the server answers 201 or 200 (push and purge).
  A 422 (the interview as it stands is refused) puts the draft back in
  progress with its answers, so the interviewer can correct it; other
  refusals keep it ready for the next send.
  The remaining count and draft ids are then reported to `/outstanding`.
- **Offline cases** (phase 3, `src/cases.ts`, `app/case.tsx`,
  `app/register.tsx`): **Send and refresh** runs, in order, offline
  registrations (`POST /deaths`, `client_death_id`), queued contact attempts
  and visit dates (`client_attempt_id`), interviews (with the case's
  `death_id`), the outstanding report (draft ids, case ids, pending
  registration ids), then downloads every page of `GET /cases` and replaces
  the stored cases (a case no longer listed is dropped; drafts keep their own
  case binding and prefill). **Start interview** on a case opens a draft
  prefilled from the case (as the web form) and bound to it; an interview on
  a registration not yet sent waits for it. A 422 marks a registration or
  attempt "Not accepted" for editing or discarding; a 404/409 on an attempt
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

## Needs a real device

Biometric enforcement: emulators do not require the biometric to release a
`requireAuthentication` entry, and `canUseBiometricAuthentication()` is false
on a stock emulator, so the biometric offer never shows there.
