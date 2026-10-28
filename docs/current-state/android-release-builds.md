---
title: Android Release Builds
doc_type: runbook
status: active
owner: engineering
last_updated: 2026-10-28
---

# Android release builds

Owner decision 2026-10-28 (`digitva-hs7e.17`): publish the latest signed
Collect and Collect Plus APKs with separate metadata and download links,
including actual file sizes. This explicitly overrides the earlier private
Plus publication hold; written WHO redistribution confirmation is still
pending and must not be implied. Local release builds are authorized in this
session. The normal package remains the default download.
Version 0.3.13 introduces the manual Settings server compatibility/build check
(`digitva-hs7e.18`); the server contract and deployed commit are distinct values.

## Public 0.3.13 APKs (2026-10-28)

Both use release certificate `6D94718A...6D361767`, versionCode 3132, target API
36 and arm64. The normal APK was installed on the connected Android 15 phone
without clearing data. Both copied phone Downloads files matched their hashes.

| Variant | Public release | Bytes | SHA-256 |
| --- | --- | ---: | --- |
| Collect | `android-v0.3.13` | 67,927,662 | `10ad21e2077f21c41e8ccfc563d34da8e05cf1e821c69ff7df6682582a6fb1e1` |
| Collect Plus | `collect-plus-v0.3.13-plus.1` | 141,184,458 | `ae2c864434212ef8d7b04f3faf7de55f802ce0e023c7e9d23e902bb0ccc89837` |

The Plus release remains labelled prerelease because its offline WHO engine is
experimental. Both APKs passed release identity/signing checks and zip alignment;
all native ELF LOAD segments support 16 KB alignment (normal 28, Plus 33).
The SmartVA/WHO engine cores match the Android 13/15 measured candidate bytes.
The benchmark Plus installation uses a debug signature; do not uninstall it to
install the production-signed Plus APK while its draft must be retained.

For staging's hosted override, deploy variant-filtering server code before
adding Plus to the folder. Then copy verified APKs from the new image's
`/opt/digitva/android` into `private/android-hosted` using temporary names and
atomic renames. Preserve older files. Verify each public metadata response and
download checksum; a successful image deployment does not replace override files.

DigitVA Collect supports enrolment, sign-in, PIN, consent, death registration,
interviews, drafts, attachments, sync, settings and online coding through the
shared native workspace (`digitva-6rxf`). Collect Plus additionally carries the
experimental offline engine. Online cases require the caller's coding access;
local coding requires a standalone account or a self-coding project with coder
access in that same project. Plain builds exclude offline engine assets.
Review keeps its existing variant and permission checks.

| Item | Value |
| --- | --- |
| Android package | `com.causeofdeathindia.digitvacollect` (was `org.digitva.collect` for the 0.1.0 test build; a different app to Android, so 0.1.0 must be uninstalled) |
| Coding app | Shared workflow in this app; no package migration |
| Release server | `https://digitvav3.causeofdeathindia.com`, staging (`EXPO_PUBLIC_API_BASE_URL`; owner 2026-10-27, `digitva-0d6l`; phones already enrolled keep their server); the QR rule still enrols on any https host under `causeofdeathindia.com` |
| APKs | one per ABI, `arm64-v8a` (most phones) and `armeabi-v7a` (older 32-bit phones); no universal APK |
| versionCode | base `major*10000 + minor*100 + patch` (0.2.0 -> `200`), each APK `base*10 + ABI digit`: `armeabi-v7a` 1, `arm64-v8a` 2 |
| Signing certificate SHA-256 | `6D:94:71:8A:08:78:71:0B:8C:A7:F2:84:11:6D:13:67:1C:F3:9E:4D:D5:F6:EB:8B:B0:FB:A7:EF:6D:36:17:67` (`CN=DigitVA Collect, O=Cause of Death India, C=IN`, RSA 4096, valid to 2056-10-14) |

The ABI split and per-ABI versionCode come from the tracked Expo config plugin
`mobile/digitva-collect/plugins/with-android-abi-splits.js`; release signing
from `plugins/with-android-release-signing.js`. Both act only when
`DIGITVA_ANDROID_RELEASE_BUILD=1` at prebuild, so a debug prebuild still makes
one debug-signed `app-debug.apk`. A release prebuild or Gradle run without all
four signing variables fails; a release is never signed with the debug key.

## Signing material

The release keystore was generated locally on 2026-10-22 (PKCS12, alias
`digitva-collect`). It lives only on the owner's machine, git-ignored:

- keystore: `private/android/digitva-collect-release.keystore`
- credentials: `private/android/release-signing.env`, also appended to `.env`

