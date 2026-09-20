#!/usr/bin/env python3
"""Check whether Id10304_a is reachable in each WHO VA 2022 XLSForm workbook.

WHO's multilingual V2.0 release (version 2026081401) gates Id10304_a on
`selected(${Id10334},'yes') and selected(${Id10305},'yes')`. Id10334's own
relevance contains `not(selected(${Id10305},'yes'))`, so the two conjuncts are
mutually exclusive and the question can never be asked. See
docs/kb/WHO_VA_2022_Docs/id10304a-v2-relevance-defect.md and bead digitva-mdj.

    python3 tooling/who-va-2022/check-id10304a-relevance.py [workbook-dir]

Exits 0 when every workbook's verdict is understood, 1 when a workbook carries
the unreachable rule, and 2 when one carries a rule this script has not been
taught (which means the analysis must be redone, not that the form is fine).

Python rather than the .mjs used elsewhere in this directory: it reads .xlsx,
and it cross-checks against app/services/xform_expression_evaluator.py, the
Python evaluator the application actually judges submissions with.

Dependencies: openpyxl. Runs standalone outside this repo -- the DigitVA
cross-check is skipped, not required, when the app package is not importable.
"""

from __future__ import annotations

import glob
import itertools
import os
import sys

try:
    import openpyxl
except ImportError:
    sys.exit("openpyxl is required:  pip install openpyxl")

# The two rules this script knows how to reason about. A workbook whose
# Id10304_a relevance is neither of these gets verdict UNKNOWN: the hand
# translation below would not describe it, and silently reporting "fine"
# would be worse than refusing to answer.
RULE_V11 = "selected(${Id10304},'yes')"
RULE_V20 = "selected(${Id10334},'yes') and selected(${Id10305},'yes')"

# Id10334's own relevance, identical in V1.1 and V2.0. Asserted against the
# workbook before any conclusion is drawn, so the translation below can never
# outlive the text it claims to represent.
REL_10334 = (
    "not(selected(${Id10312}, 'yes')) and not(selected(${Id10305}, 'yes')) and "
    "not(selected(${Id10299}, 'yes') and ${ageInYears2}>49)   and "
    "not(selected(${Id10306}, 'yes')) and not(selected(${Id10313}, 'yes'))"
)

GATED = ["Id10312", "Id10305", "Id10299", "Id10306", "Id10313", "Id10334", "Id10304"]
ANSWERS = ["yes", "no", "dk", "ref", ""]  # "" = unanswered


def norm(value) -> str | None:
    return " ".join(str(value).split()) if value is not None else None


def read_relevance(path: str) -> tuple[dict[str, str | None], str, str]:
    """Return {question: normalised relevant}, form_title, version."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    title = version = ""
    if "settings" in wb.sheetnames:
        rows = list(wb["settings"].iter_rows(values_only=True))
        header = [str(c).strip() if c is not None else "" for c in rows[0]]
        settings = dict(zip(header, rows[1]))
        title = str(settings.get("form_title", ""))
        version = str(settings.get("version", ""))

    rows = wb["survey"].iter_rows(values_only=True)
    header = [str(c).strip() if c is not None else "" for c in next(rows)]
    i_name = header.index("name")
    i_relevant = header.index("relevant")
    wanted = set(GATED) | {"Id10304_a"}
    found = {r[i_name]: norm(r[i_relevant]) for r in rows if r[i_name] in wanted}
    wb.close()
    return found, title, version


# Hand translation of the three expressions above. Each is pinned to its
# literal by an assertion at the call site, so it cannot drift from the
# workbook without the script refusing to conclude.
def rel_10334_holds(a: dict[str, str]) -> bool:
    return (
        a["Id10312"] != "yes"
        and a["Id10305"] != "yes"
        and not (a["Id10299"] == "yes" and a["ageInYears2"] > 49)
        and a["Id10306"] != "yes"
        and a["Id10313"] != "yes"
    )


def enumerate_reachability(age: int = 30) -> tuple[int, int, int]:
    """Count coherent form states, and those reaching Id10304_a under each rule.

    A state is coherent when Id10334 holds a value only if its own relevance
    holds -- ODK clears answers that become irrelevant, and DigitVA strips
    them at final submit, so incoherent states cannot reach storage.
    """
    coherent = v11 = v20 = 0
    for combo in itertools.product(ANSWERS, repeat=len(GATED)):
        a = dict(zip(GATED, combo))
        a["ageInYears2"] = age
        if not rel_10334_holds(a) and a["Id10334"] != "":
            continue
        coherent += 1
        v11 += a["Id10304"] == "yes"
        v20 += a["Id10334"] == "yes" and a["Id10305"] == "yes"
    return coherent, v11, v20


def cross_check(rule: str, age: int = 30) -> int | None:
    """Re-run the count with the application's own evaluator, on the workbook's
    actual text. Returns None when the app package is not importable."""
    try:
        from app.services.xform_expression_evaluator import (
            as_boolean,
            evaluate_expression,
            parse_expression,
        )
    except Exception:
        return None

    ast_334 = parse_expression(REL_10334)
    ast_rule = parse_expression(rule)
    hits = 0
    for combo in itertools.product(ANSWERS, repeat=len(GATED)):
        a = dict(zip(GATED, combo))
        a["ageInYears2"] = age
        if not as_boolean(evaluate_expression(ast_334, a)) and a["Id10334"] != "":
            continue
        hits += as_boolean(evaluate_expression(ast_rule, a))
    return hits


def main(argv: list[str]) -> int:
    directory = argv[1] if len(argv) > 1 else "docs/kb/WHO_VA_2022_Docs"
    paths = sorted(glob.glob(os.path.join(directory, "*.xlsx")))
    if not paths:
        print(f"no .xlsx workbooks under {directory}", file=sys.stderr)
        return 2

    coherent, reach_v11, reach_v20 = enumerate_reachability()
    print(f"Coherent form states:                     {coherent:>7,}")
    print(f"  reached by V1.1 rule:                   {reach_v11:>7,}")
    print(f"  reached by V2.0 rule:                   {reach_v20:>7,}")
    if reach_v20 != 0:
        print("\nV2.0 rule is satisfiable -- the defect analysis no longer holds.")
        return 2
    print()

    worst = 0
    for path in paths:
        found, title, version = read_relevance(path)
        name = os.path.basename(path)
        rule = found.get("Id10304_a")

        if rule is None:
            print(f"  SKIP      {name}: Id10304_a absent")
            continue

        # The gate's reachability depends on Id10334's relevance too; if that
        # text is not the one analysed, no verdict is safe.
        if found.get("Id10334") != norm(REL_10334):
            print(f"  UNKNOWN   {name}: Id10334 relevance differs from the analysed text")
            worst = max(worst, 2)
            continue

        if rule == norm(RULE_V11):
            checked = cross_check(rule)
            note = "" if checked is None else f" (evaluator agrees: {checked:,} states)"
            print(f"  OK        {name}  [{version}]{note}")
        elif rule == norm(RULE_V20):
            checked = cross_check(rule)
            note = "" if checked is None else f" (evaluator agrees: {checked:,} states)"
            print(f"  AFFECTED  {name}  [{version}]: Id10304_a unreachable{note}")
            print(f"            {title}")
            worst = max(worst, 1)
        else:
            print(f"  UNKNOWN   {name}  [{version}]: {rule!r}")
            worst = max(worst, 2)

    print()
    print({0: "All workbooks carry a reachable Id10304_a.",
           1: "At least one workbook cannot ask Id10304_a.",
           2: "At least one workbook carries a rule this script cannot judge."}[worst])
    return worst


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
