#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["openpyxl"]
# ///
"""Check whether Id10304_a can ever be asked in a WHO VA 2022 XLSForm.

Background
----------
The 2022 WHO Verbal Autopsy instrument asks Id10304_a, "Did she faint when she
had the sharp abdominal pain?", to detect a ruptured ectopic pregnancy.

In release V1.1 (version 2023072701) it is gated on:

    selected(${Id10304},'yes')

In the multilingual release V2.0 (version 2026081401) it is gated on:

    selected(${Id10334},'yes') and selected(${Id10305},'yes')

That second condition can never be true. Id10334 ("Did she have a pregnancy
that ended in an abortion or miscarriage within 6 weeks before her death?")
carries this relevance, unchanged between the two releases:

    not(selected(${Id10312}, 'yes')) and not(selected(${Id10305}, 'yes')) and
    not(selected(${Id10299}, 'yes') and ${ageInYears2}>49) and
    not(selected(${Id10306}, 'yes')) and not(selected(${Id10313}, 'yes'))

so Id10334 is asked only when Id10305 is NOT "yes", while the new rule for
Id10304_a requires Id10305 to BE "yes". The two conjuncts are mutually
exclusive, Id10334 holds no value in any state where Id10305 is "yes", and the
conjunction is false everywhere. Under V2.0 the question is never presented,
in any language, and the field is uniformly empty in the collected data --
which an algorithm or a reviewing physician reads as "absent", not "no".

The failure is silent: the form validates, converts and deploys normally.

What this script does
---------------------
1. Enumerates every combination of the seven questions the two rules depend
   on, over the answers yes / no / dk / ref / unanswered, and reports in how
   many the question is reachable under each rule. States where Id10334 holds
   a value although its own relevance is false are excluded, because ODK
   clears answers that become irrelevant.
2. Reads each XLSForm workbook given and reports a verdict for it.

Usage
-----
    uv run check-id10304a-relevance.py                      # every .xlsx here
    uv run check-id10304a-relevance.py FORM.xlsx [MORE...]  # named workbooks
    uv run check-id10304a-relevance.py path/to/directory    # every .xlsx in it

`uv run` needs no setup: the script declares its own dependency (openpyxl) in
the PEP 723 header above, and uv fetches it into a throwaway environment. See
https://docs.astral.sh/uv/ to install uv. Without uv, `pip install openpyxl`
and use `python3` in place of `uv run`.

Two CSVs are written, one per release -- id10304a-states-v1.1.csv and
id10304a-states-v2.0.csv (--csv-prefix to rename, --no-csv to skip). They hold
the same states in the same order, differing only in the `release` column and
the final one, Id10304_a_reachable, so the two releases can be compared row
for row, or concatenated into a single frame. Every
one of the 5**7 = 78,125 states is written; state_is_coherent marks the 41,225
that can actually arise in an interview. The counts printed below can
therefore be recomputed from the files rather than taken on trust.

Exit status
-----------
    0   every workbook can ask Id10304_a
    1   at least one workbook can never ask it
    2   at least one workbook carries logic this script was not written for,
        or the built-in self-check failed

Status 2 matters: if a later release changes this logic again, the script says
UNKNOWN rather than reporting a false all-clear.

Requires Python 3.9 or newer. The only dependency is openpyxl, declared in
the header so that `uv run` installs it automatically.
"""

from __future__ import annotations

import argparse
import csv
import glob
import itertools
import os
import sys

try:
    import openpyxl
except ImportError:
    sys.exit("This script needs openpyxl. Either run it with `uv run "
             "check-id10304a-relevance.py`, or install it with `pip install openpyxl`.")


# --------------------------------------------------------------------------
# The expressions this script is written for. A workbook carrying anything
# else is reported UNKNOWN rather than judged.
# --------------------------------------------------------------------------

RULE_V11 = "selected(${Id10304},'yes')"
RULE_V20 = "selected(${Id10334},'yes') and selected(${Id10305},'yes')"

RELEVANCE_ID10334 = (
    "not(selected(${Id10312}, 'yes')) and not(selected(${Id10305}, 'yes')) and "
    "not(selected(${Id10299}, 'yes') and ${ageInYears2}>49)   and "
    "not(selected(${Id10306}, 'yes')) and not(selected(${Id10313}, 'yes'))"
)

# The questions the rules above depend on.
QUESTIONS = ["Id10312", "Id10305", "Id10299", "Id10306", "Id10313", "Id10334", "Id10304"]
ANSWERS = ["yes", "no", "dk", "ref", ""]          # "" means unanswered
AGE = 30                                           # any value under 50; see note below

# Expected counts, so that an accidental edit to the logic below is caught
# rather than silently changing the result. Id10299 is only consulted together
# with ageInYears2 > 49; with AGE below 50 that conjunct is false regardless,
# which is the branch relevant to a death in the reproductive age range.
EXPECTED = (41225, 8245, 0)