The variables are the names the signing plugin reads:

| Variable | Value |
| --- | --- |
| `ANDROID_RELEASE_STORE_FILE` | Absolute path of the keystore |
| `ANDROID_RELEASE_KEYSTORE_PASSWORD` | Keystore password |
| `ANDROID_RELEASE_KEY_ALIAS` | `digitva-collect` |
| `ANDROID_RELEASE_KEY_PASSWORD` | Key password (equal to the store password: PKCS12 has one) |

Back the keystore and its password up to the team's encrypted offline store:
losing it means no update can ever install over this app. Never commit the
keystore, its base64 payload or a password.

The GitHub Actions workflow
[`.github/workflows/android-release.yml`](../../.github/workflows/android-release.yml)
signs from the protected `android-release` environment. Its secrets still hold
the 0.1.0 key (`1E60B3C0...`); before a CI release, replace them with this
keystore so CI builds can update the 0.2.0 install:

```sh
base64 < private/android/digitva-collect-release.keystore | tr -d '\n' > /private/tmp/digitva-collect.keystore.b64
gh secret set ANDROID_RELEASE_KEYSTORE_BASE64 --env android-release < /private/tmp/digitva-collect.keystore.b64
gh secret set ANDROID_RELEASE_KEYSTORE_PASSWORD --env android-release
gh secret set ANDROID_RELEASE_KEY_ALIAS --env android-release
gh secret set ANDROID_RELEASE_KEY_PASSWORD --env android-release
gh variable set ANDROID_RELEASE_CERT_SHA256 --env android-release --body '6D94718A0878710B8CA7F284116D13671CF39E4DD5F6EB8BB0FBA7EF6D361767'
rm /private/tmp/digitva-collect.keystore.b64
```

## Local release build

```sh
cd mobile/digitva-collect
set -a; . ../../private/android/release-signing.env; set +a
export DIGITVA_ANDROID_RELEASE_BUILD=1 \
  EXPO_PUBLIC_API_BASE_URL=https://digitvav3.causeofdeathindia.com \
  DIGITVA_ANDROID_VERSION_CODE=200 ANDROID_HOME=~/Library/Android/sdk
npx expo prebuild --platform android --clean --non-interactive
(cd android && ./gradlew --no-daemon clean assembleRelease)
# android/app/build/outputs/apk/release/app-{arm64-v8a,armeabi-v7a}-release.apk
../../scripts/verify-android-release.sh android/app/build/outputs/apk/release/app-arm64-v8a-release.apk \
  6D94718A0878710B8CA7F284116D13671CF39E4DD5F6EB8BB0FBA7EF6D361767 https://digitvav3.causeofdeathindia.com 2002
```

Keep the variables exported for both prebuild and Gradle: Gradle embeds the
JavaScript bundle and reads the signing variables itself.

## Release 0.2.0 (built 2026-10-22, not yet published)

| Asset | Bytes | versionCode | SHA-256 |
| --- | --- | --- | --- |
| `digitva-collect-0.2.0-arm64-v8a.apk` | 64,286,073 | 2002 | `0f325e1e2f1e302295a10f8bfd4b5018a37e68d1a993557ccd33a194e60db421` |
| `digitva-collect-0.2.0-armeabi-v7a.apk` | 53,537,189 | 2001 | `062def8593c0c195e8bc14cb443c2e283cbb776cb33810128e7cf2edf51be231` |

Minimum SDK 24, target SDK 36, not debuggable. The assets and their
`.sha256` files are staged in `private/android-artifacts/0.2.0/`. Publish them
as GitHub release `android-v0.2.0`; the enrolment email, help page and footer
then use:

```text
DIGITVA_ANDROID_APK_URL=https://github.com/drguptavivek/DigitVA/releases/download/android-v0.2.0/digitva-collect-0.2.0-arm64-v8a.apk
```

The server shows one link, so give the `armeabi-v7a` APK to the few older
32-bit phones directly. The 0.1.0 prerelease (`org.digitva.collect`, version
code 6, cert `1E60B3C0...`) is superseded.

## CI build and publish

From the Actions tab, select `main` and run **Android release APK**. The
workflow builds the vendored WHO package, runs `npm ci`, the typecheck and
tests, derives the base versionCode from `app.json`, generates the Android
project and runs `assembleRelease`. It verifies both APKs and uploads
`digitva-collect-<version>-<abi>.apk` with `.sha256` files as a 14-day
artifact. With `publish: true` and tag `android-v<version>` (it must match
`app.json`), the publish job alone has `contents: write` and creates the
release with those four assets. Rebuilding the same version reproduces the
same versionCodes, so bump `app.json` before every published release.

