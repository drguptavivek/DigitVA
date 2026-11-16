# SmartVA parity kit: Collect Plus engine on the phone versus the server's stored result

Runs every case the dev server has scored with SmartVA through the offline SmartVA engine on an Android phone and on
the iOS Simulator, and compares each reply with the result the server stored in `va_smartva_results`. The SmartVA
counterpart of `scripts/icd11-parity`. The source cases are research data: everything derived from a case (requests,
expected results, replies, mismatch examples, sid hashes) stays under `private/smartva-parity/` (git-ignored, checked by
`run.sh`). Only code, this README and the aggregate `results/*/summary.txt` and `run.json` are in the repository.

## What is compared

1. **Cases.** One row per `va_sid`: its `va_smartva_status = 'active'` row. Every sid has exactly one, and each points
   at the submission's current `active_payload_version_id`, so the choice is unambiguous (the deactive rows are earlier
   runs). The stored row's run (`va_smartva_runs.run_metadata`) gives the engine version where it was recorded.
2. **Input** (`export.py` in the app container, piped into `build_requests.js` on the host; raw payloads never touch
   disk). The values are the row the server's own `_clean_payload_for_smartva` makes of the payload (what SmartVA read),
   kept to the fields the app's `cleanSmartVaInput` keeps (its PII filter) and passed through the app's
   `createSmartVaRequest`, both from `mobile/digitva-collect/src/smartva/input.ts` compiled by `tsc`. The phone
   cleaner drops one field the server reads, `Id10476_audio` (an attachment name, in the app's PII list), and spells a
   JSON number as JavaScript does (`5` where the server wrote `5.0`); `requests-phone.tsv` is the app cleaner's own
   output, for a run that shows those spellings change nothing.
3. **Options.** `hiv`/`malaria` from the run's `run_metadata` where recorded, else the server's
   `_derive_smartva_run_options` now; country `smartva_country(form)`; `hce`/`freetext` the form's flags. Today every
   case resolves to `IND`, hiv off, malaria off, hce on, freetext on.
4. **Engine call** (`harness.c`): `smartva_score_json([input], country, hiv, malaria, hce, freetext, 0, ...)`, the call
   `SmartVaJni.cpp` and `DigitvaSmartvaModule.swift` make, after `smartva_version()` and with no warm-up, as the app.
5. **Fields** (`compare.py`). The server stored the likelihoods CSV row as read by pandas; the phone's JSON prediction is
   put in that shape with the server's rules: `age` as `format(float(age), ".1f")`, `sex` 1 Male / 2 Female / else
   Missing (the engine's CSV writer), `resultfor` = `for_<module>`, cause, likelihood, key symptom and all symptoms as
   strings with `""` as NULL, ICD-10 of each cause from the app's `va-icd10.json` (as `projection.ts`). The server's
   merged table (`VA_SMARTVA_ICDS`, NEONATE | CHILD | ADULT) gives the same code for every cause of the app's table;
   `compare.py` checks that on every run. A server `format_output` failure (no output row) matches a reply without a
   prediction; the two `execution` failures never reached the engine and are not compared.
6. **Android vs iOS**: the whole reply (return code and body, including the CSV outputs) byte for byte.

Results are broken out by the engine that scored the stored row: rows before 2026-10-22 have no recorded engine (the
Rust engine and the version record landed together in `3dbd60206`; before it the server ran the Python SmartVA-Analyze,
its only engine), then `smartva-rust 0.2.0`, then `3.0.2`, the version on the phone. Exit status 1 on any difference.

## Run

Needs the dev stack (`docker compose up -d`), node, the NDK (`ANDROID_NDK`), a phone on adb, Xcode and a booted
simulator, and the libraries from `scripts/build-smartva-android.sh` and `scripts/build-smartva-ios.sh`.

    scripts/smartva-parity/run.sh corpus     # dev DB, read-only -> private/smartva-parity/corpus/
    scripts/smartva-parity/run.sh ios        # SIM_UDID=...; replies -> private/smartva-parity/runs/<date>-ios/
    scripts/smartva-parity/run.sh android    # /data/local/tmp/smartva-parity, removed afterwards

`COMPARE_ONLY=1` compares replies already in the run directory. Per-case mismatch examples are in
`private/smartva-parity/runs/<date>-<platform>/mismatch-examples.jsonl`.

## Results (`results/<date>-<platform>/`)

`summary.txt` is `compare.py`'s output; `run.json` adds date, device, OS, library path and sha256, corpus sha256s, kit
commit and whether the kit was dirty. No case data.

| date | platform | engine | cases | outcome |
| --- | --- | --- | --- | --- |
| 2026-11-05 | iOS Simulator (iPhone 17, iOS 26.5, M5 Pro) | 3.0.2 | 8,399 | vs current server engine: 8,399 identical (8,282 scored, 117 no prediction on either side). vs stored: 7,103 + 969 + 2 + 2 identical, 117 no prediction on either side; 203 Python-era rows differ only in key symptoms; 1 Python-era row had no output where both engines now score; 2 rows never reached the engine (a server `execution` failure, scored fine now). Median 26.0 ms, p95 27.8 ms |
| 2026-11-05 | Android, SM-E146B, Android 15 | 3.0.2 | 8,399 | the same counts in both comparisons; all 8,399 replies byte-identical to iOS. Median 92.3 ms, p95 93.1 ms, with the phone at load average ~14 from other work |

The app-cleaned input (`requests-phone.tsv`, iOS only, not part of the verdict) differs from the server's in 193 cases,
always a whole number written `N` where the server wrote `N.0` (mostly `Id10120`, the `age*` fields, `Id10161`,
`Id10413_d`). In 37 of them the result changes, and in 36 the app's spelling gives more endorsed symptoms. Read
`summary.txt` for the counts.

## Not covered

A real iPhone and a release build; options other than IND with HIV off, malaria off, HCE on and free text on (every
case resolves to that); why the Python engine picked other key symptoms (attributed to the engine, not reconciled);
whether the app's drafts ever hold JSON numbers for these fields; what `projectSmartVaResult` does with the 117 replies
that have no prediction (the app throws).
