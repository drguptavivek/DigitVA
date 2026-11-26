---
title: Android Release Builds
doc_type: runbook
status: active
owner: engineering
last_updated: 2026-11-26
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

## Public 0.3.31 APKs and Play bundle (2026-11-26)

Supersedes 0.3.30, which never reached phones. Adds the org-unit lineage
pickers on the phone (death registration, worklist and its filters). Collect
(run 45770406038), Collect Plus (run 45770410012), web release
`expo-web-v2026.11.26.2`
(`c32d4abb76f78392b508844ad9740b70525b90fd5a5f258c1542ded11419541a`, run
45770401749) and the Play bundle (run 45770414218, artifact only, expires
about 2026-12-10; the Play upload is the owner's) were all built on CI from
`8afd83fac`. Pinned in `docker-compose.yml` by `4f258002e`. Release
certificate `6d94718a…6d361767`, versionCode 3312 (arm64), staging API
origin, checked with `scripts/verify-android-release.sh`; checksums verified
after download against each release's `.sha256`. Not yet on staging: the
image that carries them (built from `634711950`, which adds the public DORIS
cache fix) needs the owner's go to deploy. After that deploy, to offer them
to phones on the staging host (SSM session):

```bash
cd /data/DigitVA/private/android-hosted
for f in digitva-collect-0.3.31-arm64-v8a.apk digitva-collect-plus-0.3.31-arm64-v8a.apk; do
  sudo -Hu ubuntu docker cp "minerva_app:/opt/digitva/android/$f" ".$f.tmp"
done
printf '%s  %s\n' \
  ce1de1c9b004f4672ec194b9feb801249918325aa18295f2fbce8755944a3bd3 .digitva-collect-0.3.31-arm64-v8a.apk.tmp \
  27abbad5ddb0423be32efe89659088ce977b3cd00a92934f06db8347eee6db0a .digitva-collect-plus-0.3.31-arm64-v8a.apk.tmp \
  | sha256sum -c
sudo -Hu ubuntu mv .digitva-collect-0.3.31-arm64-v8a.apk.tmp digitva-collect-0.3.31-arm64-v8a.apk
sudo -Hu ubuntu mv .digitva-collect-plus-0.3.31-arm64-v8a.apk.tmp digitva-collect-plus-0.3.31-arm64-v8a.apk
curl -s https://digitvav3.causeofdeathindia.com/api/v1/app/android/latest   # expect 0.3.31
```

Run the two `mv` lines only after `sha256sum -c` prints OK for both.

| Variant | Public release | Bytes | SHA-256 |
| --- | --- | ---: | --- |
| Collect | `android-v0.3.31` | 70,011,612 | `ce1de1c9b004f4672ec194b9feb801249918325aa18295f2fbce8755944a3bd3` |
| Collect Plus | `collect-plus-v0.3.31-plus.1` (prerelease) | 150,950,748 | `27abbad5ddb0423be32efe89659088ce977b3cd00a92934f06db8347eee6db0a` |

## Public 0.3.30 APKs and Play bundle (2026-11-26)

Collect built on CI from `577739af6` (run 45673942075); Collect Plus (run
45679711537) and web release `expo-web-v2026.11.25.1`
(`fc67d7da757924e76e249be91f3a9198517b25988b3273f7b1f43111b512c3f9`) from
`56bde4541`, which adds only a test fix, so the app code is identical. Pinned
in `docker-compose.yml` by `a4b9fd083`, the commit staging runs. Release
certificate `6d94718a…6d361767`, versionCode 3302 (arm64), checked with
`scripts/verify-android-release.sh`; checksums verified after download
against each release's `.sha256`. The Play bundle is a run artifact of
`android-play-bundle.yml` (run 45673955783, from `577739af6`); the Play
upload is the owner's (the artifact expires about 2026-12-09). Not yet copied
into staging's `private/android-hosted`: `/api/v1/app/android/latest` still
offers 0.3.29 until the owner's go. The running image holds both APKs in
`/opt/digitva/android` with the hashes below (checked 2026-11-26). To offer
them to phones, on the staging host (SSM session):

```bash
cd /data/DigitVA/private/android-hosted
for f in digitva-collect-0.3.30-arm64-v8a.apk digitva-collect-plus-0.3.30-arm64-v8a.apk; do
  sudo -Hu ubuntu docker cp "minerva_app:/opt/digitva/android/$f" ".$f.tmp"
done
printf '%s  %s\n' \
  03e8280f388bfc8e238d7551b835ef8b29c305be6fc732f6d75cf18286d807e8 .digitva-collect-0.3.30-arm64-v8a.apk.tmp \
  868732c398f7ea446d83b37f52c6805672758486087df5a55936bce38336c982 .digitva-collect-plus-0.3.30-arm64-v8a.apk.tmp \
  | sha256sum -c
sudo -Hu ubuntu mv .digitva-collect-0.3.30-arm64-v8a.apk.tmp digitva-collect-0.3.30-arm64-v8a.apk
sudo -Hu ubuntu mv .digitva-collect-plus-0.3.30-arm64-v8a.apk.tmp digitva-collect-plus-0.3.30-arm64-v8a.apk
curl -s https://digitvav3.causeofdeathindia.com/api/v1/app/android/latest   # expect 0.3.30
```

Run the two `mv` lines only after `sha256sum -c` prints OK for both.

| Variant | Public release | Bytes | SHA-256 |
| --- | --- | ---: | --- |
| Collect | `android-v0.3.30` | 70,004,984 | `03e8280f388bfc8e238d7551b835ef8b29c305be6fc732f6d75cf18286d807e8` |
| Collect Plus | `collect-plus-v0.3.30-plus.1` (prerelease) | 150,944,116 | `868732c398f7ea446d83b37f52c6805672758486087df5a55936bce38336c982` |

## Public 0.3.25 APKs and Play bundle (2026-11-18)

Built on CI from `4926c6ea4` (APK run 44257806258, Plus 44257811174, Play
bundle 44257815327), pinned in `docker-compose.yml` with web release
`expo-web-v2026.11.18.3` (`e0f1e68b0b287edbf17212cd6bb54f7c9ae5b3eda4bd0878e242c7479905d9ca`,
built from `8ff6c707a`). Release certificate `6d94718a…6d361767`; checksums verified
after download against each release's `.sha256`. Contents: Interview
language offers the project's Narration languages (native script), with the
web fixes of the same day (`CHANGELOG.md`, 2026-11-18). Later commits that
day change only the web app and a Collect Plus queue icon, so no rebuild.
The Play upload is the owner's.

| Variant | Public release | Bytes | SHA-256 |
| --- | --- | ---: | --- |
| Collect | `android-v0.3.25` | 70,073,085 | `dc8c29c7e6d7afef5cfa7575cb9656a9b2daa5a85258c8cf2ac6cd52cf59ea41` |
| Collect Plus | `collect-plus-v0.3.25-plus.1` (prerelease) | 150,907,661 | `68b91901b0fc84308bef17b0e8792be83fdc186546d75adf08d9ec48b8c16bd7` |

## Public 0.3.24 APKs and Play bundle (2026-11-18)

Built on CI from `7b7412950` (both variants and the Play bundle), pinned in
`docker-compose.yml` by `ad9603e0e` with web release `expo-web-v2026.11.18.1`
(`b331824b8ac519515f1049b24d0e8ed9d9d82ee3ce74d33a8dd955060e4caf1c`). Release
certificate `6d94718a…6d361767`; checksums verified after download against
each release's `.sha256`. Contents: Android 9 photo storage permission and
keyboard room, phone coding layout, ICD-10 code titles, Appearance setting
(`CHANGELOG.md`, 2026-11-18). The Play bundle is a run artifact of
`android-play-bundle.yml` (run 44161580345); the Play upload is the owner's.
Staging's `/download/android` serves `private/android-hosted`, not the image
pin. On the owner's go (2026-11-18) both 0.3.24 APKs were copied there from
the image's `/opt/digitva/android` under temporary names, checksum-verified
and renamed in (older files kept); both public downloads and
`/api/v1/app/android/latest` (both variants) return the checksums below.

| Variant | Public release | Bytes | SHA-256 |
| --- | --- | ---: | --- |
| Collect | `android-v0.3.24` | 70,070,229 | `cf6bc7383e3bc54b6307bff9e7f170faba9b27038883c2fdc4633c9bd2ca4c3a` |
| Collect Plus | `collect-plus-v0.3.24-plus.1` (prerelease) | 150,904,809 | `ad3e6f6c24df00af0c8eb05853c5fc4ece1af08a2a510531f85f6705124b0def` |

## Public 0.3.15 APKs (2026-10-29)

Built on CI from `d8a3a9149` (both variants), pinned in `docker-compose.yml`
with web release `expo-web-v2026.10.29.2`. Release certificate, versionCode
3152 (arm64); checksums verified after download. They show only what the build
and the account state allow (`798d40952`; `CHANGELOG.md`, 2026-10-29).

| Variant | Public release | Bytes | SHA-256 |
| --- | --- | ---: | --- |
| Collect | `android-v0.3.15` | 67,972,726 | `b1c85220469463dc7cf4312f582144e27a67f028ceb3874b6e297b0a6bc46ad9` |
| Collect Plus | `collect-plus-v0.3.15-plus.1` (prerelease) | 141,228,810 | `89b7fc111372f3150447d1e35ca49e1b38c0153b44f9591f5ddd0e0f59f95286` |

## Public 0.3.14 APKs (2026-10-29)

Built on CI from `20f65ba57` (Collect) and `140ead14e` (Collect Plus, the first
CI build with the bundled SmartVA engine), with web release
`expo-web-v2026.10.29.2` from `a4d7bce83`; the three are pinned in
`docker-compose.yml` until 0.3.15. Both use the release certificate; versionCode 3142 (arm64).
Checksums verified after download from the releases. The phone acceptance
fixes in them are listed under 2026-10-29 in `CHANGELOG.md` (`digitva-7amd`).

| Variant | Public release | Bytes | SHA-256 |
| --- | --- | ---: | --- |
| Collect | `android-v0.3.14` | 67,951,734 | `031345b879322cf01bc2c0b83e94da30515cdf8176120c0499af388497ace51e` |
| Collect Plus | `collect-plus-v0.3.14-plus.1` (prerelease) | 141,207,826 | `a6fc8a2b5b4e2869dbcb7adab5c28dad864d703039823698674d177b4596e41c` |

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

## Hermes source maps and symbolicating crashes

Release JavaScript ships as Hermes bytecode, so a logcat stack shows only a
bytecode position such as `run@1:3850100` (line 1, column = byte offset). The
Gradle bundle task composes the Metro and Hermes maps into
`mobile/digitva-collect/android/app/build/generated/sourcemaps/react/release/index.android.bundle.map`.
It is not packaged in the APK. Both APK workflows (**Android release APK** and
**Collect Plus Android release**) upload it as a separate workflow artifact,
never a GitHub release asset:

| Build | Artifact name |
| --- | --- |
| Collect | `hermes-sourcemap-collect-<app.json version>-<full commit sha>` |
| Collect Plus | `hermes-sourcemap-collect-plus-<app.json version>-<full commit sha>` |

Retention is 90 days, the repository maximum
(`gh api repos/drguptavivek/DigitVA/actions/permissions/artifact-and-log-retention`);
a larger `retention-days` makes the upload fail. For releases that must stay
symbolicatable longer, download the artifact and archive it with the APK
backups. The repository is public, so any signed-in GitHub user can download
workflow artifacts; the map exposes only source that is already public. The
Google Play bundle workflow uploads its own map as
`hermes-sourcemap-collect-play-<version>-<sha>`.

To find a release's map, get its commit from the release (`gh release view
android-v0.3.13 --json targetCommitish`) or the workflow run, then:

```sh
gh run list --workflow android-release.yml --commit <sha>      # run id
gh run download <run-id> -n hermes-sourcemap-collect-<version>-<sha> -D /private/tmp/map
cd mobile/digitva-collect   # npm ci first; metro-symbolicate ships with Metro
npx --no-install metro-symbolicate /private/tmp/map/index.android.bundle.map < stack.txt
```

`stack.txt` holds the lines copied from `adb logcat`, for example
`at run (index.android.bundle:1:3850100)` or `run@1:3850100`; each is replaced
by the original file, line and function. Use the map of the exact build that
crashed: offsets from another version map to the wrong code.

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