## Google Play bundle - primary release path

Google Play is the primary release path (owner, 2026-10-28, `digitva-a770`);
CI builds a signed AAB for owner review/upload. Downloadable APK releases remain supported alongside the store bundle. Native HMR/debug builds may run
locally for emulator testing; release builds remain on CI. This supersedes the
earlier blanket restriction on local debug builds.
The build flag `DIGITVA_DISTRIBUTION=play` (unset means the sideloaded APK
build; any other value fails the config) changes three things:

- `app.config.js` sets `extra.digitvaDistribution` to `play` (otherwise
  `sideload`). The app reads it through `isPlayDistribution()` in
  `src/appVariant.ts`: Settings > About shows "App updates come from Google
  Play." in place of the update check and Download button, and the start-up
  update check does not run, so no screen offers the hosted APK (Play's Device
  and Network Abuse policy forbids self-update).
- `plugins/with-android-abi-splits.js` stands aside: one universal AAB, which
  Play splits per device itself.
- The versionCode is `base * 10 + 3`, with `base = major*10000 + minor*100 +
  patch`, so the bundle sits above the same version's per-ABI APKs (`+1`
  armeabi-v7a, `+2` arm64-v8a).

From the Actions tab, select `main` and run **Android Google Play bundle**
(`.github/workflows/android-play-bundle.yml`). It uses the `android-release`
environment, the same signing secrets, API origin and screenshot setting as
the APK workflow, builds the vendored WHO package, runs `npm ci`, the
typecheck and tests, then prebuilds and runs `./gradlew bundleRelease` with
the flag set on both steps (the JS bundle reads the config again at Gradle
time). After prebuild it checks `android/app/build.gradle` has no ABI splits
and carries the `+3` versionCode. It verifies the AAB with `jarsigner -verify`,
rejects debug signing, compares the `keytool -printcert -jarfile` SHA-256 with
`ANDROID_RELEASE_CERT_SHA256`, and applies the same embedded-JavaScript origin
checks as the APK script. It uploads `digitva-collect-<version>-play.aab` and
its `.sha256` as a 14-day run artifact only: no GitHub release and no Play
upload. The bundle is signed with the existing release key for now; which key
becomes the Play App Signing upload key is the owner's decision.

## Verification boundary

`scripts/verify-android-release.sh APK CERT_SHA256 API_ORIGIN VERSION_CODE`
rejects debug signing, compares the certificate, requires package
`com.causeofdeathindia.digitvacollect`, label `DigitVA` and the expected
versionCode, and checks the embedded Hermes `index.android.bundle` contains the
HTTPS API origin and no development origin (`http://localhost:8051`,
`http://10.0.2.2:8051`; `src/enrolment.ts` keeps them behind `__DEV__`). The
0.2.0 arm64 APK was installed on an arm64 emulator: it opened on the enrolment
screen with no coding or review entry. This does not replace physical
Android installation, login, offline, PIN, biometric or background-lock
acceptance (`digitva-p6fs.5`).

## Dependency alignment and advisory posture

`mobile/digitva-collect/package.json` explicitly pins `react-native-reanimated`
(`4.5.1`) and `react-native-worklets` (`0.10.1`) to the versions bundled by
Expo SDK 57 (`expo/bundledNativeModules.json`), keeping `expo-modules-core`'s
peer constraint (`^0.7.4 || ^0.8.0 || ^0.9.0 || ^0.10.0`) satisfied.

On a clean lockfile (`digitva-dd67`), `source-map-js` is updated to `>=1.2.2`
(`GHSA-68fv-2mgg-jv7q`). The remaining `npm audit` findings are inherited from
Expo SDK 57:

- Build/test/CLI-only dependencies not bundled into the app runtime: `braces`
  (`<=3.0.3` via `micromatch` in Metro/Jest), `node-forge` (`<=1.4.0` via
  `@expo/cli` code-signing helpers), `sprintf-js` (`<=1.1.3` via `argparse` /
  `js-yaml` in CLI/lint tooling), and `uuid` (`<11.1.1` via `xcode` in
  `@expo/config-plugins`; runtime UUID generation uses `expo-crypto`).
- Runtime transitive dependency: `decode-uri-component` (`<=0.4.2` via
  `expo-router@57.0.24 -> query-string@7.1.3`), where `npm audit`'s automated
  fix requires a breaking major upgrade to `expo-router@58.x` (deferred until a
  scheduled Expo SDK upgrade).