def id10334_is_relevant(answer: dict) -> bool:
    """RELEVANCE_ID10334, written out."""
    return (
        answer["Id10312"] != "yes"
        and answer["Id10305"] != "yes"
        and not (answer["Id10299"] == "yes" and answer["ageInYears2"] > 49)
        and answer["Id10306"] != "yes"
        and answer["Id10313"] != "yes"
    )


def reachable_under_v11(answer: dict) -> bool:
    """RULE_V11, written out."""
    return answer["Id10304"] == "yes"


def reachable_under_v20(answer: dict) -> bool:
    """RULE_V20, written out."""
    return answer["Id10334"] == "yes" and answer["Id10305"] == "yes"


# One file per release, so each can be read on its own terms: the columns are
# identical and only the final one differs, which makes the two directly
# comparable row for row.
RELEASES = [
    ("V1.1", "2023072701", RULE_V11),
    ("V2.0", "2026081401", RULE_V20),
]

# "release" is a column rather than a comment line above the header, so that
# the files load with pandas.read_csv or csv.DictReader without any argument,
# and concatenate into one frame if that is wanted.
CSV_COLUMNS = ["release"] + QUESTIONS + [
    "ageInYears2",
    "Id10334_is_relevant",
    "state_is_coherent",
    "Id10304_a_reachable",
]


def every_state():
    """Yield one row per combination of answers: all 5**7 of them.

    `state_is_coherent` is 0 for a state in which Id10334 holds an answer
    although its own relevance is false. ODK clears answers to questions that
    become irrelevant, so those states cannot arise in a real interview; they
    are emitted anyway, marked, so that the exclusion can be audited rather
    than taken on trust.
    """
    for combination in itertools.product(ANSWERS, repeat=len(QUESTIONS)):
        answer = dict(zip(QUESTIONS, combination))
        answer["ageInYears2"] = AGE
        relevant = id10334_is_relevant(answer)
        coherent = relevant or answer["Id10334"] == ""
        row = {question: (answer[question] or "(unanswered)") for question in QUESTIONS}
        row["ageInYears2"] = AGE
        row["Id10334_is_relevant"] = int(relevant)
        row["state_is_coherent"] = int(coherent)
        row["V1.1"] = int(coherent and reachable_under_v11(answer))
        row["V2.0"] = int(coherent and reachable_under_v20(answer))
        yield row


def enumerate_states(csv_prefix: str | None = None) -> tuple[int, int, int]:
    """Return (coherent states, reachable under V1.1, reachable under V2.0).

    When `csv_prefix` is given, writes one file per release --
    `<prefix>-v1.1.csv` and `<prefix>-v2.0.csv` -- each holding every state
    with that release's reachability in the final column. The totals are
    counted from the same rows that are written, so the files always reconcile
    with the figures printed beside them.
    """
    coherent = under_v11 = under_v20 = 0

    handles, writers = {}, {}
    if csv_prefix:
        for label, version, rule in RELEASES:
            path = f"{csv_prefix}-{label.lower()}.csv"
            handle = open(path, "w", newline="", encoding="utf-8")
            writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS,
                                    extrasaction="ignore")
            writer.writeheader()
            handles[label], writers[label] = handle, writer

    try:
        for row in every_state():
            for label in writers:
                writers[label].writerow(
                    {**row, "release": label, "Id10304_a_reachable": row[label]}
                )
            if not row["state_is_coherent"]:
                continue
            coherent += 1
            under_v11 += row["V1.1"]
            under_v20 += row["V2.0"]
    finally:
        for handle in handles.values():
            handle.close()
    return coherent, under_v11, under_v20


def csv_paths(prefix: str) -> list[str]:
    return [f"{prefix}-{label.lower()}.csv" for label, _, _ in RELEASES]


# --------------------------------------------------------------------------
# Reading workbooks
# --------------------------------------------------------------------------

def collapse(value) -> str:
    """Normalise whitespace so formatting differences are not read as changes."""
    return " ".join(str(value).split()) if value is not None else ""


def read_workbook(path: str) -> dict:
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)

    title = version = ""
    if "settings" in workbook.sheetnames:
        rows = list(workbook["settings"].iter_rows(values_only=True))
        if len(rows) >= 2:
            header = [collapse(cell) for cell in rows[0]]
            settings = dict(zip(header, rows[1]))
            title = collapse(settings.get("form_title"))
            version = collapse(settings.get("version"))

    if "survey" not in workbook.sheetnames:
        workbook.close()
        raise ValueError("no 'survey' sheet")

    rows = workbook["survey"].iter_rows(values_only=True)
    header = [collapse(cell) for cell in next(rows)]
    if "name" not in header or "relevant" not in header:
        workbook.close()
        raise ValueError("'survey' sheet has no 'name' or 'relevant' column")

    name_at, relevant_at = header.index("name"), header.index("relevant")
    wanted = {"Id10304_a", "Id10334"}
    relevance = {}
    for row in rows:
        question = collapse(row[name_at]) if name_at < len(row) else ""
        if question in wanted:
            relevance[question] = collapse(row[relevant_at]) if relevant_at < len(row) else ""

    workbook.close()
    return {"title": title, "version": version, "relevance": relevance}


