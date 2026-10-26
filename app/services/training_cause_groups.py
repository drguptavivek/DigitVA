"""WHO 2022 VA cause of a stored ICD code, for the training report.

The training report compares a trainee's ICD-11 final cause with the source
case's ICD-10 cause by the WHO 2022 VA cause both fall in (``VAs-01.04``...).
Two shipped tables give it, read once per process from ``resource/``:

- ICD-10: the WHO cause-list annex (``who_2022_va_cause_list_icd10_icd11.csv``).
  A single code beats a range that contains it; two different causes at the
  same specificity are ambiguous and the code is unmappable.
- ICD-11: the expanded one-cause-per-code table of the ``WHO_2022_VA_2026``
  scheme (``who_2022_va_2026_icd11_native_mappings.csv``). A code the table
  lacks falls back to its stem, one character shorter at a time.

Nothing here reads the database or a case; callers pass the stored value
(``"<CODE> <title>"``).
"""

from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path

from app.services.icd_coding_value import (
    classification_of_value,
    extract_icd_code,
    icd11_primary_stem_of,
)
from app.services.va_code_mapping_public_service import icd10_in_range, parse_icd10_ranges

_RESOURCE = Path(__file__).resolve().parents[2] / "resource"
ANNEX_PATH = _RESOURCE / "who_2022_va_cause_list_icd10_icd11.csv"
ICD11_PATH = _RESOURCE / "who_2022_va_2026_icd11_native_mappings.csv"


@lru_cache(maxsize=1)
def _annex() -> tuple[tuple, dict]:
    """``(icd10 entries, titles)``: entries are ``(is_single, start, end, va_code)``."""
    entries = []
    titles = {}
    with open(ANNEX_PATH, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            va_code = row["va_code"].strip()
            titles[va_code] = row["va_title"].strip()
            for _token, start, end in parse_icd10_ranges(row["icd10_codes"]):
                entries.append((start == end, start, end, va_code))
    return tuple(entries), titles


@lru_cache(maxsize=1)
def _icd11() -> dict:
    with open(ICD11_PATH, newline="", encoding="utf-8") as handle:
        return {row["icd_code"].upper(): row["source_category"] for row in csv.DictReader(handle)}


def va_cause_title(va_code: str | None) -> str | None:
    return _annex()[1].get(va_code) if va_code else None


def _icd10_cause(code: str) -> str | None:
    entries, _titles = _annex()
    hits = [(single, va) for single, start, end, va in entries if icd10_in_range(code, start, end)]
    if any(single for single, _va in hits):
        hits = [hit for hit in hits if hit[0]]
    causes = {va for _single, va in hits}
    return causes.pop() if len(causes) == 1 else None


def _icd11_cause(code: str) -> str | None:
    table = _icd11()
    while len(code) >= 4:
        if code in table:
            return table[code]
        code = code[:-1].rstrip(".")
    return None


def va_cause_of(value: str | None, provenance_item: dict | None = None) -> str | None:
    """The WHO 2022 VA cause code (``VAs-..``) of a stored coding value, or
    None when the value is empty, malformed, outside the annex or ambiguous.
    An ICD-11 value maps by its primary stem (``icd11_primary_stem_of``:
    ``provenance_item["primary_stem"]``, else the first stem)."""
    classification = classification_of_value(value)
    if classification is None:
        return None
    if classification == "icd10":
        return _icd10_cause(extract_icd_code(value, "icd10"))
    return _icd11_cause(icd11_primary_stem_of(value, provenance_item))
