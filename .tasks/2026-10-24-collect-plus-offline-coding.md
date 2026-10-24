# Collect Plus: experimental offline coding on Android

- **Status:** phase A in progress
- **Priority:** high (owner request 2026-10-24)
- **Created:** 2026-10-24
- **Bead:** digitva-hs7e
- **Goal:** An experimental Android build, "DigitVA Collect Plus", that adds the Expo
  coding workspace to digitva-collect and runs ICD-11 search, codeinfo, DORIS and
  CoDEdit on the phone. A coder self-codes a case on the phone and the result syncs
  to the server. We profile memory pressure and latency during coding, search and
  DORIS.

## Decisions

- **App:** a build variant of `mobile/digitva-collect` (owner 2026-10-24), not a new
  `digitva-coder` project. Distinct applicationId suffix `.plus`, its own name and
  versionName, and it installs beside the normal app. It is adb or local install only:
  never uploaded to staging `/download/android`, never pinned in `docker-compose.yml`.
  The plain collect build stays data-collection only and stays byte-for-byte unaffected
  when the variant is off.
- **Engine:** our 2026-10-21 NativeAOT spike, preserved in
  `private/icd11-offline-spike/` (gitignored, 934 MB). It runs WHO ICD-API 2.6.0 code
  in-process, the same version the staging server uses (`whoicd/icd-api:2.6.0`), and
  exposes `digitva_icd11_{init,search,codeinfo,doris,codedit,free}`. It was compiled
  on macOS. It is chosen over the third-party prototype (substring search only,
  DORIS 1.2.1, which differs from the server, Linux-only build). The 131 MB `.so` and
  its data are never committed; the variant build copies them from `private/`.
- **Licence:** the owner ruled it not breached (2026-10-21). This is also why the
  build stays off public downloads.
- **Sync (phase B):** the phone uses the local engine for search, codeinfo and DORIS.
  Before the final save, when online, it calls the server's existing DORIS process
  endpoint to get the server result and `process_token`, compares that with the
  offline result (a parity record kept locally, in the encrypted DB), and then saves
  through the existing API. No new server endpoint in the first cut. Persisting
  server-side "offline" provenance needs an additive migration; it is a later step,
  taken only if the owner asks.
- **Engine safety:** never log the engine's `{"error"}` payloads (stack traces, and
  possibly certificate text). Init runs once per process on a worker thread; a
  failure is sticky until the app restarts.

## Phases

- **A (now, new files only, no overlap with DORIS parity writers gfx8 and 4m61):**
  1. The Plus variant (app.config, config plugins: arm64-only, extracted native libs).
  2. A local Expo module `digitva-icd11` (Kotlin, JNI shim adapted from
     `private/icd11-offline-spike/apptest/jni/shim.c`, engine data copied to `filesDir`).
  3. A JS `offlineEngine` API.
  4. Native coding and workspace routes enabled in Plus only.
  5. An adb profiling script.
- **B (after gfx8 and 4m61 merge):**
  1. In Plus, route DorisPanel search, codeinfo and process to the offline engine.
  2. A native search UI, because the picker WebView host is served by the server.
  3. The parity check and sync at final save.
  4. An offline case queue.
- **C:** a profiling run comparing baseline 0.3.10, the engine in the main process, and
  the engine in an `:icd11` process. Steps: cold start, open case, 5 searches, process,
  save, sync. Measure PSS, lmk/trim and latency on the SM-E146B (6 GB model, MemTotal 5.3 GB), which is representative: coders have at least 6 GB phones (owner 2026-10-24).

## Done means

- A measured table: baseline vs in-process vs `:icd11`.
- One case self-coded on the phone and visible on staging, with a parity verdict
  between the offline and server DORIS results.

## Owner decisions 2026-10-24 (after phase A)

- The engine's start-up telemetry/HTTPS call may connect. The app must never crash
  because of it: bundle an Android OpenSSL build for the engine (the linux-bionic
  NativeAOT runtime looks for libssl, which Android does not expose to apps), give the
  call a short timeout, and keep the engine in the `:icd11` process so an engine
  failure never takes down the coding screens (restart on next use, "offline engine
  unavailable" in the UI).
- A background worker runs the async jobs: a priority queue in the engine process
  (interactive search/DORIS first, then init and index build, then cache saves), with
  progress reported to the app and resume after a kill. Sync of coded cases runs in an
  app-side background worker, so it survives the screen closing.
- Start-up: warm up in the background after launch; persist the built index; save the
  cache when the app is backgrounded (follow-up after the current start-up writer).
- Profiling builds (owner 2026-10-24): a Plus **dev build** (debug, dev client on Metro
  over USB) for Hermes/React DevTools/Android Studio profiling, plus a **profileable
  release** Plus build (`android:profileable shell="true"`) for representative numbers.
  Engine phases and calls emit `android.os.Trace` sections so one Perfetto trace shows
  UI, search and DORIS together. Queued after the start-up writer; Haiku writer, Sonnet
  reviewer.
- WHO file downloads (owner 2026-10-25): allowed during **first-time setup only**. The
  engine's start-up fetches (icdcdn.who.int languageResources.txt;
  icd11files.blob.core.windows.net DORIS_v2.1_1.2.0.zip, possibly the index zip) may run
  on the first init after install or data reset, when online, with a bundled Android
  OpenSSL so they cannot abort the engine, and with a short timeout. What they fetched
  is kept on disk with size and sha256 recorded. Later inits block the network (the
  dead-proxy guard). The engine check shows whether setup downloaded or used the shipped
  copies, so parity with the server stays explainable.
- Builds (owner 2026-10-25): no more local APK or web-export builds; everything builds on
  GitHub Actions. The engine bundle (NativeAOT .so + WHO data) and the Collect Plus APK may
  be public GitHub release assets (owner's call; the repo is public). The Plus workflow
  downloads a pinned, sha256-checked engine release asset, stages it and builds.
