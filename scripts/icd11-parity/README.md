# ICD-11 parity kit: Collect Plus engine on the phone versus the WHO container

Runs the same requests through the offline ICD-11 engine on an Android phone (`phone_harness.c`, through the engine's one call
`digitva_icd11_call`) and through WHO's official `whoicd/icd-api` container, and compares the replies. All test data is DigitVA's; WHO's
container is only the reference. The engine and its interface are described in
`docs/current-state/icd11-android-engine-interface.md`.

## Why this covers the coding screen

Three links, each checked on its own:

1. **TypeScript port == DigitVA server, given WHO's replies.** Jest replays `scripts/icd11-golden` (owner-approved, frozen): for 173 DORIS,
   44 postcoordination and 238 search inputs it feeds the TypeScript layer (terms, code info, selection check, postcoordination,
   postcoordination-options, hierarchy, related, details, DORIS and CoDEdit) the WHO replies the server received and requires the server's
   reply back. Every WHO read the TypeScript layer makes is one of the engine's five ops (`search`, `codeinfo`, `entity` with an optional
   `residual`, `foundation_entity`, `doris`/CoDEdit).
2. **Phone engine == WHO container on every such read.** This kit: the same request through the engine's one call on the phone and through the
   container's REST API, replies compared field for field. `golden` is exactly the requests of link 1, so while the container has the digest the fixtures were recorded with
   (`fixtures/manifest.json`; `run.json` records the run's), the replies the port was tested on are the replies the phone gives;
   `sweep` is the picker's reads (and a superset of their options) for every code of our datasets, beyond what the golden corpora hold.
3. **Therefore** the phone's coding screen answers as the server's does, for these inputs. The argument stops where the requests do: an
   input outside `golden`, `sweep`, the certificate datasets, `queries.json` and `calls.json` is not covered by the run, only by the
   engine being the same code as WHO's. Within the sweep's codes the picker can still reach reads it does not make: options below the first
   expandable root of an axis or more than one level down ("More choices"), composed expressions beyond the first value per axis, the
   full route set for a code reached by navigation, and subtree searches past the first 3 axes.

## What is compared (`compare.py`)

- Every field of the reply. A pair matches when both sides succeed (HTTP 2xx) with equal JSON, or both refuse the request (any non-2xx;
  the phone's in-process call and the container's web stack word their errors differently, so refusals are compared as "refused").
- JSON field names are case-sensitive: the bridge must write what the container's REST layer writes (camelCase `stemCode`), not the
  controller's PascalCase. The comparer of commit `0e2b603d1`, which produced the 2026-10-29 run, compared names case-insensitively.
- A search's `uniqueSearchId` (a random id per request) is dropped.
- The bridge's own bounds (`include=descendant`, `limit` with `flatResults=false`) are refusals the container does not make;
  `run_container.py` writes the bridge's refusal bodies for them and `compare.py` requires those bodies exactly.
- Latency of each side is printed; it is not part of the verdict.
- Exit status 1 on any mismatch or any request seen on one side only.

## Datasets (`datasets/`, committed)

| dataset | content |
| --- | --- |
| `hash-synthetic-10k` | 10,000 certificates made by `make_certificates.py` from `conditions.json` (39 conditions), hash-driven and reproducible |
| `clinical-variants-10k` | DigitVA's earlier DORIS suite: 250 scenario families x 40 challenge variants (10,000) and 10 edge cases, with the team's reference outputs |
| `api-sweep` | 8,909 reads (code info, entity, residual, foundation entity, search) that the coding screen makes for the 401 ICD-11 codes of the datasets above and of the golden corpora, discovered from the WHO container on 2026-10-31 by `make_sweep.py` |

Each has a README with its provenance and sha256. Also fixed: `queries.json` (92 search texts, 57 code-info inputs), `calls.json` (118
generic calls: search and code-info options, entity, foundation entity, the bounds) and 5 malformed requests in `build_inputs.py`.

Not a dataset but a section: **`golden`**, derived by `build_inputs.py` from the committed `scripts/icd11-golden/fixtures` (their `who` maps
hold every WHO REST request the server made, 2,659 in all). Each distinct request becomes an engine call by the inverse of
`run_container.rest` (search form body to `q` and flags; `mms/codeinfo/<code>`; `mms/<id>[/unspecified|other]` to `entity`;
`icd/entity/<id>` to `foundation_entity`; the DORIS and CoDEdit POSTs to one certificate line each, sent to both). Every derived request is
run back through `run_container.rest` and must equal the recorded method, path and body; any that does not stops `build_inputs.py` with the
list. Result: 1,753 distinct requests (1,431 calls: 856 entity, 105 residual entity, 238 search, 206 code info, 26 foundation entity; 161
certificates, each DORIS and CoDEdit), all round-tripped, none unmapped. Ids `golden/<n>-<op>` and `golden/cert-<n>` follow the sorted
canonical key. `run.json` records the hash of the derived list and of the golden `manifest.json`. The recorded searches are the server's (no
`limit`); the phone sends `limit` 20, which the sweep's searches and `calls.json` cover.

## Profiles (`eval.sh`)

