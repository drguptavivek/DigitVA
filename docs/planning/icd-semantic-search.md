---
title: ICD Semantic Search (browser-local) — measured quality, footprint and the telemetry-first decision
doc_type: planning
status: draft
owner: engineering
last_updated: 2026-09-25
---

# ICD semantic search over ICD-10 / ICD-11 titles (`digitva-zpe`)

## Problem

The ICD coding screens and the admin ICD browsers search by SQL substring
(`ILIKE` on code and title, `app/services/icd10_2019_2_service.py`,
`app/services/icd11_mms_service.py`). A coder who types a clinical
description — "baby did not cry at birth" — instead of a code or title word
finds nothing. The bead proposed embedding-based search running in the
user's browser.

## Constraints (owner)

- English only.
- Nothing heavy on the 4 GB server VM: no embedding model or inference
  service server-side.
- Vectors precomputed offline and served as a static file; the query is
  embedded client-side (WASM), so CSP needs `'wasm-unsafe-eval'` (not
  present today, `app/__init__.py:98-121`).
- **Browser memory ceiling: 2 GB** (owner, 2026-09-25). The feature must
  not burden client machines: lazy loading, no per-page cost, and a
  measured — not asserted — footprint before any ship.
- Real-use evidence before real spend: measure what coders actually type
  via telemetry on the existing search before deciding to build ML.

## What was measured (2026-09-25)

`tooling/icd-semantic-search/quality_check.py` embeds every searchable
title — ICD-10 12,475 category rows, ICD-11 18,505 in-scope categories
(chapter X excluded, the generator scope) — with the exact quantized ONNX
models the browser would run, and scores 30 VA-style clinical phrases
where each phrase's expected codes are grounded in the catalogues
(exact codes and title substrings; the script fails on an expectation
that matches nothing).

Run: `uv run --isolated --no-project --with
transformers,onnxruntime,numpy,huggingface_hub python
tooling/icd-semantic-search/quality_check.py [--model ...]`.

| model (int8 ONNX) | ICD-10 hit@5 | hit@10 | MRR | ICD-11 hit@5 | hit@10 | MRR |
| --- | --- | --- | --- | --- | --- | --- |
| all-MiniLM-L6-v2 | 9/30 | 11/30 | 0.22 | 4/27 | 4/27 | 0.12 |
| bge-small-en-v1.5 + retrieval prefix | 9/30 | 15/30 | 0.24 | 5/27 | 7/27 | 0.21 |

Common failures at any rank near the top: measles, tuberculosis,
oesophageal and prostate malignancy, puerperal sepsis, hypertensive
headache — symptom narratives vs terse nosological titles is a hard
asymmetry for general-purpose 22-33M-parameter encoders. Corpus-wide
embedding takes ~30 s on a desktop CPU for either model, so server-side
batch embedding is cheap if ever wanted; per-query quality is the
bottleneck, not compute.

### Footprint (arithmetic on the measured corpora, 31k titles × 384 dims)

- Quantized model file: 23.0 MB (MiniLM-L6) / 34.0 MB (bge-small).
- Vector matrix: 47.7 MB fp32, 23.8 MB fp16, 11.9 MB int8.
- Code+title metadata: ~2-3 MB compact.
- A minimal lazy-loaded payload is therefore ~35-60 MB one-time, and the
  WASM heap for one 128-token query is far below the 2 GB ceiling — the
  2 GB cap is trivially satisfiable. **Retrieval quality is what fails**,
  and it fails while asking every client machine to download and hold a
  model. That fails the "must not burden a client machine" test for the
  value delivered.

## Decision

**Browser-ML semantic search is parked.** Building it now would cost
every client a ~35-60 MB payload plus a WASM runtime for measured
hit@10 of roughly half on hand-written phrases — and real coder queries
may be closer to the lexical search's sweet spot (code fragments, title
words) than these phrases assume. WHO's ICD API/ECT remains
complementary and is not blocked by this.

## Phase 0 — telemetry on the existing coding search (next)

Capture how the search is actually used, then let the data decide.

- On `/api/v1/icd10/2019-2/coding-search/<va_sid>` and
  `/api/v1/icd11/coding-search/<va_sid>`: catalogue, normalized query
  (truncate ~128 chars), result count, latency ms, and a client-generated
  `search_id`.
- When a coder picks a code from the picker (coding screen save): the
  chosen code and its rank in that `search_id`'s result set.
- PII discipline: queries are clinical terms; capture the term only, no
  `va_sid`, no user identity beyond role; retention ~90 days with an
  admin CSV export. A coder can still paste a name — the 128-char
  truncate bounds it and the export is admin-gated.
- Open question for the owner: table namespace for operational telemetry
  (the repo convention covers `mas_*`/`map_*`/`auth_*` only) — propose
  `cod_search_telemetry` outside those namespaces, or reuse the audit-log
  pattern if the owner prefers.
- Signals it yields: share of queries that are code fragments vs title
  words vs narrative phrases; zero-result and no-selection rates;
  reformulation chains; rank of the eventually chosen code.

## Re-opening gate for browser ML

Only if telemetry shows narrative queries the lexical search fails to
serve:

1. Quality gate: hit@5 ≥ 70% and MRR ≥ 0.5 on an extended, telemetry-
   derived phrase set (the committed 30-phrase corpus is the floor).
2. Footprint gate: ≤ 100 MB lazy-loaded payload, loaded only when the
   coder opens the semantic mode; measured browser heap (Chrome
   `performance.memory`) well under the 2 GB ceiling; WASM single-thread.
3. CSP change (`'wasm-unsafe-eval'`) shipped as its own reviewed commit.
4. Freshness: vectors rebuilt offline on ICD catalogue edits, versioned
   like the public CSV cache (`public_data_version()` precedent), served
   cache-busted.

## Cheap lexical wins to consider from the telemetry (no ML)

- Trigram/fuzzy matching against title words for typos.
- A curated synonym layer: the 63 VA cause titles and their mapped ICD
  ranges (`resource/who_2022_va_cause_list_icd10_icd11.csv`) are a
  ready-made phrase→code starter dictionary.
