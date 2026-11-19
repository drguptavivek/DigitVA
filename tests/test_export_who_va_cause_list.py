"""The committed Collect asset equals what scripts/export_who_va_cause_list.py builds from the CSV."""

import json

from scripts.export_who_va_cause_list import OUTPUT, build_list


def test_committed_who_va_cause_list_matches_csv():
    built = build_list()
    assert built["rows"]  # subject present before comparing
    assert json.loads(OUTPUT.read_text(encoding="utf-8")) == built, "run: python3 scripts/export_who_va_cause_list.py"
