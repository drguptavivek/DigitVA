"""scripts/manual-db-restore.sh: the swap must close connections before renaming.

Exercised for real in digitva-rbj8 (a client connecting after the pre-check made
the rename fail with "being accessed by other users"); this guards the order.
"""
from pathlib import Path

SCRIPT = (Path(__file__).resolve().parents[1] / "scripts" / "manual-db-restore.sh").read_text()


def test_connections_are_blocked_and_terminated_before_the_rename():
    block = SCRIPT[SCRIPT.index("==> Swapping"):]
    deny = block.index("ALLOW_CONNECTIONS false")
    kill = block.index("pg_terminate_backend")
    rename = block.index("RENAME TO")
    assert deny < kill < rename
