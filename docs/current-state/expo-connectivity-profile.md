---
title: Expo Web Poor Connectivity Profile
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-10-25
---

# Expo web poor connectivity profile

The WHO engine, canonical instrument and renderer are deferred from login and
coding startup. Eligible interview users can download verified public runtime
assets after login, without executing the WHO module on the home screen.
Small presentation controls stay in the app. Clinical rules remain canonical.
See [hosting and caching](expo-client.md) for the runtime and update contract.

## Browser measurements

Desktop Chrome used the same local Flask backend and gzip-enabled nginx for both
exports. CDP throttled downloads to 200,000 bytes/s (1.6 Mbps), uploads to 64,000
bytes/s (512 kbps), and latency to 400 ms. Each cell is the median of three
trials. Cold trials bypassed the service worker and disabled browser cache;
warm trials enabled both after a separate cache-fill run. The endpoints were
the signed-in home screen and the first rendered WHO interview section/footer.
Times include browser automation overhead and are not complete-interview times.

| Screen and cache | Baseline | Candidate | Change |
| --- | ---: | ---: | ---: |
| Home, cold | 6.269 s | 4.990 s | 20.4% faster |
| Home, warm | 1.948 s | 1.944 s | Essentially unchanged |
| Direct interview, cold | 9.405 s | 10.897 s | 1.492 s slower |
| Interview, warm | 4.851 s | 4.880 s | Essentially unchanged |

Baseline was the CI export of a14f6fa24. Candidate timings used the local Docker
source-mapped export of the code subsequently committed as 3eaaf3b0c. The owner
accepted the roughly 1.5-second cold direct-interview tradeoff; startup overlap
was not added. Source maps verified zero WHO package sources in initial JS.
These are desktop results, not physical-phone measurements.

The final non-source-mapped CI artifact of 3eaaf3b0c was downloaded and verified
separately. Its initial scripts total 2,340,739 raw bytes / 597,090 gzip bytes,
with the WHO runtime deferred (1,246,172 raw / 250,034 gzip). The initial gzip
size is about 30% below the measured baseline. Source-map comments account for
small differences from the timed candidate; final CI was not used for the
timing table. The canonical-instrument placement and initial-byte gates pass.

## Recovery and cache acceptance

- Home-screen cache inspection found only hashed public entry/common/Metro/WHO
  assets. WHO was cached without a WHO script element on the home screen.
  No API responses, private definitions or answers were present in this cache.
- A blocked WHO chunk produced the existing retry UI. Removing the block and
  selecting “Try again” restored the form without reloading the document.
- In an owned synthetic training draft, an offline answer edit remained visible
  with the connection error and “Draft not saved yet”. After reconnection,
  saving succeeded; reloading restored the edited answer from the server.
- Canonical training form/list navigation works, including an explicit
  back-to-collection destination for direct links. The identifier warning in
  the old comparison export was absent in the current export.
- The exact downloaded CI artifact also rendered the restored training draft
  on a fresh local origin. “Save and leave” returned to
  `/app/training/interview` without the identifier warning.

The download failure test blocked the chunk request; a mid-transfer interruption
was not independently demonstrated in Chrome. Worker cancellation, partial-cache
reuse, integrity rejection and retry have automated regression coverage.
Interview submission and physical-device acceptance were not performed here.

## Build and validation

[CI run 40198746587](https://github.com/drguptavivek/DigitVA/actions/runs/40198746587)
passed both WHO and app jobs for 3eaaf3b0c9b4f01763c3aa98685c106040687a48.
The app consumed the verified WHO artifact from the same commit. Both downloaded
archive checksums, the 35-file WHO manifest/install verification and a fresh
strict profile of the downloaded app passed. Publishing was disabled; staging
was not deployed.

The app passed 180 Jest suites / 2,706 tests and TypeScript checks. The public
asset/profile/package helper checks passed 33 Node tests. Affected backend
coverage passed 519 tests plus 125 subtests before packaging-only changes.
WHO build, types and entrypoint tests passed. Its full serial vendor suite was
933/935: the draft-save-order failure reproduced on the unchanged baseline;
the navigation failure passed isolated reruns. Both remain tracked in
`digitva-dv58`, without skipped or weakened assertions.

Sanitized local traces and artifact verification outputs are under
`/private/tmp/digitva-web-profile-20261025` and
`/private/tmp/digitva-paired-ci-40198746587`; these temporary files are not
required for running the application.

## Published release

The owner subsequently authorized publication. Run
[40200511607](https://github.com/drguptavivek/DigitVA/actions/runs/40200511607)
built and published [expo-web-v2026.10.25.2](https://github.com/drguptavivek/DigitVA/releases/tag/expo-web-v2026.10.25.2)
from `1892f085ddb5ca41ca6ee1c7d0449ef0470f8b9d`. Both downloaded archive
checksums, app/WHO release/source/component metadata and a fresh strict profile
passed. Published initial scripts total 2,340,741 raw / 597,097 gzip bytes;
the slight difference from the prior artifact is public release metadata.
App archive SHA-256:
`63c9db9b987498a9c85c061278e46ebdbdb3c7093c319820349ae41b571a45f0`.
WHO archive SHA-256:
`a6eca940dd775a7fff17b86f1e2f14e410ec1939cfd5311983e6226fa0425b42`.
This publication did not update Compose pins, build a server image or deploy
staging. Those steps follow the deployment runbook.
