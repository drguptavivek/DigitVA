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

`tooling/icd-semantic-search/quality_check.py` scores 30 VA-style clinical
phrases whose expected codes are grounded in the catalogues (exact codes and
title substrings; the script fails on an expectation that matches nothing).
It now runs a ladder of configurations, each isolating one candidate
improvement:

Run: `uv run --isolated --no-project --with
transformers,onnxruntime,numpy,huggingface_hub python
tooling/icd-semantic-search/quality_check.py --mode <mode> [--context]
[--cause-doc title|full] [--model ...] [--query-prefix ...]`.

Corpora: ICD-10 12,475 category rows, ICD-11 18,505 in-scope categories
(chapter X excluded), and — for the causes mode — the 63 VA causes from
`resource/who_2022_va_cause_list_icd10_icd11.csv` with their WHO
definitions from `resource/va_cause_definitions_who_2022.json`.

| configuration | ICD-10 top-5 | top-10 | MRR | ICD-11 top-5 | top-10 | MRR |
| --- | --- | --- | --- | --- | --- | --- |
| lexical substring (today's endpoints) | 0/30 | 0/30 | 0.00 | 0/27 | 0/27 | 0.00 |
| lexical token overlap | 0/30 | 0/30 | 0.00 | 1/27 | 2/27 | 0.01 |
| dense MiniLM-L6 over 31k titles | 9/30 | 11/30 | 0.22 | 4/27 | 4/27 | 0.12 |
| dense bge-small + prefix | 9/30 | 15/30 | 0.24 | 5/27 | 7/27 | 0.21 |
| dense bge-base (3x params) + prefix | 10/30 | 13/30 | 0.24 | 6/27 | 7/27 | 0.16 |
| dense bge-small + block/chapter context | 8/30 | 13/30 | 0.28 | 5/27 | 7/27 | 0.16 |
| hybrid RRF (dense + tokens) bge-small | 4/30 | 5/30 | 0.14 | 4/27 | 4/27 | 0.12 |
| **63 VA causes + definitions, MiniLM-L6** | **top-3 21/30** | **22/30** | **0.59** | **19/27** | **21/27** | **0.60** |
| **63 VA causes + definitions, bge-small** | **top-3 20/30** | **22/30** | **0.57** | **18/27** | **21/27** | **0.61** |
| 63 VA causes, title only, bge-small | 14/30 | 20/30 | 0.46 | 12/27 | 18/27 | 0.45 |

For the causes rows the columns are top-3 and top-5 of the 63 causes
(the coder picks a cause; its mapped codes follow). Findings:

- **Ranking 63 causes instead of 31k titles roughly triples quality**
  (MRR 0.22 -> 0.59). The WHO definitions carry most of it (title-only
  drops to 0.45-0.46). The smallest model (MiniLM-L6, 23 MB int8) is as
  good as bge-small; the document payload is 63 x 384 fp32 vectors
  (~0.1 MB).
- Direct dense search over titles is capped near hit@10 50%: bigger
  encoders do not help (bge-base is flat-to-worse than bge-small),
  hierarchy-context enrichment is a wash, and naive RRF fusion with the
  token ranker actively hurts (weak-ranker noise displaces good dense
  neighbours).
- Narrative queries score exactly 0/30 on today's whole-phrase substring
  search — the problem this bead exists for is real.
- Residual gaps in causes mode: rabies ranks ~52 of 63 (thin definition
  competition); bronchiectasis/alcohol-liver/peritonitis land top-15..41;
  and the coverage table itself is incomplete — VAs-12.01's ICD-10 cell
  is empty because footnote f holds the ranges
  (`resource/who_2022_va_cause_list_footnotes.csv`), and the ICD-11
  preterm codes are not covered by any cause token list. Those two
  "misses" are coverage artifacts, not retrieval failures.

Corpus-wide embedding takes ~30 s on a desktop CPU for either model, so
server-side batch embedding is cheap if ever wanted; per-query quality is
the bottleneck, not compute.

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

**Direct browser-ML search over ICD titles stays parked**: ~35-60 MB
payload per client for hit@10 ~50% fails the no-client-burden bar, and
every cheap generic fix measured (bigger model, context enrichment, RRF
fusion) does not move it.

**The promising shape is the two-stage reduction**: rank the 63 VA causes
(embedded with their WHO definitions) client-side, then let the coder pick
the code from that cause's mapped codes — which the existing lexical
search can serve within the reduced list. Measured MRR 0.57-0.61 with a
23 MB lazy-loaded model and a ~0.1 MB vector file. This is the candidate
to prototype **after** phase-0 telemetry confirms narrative queries exist
and in what volume; WHO's ICD API/ECT remains complementary.

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

## Re-opening gate for browser ML (updated for the causes shape)

Only if telemetry shows narrative queries the lexical search fails to
serve:

1. Quality gate: on an extended, telemetry-derived phrase set, top-3
   cause accuracy ≥ 70% and MRR ≥ 0.5 (the committed 30-phrase corpus
   already meets MRR ≥ 0.5 at top-3 20-21/30 — extend it with real
   queries and re-measure).
2. Coverage gate: the cause->code expansion uses the same tables the
   reports use (annex + footnotes, including footnote f's transport
   ranges), not the raw cause-list cells — two of today's misses are
   coverage-table artifacts.
3. Footprint gate: ≤ 100 MB lazy-loaded payload (causes shape:
   ~23 MB), loaded only when the coder opens the semantic mode; measured
   browser heap (Chrome `performance.memory`) well under the 2 GB
   ceiling; WASM single-thread.
4. CSP change (`'wasm-unsafe-eval'`) shipped as its own reviewed commit.
5. Freshness: cause vectors rebuilt offline when the cause list,
   definitions or mapping tables change, versioned like the public CSV
   cache (`public_data_version()` precedent), served cache-busted.

## Cheap wins to consider from the telemetry (no ML)

- Trigram/fuzzy matching against title words for typos.
- The 63-cause dictionary as a *lexical* synonym layer: match query words
   against the cause definitions' terms, then offer the cause's codes. The
  definitions are already the measured difference between 0.46 and 0.59.
