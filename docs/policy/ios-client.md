---
title: iOS Client (DigitVA Collect on iPhone and iPad)
doc_type: policy
status: draft
owner: drguptavivek
last_updated: 2026-11-05
---

# iOS Client Policy

Baseline for running the Expo client (`mobile/digitva-collect`) on iOS:
plain DigitVA Collect (online and offline interviews, the encrypted local store
and the phone shell) and Collect Plus with its offline engines. Android and
the web behave exactly as before. Where this page says nothing, the Android
rules in [field data collection](field-data-collection.md) and the
[Expo client policy](expo-client.md) apply unchanged.

## Identity and distribution

- Bundle identifiers mirror the Android packages:
  `com.causeofdeathindia.digitvacollect` (DigitVA Collect),
  `com.causeofdeathindia.digitvacollect.dev` (`APP_VARIANT=development`) and
  `com.causeofdeathindia.digitvacollect.plus` (`APP_VARIANT=plus`). Each
  variant installs beside the others, as on Android.
- iOS is distributed only through the App Store and TestFlight. There is no
  sideloaded build, so the app never checks the hosted APK, never offers an
  in-app update download and never links to Google Play. Settings shows an
  "updates come from the App Store" row with a link to the listing only when the
  build carries the App Store id (`DIGITVA_IOS_APP_STORE_ID`, digits only);
  without it the row is hidden.
- Build configuration (`app.config.js`): `DIGITVA_IOS_RELEASE_BUILD=1` marks a
  release build. It requires `EXPO_PUBLIC_API_BASE_URL` to be an exact HTTPS
  origin (the same rule as `DIGITVA_ANDROID_RELEASE_BUILD=1`) and a positive
  integer `DIGITVA_IOS_BUILD_NUMBER` (CFBundleVersion). Other builds use build
  number `1`. iPad is supported (`supportsTablet`).

## Known differences from Android

- **Screen capture.** `expo-screen-capture` on iOS hides the app-switcher
  snapshot only. iOS does not let an app block screenshots or screen
  recording, so an iOS user can capture an open interview. This is accepted as
  a known difference, not a gap to be worked around.
- **Background notification sync stays Android-only.** The background task
  (`src/notificationTask.ts`) is registered only on Android. iOS
  BGTaskScheduler gives no timing guarantee and is not relied upon, so an iOS
  user sees new notices only after opening the app and syncing.
- **Performance telemetry stays Android-only.** The server accepts only
  platform `android` (`app/services/app_telemetry_service.py`, the `platform`
  enum), so the iOS client never sends a telemetry batch. Widening it needs a
  separate policy change on both sides.
- **Phone clock.** The "Date & time settings" button opens the app's page in
  iOS Settings, since iOS has no public link to the date and time page.
- **Sharing.** Exports, backups and the error log use the iOS share sheet
  (`expo-sharing`) instead of the Android SEND intent. The private-cache file
  is deleted when the share sheet closes, as on Android.
- **Dates in the WHO form.** iOS has no system date dialog, so the form's date
  questions open an in-app picker with Cancel and Done.
- **Device labels.** Display and export text names the device "iPhone" or
  "iPad" and the iOS version where Android text says "Android". Stored data
  shapes and column names do not change (the error log's `android` column
  holds the iOS version on iOS).

## Collect Plus on iOS

Offline Plus engines (ICD-11, DORIS, offline profile and identity, standalone
mode) are gated by `offlineEnginePlatform()` (Android or iOS, never the web)
together with `isPlusVariant()`. `isPlusVariant()` is true only when the build
says so (`extra.appVariant === "plus"`) or the `DigitvaIcd11` native module is
present (`requireOptionalNativeModule("DigitvaIcd11")`). It does not check that
the engines are linked: the CI Plus build (`DIGITVA_IOS_SKIP_ICD11=1`) still
shows the offline coding routes with no ICD-11 module behind them, so it is a
compile check only, never a build to hand out.

- Engines: `plugins/with-ios-collect-plus.js` stages the ICD-11 xcframework
  (`DIGITVA_ICD11_IOS_XCFRAMEWORK`, else the spike's `bridge-aot/pub-ios/`)
  and its WHO data into `modules/digitva-icd11/ios/Engine/`, and the SmartVA
  xcframework (`scripts/build-smartva-ios.sh`) into
  `modules/digitva-smartva/ios/Engine/`. The plain build excludes both modules
  from autolinking. Both engines run in the app process; details in
  [the engine interface](../current-state/icd11-android-engine-interface.md#ios).
- `DIGITVA_IOS_SKIP_ICD11=1` builds Plus with SmartVA only. CI uses it, because
  no iOS ICD-11 engine is published for it to fetch; the full Plus app is built
  on a Mac with `scripts/ios-local-build.sh plus`.

## Encryption and export compliance

Owner decision 2026-11-05: the app keeps full encryption,
uses only standard algorithms through the operating system's crypto or HTTPS,
and declares `ITSAppUsesNonExemptEncryption = false` in `app.json`. The flag
is an export-control declaration, not an encryption switch.

Audit of 2026-11-05 (what backs each use on iOS):

- Local store and passphrase backup: SQLCipher (AES-256, PBKDF2-HMAC-SHA512,
  per-page HMAC) built with `-DSQLCIPHER_CRYPTO_CC`, i.e. Apple CommonCrypto
  (`node_modules/expo-sqlite/ios/ExpoSQLite.podspec`).
- Keys and identity: Keychain via `expo-secure-store` (Security.framework);
  key material from `SecRandomCopyBytes` via `expo-crypto`.
- Integrity hashes and IDs: `expo-crypto` (CommonCrypto SHA-256, `UUID()`).
- Transport: HTTPS through NSURLSession.
- SmartVA (Rust, `mobile-core`): no crypto crates. ICD-11 engine: `Bridge.cs`
  uses no crypto or TLS; its runtime would use Apple's crypto.

Rules that keep the declaration true:

- No bundled crypto library (OpenSSL, BoringSSL, libsodium, pure-JS ciphers)
  and no custom or non-standard algorithm for encryption, key derivation or
  authentication. Encryption goes through CommonCrypto/CryptoKit,
  Security.framework or the OS TLS stack.
- Two hand-written SHA-256 functions exist for non-security hashing only
  (consent-notice text integrity in `src/consent.ts`, the demo sign-up
  proof-of-work in `src/pow.ts`). Hashing for integrity is not encryption;
  moving them to `expo-crypto` is optional clean-up, not a release condition.
- A new dependency, a WHO assembly with a crypto library, or end-to-end
  encryption between users means re-checking this declaration before release.
