---
title: XLSForm Expression Evaluator Policy
doc_type: policy
status: active
owner: engineering
last_updated: 2026-09-20
---

# XLSForm Expression Evaluator Policy

Decided by the owner 2026-09-20 (beads digitva-cal.1): Python must be able to
parse and evaluate a WHO VA 2022 instrument's `relevant`/`constraint`/
`calculation` expressions itself, rather than trusting a browser-computed
boolean. This baseline is the evaluator only — it changes no intake
behaviour. Server-side re-derivation of submission validity is a separate,
later change (beads digitva-cal.2).

## Two evaluators now exist

- `vendor/who-va-2022/src/engine/expression.ts` is the original, and remains
  the single source of truth for the client: it is what actually gates the
  browser form.
- `app/services/xform_expression_evaluator.py` is a Python port of the same
  grammar and semantics (`tokenize` / `parseExpression` /
  `evaluateExpression`, and the coercion helpers `isEmpty`, `asBoolean`,
  `asNumber`, `equal`, `dateNumber`), for server-side code that has no
  browser to ask.

Two independent implementations of the same rules is a real risk, not a
theoretical one: commit `78757d4` fixed a bug where the TypeScript
tokenizer's own backslash handling silently corrupted `\d` inside a `regex()`
pattern. A port done by inspection, with no way to notice the same class of
mistake, would reproduce that risk in Python instead of removing it.

## What keeps the two honest: the conformance corpus

`tooling/who-va-2022/build-expression-corpus.mjs` extracts every unique
expression the composed instrument (WHO base plus every DigitVA extension)
carries in `relevant`, `constraint` or `calculation`, evaluates each one in
the real TypeScript engine against a set of designed answer fixtures, and
writes the results — the golden output — to the committed
`vendor/who-va-2022/src/generated/expression-conformance-corpus.json`.

`tests/services/test_xform_expression_evaluator.py` reads that file and
requires the Python evaluator to reproduce every case exactly, including the
cases that evaluate to `NaN` (JSON cannot represent `NaN`; the corpus flags
these explicitly with a `resultIsNaN` field rather than losing them to
JSON's `null`) and the cases that read as `true` (a corpus whose every case
happened to be `false` would not actually prove the port evaluates a
condition, only that it never crashes).

Regenerate the corpus after any change to
`vendor/who-va-2022/src/engine/expression.ts`, the composed instrument
(`vendor/who-va-2022/src/instrument.ts` / `digitva-extension.ts`), or the
fixture design itself:

```bash
cd tooling/who-va-2022 && npm run build:expression-corpus
```

This is deterministic — no timestamp, no build id, `now` and its timezone
fixed rather than read from the wall clock — so running it again on an
unmodified tree reproduces the committed file byte for byte
(`tooling/who-va-2022/tests/build-expression-corpus.test.mjs` pins this, the
same way `build-layer-reference.test.mjs` pins it for the translation
reference artifact).

## Evaluation is locale-independent by construction

Worth stating because it bounds the whole problem: **a translation can never
change how an expression evaluates.** Verified 2026-09-20 against the live
reference -- the only translatable `(item_kind, field)` pairs that exist are
`question.label` (556), `question.guidance_hint` (340), `question.hint` (215)
and `choice.label` (324). A choice *value* is not a translation target in any
field or any locale, and an import can never create an item, so
`selected(${sa01}, '1')` compares the same `'1'` in all thirteen languages.
Value labels change with language; coded values do not.

The consequence for the traps below: the Unicode-digit divergence cannot reach
a coded response, because coded values are ASCII literals fixed in the
instrument. It can only reach a field the interviewer *types* -- the seven
`dataType: "string"` duration fields `sa13`-`sa19`, whose constraint is
`regex(., '^(?!0{1,3}$)\d{1,3}$')` -- where a Devanagari or Bengali IME can
produce native digits. That is a narrow surface, and the reason to guard it is
not mainly that scenario: it is that a server which accepts what the client
refuses is a worse failure than either engine being wrong alone. The corpus
enforces agreement; `re.ASCII` is what agreement requires here.

