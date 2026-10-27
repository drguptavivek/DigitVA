#!/usr/bin/env python3
"""Regenerate corpus_expected.json from the reference Python SmartVA-Analyze.

Run from anywhere:  python3 desktop/crates/digitva-smartva/tests/fixtures/regenerate_expected.py
Needs `uv` (installs click/numpy/pandas/... into an ephemeral env; Python 3.12).
Inputs: corpus_inputs.json (synthetic; see README.md). Output: corpus_expected.json,
which records the SmartVA version and vendor git revision it came from.
"""
import csv, json, re, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
SMARTVA = REPO / "vendor" / "smartva-analyze"
DEPS = ["click", "colorama", "matplotlib", "numpy", "pyparsing", "python-dateutil", "pytz",
        "tornado", "progressbar2", "xlsxwriter", "pandas", "stemming"]
# Same pattern as app/services/smartva_service.py _SMARTVA_REPORT_REJECTION_RE.
REJECT = re.compile(r"^SID:\s+(?P<sid>\S+)\s+\(row\s+\d+\)\s+(?P<reason>.+)$")
FIELDS = [f"{n}{i}" for i in (1, 2, 3) for n in ("cause", "likelihood")]


def main() -> None:
    spec = json.loads((HERE / "corpus_inputs.json").read_text())
    opts, rows = spec["options"], spec["rows"]
    version = re.search(r'^version = "([^"]+)"', (SMARTVA / "pyproject.toml").read_text(), re.M).group(1)
    rev = subprocess.run(["git", "-C", str(SMARTVA), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        header = sorted({k for r in rows for k in r})
        with open(tmp / "in.csv", "w", newline="") as f:
            w = csv.DictWriter(f, header)
            w.writeheader()
            w.writerows(rows)
        (tmp / "out").mkdir()
        cmd = ["uv", "run", "--no-project", "--python", "3.12", *[x for d in DEPS for x in ("--with", d)],
               "python", "app.py", "--country", opts["country"], "--hiv", str(opts["hiv"]),
               "--malaria", str(opts["malaria"]), "--hce", str(opts["hce"]),
               "--freetext", str(opts["freetext"]), "--figures", "False",
               str(tmp / "in.csv"), str(tmp / "out")]
        subprocess.run(cmd, cwd=SMARTVA, env={**__import__("os").environ, "PYTHONPATH": "src"},
                       check=True, stdout=subprocess.DEVNULL)
        mon = tmp / "out" / "4-monitoring-and-quality"
        records = {}
        for module in ("adult", "child", "neonate"):
            p = mon / "intermediate-files" / f"{module}-likelihoods.csv"
            if not p.exists():
                continue
            # SmartVA pads fixed-width fields with NUL bytes (see _read_smartva_csv in the server).
            for r in csv.DictReader(p.read_bytes().replace(b"\x00", b"").decode().splitlines()):
                records[r["sid"].strip()] = {k: (r[k].strip() or None) for k in FIELDS}
        rejected = {}
        for line in (mon / "report.txt").read_text().splitlines():
            m = REJECT.match(line.strip())
            if m:
                rejected[m["sid"]] = m["reason"].strip()
    out = {"smartva_version": version, "smartva_git_rev": rev, "options": opts,
           "records": records, "rejected": sorted(rejected)}
    (HERE / "corpus_expected.json").write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
    print(f"wrote {len(records)} records, {len(rejected)} rejected (SmartVA {version})")


if __name__ == "__main__":
    sys.exit(main())
