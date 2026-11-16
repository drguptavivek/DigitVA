#!/usr/bin/env python3
"""Compare the phone engine's SmartVA replies with what the server stored, case by case.

The server stored its result from SmartVA's likelihoods CSV (va_smartva_04_formatsmartvaresult.py, read by pandas,
then smartva_service.py); the phone gets the same prediction as JSON (smartva_score_json). The phone's raw prediction
is put in the server's stored shape with the server's own rules, and compared field by field:
  age          format(float(age), ".1f")                      (smartva_service.py)
  gender       sex 1 Male, 2 Female, else Missing              (engine.rs, the likelihoods CSV writer)
  resultfor    "for_" + module                                 (the likelihoods file the row came from)
  causeN, likelihoodN, keysymptomN (key_symptomN), allsymptoms (all_symptoms): the string; "" is NULL (pandas reads
               an empty cell as NaN, stored as NULL)
  causeNicd    the phone's own table (va-icd10.json by_module[module][cause], as projection.ts), against the stored
               code; the server's table (VA_SMARTVA_ICDS, NEONATE | CHILD | ADULT) is checked to give the same code
A server row that failed with "format_output" (SmartVA wrote no output row) matches a phone reply with no prediction.
Server rows that failed with "execution" never reached the engine; they are counted apart and not compared.

Writes the aggregate summary to stdout (no case data). Per-case mismatch examples (id = sha256(va_sid)[:16], field,
server value, phone value) go to --examples, which must be under private/. --other compares a second platform's
replies byte for byte with the first. Exit status 1 on any mismatch, engine error, or Android/iOS difference.

--expected replaces the stored results with rescore_server.py's: the same cases scored again now by the server's
pipeline, to tell an older server engine from a phone difference (the cases keep their stored row's engine bucket).

usage: compare.py CORPUS_DIR REPLIES [--expected server-now.jsonl] [--other REPLIES] [--examples FILE] [--stats FILE] [--label NAME]
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PHONE_ICD10 = REPO / "mobile/digitva-collect/src/smartva/va-icd10.json"
TEXT_FIELDS = [(f"cause{n}", f"cause{n}") for n in (1, 2, 3)] + [(f"likelihood{n}", f"likelihood{n}") for n in (1, 2, 3)] \
    + [(f"keysymptom{n}", f"key_symptom{n}") for n in (1, 2, 3)] + [("allsymptoms", "all_symptoms")]
EXAMPLES_PER_KIND = 5


def read_replies(path: Path) -> tuple[dict, dict]:
    """{id: (ms, rc, body)} and the META values."""
    replies, meta = {}, {}
    with path.open() as handle:
        for line in handle:
            parts = line.rstrip("\n").split("\t", 4)
            if parts[0] == "R" and len(parts) == 5:
                replies[parts[1]] = (float(parts[2]), int(parts[3]), parts[4])
            elif parts[0] == "META":
                meta[parts[1]] = parts[2:]
    return replies, meta


def server_shape(prediction: dict, phone_icd: dict) -> dict:
    """The phone's raw prediction in the shape and spelling the server stores."""
    def text(value):
        return None if value is None or value == "" else str(value)

    age = prediction.get("age")
    module = prediction.get("module")
    shaped = {
        "age": format(float(age), ".1f") if age is not None else None,
        "gender": {1: "Male", 2: "Female"}.get(prediction.get("sex"), "Missing"),
        "resultfor": f"for_{module}" if module else None,
    }
    for stored, raw in TEXT_FIELDS:
        shaped[stored] = text(prediction.get(raw))
    for n in (1, 2, 3):
        cause = shaped[f"cause{n}"]
        shaped[f"cause{n}icd"] = phone_icd.get(module, {}).get(cause) if cause else None
    return shaped


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("corpus", type=Path)
    parser.add_argument("replies", type=Path)
    parser.add_argument("--other", type=Path)
    parser.add_argument("--examples", type=Path)
    parser.add_argument("--label", default="phone")
    parser.add_argument("--expected", type=Path,
                        help="server-now.jsonl (rescore_server.py): compare with the server's current engine instead")
    parser.add_argument("--stats", type=Path, help="aggregate counts as JSON (no case data), for run.json")
    args = parser.parse_args()
    if args.examples and "private" not in args.examples.resolve().parts:
        parser.error("--examples must be under private/")

    phone_icd = json.loads(PHONE_ICD10.read_text())["by_module"]
    icds = json.loads((args.corpus / "server_icds.json").read_text())
    server_icd = icds["NEONATE"] | icds["CHILD"] | icds["ADULT"]
    cases = [json.loads(line) for line in (args.corpus / "expected.jsonl").open()]
    if args.expected:
        now = {row["id"]: row["expected"] for row in map(json.loads, args.expected.open())}
        for case in cases:
            case["expected"] = now[case["id"]]
    replies, meta = read_replies(args.replies)

    outcome = defaultdict(Counter)        # engine bucket -> verdict
    field_kinds = defaultdict(Counter)    # engine bucket -> field
    examples = defaultdict(list)
    icd_table_disagrees = 0
    latencies = []
    first_ms = None

    def record(bucket, kind, case_id, server_value, phone_value):
        field_kinds[bucket][kind] += 1
        if len(examples[(bucket, kind)]) < EXAMPLES_PER_KIND:
            examples[(bucket, kind)].append((case_id, server_value, phone_value))

    order = list(replies)
    if order:
        first_ms = replies[order[0]][0]
        latencies = [replies[case_id][0] for case_id in order[1:]]
    for case in cases:
        bucket, expected, case_id = case["engine"], case["expected"], case["id"]
        if expected["outcome"] == "failed" and expected["failure_stage"] == "execution":
            outcome[bucket]["server never ran the engine (execution failure), not compared"] += 1
            continue
        if case["refused"]:
            outcome[bucket]["phone refused the request (createSmartVaRequest)"] += 1
            continue
        if case_id not in replies:
            outcome[bucket]["no phone reply"] += 1
            continue
        _, rc, body = replies[case_id]
        if rc != 0 or not body.startswith("{"):
            outcome[bucket]["phone engine error"] += 1
            record(bucket, "engine error", case_id, expected["outcome"], body[:200])
            continue
        result = json.loads(body)
        predictions = result.get("predictions") or []
        if expected["outcome"] == "failed":
            if not predictions:
                outcome[bucket]["identical: no prediction on either side"] += 1
            else:
                outcome[bucket]["different"] += 1
                record(bucket, "phone predicts, server had no output row", case_id, None,
                       predictions[0].get("cause1"))
            continue
        if len(predictions) != 1:
            outcome[bucket]["different"] += 1
            record(bucket, "phone has no prediction, server has one", case_id, expected["cause1"], len(predictions))
            continue
        shaped = server_shape(predictions[0], phone_icd)
        for n in (1, 2, 3):
            cause = shaped[f"cause{n}"]
            if cause and server_icd.get(cause) != shaped[f"cause{n}icd"]:
                icd_table_disagrees += 1
        differing = [name for name, value in shaped.items() if expected[name] != value]
        if not differing:
            outcome[bucket]["identical"] += 1
            continue
        outcome[bucket]["different"] += 1
        for name in differing:
            record(bucket, name, case_id, expected[name], shaped[name])

    reference = "the server's current engine (rescore_server.py)" if args.expected else "the server's stored result"
    lines = [f"SmartVA parity: {args.label} engine vs {reference}",
             f"engine version: {meta.get('version', ['?'])[0]}",
             f"cases: {len(cases)}, phone replies: {len(replies)}",
             "server ICD table (merged) vs the phone's table: "
             + ("same code for every phone cause" if not icd_table_disagrees else f"{icd_table_disagrees} differ"), ""]
    failing = icd_table_disagrees > 0
    for bucket in sorted(outcome, key=lambda b: -sum(outcome[b].values())):
        lines.append(f"server engine {bucket}: {sum(outcome[bucket].values())} cases")
        for verdict, count in outcome[bucket].most_common():
            lines.append(f"  {verdict}: {count}")
            failing |= not verdict.startswith(("identical", "server never ran"))
        for kind, count in field_kinds[bucket].most_common():
            lines.append(f"    differs in {kind}: {count}")
    inputs = Counter()
    for case in cases:
        difference = case["input"]
        inputs["phone drops fields the server read"] += bool(difference["dropped"])
        inputs["phone adds fields"] += bool(difference["added"])
        inputs["numbers spelt differently (phone-cleaned variant)"] += bool(difference["numeric"])
        inputs["other value differences"] += bool(difference["other"])
    lines += ["", "input, phone cleaner vs server cleaner (cases): "
              + ", ".join(f"{name} {count}" for name, count in inputs.items())]
    stats = {"cases": len(cases), "replies": len(replies), "engine_version": meta.get("version", [None])[0],
             "by_server_engine": {bucket: dict(outcome[bucket]) for bucket in outcome},
             "differing_fields": {bucket: dict(field_kinds[bucket]) for bucket in field_kinds},
             "input_differences": dict(inputs), "icd_table_disagreements": icd_table_disagrees}
    if latencies:
        stats["latency_ms"] = {"first": first_ms, "median": statistics.median(latencies),
                               "p95": percentile(latencies, 0.95), "max": max(latencies)}
        lines.append(f"latency ms: first call {first_ms:.1f}; rest median {statistics.median(latencies):.1f}, "
                     f"p95 {percentile(latencies, 0.95):.1f}, max {max(latencies):.1f}")
    if "end" in meta:
        lines.append(f"peak RSS: {int(meta['end'][1]) // 1024} MiB")
    if args.other:
        other, other_meta = read_replies(args.other)
        same = sum(1 for case_id, reply in replies.items() if case_id in other and other[case_id][1:] == reply[1:])
        only = len(set(replies) ^ set(other))
        identical = same == len(replies) == len(other) and not only
        failing |= not identical
        stats["other_platform"] = {"replies_byte_identical": same, "one_side_only": only, "identical": identical}
        lines += ["", f"vs {args.other.parent.name} (engine {other_meta.get('version', ['?'])[0]}): "
                  f"{same} of {len(replies)} replies byte-identical (rc and body), {only} seen on one side only"]
    lines += ["", "verdict: " + ("PASS (every compared case identical)" if not failing else "MISMATCH")]
    print("\n".join(lines))
    stats["verdict"] = "PASS" if not failing else "MISMATCH"
    if args.stats:
        args.stats.write_text(json.dumps(stats, indent=1) + "\n")

    if args.examples:
        args.examples.parent.mkdir(parents=True, exist_ok=True)
        with args.examples.open("w") as handle:
            for (bucket, kind), rows in sorted(examples.items()):
                for case_id, server_value, phone_value in rows:
                    handle.write(json.dumps({"engine": bucket, "field": kind, "id": case_id,
                                             "server": server_value, "phone": phone_value}, ensure_ascii=False) + "\n")
    return 1 if failing else 0


if __name__ == "__main__":
    sys.exit(main())
