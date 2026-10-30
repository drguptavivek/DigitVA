# api-sweep

The reads that the Collect Plus coding screen makes for every ICD-11 code of DigitVA's datasets, plus options the screen never sends
(`flexiblemode`, `convertToTerminalCodes`, `include`) as a superset; within those codes it is capped (see below and the kit README), made by
`scripts/icd11-parity/make_sweep.py` from the WHO container on 2026-10-31. Release 2026-01; container `whoicd/icd-api@sha256:1b77eb6dc43e0c65a12e9e9340ad178493c93488e728d0d936507cc57ada1b7c`.

`calls.jsonl.gz`: 8,909 requests, one `{"op", "args"}` JSON line each, sorted, gzip -9n. Unpacked, its sha256 is

    ac1528317bd286d626934d0d4632ebdde9c75def40d959968906867ccf5d7a6c

| op | requests |
| --- | --- |
| `codeinfo` | 2,465 |
| `entity` | 4,840 |
| `foundation_entity` | 662 |
| `search` | 942 |

Every id in it (entity ids, URIs, codes of composed expressions) was discovered from the container on 2026-10-31; none is guessed, as in
`calls.json`. A 404 answer is a request like any other: the phone engine must refuse it too. `build_inputs.py` turns the file into the
section `sweep` (`sweep/<line>-<op>`); the run is `eval.sh full`.

## Code universe

401 distinct codes: the 39 of `conditions.json`, every `Code` of the certificates of `hash-synthetic-10k` and
`clinical-variants-10k` (10,000 + 10 edge cases) and of the golden corpora (`scripts/icd11-golden/corpus`: certificate codes,
postcoordination stems, the parts of their built expressions). Codes the container does not know (the edge cases') still get their
code-info requests.

## What is asked for each code

The picker's routes, with the caps of `mobile/digitva-collect/src/workspace/dorisGuidance.ts` (12 axes, 12 roots, options, siblings,
children, related, exclusions; 12 ancestors) and `dorisTerminology.ts` (search limit 20):

- code info: plain, `flexiblemode`, `convertToTerminalCodes`
- entity of the stem (a residual stem is read as its residual): plain, `include=ancestor`, `include=diagnosticCriteria`; the residual children
  `unspecified` and `other` of the stem's category; `foundation_entity` of its `source`, plain and `include=ancestor`
- hierarchy: the entity of each ancestor, sibling and child, and the foundation entity of each related maternal and perinatal link
- related: the coded entity of each related foundation entity and its children
- details: the entity of each exclusion target
- postcoordination: the entity of every axis root; postcoordination-options: the children of each axis's first expandable root
- composed expressions: `stem&X...` for extension values and `stem/code` for any other, the first value of each axis, a second value where
  the axis allows several, one expression with the first value of every axis, and code info of each first value
- search (`q="<text>%"`, the four flags, `limit` 20): the stem's title when 2 to 80 characters, and its first 4 letters; for each of the first
  3 axes, the first coded root's title and its first 3 letters with `subtreesFilter` set to the axis's roots

Not covered: `include` on related entities, `descendant` (the bridge refuses it, `calls.json` tests that), a stem reached by a code the
datasets do not contain, and search texts a coder might type (`queries.json`, the golden search corpus and the titles above stand for them).

## Regenerate

    python3 scripts/icd11-parity/make_sweep.py            # writes calls.jsonl.gz and this README
    python3 scripts/icd11-parity/make_sweep.py --check    # exits 1 when the file would change

Needs the WHO container (`whoicd/icd-api:2.6.0`) on 127.0.0.1:8382. A different container image or release changes the ids and the replies;
record the new digest here.
