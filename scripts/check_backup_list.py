#!/usr/bin/env python3
"""Gate for deploy scripts: read `flask backups db-list --limit 1` on stdin.

Exit 0 only if the first data row (the line after the two header lines,
starting with whitespace and an ISO timestamp) has status "success" and was
started within MAX_AGE_SECONDS (default 900). Anything else exits 1 with the
reason on stderr. Format source: app/commands/backups.py db_list.
"""
import sys
from datetime import datetime, timezone


def check(text, now=None, max_age=900):
    """Return None when the newest backup is fresh and successful, else a reason."""
    now = now or datetime.now(timezone.utc)
    rows = [ln.split() for ln in text.splitlines() if ln[:1] == " " and ln.strip()]
    if not rows:
        return "no backup row in db-list output"
    try:
        started = datetime.fromisoformat(rows[0][0])
    except ValueError:
        return f"unreadable timestamp {rows[0][0]!r}"
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    if len(rows[0]) < 2 or rows[0][1] != "success":
        return f"newest backup status is {rows[0][1:2] or 'missing'}, not success"
    age = (now - started).total_seconds()
    if age > max_age:
        return f"newest successful backup is {int(age)}s old (limit {max_age}s)"
    return None


if __name__ == "__main__":
    reason = check(sys.stdin.read(), max_age=int(sys.argv[1]) if len(sys.argv) > 1 else 900)
    if reason:
        print(reason, file=sys.stderr)
        sys.exit(1)