| profile | certificates | suite | malformed | search | code info | calls | golden | sweep | request lines |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `quick` | first 200 of `hash-synthetic-10k` | none | 5 | 92 | 57 | 118 | 1,592 | none | 2,064 |
| `full` | all 10,000 of `hash-synthetic-10k` | 10,000 + 10 edge | 5 | 92 | 57 | 118 | 1,592 | 8,909 | 30,783 |

`quick` is the earlier 472 plus `golden` (1,431 calls and 161 certificates), so every read the golden sets prove is checked on the phone in
a few minutes. `full` is everything. A request line is one call or one certificate (a certificate is two engine calls, DORIS then CoDEdit).
The 472 requests keep their ids (`ours/`, `suite/`, `edge/`, `malformed/`, `search/`, `codeinfo/`, `call/`), so older results stay comparable;
`compare.py` prints `golden` and `sweep` as sections of their own, with their own latency lines (the 161 golden certificates are
counted in the DORIS and CoDEdit latency lines with the other certificates).

Every certificate goes through DORIS and then CoDEdit. `eval.sh` takes the certificates from the committed file and stops if
`make_certificates.py` would now produce other bytes.

## Run

Needs a phone on adb (arm64, 6 GB or more), the Android NDK (`ANDROID_NDK`, default the macOS SDK path), `gh`, `python3`, and the WHO
container on 127.0.0.1:8382 (`docker compose up -d icd_api_service`).

    scripts/icd11-parity/eval.sh quick [RUN_NAME]
    scripts/icd11-parity/eval.sh full  [RUN_NAME]

It downloads the engine archive and the Collect Plus APK pinned by `scripts/icd11-engine.env` (version), `.github/workflows/collect-plus-release.yml` (archive sha256) and `run_phone.sh` (APK sha256), builds the
harness, runs both sides, compares, and writes the results. The raw work directory (library, harness, uncompressed tables) is a temp
directory outside the repo; its path is printed. A library built locally is tested with `ENGINE_SO=... STAGED=... eval.sh quick`
(see `run_phone.sh`); the directory then says `engine-local`. `run_phone.sh WORK_DIR SUITE_FIXTURES_DIR|- [golden][,sweep]` alone does the phone, container and compare steps into a work directory of
your choice (without the third argument, the earlier list of 472).

### Regenerate the sweep

    python3 scripts/icd11-parity/make_sweep.py            # asks the container (read-only), writes datasets/api-sweep/
    python3 scripts/icd11-parity/make_sweep.py --check    # exits 1 when calls.jsonl.gz would change

Caps (set to the picker's own, `dorisGuidance.ts`): 12 axes, 12 roots per axis, 12 siblings, children, related and exclusions, 12 ancestors,
search `limit` 20; subtree searches for the first 3 axes of each stem only; one second value per axis. The dataset README lists what is
asked for each code and what is left out. A new WHO release or container image changes the ids: regenerate and record the digest.

## Results (`results/`)

One directory per run, `<date>-<profile>-engine-<engine version or local>[-<RUN_NAME>]`:

| file | content |
| --- | --- |
| `requests.tsv.gz` | the request list sent to both sides |
| `phone.tsv.gz`, `container.tsv.gz` | each side's replies (status, body, latency) |
| `summary.txt` | `compare.py`'s output |
| `run.json` | date (UTC), profile, request counts per section, kit commit and whether the kit tree was dirty, compare.py commit, engine tag and archive sha256 (or local .so sha256), source of the OpenSSL and libc++ libraries (Plus APK tag and sha256, or STAGED), phone model and Android version, container image digest, dataset sha256s, compare exit status, `backfilled` |

`eval.sh` writes the results even when `compare.py` finds mismatches, then exits with its status.

| date | profile | engine | requests | outcome |
| --- | --- | --- | --- | --- |
| 2026-10-29 | full (before the one-call interface; no `calls.json`) | 2026.10.25.1 | 20,164 | 1 mismatch: `search/091`, empty text (phone 200, container 400); codeinfo 8 and malformed 4 refused on both sides; case-insensitive comparer. Backfilled |
| 2026-10-30 | quick | 2026.10.29.1 | 472 | no mismatch: 431 same, 41 refused on both sides (28 calls, 8 code info, 4 malformed, 1 search). Backfilled |
| 2026-10-30 | quick (`eval-kit`, first run of `eval.sh`, engine archive from the release) | 2026.10.29.1 | 472 | no mismatch: 431 same, 41 refused on both sides, as above |
| 2026-10-30 | full (`surface`, first run with `golden` and `sweep`) | 2026.10.29.1 | 30,783 | no mismatch: 30,088 same, 695 refused on both sides (648 sweep, 28 calls, 8 code info, 6 golden, 4 malformed, 1 search) |
| 2026-10-30 | full (`apk-0.3.18`: engine, OpenSSL and libc++ from the published Collect Plus 0.3.18 APK) | 2026.10.29.1 | 30,783 | no mismatch: 30,088 same, 695 refused on both sides |
| 2026-10-30 | quick (`cleanroom`: engine library from a clean-room build in a fresh Ubuntu container from the GitHub clone and WHO's public inputs, sha256 `30fc17da…`) | local | 2,064 | no mismatch: 2,017 same, 47 refused on both sides |

Each row is a folder in `results/`; `run.json` of each says what is unknown (null). The 2026-10-29 `summary.txt` must be read with the comparer of
commit `0e2b603d1`.
