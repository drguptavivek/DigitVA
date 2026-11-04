---
title: iOS Client (DigitVA Collect on iPhone and iPad)
doc_type: policy
status: draft
owner: drguptavivek
last_updated: 2026-11-04
---

# iOS Client Policy

Baseline for running the Expo client (`mobile/digitva-collect`) on iOS
(bead `digitva-nujw.1`). Phase 1 brings plain DigitVA Collect to iOS: online and
offline interviews, the encrypted local store and the phone shell. Android and
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
says so or the `DigitvaIcd11` native module is present
(`requireOptionalNativeModule("DigitvaIcd11")`), so an iOS build without the
native engines behaves as plain Collect. On iOS the offline device identity
lives in the Keychain (`WHEN_UNLOCKED_THIS_DEVICE_ONLY`); unlike the Android
Keystore, a Keychain item can survive an uninstall and reinstall.

## Open owner decisions

- **Export compliance (`ITSAppUsesNonExemptEncryption`).** The app uses
  SQLCipher for the local store. Whether it qualifies for an exemption, and so
  how this key is set, is an open owner decision. Until it is decided the key is
  not set in the app config, and App Store Connect asks the question on each
  upload.
