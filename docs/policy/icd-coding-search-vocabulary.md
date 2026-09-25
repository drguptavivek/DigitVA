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
  `note`, `sort_order` (smallint, default 100, lower first), `is_active`,
  timestamps. Multiple rows per term are the mechanism for multi-code
  targets: `head injury` fans out to five external-cause codes, `sepsis`-
  family terms link to both catalogues. `sort_order` breaks ties among a
  term's several targets so the reviewed order lists first regardless of
  code string order (`digitva-3t2` — TB's target was narrowed to ICD-10
  A16 and ICD-11 1B10.Z, since a verbal autopsy cannot know bacteriological
  confirmation and A15/A16/1B10.x share one VA bucket; the bare
  `tuberculosis` term now promotes that pair; `head injury`
  remains the multi-target example: V89.2, W19, Y09, W20, X59 in that
  order).
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
  matches, and any query that starts the title or the start of ANY word
  inside it — a word boundary is the string's start or the position right
  after a non-alphanumeric character, so "myoc" reaches "Acute
  **myoc**ardial infarction" but "art" inside "he**art**" stays mid-word)
  and `"expanded"` (title substrings that are not a word start; later
  semantic cause suggestions). The picker renders two columns from it —
  "Focused matches" left, "Term matches" right (one column on a narrow
  dropdown); nothing is hidden behind a toggle — and every path still
  terminates at an ICD code selection. `result_tier` and `core_title` (see
  below) are shared helpers in `icd_search_vocabulary_service.py`, used by
  both `icd10_2019_2_service.py` and `icd11_mms_service.py` — no longer
  duplicated per catalogue. After SQL fetches and ranks the capped result
  list, the service does one further Python pass — a stable sort moving
  focused-tier rows ahead of expanded ones — so the tier computed with
  word-boundary and qualifier-stripped matching also governs display
  order; this never changes WHICH rows SQL fetched or the catalogue's own
  policy filters.
- **Qualifier stripping (`core_title`, `digitva-wqc`)**: WHO titles carry
  boilerplate that pushes the actual diagnosis word away from the title's
  start — "other and unspecified", "other", "not otherwise specified",
  "nos", "not elsewhere classified", "nec", "of unspecified origin",
  "unspecified origin", "unspecified", "not confirmed bacteriologically or
  histologically", "not confirmed", "without mention of bacteriological or
  histological confirmation", "in diseases classified elsewhere",
  "classified elsewhere". `core_title` removes these case-insensitively as
  whole words/phrases (longest phrase first, so "other and unspecified"
  goes as one unit rather than leaving a stray "and"), then tidies
  whitespace and comma debris; it falls back to the tidied original when
  stripping empties the text (a query or title that IS "other" stays
  searchable). Used for tier classification (title and query, alongside
  the raw forms), the in-Python re-rank above, and fuzzy similarity
  (`fuzzy_vocabulary_matches`) — never to change which rows the SQL WHERE
  fetches. Example: "respiratory tuberculosis" reaches both A15
  ("Respiratory tuberculosis, bacteriologically and histologically
  confirmed") and A16 ("...not confirmed bacteriologically or
  histologically") as focused, and "gastroenteritis" reaches A09 ("Other
  gastroenteritis and colitis of infectious and unspecified origin") as
  focused even though the qualifier words sit ahead of it.
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
- Exact match on `term_normalized` first (any spelling/hyphen variant).
  For a normalized query of 3+ characters (`PREFIX_MIN_QUERY_LEN`,
  `digitva-wqc`), vocabulary lookup ALSO matches keys the query is a
  PREFIX of — "dysen" reaches the stored key "dysentery" — so a partially
  typed clinician term still surfaces its target before the coder finishes
  typing. A query under 3 characters stays exact-only (`MI` must not
  prefix-match into an unrelated longer key, and cannot become a prefix
  hit of its own). Exact matches always rank before prefix matches;
  within each group, a multi-code term orders by `sort_order` then
  `icd_code`. Prefix hits are capped at 10 distinct codes so one short
  prefix cannot flood the picker. This is vocabulary-only — the lexical
  catalogue search is unaffected and multi-code families it already finds
  stay reachable the same way (`tuberculosis` finds the A15/A16 family
  lexically).
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

## Help-page search demo (`digitva-zm1`)

`/help/icd-codes/search-demo` and `GET /api/v1/coding-search-demo/search`
(`classification`, `q`, `age_group`, `sex`) let a coder try this search
outside a real death: the endpoint calls the same search functions the coding
screen uses (`search_icd10_2019_2_coding_choices_for_policy`,
`search_icd11_mms`), filtered by an explicit age group and sex instead of a
submission's own. Demo searches are never written to `cod_search_telemetry`
and never receive an `X-Search-Id`.
