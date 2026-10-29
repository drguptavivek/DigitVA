"""Build 10,000 distinct synthetic DORIS certificates from conditions.json, deterministically.

Every choice comes from SHA-256 of (certificate number, field name), never from a random
generator, so the same conditions.json gives the same file, byte for byte, on any machine
and Python version. Certificates whose canonical JSON repeats are skipped until COUNT
distinct ones exist. One JSON object per line: {"id", "group", "certificate"}, the
certificate in the WHO DORIS JSON format (docs/kb/DORIS/who-doris-death-certificate-json-format.md).

Varied: age group; sex (male, female, unknown); age as an estimated age, full dates of
birth and death, or a year-only date of birth; one to four Part I lines; zero to two
Part II conditions; intervals (unknown, hours, days, months, years); surgery, autopsy and
manner of death blocks; maternal and fetal or infant blocks where they apply.

usage: python3 scripts/icd11-parity/make_certificates.py [OUT.jsonl] [COUNT]
"""
import hashlib
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).parent
GROUPS = ["adult", "adult", "adult", "adult", "child", "child", "neonate", "maternal"]
AGES = {"adult": ["P18Y", "P34Y", "P52Y", "P67Y", "P81Y", "P95Y"], "child": ["P2M", "P11M", "P2Y", "P6Y", "P11Y"],
        "neonate": ["PT6H", "P1D", "P4D", "P13D", "P25D"], "maternal": ["P17Y", "P23Y", "P31Y", "P44Y"]}
BIRTH_YEARS = {"adult": [1931, 1946, 1959, 1972, 1988, 2005], "child": [2015, 2019, 2023, 2024],
               "neonate": [2026], "maternal": [1982, 1995, 2003]}
INTERVALS = ["", "PT2H", "PT12H", "P1D", "P4D", "P3W", "P2M", "P8M", "P1Y", "P6Y"]
DEATH_DATES = ["2026-01-14", "2026-04-02", "2026-07-21", "2026-10-09"]


def pick(options, number, field):
    digest = hashlib.sha256(f"{number}:{field}".encode()).digest()
    return options[int.from_bytes(digest[:8], "big") % len(options)]


def administrative(group, number):
    sex = 2 if group == "maternal" else pick([1, 1, 2, 2, 9], number, "sex")
    form = pick(["estimated", "estimated", "dates", "year"], number, "age-form")
    if group == "neonate":
        form = pick(["estimated", "dates"], number, "age-form")
    data = {"Sex": sex}
    death = pick(DEATH_DATES, number, "death")
    if form == "estimated":
        data["EstimatedAge"] = pick(AGES[group], number, "age")
    elif form == "dates":
        year = pick(BIRTH_YEARS[group], number, "birth-year")
        if group == "neonate":
            data["DateBirth"] = f"{death[:8]}0{pick([1, 2, 3, 5], number, 'birth-day')}"
            data["DateDeath"] = f"{death[:8]}{pick(['06', '09', '12'], number, 'death-day')}"
            return data
        data["DateBirth"] = f"{year}-{pick(['02', '05', '08', '11'], number, 'birth-month')}-{pick(['03', '17', '28'], number, 'birth-day')}"
        data["DateDeath"] = death
    else:
        data["DateBirth"] = str(pick(BIRTH_YEARS[group], number, "birth-year"))
        data["DateDeath"] = death
    return data


def main():
    out_path = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "certificates.jsonl"
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 10000
    conditions = json.loads((HERE / "conditions.json").read_text())
    by_group = {g: [c for c in conditions if g in c["groups"] or (g == "maternal" and "adult" in c["groups"])]
                for g in set(GROUPS)}

    def line(c, number, field):
        return {"Conditions": [{"Text": c["text"], "Code": c["code"], "LinearizationURI": c["uri"],
                                "Interval": pick(INTERVALS, number, field)}]}

    seen, rows, number = set(), [], 0
    while len(rows) < count:
        number += 1
        group = pick(GROUPS, number, "group")
        pool = by_group[group]
        lines = pick([1, 1, 2, 2, 2, 3, 3, 4], number, "lines")
        chain = []
        for n in range(lines):
            candidate = pick(pool, number, f"line-{n}")
            if candidate not in chain:
                chain.append(candidate)
        contributing = []
        for n in range(pick([0, 0, 1, 1, 2], number, "part2")):
            candidate = pick(pool, number, f"part2-{n}")
            if candidate not in chain and candidate not in contributing:
                contributing.append(candidate)
        cert = {"ICDVersion": "ICD11", "AdministrativeData": administrative(group, number),
                "Part1": [line(c, number, f"interval-{n}") for n, c in enumerate(chain)]}
        if contributing:
            cert["Part2"] = {"Conditions": [line(c, number, f"interval-ii-{n}")["Conditions"][0]
                                            for n, c in enumerate(contributing)]}
        if pick([0, 1, 2], number, "surgery-block") == 0:
            cert["Surgery"] = {"WasPerformed": pick([0, 1, 9], number, "surgery")}
        if pick([0, 1, 2], number, "autopsy-block") == 0:
            requested = pick([0, 1, 9], number, "autopsy")
            cert["Autopsy"] = {"WasRequested": requested, **({"Findings": pick([0, 1, 9], number, "findings")}
                                                             if requested == 1 else {})}
        if pick([0, 1], number, "manner-block") == 0:
            cert["MannerOfDeath"] = {"MannerOfDeath": pick([0, 0, 0, 6, 9], number, "manner")}
        if group == "maternal":
            cert["MaternalDeath"] = {"WasPregnant": pick([0, 1, 1, 9], number, "pregnant"),
                                     "TimeFromPregnancy": pick([0, 1, 2, 3, 9], number, "pregnancy-time"),
                                     "PregnancyContribute": pick([0, 1, 9], number, "pregnancy-contribute")}
        if group == "neonate":
            cert["FetalOrInfantDeath"] = {
                "MultiplePregnancy": pick([0, 0, 1, 9], number, "multiple"),
                "Stillborn": pick([0, 0, 0, 1], number, "stillborn"),
                "DeathWithin24h": pick([0, 1, 9], number, "within24h"),
                "BirthWeight": pick([900, 1450, 2100, 2800, 3400], number, "weight"),
                "PregnancyWeeks": pick([28, 32, 35, 38, 40], number, "weeks"),
                "AgeMother": pick([17, 22, 29, 36, 41], number, "mother-age"),
            }
        canonical = json.dumps(cert, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        if canonical in seen:
            continue
        seen.add(canonical)
        rows.append({"id": f"c{len(rows) + 1:05d}-{group}", "group": group, "certificate": cert})
    with open(out_path, "w") as out:
        for row in rows:
            out.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    print(f"{len(rows)} distinct certificates from {number} draws -> {out_path}")


if __name__ == "__main__":
    main()