def judge(workbook: dict) -> tuple[str, str]:
    """Return (verdict, explanation) for one workbook."""
    relevance = workbook["relevance"]

    if "Id10304_a" not in relevance:
        return "SKIP", "the workbook does not contain Id10304_a"

    # The verdict depends on Id10334's relevance as much as on the rule
    # itself, so an unrecognised Id10334 invalidates any conclusion.
    if relevance.get("Id10334", "") != collapse(RELEVANCE_ID10334):
        return "UNKNOWN", (
            "Id10334's relevance is not the expression this script reasons about, "
            "so the reachability of Id10304_a must be re-derived:\n"
            f"              found: {relevance.get('Id10334', '(absent)')}"
        )

    rule = relevance["Id10304_a"]
    if rule == collapse(RULE_V11):
        return "OK", "Id10304_a is reachable (V1.1 rule)"
    if rule == collapse(RULE_V20):
        return "AFFECTED", "Id10304_a can never be asked (V2.0 rule)"
    return "UNKNOWN", (
        "Id10304_a carries a rule this script was not written for:\n"
        f"              found: {rule}"
    )


# --------------------------------------------------------------------------

def collect_paths(arguments: list[str]) -> list[str]:
    if not arguments:
        return sorted(glob.glob("*.xlsx"))
    paths: list[str] = []
    for argument in arguments:
        if os.path.isdir(argument):
            paths.extend(sorted(glob.glob(os.path.join(argument, "*.xlsx"))))
        else:
            paths.append(argument)
    return paths


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Check whether Id10304_a can ever be asked in a WHO VA 2022 XLSForm.",
    )
    parser.add_argument("workbooks", nargs="*",
                        help="XLSForm .xlsx files, or a directory of them "
                             "(default: every .xlsx in the current directory)")
    parser.add_argument("--csv-prefix", default="id10304a-states", metavar="PREFIX",
                        help="write <PREFIX>-v1.1.csv and <PREFIX>-v2.0.csv "
                             "(default: id10304a-states; --no-csv to skip)")
    parser.add_argument("--no-csv", action="store_true", help="do not write the CSVs")
    arguments = parser.parse_args(argv)

    prefix = None if arguments.no_csv else arguments.csv_prefix
    coherent, under_v11, under_v20 = enumerate_states(prefix)

    print("Reachability of Id10304_a, by enumeration")
    print("-" * 64)
    print(f"  Coherent form states examined       {coherent:>10,}")
    print(f"  Reachable under the V1.1 rule       {under_v11:>10,}")
    print(f"  Reachable under the V2.0 rule       {under_v20:>10,}")
    if prefix:
        total = len(ANSWERS) ** len(QUESTIONS)
        print(f"  All {total:,} states written to each of:")
        for (label, version, rule), path in zip(RELEASES, csv_paths(prefix)):
            print(f"      {path}   {label} ({version}): {rule}")
    print()

    if (coherent, under_v11, under_v20) != EXPECTED:
        print(f"  SELF-CHECK FAILED: expected {EXPECTED}, got "
              f"{(coherent, under_v11, under_v20)}.")
        print("  The logic in this script has been altered; its verdicts are not "
              "trustworthy.")
        return 2

    paths = collect_paths(arguments.workbooks)
    if not paths:
        print("No .xlsx workbooks found. Pass a workbook, or a directory of them.")
        return 2

    print("Workbooks")
    print("-" * 64)
    worst = 0
    for path in paths:
        label = os.path.basename(path)
        try:
            workbook = read_workbook(path)
        except Exception as error:                      # unreadable, wrong shape
            print(f"  UNKNOWN   {label}: could not be read ({error})")
            worst = max(worst, 2)
            continue

        verdict, explanation = judge(workbook)
        version = f"  [{workbook['version']}]" if workbook["version"] else ""
        print(f"  {verdict:<9} {label}{version}")
        print(f"              {explanation}")
        if workbook["title"] and verdict in ("AFFECTED", "UNKNOWN"):
            print(f"              {workbook['title']}")
        worst = max(worst, {"OK": 0, "SKIP": 0, "AFFECTED": 1, "UNKNOWN": 2}[verdict])

    print()
    print({
        0: "Every workbook examined can ask Id10304_a.",
        1: "At least one workbook can never ask Id10304_a.",
        2: "At least one workbook carries logic this script cannot judge.",
    }[worst])
    return worst


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
