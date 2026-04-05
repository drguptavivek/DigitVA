#!/usr/bin/env python3
"""
Analyze SQLAlchemy sql.log to find time-consuming operations.

Strategy: since there is no explicit duration per log line, we compute the
time gap between consecutive timestamped lines. A large gap indicates the
preceding SQL statement (or the application code surrounding it) was slow.

Usage:
    python scripts/analyze_sql_log.py [--log logs/sql.log] [--threshold 1.0] [--top 20] [--out results.txt]
"""

import re
import sys
import argparse
from collections import defaultdict
from datetime import datetime

TIMESTAMP_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3})")
SQL_VERB_RE = re.compile(r"- (SELECT|INSERT|UPDATE|DELETE|BEGIN|COMMIT|ROLLBACK)\b", re.IGNORECASE)
TABLE_RE = re.compile(r"(?:FROM|INTO|UPDATE)\s+(\w+)", re.IGNORECASE)

TS_FORMAT = "%Y-%m-%d %H:%M:%S,%f"


def parse_ts(line: str) -> datetime | None:
    m = TIMESTAMP_RE.match(line)
    if m:
        return datetime.strptime(m.group(1), TS_FORMAT)
    return None


def extract_verb_table(line: str) -> tuple[str, str]:
    verb = "OTHER"
    table = "unknown"
    vm = SQL_VERB_RE.search(line)
    if vm:
        verb = vm.group(1).upper()
    tm = TABLE_RE.search(line)
    if tm:
        table = tm.group(1).lower()
    return verb, table


def analyze(log_path: str, threshold: float, top_n: int, out_file=None):
    slow_hits: list[tuple[float, str, str]] = []  # (gap_s, slow_line, next_line)
    summary: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))  # verb -> table -> count

    prev_ts: datetime | None = None
    prev_line: str = ""
    total_lines = 0
    matched_lines = 0

    output = open(out_file, "w") if out_file else sys.stdout

    def emit(text: str):
        print(text, file=output)

    try:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.rstrip("\n")
                total_lines += 1

                ts = parse_ts(line)
                if ts is None:
                    continue

                matched_lines += 1

                if prev_ts is not None:
                    gap = (ts - prev_ts).total_seconds()
                    if gap >= threshold:
                        slow_hits.append((gap, prev_line, line))
                        verb, table = extract_verb_table(prev_line)
                        summary[verb][table] += 1

                prev_ts = ts
                prev_line = line

        # --- Top-N slowest ---
        slow_hits.sort(key=lambda x: x[0], reverse=True)

        emit(f"\n{'='*80}")
        emit(f"SQL Log Analysis: {log_path}")
        emit(f"Total lines: {total_lines:,}  |  Timestamped: {matched_lines:,}")
        emit(f"Threshold: {threshold}s  |  Slow gaps found: {len(slow_hits):,}")
        emit(f"{'='*80}\n")

        emit(f"TOP {top_n} SLOWEST GAPS")
        emit("-" * 80)
        for i, (gap, slow_line, next_line) in enumerate(slow_hits[:top_n], 1):
            # Truncate long lines for readability
            slow_disp = slow_line[:160] + ("…" if len(slow_line) > 160 else "")
            next_disp = next_line[:120] + ("…" if len(next_line) > 120 else "")
            emit(f"\n#{i:3d}  [GAP: {gap:.3f}s]")
            emit(f"      BEFORE: {slow_disp}")
            emit(f"       AFTER: {next_disp}")

        # --- Summary by verb + table ---
        emit(f"\n\n{'='*80}")
        emit("SLOW GAPS BY SQL VERB AND TABLE")
        emit("-" * 80)
        all_rows = []
        for verb, tables in summary.items():
            for table, count in tables.items():
                all_rows.append((count, verb, table))
        all_rows.sort(reverse=True)
        emit(f"  {'COUNT':>6}  {'VERB':<10}  TABLE")
        emit(f"  {'------':>6}  {'----------':<10}  -----")
        for count, verb, table in all_rows[:50]:
            emit(f"  {count:>6}  {verb:<10}  {table}")

        emit(f"\nDone.")

    finally:
        if out_file and output is not sys.stdout:
            output.close()
            print(f"Results written to: {out_file}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Find slow SQL operations from SQLAlchemy log")
    parser.add_argument("--log", default="logs/sql.log", help="Path to sql.log (default: logs/sql.log)")
    parser.add_argument("--threshold", type=float, default=1.0, help="Gap threshold in seconds (default: 1.0)")
    parser.add_argument("--top", type=int, default=20, help="Number of top slow gaps to show (default: 20)")
    parser.add_argument("--out", default=None, help="Write output to file instead of stdout")
    args = parser.parse_args()

    analyze(args.log, args.threshold, args.top, args.out)


if __name__ == "__main__":
    main()
