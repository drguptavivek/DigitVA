---
title: iOS Native Modules (Device Info, SmartVA, ICD-11)
doc_type: current-state
status: draft
owner: drguptavivek
last_updated: 2026-11-04
---

# iOS native modules

The iOS sides of the three local Expo modules in `mobile/digitva-collect/modules/` (beads digitva-nujw.2, .3, .4).
Each module's `expo-module.config.json` lists `"platforms": ["android", "apple"]` and its Swift class under
`apple.modules`; the pod lives in the module's `ios/` folder, which is where Expo autolinking looks for a podspec. The JS
API, result maps and error codes are the Android ones (`src/performanceTelemetry.ts`, `src/smartva/nativeEngine.ts`,
`src/offlineEngine.ts`); `__tests__/ios-native-modules-source.test.js` checks the Swift sources against that contract.

Status: draft. The Swift has been type-checked on Linux against a stub of ExpoModulesCore's DSL, never compiled
against the real SDK or run on a device or simulator. See "Verified and not verified" below.

## Modules

| Module | Swift | What it does on iOS |
| --- | --- | --- |
| `digitva-device-info` | `DigitvaDeviceInfoModule.swift` | Synchronous `getHardwareProfile()`: `device_type` from the `hw.machine` sysctl (`iPad…` tablet, `iPhone…` phone, simulator `emulator`, iOS app on a Mac `other`), `ram_bucket` from `ProcessInfo.physicalMemory` and `core_bucket` from `activeProcessorCount` with the Kotlin module's boundaries, `manufacturer` `apple`. UIKit is not used: the function runs on the JS thread and `UIDevice` is main-actor isolated. |
| `digitva-smartva` | `DigitvaSmartvaModule.swift`, `SerialWorker.swift` | `isAvailable()`, `init()`, `score(requestJson)`. The request checks, the 1 MiB request and 2 MiB reply limits and the `too_large` / `bad_request` / `engine_error` / `native_error` / `unavailable` codes are those of `SmartvaService.kt` and `SmartVaJni.cpp`. The row JSON is written with sorted keys; the engine builds its CSV header from key order and reads columns by name, and a host build of the same library gave byte-identical results for original, sorted and shuffled key order (PHMRC and WHO 2016 example rows). |
| `digitva-icd11` | `DigitvaIcd11Module.swift` (module + `EngineHost`), `EngineData.swift`, `SerialWorker.swift` | `isAvailable()`, `init()`, `updateWhoFiles()` (answers `bundled_only`, as the Android service does), `call(op, input)` (rejects a bad op name with `ERR_ICD11_OP`), event `icd11Progress {phase, percent}`. Init, setup record, repair, data version and result maps mirror `EngineHost.kt` / `EngineData.kt`; the 250 000-character reply cap that Binder forces on Android is kept so both platforms answer alike. |

### Linking and `isAvailable()`

Each engine podspec checks at `pod install` time whether its staged binary is in the module's `ios/` folder. Only then
does it vendor it and add a Swift compilation condition (`DIGITVA_SMARTVA_LINKED`, `DIGITVA_ICD11_LINKED`); the Swift
imports and calls the C ABI only under that condition, and `isAvailable()` returns that compile-time fact (ICD-11 also
requires the packaged data folder). A compile-time flag was chosen over a weak-symbol check because the pod either
vendors the library or does not, the answer cannot change at run time, and an unlinked build then contains no reference
to the engine at all.

## Threading: no engine process on iOS

Android runs SmartVA in the `:smartva` process and ICD-11 in the `:icd11` process. iOS has no app-owned secondary
processes, so both engines run inside the app process, each on its own long-lived worker thread (`SerialWorker`: one
`Thread`, FIFO, started on first use). A dedicated thread is used instead of a serial `DispatchQueue` because GCD worker
threads have a fixed 512 KiB stack; SmartVA gets 8 MiB and ICD-11 32 MiB (Android's `icd11-engine` thread size;
NativeAOT start-up is stack hungry). Calls are serialized as in the Android services and the JS thread never blocks.

Consequences, accepted for Collect Plus:

- **Crash isolation is gone.** A memory fault or abort in either engine ends the whole app, including an interview in
  progress. The SmartVA Rust ABI catches panics (`guard` in `vendor/smartva-analyze/rust/src/lib.rs`); the ICD-11 bridge
  catches managed exceptions. Neither protects against native faults.
- **Memory counts against the app.** The ICD-11 engine's resident set is about 600 MB on Android. On iOS it adds to the
  app's own footprint, and jetsam ends the app (not a helper process) when the device's per-app limit is reached. Devices
  with 3 GB of RAM or less are at risk; this needs measuring on hardware.
- **Process-global state.** The ICD-11 init sets `http_proxy` / `https_proxy` (upper and lower case) to a dead local
  proxy for the whole app process, so the engine's WHO download attempts fail at once and it uses the shipped files
  (`EngineHost.kt` guardNetwork). `NSURLSession`, which React Native uses, does not read these variables. `TMPDIR` is not
  changed on iOS: the bridge sets the managed value itself and the app's own temporary folder is writable.
- **Failure is sticky per app run** (per engine process on Android): a failed ICD-11 init stays failed until the app is
  restarted.

## ICD-11 data on iOS

