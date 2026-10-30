---
title: Offline ICD-11 and DORIS in DigitVA Collect Plus - Technical Note for WHO
doc_type: reference
status: draft
owner: engineering
last_updated: 2026-10-31
---

# Offline ICD-11 and DORIS in DigitVA Collect Plus

Technical note for the WHO Classifications and Terminologies team, 30 October
2026.

DigitVA Collect Plus is an Android app that lets a trained verbal autopsy
coder certify a cause of death and run WHO DORIS with no network. It runs
WHO's own ICD-API 2.6.0 assemblies, including the DORIS rule engine, unmodified
on the phone; they are compiled to native code with .NET NativeAOT. Nothing is
reimplemented. For every request that does not use the two bounds our bridge
adds (section 5), the phone gives the same answers as the `whoicd/icd-api`
container our servers use. We found three small differences, listed in
section 5. On 30 October 2026, all 30,783 requests of our full evaluation
matched on the current engine, including every ICD-11 read the coding screen
makes (search, code info, entities, postcoordination, DORIS and CoDEdit). On
29 October, 20,164 requests matched on the engine library of the
published 0.3.14 app. We ask WHO for one written line on licensing (section 8)
and welcome review of the build.

## 1. Where to get it

| Item | Link | Checksum (SHA-256) |
| --- | --- | --- |
| Source code (MIT licence) | https://github.com/drguptavivek/DigitVA | public repository, branch `main` |
| ICD-11 engine bundle `icd11-engine-v2026.10.29.1` | https://github.com/drguptavivek/DigitVA/releases/tag/icd11-engine-v2026.10.29.1 | archive `d3fe3c3a1d7aee3fde9bb4e31224229aae1f9ff01fcbf988ff6244fdecac38c7`; library `8bfdc258f0e2c316a50656bc9d61ff07531d187f8855d9c5fd1ce4c6c109c718` |
| Collect Plus APK, prerelease 0.3.16 (arm64), asset `digitva-collect-plus-0.3.16-arm64-v8a.apk` | https://github.com/drguptavivek/DigitVA/releases/tag/collect-plus-v0.3.16-plus.1 | `ba274d35250ff4049a2dbadf09ddb0be17c208c5a57b94d27350567b798d068f` |

The 0.3.16 prerelease (tag `collect-plus-v0.3.16-plus.1`) carries engine
`icd11-engine-v2026.10.29.1`: that is the tag
`.github/workflows/collect-plus-release.yml` pins on `main`, together with
the archive checksum above.

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
   |   Process -> DORIS underlying cause         WHO start-up downloads: proxy 127.0.0.1:9,
encrypted local store (SQLCipher)                  fail at once; bundled files used
   |   later, when online
DigitVA server re-checks permission and DigitVA's ICD-11 rules; does not re-run DORIS
```

- **One engine, three entry points.** The library exports exactly
  `digitva_icd11_init`, `digitva_icd11_call` and `digitva_icd11_free`. Each call
  passes a JSON request naming a WHO API operation and returns WHO's reply as
  JSON.
- **A separate process.** The engine runs in its own Android process
  (`:icd11`), apart from the app that holds the interview.
- **No working network path.** The engine's loaders do try to download WHO
  files at start (`EngineHost.kt`). The app routes them to a dead proxy,
  `http://127.0.0.1:9`, so they fail at once and the bundled files are used.
  Analytics are off (`saveAnalytics=false`).
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
| Language resources | from the same image (`Data/languageResources.txt`) | 2.6.0 | `330edb9d…2d18`; also in the bundle manifest (`who-files.json`) |
| Settings | from the same image (`appsettings.json`, `appsettings.container.json`); not in the manifest | 2.6.0 | `190221d4…94ad6fa` (`appsettings.json`), `c727f541…6056` (`appsettings.container.json`) |

Full checksums for the three downloads are in
`.github/workflows/icd11-engine-build.yml`. The manifest `who-files.json`
lists `languageResources.txt` and the `data/*` files only. The settings
checksums come from the bundle folder of an extracted engine archive and match
`private/icd11-offline-spike/bundle_min`; the files are taken from the pinned
image. We use the released 1.2.0 DORIS rules, not 1.2.1, which is not in the
official ICD-API 2.6.0 image. WHO content keeps its CC BY-ND 3.0 IGO licence,
and the app and its exports carry WHO's attribution text.

## 4. Rebuilding it yourself

Every input is public, so WHO or anyone can rebuild the engine and check it.

### Engine library (macOS or Linux x64)

