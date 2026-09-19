"""Keep the policy doc's WHO_2022_VA_2026 override table honest.

Recomputes, from the checked-in artifacts only, the carried-forward manual
bucket overrides whose bucket differs from the one the WHO 2026 annex would
give the code, and asserts the table in
``docs/policy/who-2022-icd10-coding-allowability.md`` lists exactly those codes.

No database and no Flask app: this reads three files and compares sets, so it
runs under ``python -m unittest`` as well as pytest.
"""
import csv
import re
import unittest
from pathlib import Path

import openpyxl

REPO_ROOT = Path(__file__).resolve().parents[1]
POLICY_DOC = REPO_ROOT / "docs/policy/who-2022-icd10-coding-allowability.md"
ANNEX_CSV = (
    REPO_ROOT
    / "docs/icd-causegrp-mappings/ICD-to-VA-Buckets"
    / "who_2022_va_cause_list_icd10_icd11.csv"
)
DERIVED_WORKBOOK = (
    REPO_ROOT
    / "docs/icd-causegrp-mappings/migration-artifacts"
    / "who-2022-va-icd-cod-2026-revision"
    / "WHO_2022_VA_Bucket_Mapping_document_derived_2026_revision.xlsx"
)

OVERRIDE_SECTION_HEADING = "## Carried-forward overrides in WHO_2022_VA_2026"
CARRIED_FORWARD_NOTE_PREFIX = "Carried forward from an existing manual override"

_CODE_RE = re.compile(r"([A-Z])(\d{2})(?:\.(\d))?$")

# Token specificity, highest wins: an exact dotted code beats an exact
# three-character code, and both beat any range they fall inside
# ("Overlap Rules" in the policy doc).
_SPECIFICITY_RANGE = 1
_SPECIFICITY_EXACT_THREE_CHARACTER = 2
_SPECIFICITY_EXACT_DOTTED = 3


def _sort_key(code):
    """Return an orderable (letter, number, decimal) key, or None if not ICD-10.

    Three-character codes sort below their own dotted children, so a
    three-character range endpoint can be widened in either direction.
    """
    match = _CODE_RE.match(code)
    if match is None:
        return None
    letter, number, decimal = match.groups()
    return (letter, int(number), int(decimal) if decimal is not None else -1)


def _expand_annex_token(token, universe):
    """Yield the codes in ``universe`` that one annex ICD-10 expression selects.

    Granularity is preserved as "Allowability Rules" in the policy doc
    describes it: a three-character range selects only three-character rows, a
    dotted range only dotted rows.  A mixed range (one endpoint of each kind,
    e.g. ``I27-I46.0``) selects rows of either kind inside the interval,
    because neither endpoint alone fixes the granularity.
    """
    if "-" not in token:
        if token in universe:
            yield token
        return

    start, end = token.split("-", 1)
    start_key, end_key = _sort_key(start), _sort_key(end)
    if start_key is None or end_key is None:
        return

    start_dotted, end_dotted = "." in start, "." in end
    low = start_key if start_dotted else (start_key[0], start_key[1], -1)
    high = end_key if end_dotted else (end_key[0], end_key[1], 99)

    for code in universe:
        code_key = _sort_key(code)
        if code_key is None:
            continue
        code_dotted = "." in code
        if start_dotted and end_dotted and not code_dotted:
            continue
        if not start_dotted and not end_dotted and code_dotted:
            continue
        if low <= code_key <= high:
            yield code


def _annex_buckets(universe):
    """Map each code in ``universe`` to the VA cause the annex CSV gives it."""
    best = {}
    with ANNEX_CSV.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            va_code = row["va_code"]
            # ';' separates expressions; ',' and stray whitespace appear too.
            raw = (row["icd10_codes"] or "").replace(";", " ").replace(",", " ")
            for token in raw.split():
                if "." in token or "-" in token:
                    specificity = (
                        _SPECIFICITY_RANGE
                        if "-" in token
                        else _SPECIFICITY_EXACT_DOTTED
                    )
                else:
                    specificity = _SPECIFICITY_EXACT_THREE_CHARACTER
                for code in _expand_annex_token(token, universe):
                    if code not in best or best[code][0] < specificity:
                        best[code] = (specificity, va_code)
    return {code: value[1] for code, value in best.items()}


def _workbook_rows():
    """Read the derived 2026 workbook's ICD_Mapped sheet keyed by ICD-10 code."""
    workbook = openpyxl.load_workbook(DERIVED_WORKBOOK, read_only=True)
    try:
        rows = list(workbook["ICD_Mapped"].iter_rows(values_only=True))
    finally:
        workbook.close()
    columns = {header: index for index, header in enumerate(rows[0])}
    mapped = {}
    for row in rows[1:]:
        code = row[columns["icd_code"]]
        if not code:
            continue
        mapped[code] = {
            "va_code": row[columns["WHO_2022_VA_code"]],
            "note": row[columns["WHO_2022_VA_note"]] or "",
        }
    return mapped


def recompute_override_codes():
    """Return the carried-forward override codes that depart from the annex."""
    rows = _workbook_rows()
    annex = _annex_buckets(set(rows))
    return {
        code
        for code, row in rows.items()
        if row["note"].startswith(CARRIED_FORWARD_NOTE_PREFIX)
        and annex.get(code) != row["va_code"]
    }


def documented_override_codes():
    """Return the ICD-10 codes listed in the policy doc's override table."""
    text = POLICY_DOC.read_text(encoding="utf-8")
    start = text.index(OVERRIDE_SECTION_HEADING)
    codes = set()
    for line in text[start:].splitlines()[1:]:
        if line.startswith("## "):
            break
        if not line.startswith("| `"):
            continue
        codes.add(line.split("|")[1].strip().strip("`"))
    return codes


class Icd10TwentyTwentySixOverrideTableTest(unittest.TestCase):
    """The policy table and the artifacts must name the same override codes."""

    def test_override_table_matches_the_artifacts(self):
        documented = documented_override_codes()
        self.assertTrue(
            documented,
            f"{POLICY_DOC} has no rows under '{OVERRIDE_SECTION_HEADING}'",
        )

        recomputed = recompute_override_codes()
        self.assertTrue(
            recomputed,
            "no carried-forward override departs from the annex; the "
            "recomputation is broken or the artifacts changed",
        )

        self.assertEqual(
            set(),
            recomputed - documented,
            "override codes missing from the policy doc table",
        )
        self.assertEqual(
            set(),
            documented - recomputed,
            "policy doc table lists codes that are not overrides",
        )


if __name__ == "__main__":
    unittest.main()
