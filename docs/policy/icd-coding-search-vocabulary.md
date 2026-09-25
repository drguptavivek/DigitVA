---
title: ICD Coding Search Vocabulary
doc_type: policy
status: draft
owner: engineering
last_updated: 2026-09-25
---

# ICD coding search vocabulary (`digitva-zpe.1`)

Baseline for the first search surface of the `digitva-zpe` decision
(`docs/planning/icd-semantic-search.md`): the COD coding-search endpoints
must find codes for **clinician shorthand and diagnosis synonyms** — `MI`,
`CVA`, `CCF`, `Kochs`, `RTA`, `madhumeh` — which today score nothing because
they share no substring with any ICD title (measured: a 33-query
death-certificate batch fails only on this class). Layperson narrative is the
second surface and stays out of scope here.

## Source of truth

- One table, `mas_icd_search_terms`, is the central, updatable vocabulary for
  every ICD search surface (ICD-10 and ICD-11 coding search now; admin
  browsers may adopt it later). A row is one **term-code link**, flattened on
  purpose (owner, 2026-09-25 — one table with a source vocabulary beats a
  terms master plus mapping): `term` (display), `term_normalized` (lookup
  key: lowercased, punctuation stripped, whitespace collapsed — indexed,
  NOT unique), `icd_classification` (`icd10` | `icd11`), `icd_code`,
  `source` (`seed_used_cod` | `who_inclusion` | `admin`, later `telemetry`),
  `note`, `is_active`, timestamps. Multiple rows per term are the mechanism
  for multi-code targets: `TB` links to `A15` and `A16`, `sepsis`-family
  terms link to both catalogues.
- The seed (`resource/icd_search_vocabulary_seed.csv`, one row per link) is
  authored from the ICD-10 codes actually used as final CODs in this system
  (dev: 7,879 final CODs; ~50 codes cover 73%) plus WHO's own ICD-10
  inclusion terms mined from `icd102019en.xml` (ClaML). ICD-11 counterparts
  are picked by grounded title lookup in the frozen 2026-01 MMS export —
  the WHO 11To10 crosswalk proved unreliable for this (it picked BD12
  "High output syndromes" for I50) and is not used. Codes with no honest
  counterpart (V89, W19, J22) ship ICD-10-only. ICD-11 inclusion terms
  were harvested one-time from the self-hosted `whoicd/icd-api` image
  (2026-01 release): the entities carry titles and definitions but **no
  inclusion/synonym arrays**, so the seed gained no ICD-11 rows; the
  definitions fetched in that pass are frozen in
  `resource/icd11_definitions_2026_01.json` for the future narrative
  (semantic) surface — they are not imported by the application. The full
  in-scope catalogue was harvested (18,505 codes; 13,131 entities —
  residual `.Z`/`.Y` codes have no entity — and 6,637 with WHO
  definition text; definitions sit at stem level, so leaves inherit).
  Decision (owner, 2026-09-25): freeze the superset, embed the subset —
  any Phase-B semantic build embeds the 63 cause documents plus at most
  the top few hundred used codes' definitions, never the full corpus
  (retrieval quality dies in big haystacks; the payload stays small).
  The seeding migration inserts only when the table is empty, so admin
  edits are never overwritten by upgrades.
- Terms that the current lexical search already finds (e.g. `stroke`,
  `pneumonia`) are deliberately NOT seeded; the vocabulary holds only what
  lexical matching cannot reach.

## Matching semantics

- Results carry a `"tier"` field: `"focused"` (vocabulary hits, exact-code
  matches, title-prefix matches) and `"expanded"` (title substrings, token
  matches; later semantic cause suggestions). The picker renders the
  two-stage UI from it — focused group first, expanded behind a "show
  more" control — but every path still terminates at an ICD code
  selection.
- Spelling and hyphenation fold (digitva-zpe.3): a query matches across
  UK/US spellings and hyphen placement. Mechanism: the `localspelling`
  package (MIT, Fast Data Science) word map plus a 22-entry medical
  supplement (measured: the library alone covers 34/54 of the medical
  UK/US taxonomy) generate the query's spelling variants — the original
  always first, never removed — and each variant is also matched with
  hyphens and spaces translated out on both sides, because ICD titles are
  officially hyphenated (measured: 1,033/12,475 ICD-10 2019 and
  2,155/35,664 ICD-11 MMS 2026-01 titles contain a hyphen) while
  clinicians type unhyphenated or spaced forms. `term_normalized` folds to
  the US spelling as the one lookup key; stored keys are never rewritten
  by a migration. The fold adds no synonyms of its own — the vocabulary
  stays the only curated term list.
- Exact match on `term_normalized` only — no prefix or fuzzy matching
  (`MI` must not hijack `miliary`). Multi-code families stay reachable the
  way they are today (`tuberculosis` finds the A15/A16 family lexically).
- A vocabulary hit expands to its target code through the **same filters the
  endpoint already applies** (active/selectable policy, age and sex when a
  `va_sid` is in play). A shorthand whose target is filtered out for that
  death returns nothing extra — the vocabulary never bypasses coding policy.
- **Spelling variants fold (owner, 2026-09-25 — "US/UK matters when it
  affects search")**: `normalize_term` and the query normalization apply a
  curated UK↔US fold (diarrhoea/diarrhea, oesophag/esophag, haem/hem,
  anaemi/anemi, aetio/etio, paedi/pedi, oedem/edem, foet/fet, coeli/celi,
  anaesth/anesth, orthopaed/orthoped, tumour/tumor — no generic letter
  rules), and the lexical endpoints OR the query's spelling variants into
  their title matching. A UK-spelled query therefore finds US-spelled
  titles and vice versa, and one vocabulary row covers both spellings.
  Coverage is validated against the full linguistic taxonomy (owner,
  2026-09-25): `localspelling` covers 34 of 54 reference pairs (ae/e,
  oe/e, -our/-or, -re/-er, -logue/-log, -lyse/-lyze, misc); the 22-entry
  supplement carries the rest (derivatives like oesophageal/anaemias,
  the -aemia compounds, disc/disk, the leuc- family). "Aero-" words and
  "humoral" are identical in both variants and asserted unchanged in the
  safety tests.
- **Hyphenation trap (owner rule, 2026-09-25)**: official titles are
  hyphenated (measured: 1,033/12,475 ICD-10 and 2,155/35,664 ICD-11
  titles — Cat-scratch, Rat-bite, Non-ulcerative, Gastro-oesophageal)
  while clinicians type unhyphenated or spaced forms; matching is
  hyphen-insensitive on both sides via a query-time
  `translate(text, '-', '')` comparison arm.
- **The database is never modified for search.** All normalization —
  dialect variants, hyphen forms, vocabulary keys — happens on the query
  side as an OR-ed set matched at query time. Catalogue rows, titles and
  vocabulary rows stay exactly as WHO and the admins wrote them
  (owner, 2026-09-25: normalize the search term to both dialects and OR
  against the records; never rewrite the data).
- Vocabulary matches rank first in the result list and are marked
  (`"vocabulary": true`, display `term — target title`) so the coder can see
  why an unexpected code appeared.

## Administration

- Admin panel (admin role): list with search, create, edit term/targets/
  note, deactivate, CSV export. No delete — deactivation keeps audit history.
- Changes take effect on the next search (process-level cache keyed on the
  table's row count and latest `updated_at`, cleared on write in the writing
  worker like the other mapping caches).

## Data protection

- Terms are clinical shorthand, not patient data. No PII is stored in the
  table; admin notes are reviewed text. Phase-0 telemetry (separate work)
  will propose new terms from real queries with the same no-PII discipline.