1. Install the .NET SDK version in `mobile/digitva-collect/modules/digitva-icd11/engine-src/global.json`
   and Android NDK 28.2.13676358.
2. Pull the image, create a container, and copy the API out:
   `docker pull whoicd/icd-api:2.6.0@sha256:1b77eb6dc43e0c65a12e9e9340ad178493c93488e728d0d936507cc57ada1b7c`,
   `docker create <image>` (it prints the container id), then
   `docker cp <container>:/usr/share/icdapi ./icdapi`.
3. Build: `ICDAPI_DIR=./icdapi mobile/digitva-collect/modules/digitva-icd11/engine-src/build.sh <out-dir>`.
   It prints the library's SHA-256.
4. Package. `scripts/package-icd11-engine.sh <out-dir>` needs `node`. It reads
   the folder named by `DIGITVA_ICD11_SPIKE_DIR` (default
   `private/icd11-offline-spike`), which must hold:
   - `bridge-aot/pub-bionic/digitva_icd11.so` (the library from step 3)
   - `bundle_min/appsettings.json`
   - `bundle_min/appsettings.container.json`
   - `bundle_min/Data/languageResources.txt`
   - `data/icd11_2026-01-17_release-icf-mms_en.pbf.gz`
   - `data/ix_(2026-01-17)_foundation-icf-mms_en_v5.7.pbf.zip`
   - `data/DORIS_v2.1_1.2.0/` (the unzipped DORIS files)

   The exact recipe, with checksum checks, is the steps "Fetch WHO's data
   files and verify their sha256" and "Package the release archive" in
   `.github/workflows/icd11-engine-build.yml`. The layout is the one
   `mobile/digitva-collect/modules/digitva-icd11/scripts/stage-engine.js`
   expects.

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
- **What a fork needs.**
  - Its own `android-release` environment with the signing secrets, and the
    `ANDROID_RELEASE_CERT_SHA256` variable.
  - Its own engine release. Forks do not copy releases, and the workflow runs
    `gh release download "$ICD11_ENGINE_TAG" --repo "$GITHUB_REPOSITORY"`.
    Publish the archive from the steps above, then update the
    `ICD11_ENGINE_TAG` and `ICD11_ENGINE_SHA256` pins in the workflow.
- **Signing and installing.** The release key stays with DigitVA, so a rebuilt
  APK has a different certificate. The Plus APK uses the package id
  `com.causeofdeathindia.digitvacollect.plus`, so a rebuild signed with another
  key cannot install over the official Plus app. Install it on a phone without
  the official Plus app, or change the package id. Use it to compare behaviour
  and the bundled engine files.

## 5. Parity with WHO DORIS

| Check | What it compares | Result |
| --- | --- | --- |
| Large parity run, 29 Oct 2026, Samsung SM-E146B, engine library of Collect Plus 0.3.14 (engine release `icd11-engine-v2026.10.25.1`) | 20,164 requests sent to the phone engine and to the `whoicd/icd-api:2.6.0` container | below |
| Full evaluation (`scripts/icd11-parity/eval.sh full`), Samsung SM-E146B, engine 2026.10.29.1, 30 Oct 2026 | 30,783 requests: the 20,010 certificates and the request sets below, plus every WHO request recorded in the golden corpora (1,592) and 8,909 coding-screen reads over 401 codes | 30,783 of 30,783 matched: 30,088 identical replies, 695 refused by both, none different or one-sided (below) |
| Full evaluation with the published app's libraries (`eval.sh full`), Samsung SM-E146B, 30 Oct 2026: engine, OpenSSL and libc++ taken from the Collect Plus 0.3.18 APK (its engine is byte-identical to engine release 2026.10.29.1) | the same 30,783 requests | 30,783 of 30,783 matched: 30,088 identical, 695 refused by both |
| Clean-room rebuild, 30 Oct 2026: the engine library compiled in a fresh Ubuntu 24.04 container from our public repository and WHO's public inputs only, run on the same phone (`eval.sh quick`) | 2,064 requests, including every WHO request recorded in the golden corpora | 2,064 of 2,064 matched: 2,017 identical, 47 refused by both |
| Phone parity kit (`scripts/icd11-parity/run_phone.sh`), Samsung SM-E146B, engine 2026.10.29.1, 30 Oct 2026 | the same requests sent to the phone engine and to the container; 28 rows test the bridge's bounds (below) | 472 of 472 matched: 431 identical replies, 41 refused with the same status class, none one-sided |
| Golden corpora, frozen 30 Oct 2026 (`scripts/icd11-golden/`) | the app's TypeScript layer against recorded WHO replies | 455 fixtures (DORIS 173, postcoordination 44, search 238); 173/173 DORIS, 238/238 search, 485/485 guidance operations identical |
| JNI smoke tests (`jni_smoke.sh`) | the native bridge on the phone | run 29 Oct 2026 (bead `digitva-9cll.6`): 0 failures; no run recorded against 2026.10.29.1 |