`stageIcd11Ios` copies the same data files as the Android staging (from the engine archive or spike folder) into
`modules/digitva-icd11/ios/Icd11Data/{bundle,data}` under their original names (an app bundle keeps `.gz` files as they
are, so no `.bin` suffix) and writes `who-files.json` from the staged copies. The pod ships it as
`DigitvaIcd11Data.bundle`. At first init it is copied to `Application Support/digitva-icd11/icd11-<DATA_VERSION>/`
through a `.partial` folder renamed into place. `Application Support/digitva-icd11` is excluded from backup and created
with `NSFileProtectionCompleteUntilFirstUserAuthentication` (files created inside inherit it); setup records are
written with the same protection.

## Builds

| Piece | Script | Host | Output |
| --- | --- | --- | --- |
| SmartVA | `scripts/build-smartva-ios.sh [OUT_DIR]` | any host with the Rust targets `aarch64-apple-ios`, `aarch64-apple-ios-sim`; the xcframework step needs macOS + Xcode | `private/generated/smartva-ios/`: `<target>/libsmartva_rust.a`, `frameworks/<target>/SmartvaRust.framework` (static archive, `SmartvaRust.h`, module map), `SmartvaRust.xcframework` (macOS) |
| ICD-11 engine | `modules/digitva-icd11/engine-src/build-ios.sh OUT_DIR` | macOS + Xcode + the .NET SDK in `global.json` + WHO's assemblies (`ICDAPI_DIR`) | `DigitvaIcd11Engine.xcframework` and `icd11-engine-ios-<version>.tar.gz` (+ `.sha256`) |
| Staging | `modules/*/scripts/stage-engine.js` `stageSmartvaIos()` / `stageIcd11Ios()` (`--ios` on the command line) | any | the binaries (and ICD-11 data) in each module's `ios/` (git-ignored) |
| Plus wiring | `plugins/with-ios-collect-plus.js` | any | plain build: `use_expo_modules!(exclude: ["digitva-icd11", "digitva-smartva"])` in the Podfile; Plus: staging before `pod install`, failing with the staging script's message when a binary is missing; `DIGITVA_IOS_SKIP_ICD11=1` builds Plus with SmartVA only |
| CI | `.github/workflows/ios-build.yml` | `macos-15` | unsigned Debug simulator build of the plain app on PRs; Plus (SmartVA only) on `workflow_dispatch` with `plus: true` |

SmartVA is built with `cargo rustc --crate-type staticlib` so the crate's `rlib`/`cdylib` setting in the submodule is
untouched; `IPHONEOS_DEPLOYMENT_TARGET=16.4` matches the Expo SDK's pod floor.

The ICD-11 engine is a **dynamic** framework (NativeAOT `NativeLib=Shared`, Bridge.csproj's own value), not a static
library: Microsoft's guide for iOS-like platforms (.NET 9+) builds a `.dylib`, rewrites its install name to
`@rpath/<name>.framework/<name>` and embeds it as a framework, states that shared libraries are preferred, and does not
document consuming a static NativeAOT library on iOS. A static build would put NativeAOT's runtime archives and Apple
frameworks on the app's link line; `NATIVE_LIB=Static` in `build-ios.sh` produces the archive for an experiment and
names the inputs to verify (for example `libbootstrapperdll.o`, `libRuntime.WorkstationGC.a`, `libSystem.Native.a`,
`libSystem.Globalization.Native.a`, `libSystem.IO.Compression.Native.a`,
`libSystem.Security.Cryptography.Native.Apple.a`, `libSystem.Net.Security.Native.a`). The iOS settings are passed to
`dotnet publish` as properties, so `Bridge.csproj` and the Android build are unchanged. The WHO data is not in the iOS
engine archive: both platforms stage it from the same engine archive.

## Verified and not verified

Verified on Linux (2026-11-04):

- `scripts/build-smartva-ios.sh` builds both static archives (about 56 MB each; LC_BUILD_VERSION minos 16.4) and the
  frameworks, and checks that `_smartva_version`, `_smartva_score_json` and `_smartva_free_string` are defined. Clang
  resolves `@import SmartvaRust` against the generated framework module map.
- The Swift of all three modules type-checks (Swift 6.1 for Linux, language modes 5 and 6, with and without the
  `*_LINKED` conditions) against a stub of ExpoModulesCore's DSL, the generated SmartVA framework and a framework built
  from `build-ios.sh`'s ICD-11 header.
- Jest: staging functions, the plugin and the Swift source contract (`__tests__/ios-engine-stage.test.js`,
  `__tests__/ios-collect-plus-plugin.test.js`, `__tests__/ios-native-modules-source.test.js`).

Needs macOS (not yet done):

- Compiling against the real ExpoModulesCore, `pod install`, the simulator build (the CI workflow), the xcframework
  step, and anything at run time.
- `engine-src/build-ios.sh` has never run: NativeAOT for `ios-arm64` / `iossimulator-arm64` with WHO's assemblies,
  the `AppleMinOSVersion` property, the install-name rewrite, and whether WHO's code paths work under iOS.
- That .NET's HttpClient on iOS honours the dead proxy, so no request leaves the app during ICD-11 init.
- Memory and start-up time of the ICD-11 engine in the app process on a 3–4 GB device.
