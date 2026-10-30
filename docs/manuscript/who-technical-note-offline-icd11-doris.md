---
title: Offline ICD-11 and DORIS in DigitVA Collect Plus - Technical Note for WHO
doc_type: reference
status: draft
owner: engineering
last_updated: 2026-10-30
---

# Offline ICD-11 and DORIS in DigitVA Collect Plus

Technical note for the WHO Classifications and Terminologies team, 30 October
2026.

DigitVA Collect Plus is an Android app that lets a trained verbal autopsy
coder certify a cause of death and run WHO DORIS with no network. It runs
WHO's own ICD-API 2.6.0 assemblies, including the DORIS rule engine, unmodified
on the phone; they are compiled to native code with .NET NativeAOT. Nothing is
reimplemented: the phone gives the same answers as the `whoicd/icd-api`
container our servers use. On 472 recorded requests the phone and the
container agreed on every one. We ask WHO for one written line on licensing
(section 8) and welcome review of the build.

## 1. Where to get it

| Item | Link | Checksum (SHA-256) |
| --- | --- | --- |
| Source code (MIT licence) | https://github.com/drguptavivek/DigitVA | public repository, branch `main` |
| ICD-11 engine bundle `icd11-engine-v2026.10.29.1` | https://github.com/drguptavivek/DigitVA/releases/tag/icd11-engine-v2026.10.29.1 | archive `d3fe3c3a1d7aee3fde9bb4e31224229aae1f9ff01fcbf988ff6244fdecac38c7`; library `8bfdc258f0e2c316a50656bc9d61ff07531d187f8855d9c5fd1ce4c6c109c718` |
| Collect Plus APK, prerelease 0.3.15 (arm64) | https://github.com/drguptavivek/DigitVA/releases/tag/collect-plus-v0.3.15-plus.1 | `89b7fc111372f3150447d1e35ca49e1b38c0153b44f9591f5ddd0e0f59f95286` |

The published 0.3.15 APK carries the earlier engine (`icd11-engine-v2026.10.25.1`)
and predates the complete offline DORIS workflow described here. A Collect Plus
prerelease built with engine 2026.10.29.1 will be added to this table when it
is published. [OPEN: owner to publish 0.3.16 prerelease before this note is
sent.]

The APK is signed with DigitVA's release key (certificate
`CN=DigitVA Collect, O=Cause of Death India`). It needs an arm64 Android phone,
Android 7.0 (API 24) or later; we test on 6 GB phones (section 6).

## 2. How it works

```
Collect Plus app (React Native)                  ":icd11" process (separate)
-------------------------------                  ---------------------------
WHO 2022 VA interview                            libdigitva_icd11.so
   |                                               = WHO ICD-API 2.6.0 assemblies
coder opens DORIS panel                              (search, codeinfo, postcoordination,
   |   ICD-11 search / pick / postcoordinate         CoDEdit, DorisRuleEngine 1.1.176)
   |------------- JSON request over JNI ----------> + DigitVA Bridge.cs (3 C exports)
   |<------------ JSON reply ----------------------+ WHO data: ICD-11 2026-01 MMS (English),
certificate (Part I / II, intervals)                   search index, DORIS rules v2.1 1.2.0
   |   Process -> DORIS underlying cause         network: none (proxy pinned to 127.0.0.1:9)
encrypted local store (SQLCipher)
   |   later, when online
DigitVA server re-checks and re-processes with the official whoicd/icd-api container
```

- **One engine, three entry points.** The library exports exactly
  `digitva_icd11_init`, `digitva_icd11_call` and `digitva_icd11_free`. Each call
  passes a JSON request naming a WHO API operation and returns WHO's reply as
  JSON.
- **A separate process.** The engine runs in its own Android process
  (`:icd11`), apart from the app that holds the interview.
- **No network.** WHO startup downloads are blocked and analytics are off
  (`saveAnalytics=false`); the engine reads only the bundled data.
- **Runs only with coding enabled.** Every engine start and call is refused
  while ICD-11/DORIS coding is off, which is the default on a new install.
  Coding is limited to the standalone and self-coding modes (section 7). With
  coding on, the engine may start soon after the app opens, so it is ready
  when the coder opens a case.

The full interface is in
[`docs/current-state/icd11-android-engine-interface.md`](../current-state/icd11-android-engine-interface.md).

## 3. WHO inputs bundled