**The bridge's two bounds.** The bridge adds a `limit` trim on search, and it
refuses `include=descendant` and `limit` together with `flatResults=false`. WHO's
container knows none of these. For those rows the parity runner trims or
refuses the container's reply the way the bridge does
(`docs/current-state/icd11-android-engine-interface.md`). A request that uses
neither is WHO's reply, unchanged.

These checks establish that the phone reproduces WHO's software; they do not
measure clinical accuracy. Not yet covered: the Android service's Binder paths
(`digitva-9cll.6`), and an end-to-end run of the complete offline coding
journey on a phone with a published Plus build (`digitva-9cll.5`).

### The 30 October full evaluation: 30,783 requests

Same phone, container and data as the 29 October run below, on the current
engine (2026.10.29.1) and its single call interface, which takes the same
options the server sends. Field names are now compared case-sensitively.

| Request set | Requests | Identical | Refused by both | Different |
| --- | --: | --: | --: | --: |
| Synthetic certificates (DORIS, then CoDEdit) | 10,000 | 10,000 | 0 | 0 |
| Earlier DigitVA suite | 10,000 | 10,000 | 0 | 0 |
| Erroneous certificates | 10 | 10 | 0 | 0 |
| Malformed requests | 5 | 1 | 4 | 0 |
| ICD-11 search texts | 92 | 91 | 1 | 0 |
| Code info: stem, postcoordinated and malformed codes | 57 | 49 | 8 | 0 |
| Search, code info, entity and foundation options, and the bridge's bounds | 118 | 90 | 28 | 0 |
| Golden: every WHO request recorded for the golden corpora (search, code info, entities, residual categories, foundation, DORIS and CoDEdit) | 1,592 | 1,586 | 6 | 0 |
| Sweep: the coding screen's reads for 401 codes (code info in three modes, entities and their `unspecified`/`other` residuals, hierarchy, related and details reads, postcoordination axes and composed `&`/`/` expressions, picker and subtree searches) | 8,909 | 8,261 | 648 | 0 |
| **Total** | **30,783** | **30,088** | **695** | **0** |

Most refusals are reads of residual categories that do not exist (404 on both
sides). The empty search text, which differed on 29 October, is now refused on
both sides. The app's TypeScript layer is tested against the golden replies
(table above), so with the golden requests matching on the phone, the phone's
coding screen answers as the server's does for these inputs. The inputs,
results and `run.json` (engine, phone, container digest, dataset hashes) are in
`scripts/icd11-parity/results/2026-10-30-full-engine-2026.10.29.1-surface/`.

### The 29 October run: 20,164 requests

Every DORIS and CoDEdit result on 20,010 certificates was identical, field for
field. Search and code info agreed on every input except an empty search text.
This run used the engine library from Collect Plus 0.3.14, which is
byte-identical to the 2026.10.25.1 engine release. The 30 October run above is
the check against 2026.10.29.1.

**Set-up.** Phone: Samsung SM-E146B, Android 15, with the shipped WHO data and
the app's OpenSSL, network blocked. Reference: `whoicd/icd-api:2.6.0` (image
digest `1b77eb6d…`), called over REST with the same requests the DigitVA server
sends. Both sides use ICD-11 MMS 2026-01 and DORIS rule engine 1.1.176.

| Request set | Requests | Identical | Refused by both | Different |
| --- | --: | --: | --: | --: |
| New synthetic certificates (generated for this run) | 10,000 | 10,000 | 0 | 0 |
| Earlier DigitVA suite (reference outputs from DORIS 1.2.1) | 10,000 | 10,000 | 0 | 0 |
| Erroneous certificates (empty or null parts, blank lines, unknown, empty or uncoded entries) | 10 | 10 | 0 | 0 |
| Malformed requests (not JSON, null, empty object, array, empty text) | 5 | 1 | 4 | 0 |
| ICD-11 search texts | 92 | 91 | 0 | 1 |
| Code info: stem, postcoordinated and malformed codes | 57 | 49 | 8 | 0 |

The earlier suite's stored reference outputs were produced with DORIS 1.2.1.
The comparison in this run is phone against container, and both sides ran rule
engine 1.1.176.

