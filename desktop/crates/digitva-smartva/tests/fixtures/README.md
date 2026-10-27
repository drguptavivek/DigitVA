# digitva-smartva parity fixtures

- `corpus_inputs.json`: 8 synthetic WHO 2016 rows. Source is `vendor/smartva-analyze/test/example/input/WHO_2016_1_5_1_example.csv`
  (fictional upstream test data), with group prefixes stripped and name/instance-id columns dropped, sids `FIX-01..`.
  `FIX-REJ-01` is a copy with all age fields removed so SmartVA rejects it ("does not have valid age data").
- `corpus_expected.json`: reference output of the Python SmartVA-Analyze (cause1-3, likelihood1-3, rejected SIDs);
  records the SmartVA version and vendor git revision it was made with.

Regenerate (needs `uv`; no other setup): `python3 desktop/crates/digitva-smartva/tests/fixtures/regenerate_expected.py`

Test: `cd desktop && cargo test -p digitva-smartva --test corpus_parity`. Causes and likelihood labels must match exactly
(categorical; no numeric tolerance). Missing fixtures fail the test. Never put real submissions in this directory.
