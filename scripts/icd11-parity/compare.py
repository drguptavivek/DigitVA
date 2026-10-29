"""Compare the phone engine's results with the WHO container's, request by request.

Both files come from phone_harness.c and run_container.py over the same build_inputs.py list.
A pair matches when both sides succeed (HTTP 2xx) with equal JSON, or both refuse the request
(any non-2xx; the phone's in-process call and the container's web stack word their errors
differently, so only "refused" is compared). JSON field names are compared case-insensitively:
the container's REST layer writes camelCase (`stemCode`), the in-process call the controller's
own PascalCase (`StemCode`). A search's `uniqueSearchId` (a random id per request) is
left out. Prints a table per section and the latency of each side; exits 1 on
any mismatch.

usage: python3 scripts/icd11-parity/compare.py PHONE.tsv CONTAINER.tsv
"""
import json
import statistics
import sys


def lower_keys(value):
    if isinstance(value, dict):
        return {k.lower(): lower_keys(v) for k, v in value.items()}
    if isinstance(value, list):
        return [lower_keys(v) for v in value]
    return value


# Fields WHO fills fresh on every request: a search's uniqueSearchId is a new random id each call.
VOLATILE = {"uniquesearchid"}


def parse(body):
    try:
        value = lower_keys(json.loads(body))
    except ValueError:
        return body
    if isinstance(value, dict):
        for key in VOLATILE:
            value.pop(key, None)
    return value


def load(path):
    rows = {}
    for line in open(path, encoding="utf-8"):
        parts = line.rstrip("\n").split("\t")
        if parts[0] == "CERT":
            _, ident, t1, t2, s1, s2, b1, b2 = parts
            rows[ident] = {"kind": "doris", "ms": [float(t1), float(t2)],
                           "calls": [(int(s1), parse(b1)), (int(s2), parse(b2))]}
        elif parts[0] in ("SEARCH", "CODEINFO"):
            _, ident, t, s, b = parts
            rows[ident] = {"kind": parts[0].lower(), "ms": [float(t)], "calls": [(int(s), parse(b))]}
    return rows


def ok(status):
    return 200 <= status < 300


def verdict(a, b):
    """'same', 'both refused', or a short reason for the mismatch."""
    outcomes = []
    for (sa, ba), (sb, bb) in zip(a["calls"], b["calls"]):
        if ok(sa) and ok(sb):
            if ba != bb:
                fields = sorted(k for k in set(ba) | set(bb) if ba.get(k) != bb.get(k)) \
                    if isinstance(ba, dict) and isinstance(bb, dict) else ["body"]
                return "differs: " + ", ".join(fields[:6])
            outcomes.append("same")
        elif not ok(sa) and not ok(sb):
            outcomes.append("refused")
        else:
            return f"one side refused (phone {sa}, container {sb})"
    return "both refused" if outcomes and all(o == "refused" for o in outcomes) else "same"


def spread(values):
    values = sorted(values)
    p95 = values[min(len(values) - 1, int(0.95 * len(values)))]
    return f"median {statistics.median(values):.1f}, p95 {p95:.1f}, max {values[-1]:.1f} ms"


def main():
    phone, container = load(sys.argv[1]), load(sys.argv[2])
    only = sorted(set(phone) ^ set(container))
    sections = {}
    mismatches = []
    for ident in sorted(set(phone) & set(container)):
        section = ident.split("/", 1)[0]
        v = verdict(phone[ident], container[ident])
        tally = sections.setdefault(section, {"total": 0, "same": 0, "both refused": 0, "mismatch": 0})
        tally["total"] += 1
        if v in ("same", "both refused"):
            tally[v] += 1
        else:
            tally["mismatch"] += 1
            mismatches.append((ident, v))
    print(f"requests: phone {len(phone)}, container {len(container)}, only on one side {len(only)}")
    print(f"{'section':10} {'total':>6} {'same':>6} {'refused':>8} {'mismatch':>9}")
    for section, t in sections.items():
        print(f"{section:10} {t['total']:6} {t['same']:6} {t['both refused']:8} {t['mismatch']:9}")
    for ident, v in mismatches[:40]:
        print(f"  {ident}: {v}")
    for kind, label in [("doris", "DORIS"), ("search", "search"), ("codeinfo", "code info")]:
        p = [r["ms"][0] for r in phone.values() if r["kind"] == kind]
        c = [r["ms"][0] for r in container.values() if r["kind"] == kind]
        if p:
            print(f"{label:10} phone {spread(p)} | container (REST, same machine) {spread(c)}")
    p = [r["ms"][1] for r in phone.values() if r["kind"] == "doris"]
    c = [r["ms"][1] for r in container.values() if r["kind"] == "doris"]
    print(f"{'CoDEdit':10} phone {spread(p)} | container (REST, same machine) {spread(c)}")
    sys.exit(1 if mismatches or only else 0)


if __name__ == "__main__":
    main()