**The certificates.** The 10,000 new certificates come from 39 ICD-11 codes
common in verbal autopsy, across adults, children, neonates and maternal
deaths. They vary sex (including unknown), age (estimated age, full dates,
year-only date of birth), one to four Part I lines, zero to two Part II
conditions, intervals from unknown to years, and the surgery, autopsy,
manner-of-death, maternal and fetal or infant blocks. Every choice is derived
from a hash of the certificate number, so the set is the same on every run
(SHA-256 `aa1eea02…`).

**How results are compared.** Every field must be equal. Field names are
compared ignoring case, because the REST layer writes camelCase (`stemCode`)
and the in-process call returns the controller's PascalCase (`StemCode`). A
search's `uniqueSearchId`, a new random identifier on every call, is left out.
For refused requests only the refusal is compared, because the two layers word
errors differently.

**The differences we found.**

- **Empty search text.** The container refuses it (400, "q parameter should
  contain a value"); the in-process call returns an empty result list (200). On
  the phone the picker therefore shows no results rather than an error.
- **Error status.** Text that is not JSON, or an empty body, is refused with
  400 by the container and 500 by the in-process call; both refuse.
- **Search options.** The phone's search takes the text alone, with WHO's
  default options; the server sends coding-mode options (prefix matching,
  postcoordination included). The 92 texts were compared with default options
  on both sides.

**Reproducing it.** The kit is in our repository (`scripts/icd11-parity`);
`scripts/icd11-parity/eval.sh quick|full` runs it from committed datasets and
writes each run to `results/` (`scripts/icd11-parity/README.md`). It holds a
fixed condition list, the certificate generator, a fixed query list, the phone
harness in C, a container runner, a comparison script and one script that
downloads the pinned engine and APK, checks their SHA-256 and runs everything.

### Validation around DORIS

DigitVA adds checks before and after WHO's engine. None of them changes WHO's
answer.

- **Final codes only.** FER-CE-883 is an extension code used alone; BER-CE-10
  is a category ("not a terminal code"). DigitVA refuses both up front with
  `422 INVALID_SELECTION`; WHO's CoDEdit flags them only after processing. The
  check applies on the server, offline and in both pickers.
- **Certificate rules.** A Part I line may not be left blank between filled
  lines. Each interval must be a valid ISO 8601 duration, and all conditions on
  a line must use the same interval. An interval longer than the age at death
  only warns.
- **Picker rule.** A stem whose postcoordination is mandatory is not staged
  until it is built. This is a picker rule, not a certificate rule.
- **Personal data.** The phone checks every engine input before the call
  (`src/workspace/piiBoundary.ts`). It refuses fields named as personal or
  registration identifiers (name, phone, address, Aadhaar, ABHA and so on),
  and any text with a 12-digit Aadhaar-like or 10-digit Indian mobile pattern.
  Names typed into free text cannot be detected.

All checks are listed in
[`docs/current-state/doris-validation-checks.md`](../current-state/doris-validation-checks.md).

## 6. Performance on a phone

Measured on a Samsung SM-E146B (6 GB model, 5.3 GiB visible to Android,
Android 15) with the arm64 release build.

**Per call, 29 Oct 2026 run, engine warm, measured in the engine process**
(20,010 certificates, 92 searches, 57 code-info calls)

| Operation | Median | 95th percentile | Slowest |
| --- | --: | --: | --: |
| DORIS | 3.5 ms | 5.5 ms | 64 ms |
| CoDEdit | 4.1 ms | 5.3 ms | 270 ms |
| Search | 3.5 ms | 75 ms | 614 ms |
| Code info | under 0.1 ms | 0.8 ms | 276 ms |

Few calls were slow: the first certificate (DORIS 47 ms), one pause in the
middle of the run (CoDEdit 270 ms), broad searches such as "cancer" (614 ms)
and "liver cancer" (256 ms), and the first postcoordinated code-info lookup,
1B12.2&XA0G74 (275 ms). In that run the engine started in 20.9 s; memory was
504 MB after start, 591 MB at the end, and peaked at 1,050 MB during start-up.

**Per call under the full evaluation load, 30 Oct 2026, engine warm, measured
in the engine process** (the `eval.sh full` run with the libraries of the
published Collect Plus 0.3.18 APK: 50,959 engine calls in one process, back to
back; the container column is WHO's container on the Mac running the same
requests over REST, for scale only)

| Operation | Calls | Phone median | Phone 95th / 99th percentile | Phone slowest | Container median / 95th |
| --- | --: | --: | --: | --: | --: |
| DORIS | 20,176 | 3.4 ms | 5.3 / 6.6 ms | 141 ms | 1.0 / 1.8 ms |
| CoDEdit | 20,176 | 4.4 ms | 5.5 / 6.0 ms | 348 ms | 0.7 / 1.1 ms |
| Search | 1,325 | 5.2 ms | 54 / 186 ms | 681 ms | 1.7 / 10.8 ms |
| Code info | 2,734 | under 0.1 ms | 0.5 / 0.7 ms | 269 ms | 0.6 / 0.7 ms |
| Entity | 4,445 | 0.3 ms | 1.3 / 4.2 ms | 70 ms | 0.6 / 1.1 ms |
| Residual entity (`unspecified`, `other`) | 1,398 | 0.2 ms | 3.0 / 16 ms | 43 ms | 0.6 / 1.5 ms |
| Foundation entity | 705 | 0.1 ms | 0.4 / 0.6 ms | 0.7 ms | 0.6 / 0.8 ms |

The phone spent 173 s on the 50,959 calls (about 295 calls a second). Lookups
(code info, entities) are faster on the phone than over the container's REST
layer, because they skip HTTP; DORIS, CoDEdit and broad searches are three to
six times slower. The engine started in 19.6 s. Its memory was 511 MB after
start and grew steadily to 1,082 MB at the end of the run (peak 1,179 MB): the
29 October run, without the 6,548 entity reads of the golden and sweep sets,
ended at 591 MB, so the growth follows the number of distinct entities read
and is most likely WHO's entity cache; a coding session reads far fewer. The
engine used one core throughout; the battery stayed at 26.4 °C and Android's
thermal status at 0 (none), sampled every 5 s over the last part of the run.

**Per call as the app sees it, first calls, including the hop to the engine
process**

| Operation | Time |
| --- | --- |
| ICD-11 search | 35 to 120 ms per query |
| DORIS underlying cause | 40 to 100 ms per certificate (7 ms on a repeat) |
| CoDEdit | 5 to 16 ms |
| Code details | under 3 ms |

**Start-up and memory**

| Measure | Result |
| --- | --- |
| Live measurement, measured 30 Oct 2026 with 2 to 3 s sampling: engine start | about 15 s |
| Same: engine memory while starting (PSS) | peak 761 MB |
| Same: engine memory once ready (PSS) | 527 to 573 MB, idle CPU 0%, 19 to 25 threads |
| Same: app process memory (PSS) | 142 to 222 MB during coding |
| Baseline 28 Oct 2026, first setup after install | 20.5 s total, 20.3 s engine initialisation (copying WHO files 0.13 s); sampled engine PSS peak 1,191.0 MiB |
| Baseline 28 Oct 2026, next cold start | 17.8 s total, 17.7 s engine initialisation; sampled engine PSS peak 871.7 MiB, settling about 528 MiB |
| Earlier build (`docs/current-state/expo-client.md`) | launch to engine ready 19.9 to 21.3 s; engine PSS peak 801 to 824 MB during initialisation, then 548 MB; main process about 130 MB |
| Install size, Collect Plus 0.3.16 APK | 148,761,770 bytes (142 MiB) |
| Install size on the phone (28 Oct baseline) | app 354 MB, data 501 MB, total 855 MB |

The start-up cost is paid once per app process, and only when coding is
enabled. The engine then stays ready until Android stops the process. Sampled
maxima are not allocation peaks. Keeping the engine in its own process lowers
the peak in the app's process and lets Android reclaim it without closing the
app, so it is the default.

## 7. Data protection and consent

- **On the phone.** Interviews and certificates are kept in an encrypted
  SQLCipher database. Its key needs the Android Keystore and the coder's PIN
  (6 to 16 digits). The database is wiped after 5 wrong PINs. Screenshots are
  blocked, except in field-test builds with a dated allowance (currently until
  25 Nov 2026).
- **Engine.** The engine receives the search text, the certificate (causes,
  codes, intervals) and the fields DORIS needs, such as sex and age, but not
  the interview record. The personal-data boundary in section 5 stops
  identifier fields and number patterns before any call. Its start-up
  downloads fail against the dead proxy (section 2).
- **Upload.** A phone uploads only to the DigitVA server it is enrolled with.
  A standalone account keeps everything on the phone until that phone is
  enrolled; it then sends each interview with its consent and offline coding
  (`docs/current-state/device-collection-api.md`, "Standalone push"). The
  server re-checks permission and re-applies DigitVA's ICD-11 allowability
  rules to the imported result; it does not re-run DORIS. A disagreement is
  flagged and the case goes to a reviewer. The offline result is held for
  review. The app has no third-party analytics.
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
  WHO has not answered any of the four points in writing.
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
