"""scripts/check_backup_list.py against sample `flask backups db-list` output."""
import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "check_backup_list", Path(__file__).resolve().parents[1] / "scripts" / "check_backup_list.py"
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

NOW = datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc)
HEAD = (
    "Backup store: s3 · prefix p · keep 7 · daily at 02:00 UTC\n"
    "Successful backups: 3 (1000 bytes recorded)\n"
)


def row(minutes_ago, status="success", err=""):
    ts = (NOW - timedelta(minutes=minutes_ago)).isoformat()
    return f"  {ts}  {status:<8} s3    {1234:>12}  db/x.dump{err}\n"


def test_fresh_success_passes():
    assert mod.check(HEAD + row(2), now=NOW) is None


def test_failed_newest_row_fails_even_though_header_says_successful():
    assert "not success" in mod.check(HEAD + row(2, "failed", "  [E]"), now=NOW)


def test_stale_success_fails():
    assert "old" in mod.check(HEAD + row(300), now=NOW)


def test_no_rows_fails():
    assert mod.check(HEAD + "No backups recorded yet.\n", now=NOW)