| Input | Source | Version | SHA-256 |
| --- | --- | --- | --- |
| ICD-API assemblies (incl. DorisRuleEngine, OCT) | Docker image `whoicd/icd-api:2.6.0@sha256:1b77eb6dc43e0c65a12e9e9340ad178493c93488e728d0d936507cc57ada1b7c`, `/usr/share/icdapi` | ICD-API 2.6.0, rule engine 1.1.176 | pinned by image digest |
| ICD-11 MMS + ICF data | https://icdcdn.who.int/customversions/icd11_2026-01-17_release-icf-mms_en.pbf.gz | 2026-01, English | `2fd67533…1901` |
| Search index | https://icdcdn.who.int/released-index-files/ix_(2026-01-17)_foundation-icf-mms_en_v5.7.pbf.zip | v5.7 | `f7c1b463…9952` |
| DORIS rules | https://icd11files.blob.core.windows.net/doris/DORIS_v2.1_1.2.0.zip | 2.1, 1.2.0 | `c4876903…59ae` |
| Settings and language resources | from the same image (`appsettings.json`, `appsettings.container.json`, `Data/languageResources.txt`) | 2.6.0 | in the bundle manifest |

Full checksums are in `.github/workflows/icd11-engine-build.yml`. We use the
released 1.2.0 DORIS rules, not the unreleased 1.2.1. WHO content keeps its
CC BY-ND 3.0 IGO licence, and the app and its exports carry WHO's attribution
text.

## 4. Rebuilding it yourself

Every input is public, so WHO or anyone can rebuild the engine and check it.

### Engine library (macOS or Linux x64)

1. Install the .NET SDK version in `mobile/digitva-collect/modules/digitva-icd11/engine-src/global.json`
   and Android NDK 28.2.13676358.
2. Pull the image and copy the API out:
   `docker pull whoicd/icd-api:2.6.0@sha256:1b77eb6dc43e0c65a12e9e9340ad178493c93488e728d0d936507cc57ada1b7c`,
   then `docker cp <container>:/usr/share/icdapi ./icdapi`.
3. Build: `ICDAPI_DIR=./icdapi mobile/digitva-collect/modules/digitva-icd11/engine-src/build.sh <out-dir>`.
   It prints the library's SHA-256.
4. Download the three WHO data files in section 3, then package:
   `scripts/package-icd11-engine.sh <out-dir>`.

The same steps run on GitHub Actions in
`.github/workflows/icd11-engine-build.yml` (Ubuntu 24.04), which also checks
the exports and 16 KB page alignment and compares the result with the pinned
release.

**Reproducibility.** A rebuild on macOS reproduces the released library byte
for byte. The Linux CI build differs in about 1.6 KB: the GNU build ID, the
`.comment` section and a little early `.rodata`. The code section is the same
size, and the other 12 files in the archive are identical. We track this as
`digitva-9cll.11`; until it is closed the macOS build is the released one.
Compare unpacked files, not archives: bsdtar and GNU tar produce different
archive bytes.

### APK

- **On GitHub Actions.** `.github/workflows/collect-plus-release.yml` downloads
  the engine release and checks its pinned SHA-256. It builds SmartVA, runs
  `APP_VARIANT=plus npx expo prebuild`, then `./gradlew assembleRelease`
  (arm64) and `scripts/verify-android-release.sh`. A fork can run it with
  `publish=false` to get an unpublished APK.
- **Signing.** The release key stays with DigitVA, so a rebuilt APK has a
  different certificate and installs beside, not over, the official app. Use
  it to compare behaviour and the bundled engine files, not to replace an
  installed copy.

## 5. Parity with WHO DORIS

| Check | What it compares | Result |
| --- | --- | --- |
| Phone parity kit (`scripts/icd11-parity/run_phone.sh`), Samsung SM-E146B, engine 2026.10.29.1, 30 Oct 2026 | the same requests sent to the phone engine and to the `whoicd/icd-api:2.6.0` container | 472 of 472 matched: 431 identical replies, 41 refused with the same status class, none one-sided |
| Golden corpora, frozen 30 Oct 2026 (`scripts/icd11-golden/`) | the app's TypeScript layer against recorded WHO replies | 455 fixtures (DORIS 173, postcoordination 44, search 238); 173/173 DORIS, 238/238 search, 485/485 guidance operations identical |
| JNI smoke tests (`jni_smoke.sh`) | the native bridge on the phone | 10 + 30 checks pass |

These establish that the phone reproduces WHO's software; they do not measure
clinical accuracy. Not yet covered: the Android service's Binder paths
(`digitva-9cll.6`), and an end-to-end run of the complete offline coding
journey on a phone with a published Plus build (`digitva-9cll.5`).

### Validation around DORIS

DigitVA adds checks before and after WHO's engine. None of them changes WHO's
answer.

