"""Write REVIEW.md: every corpus item in a table, for the owner to approve or edit.

usage: python3 scripts/icd11-golden/review.py      (host Python, no dependencies)
"""

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def cell(text) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def certificate_summary(cert: dict) -> str:
    admin = cert.get("AdministrativeData", {})
    who = {1: "M", 2: "F", 9: "sex?"}.get(admin.get("Sex"), "")
    when = admin.get("EstimatedAge") or "/".join(v for v in (admin.get("DateBirth"), admin.get("DateDeath")) if v)
    lines = []
    for line in cert.get("Part1", []):
        conds = []
        for c in line.get("Conditions", []):
            conds.append(f"{c.get('Code') or 'uncoded'} {c.get('Text', '')}".strip())
        iv = next((c.get("Interval") for c in line.get("Conditions", []) if "Interval" in c), None)
        lines.append(" + ".join(conds) + (f" [{iv}]" if iv else ""))
    text = " **due to** ".join(lines)
    part2 = cert.get("Part2", {}).get("Conditions", [])
    if part2:
        text += " ; II: " + ", ".join(f"{c.get('Code') or 'uncoded'}" for c in part2)
    blocks = [k for k in ("Surgery", "Autopsy", "MannerOfDeath", "FetalOrInfantDeath", "MaternalDeath") if k in cert]
    return f"{who} {when}: {text}" + (f" ; blocks: {', '.join(blocks)}" if blocks else "")


def table(title, intro, header, rows) -> str:
    out = [f"## {title}", "", intro, "", "| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(cell(c) for c in row) + " |" for row in rows]
    return "\n".join(out) + "\n"


def main():
    doris = json.loads((HERE / "corpus/doris.json").read_text())["items"]
    pcs = json.loads((HERE / "corpus/postcoordination.json").read_text())["items"]
    search = json.loads((HERE / "corpus/search.json").read_text())["items"]
    built = sum(len(i.get("built", [])) for i in pcs)
    parts = [
        "# Golden corpora: draft for owner review\n",
        "All three sets are `\"status\": \"draft\"`. Edit the JSON in `corpus/` (or tell the writer what to add or "
        "drop), then re-record (README.md) and regenerate this file with `python3 scripts/icd11-golden/review.py`.\n",
        f"Counts: DORIS {len(doris)} certificates, postcoordination {len(pcs)} stems with {built} built expressions, "
        f"search {len(search)} terms.\n",
        table("DORIS certificates", "Input is `group, sex, age or dates: Part I lines (top = immediate cause), Part II, blocks`.",
              ["id", "group", "input", "why", "source"],
              [(i["id"], i["group"], certificate_summary(i["certificate"]), i["why"], i["source"]) for i in doris]),
        table("Postcoordination stems", "Each stem is recorded through codeinfo, selection-check, postcoordination, "
              "postcoordination-options (first expandable root of every axis), hierarchy, related and details. "
              "Built expressions go through codeinfo, selection-check, hierarchy, related and details.",
              ["id", "stem", "category", "built expressions", "why", "source"],
              [(i["id"], i["stem"], i["category"], "<br>".join(f"`{b['expression']}` {b['why']}" for b in i.get("built", [])),
                i["why"], i["source"]) for i in pcs]),
        table("Search terms", "Recorded with the server's options (`q=<term>%`, includePostcoordination, flatResults, "
              "highlightingEnabled, medicalCodingMode), limit 20; the expected top 5 are kept in order.",
              ["id", "query", "kind", "why", "source"],
              [(i["id"], i["query"], i["kind"], i["why"], i["source"]) for i in search]),
    ]
    (HERE / "REVIEW.md").write_text("\n".join(parts))


if __name__ == "__main__":
    main()