## Divergence traps, and how each is handled

**`\d` is not the same in both languages.** Python's `re` matches Unicode
decimal digits with `\d` by default; JavaScript's `RegExp` without a `u` flag
does not. The composed instrument's social-autopsy layer carries
`regex(.,'^(?!0{1,3}$)\d{1,3}$')` on `sa13`–`sa19`, so a Devanagari-digit
answer would pass this check server-side and fail it in the browser. Fixed
by compiling every `regex()` pattern with `re.ASCII` in
`_evaluate_call`. Pinned by a corpus case built specifically for this pattern
(a `candidate_N` scenario using the Devanagari string `१२३`) and by
`test_devanagari_digit_reads_false_under_ascii_regex`, which fails on its own
— independent of the general corpus comparison — if `re.ASCII` is ever
dropped.

**A backslash is an ordinary character.** XPath 1.0 string literals have no
escape mechanism; the only quote-escaping convention is the doubled quote
(`''`/`""`). This is what commit `78757d4` fixed in the TypeScript tokenizer
after it was silently corrupting `\d` (reading a backslash as introducing an
escape sequence consumed the closing quote of a literal ending in a
backslash). `_tokenize` in the Python module ports that same string-literal
loop, with the same comment explaining why a backslash gets no special
handling.

**`today()` and date arithmetic.** `formatLocalDate` in the TypeScript engine
reads a `Date`'s *local* getters — whatever the browser's device considers
"local". The Python port has no equivalent ambient notion of local time:
`evaluate_expression`'s `options.now` must be an explicit, timezone-aware
`datetime`, and `today()` formats it directly. The corpus fixes both an
explicit instant (`now: "2024-06-15T09:00:00"`) and the zone it is read in
(`timezone: "Asia/Kolkata"`, this application's primary deployment
timezone) — the generator pins `process.env.TZ` before creating any `Date`,
so regenerating the corpus is reproducible regardless of the host machine's
own timezone. `date_number()` (the numeric form of an ISO date string used
in comparisons like `. <= today()`) is timezone-independent for the
date-only strings this instrument actually produces: it is parsed as UTC
midnight in both engines, so only the "what day is today" step is
timezone-sensitive, not the arithmetic once a date string exists.

**Coercion.** `is_empty`, `as_boolean`, `as_number`, `equal` and
`date_number` are ported literally from `expression.ts`, not rewritten with
Python truthiness — which would diverge on `0`, `""`, `"0"` and `None` (e.g.
`asBoolean(0)` is `false` but `asBoolean("0")` is also `false`, while
`equal(0, "")` is `false` because `isEmpty("")` is `true` but `isEmpty(0)` is
not).

## What did not port faithfully, and why it does not matter here

`asNumber`'s fallback to JavaScript's `Number(string)` coercion is ported as
a regex-validated subset (decimal and scientific-notation literals, plus
`Infinity`/`-Infinity`) rather than the full ECMAScript `Number()` grammar,
which also accepts hex/octal/binary literal forms (`"0x1A"` etc). No answer
value or expression literal in the composed instrument produces those forms;
porting them would be speculative coverage the corpus could not even
exercise, since nothing generates that fixture case from real instrument
content.

## Regenerating the corpus

```bash
cd tooling/who-va-2022
npm run build:expression-corpus   # writes vendor/who-va-2022/src/generated/expression-conformance-corpus.json
npm run test:web                  # pins byte-for-byte reproducibility and the fixture-design invariants
```

Then, from the repository root, re-run the Python conformance test:

```bash
docker compose exec -T -e TEST_DATABASE_URL=postgresql://minerva:minerva@minerva_db_service:5432/<your test db> \
  minerva_app_service uv run --no-sync python -m pytest tests/services/test_xform_expression_evaluator.py -q -p no:cacheprovider
```