- **Final codes only.** A certificate refuses an extension code alone or a
  category with children (`422 INVALID_SELECTION`), the same rule WHO's
  CoDEdit flags as BER-CE-10 and FER-CE-883. It applies on the server, offline
  and in both pickers.
- **Certificate rules.** A Part I line may not be left blank between causes,
  intervals must be valid, and mandatory postcoordination must be complete.
- **Personal data.** Names, phone numbers and Aadhaar-like numbers are refused
  before any engine call.

All checks are listed in
[`docs/current-state/doris-validation-checks.md`](../current-state/doris-validation-checks.md).

## 6. Performance on a phone

Measured on a Samsung SM-E146B (6 GB model, 5.3 GB usable RAM, Android 15)
with the arm64 release build.

| Measure | Result |
| --- | --- |
| Engine start (process start to ready) | 17.7 to 20.3 s, about 15 s on 30 Oct 2026 |
| Engine memory while starting (PSS) | peak 761 MB to 1,191 MB, depending on sampling |
| Engine memory once ready (PSS) | 527 to 573 MB, idle CPU 0%, 19 to 25 threads |
| App process memory (PSS) | 142 to 222 MB during coding |
| ICD-11 search | 35 to 120 ms per query |
| DORIS underlying cause | 40 to 100 ms per certificate |
| CoDEdit | 5 to 16 ms |
| Code details | under 3 ms |
| Install size | APK 141 MB; on the phone 354 MB app plus 501 MB data |

The start-up cost is paid once per app process, and only when coding is
enabled. The engine then stays ready until Android stops the process. Search
and DORIS calls did not raise its memory: it stayed at 539 to 545 MB across
repeated certificates.

## 7. Data protection and consent

- **On the phone.** Interviews and certificates are kept in an encrypted
  SQLCipher database. Its key needs the Android Keystore and the coder's PIN
  (6 to 16 digits). The database is wiped after 5 wrong PINs, and screenshots
  are blocked.
- **Engine.** The engine receives the search text, the certificate (causes,
  codes, intervals) and the fields DORIS needs, such as sex and age, but not
  the interview record. It makes no network calls.
- **Upload.** Interviews and offline coding go only to the DigitVA server the
  phone is enrolled with. The server re-checks permission, re-processes the
  certificate with the official WHO container, and holds the offline result
  for review. The app has no third-party analytics.
- **Consent and permission.**
  - ICD-11/DORIS coding is off on a new install, and turning it on grants
    nothing by itself.
  - Coding needs Collect Plus plus a standalone account or a self-coding
    project with an active coder permission.
  - A refusal of interview or data-processing consent stops collection and
    coding.

## 8. Licensing status and our request to WHO

- **Our understanding.** Every input is publicly downloadable, and the
  assemblies and data are bundled unmodified. WHO content keeps its CC BY-ND
  3.0 IGO licence and attribution. Collect Plus is published only as a
  prerelease marked experimental.
- **What we have.** On 21 October 2026 we asked icd@who.int whether DigitVA may:
  1. incorporate the ICD-API assemblies and data in an Android app;
  2. treat NativeAOT compilation as not being a modification;
  3. use WHO's preferred method for Android;
  4. use WHO's preferred attribution.

  WHO kindly recommended the REST endpoints and offered a call. On the call on
  29 October 2026, WHO welcomed the Android work and asked for this write-up.
  We have no written answer on points 1 and 2.
- **Our request.** One written line confirming points 1 and 2. A second line,
  if possible, allowing redistribution of the WHO data files inside the APK
  and the engine release. We will follow any conditions WHO sets, including
  attribution, versions, or limiting distribution until WHO is satisfied.
- **Future breakage.** On the call WHO raised the risk that a future WHO
  release breaks the build. The engine bundle pins each WHO input by version and
  checksum, so a new WHO release changes nothing until we rebuild and rerun
  both parity suites against it. We would welcome early notice of ICD-API or
  DORIS releases.

## 9. Contacts and sources

- Owner and maintainer: Dr Vivek Gupta, Cause of Death India
  (https://causeofdeathindia.com). [OPEN: owner to add an email for WHO.]
- Repository: https://github.com/drguptavivek/DigitVA.
- Releases: https://github.com/drguptavivek/DigitVA/releases.
- Engine interface and performance:
  `docs/current-state/icd11-android-engine-interface.md`.
- Validation checks: `docs/current-state/doris-validation-checks.md`.
- Release process: `docs/current-state/release-process.md`.
- Licensing record: `docs/policy/icd11-local-api-runtime.md`.
