"""Process startup: a forked child must not reuse the parent's pooled DB
connection, and beat's app has no routes. Each runs in a fresh interpreter."""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _run(code):
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


FORK_CODE = """
import json, os
import sqlalchemy as sa
from config import TestConfig
from app import create_app, db

app = create_app(TestConfig)
with app.app_context():
    db.session.execute(sa.text("SELECT 1"))
    db.session.remove()
    parent_before = db.engine.pool.checkedin()
    read, write = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.write(write, str(db.engine.pool.checkedin()).encode())
        os._exit(0)
    os.waitpid(pid, 0)
    child = int(os.read(read, 16))
    parent_after = db.session.execute(sa.text("SELECT 1")).scalar()
print(json.dumps({"parent_before": parent_before, "child": child, "parent_after": parent_after}))
"""


def test_forked_child_drops_inherited_db_pool():
    out = _run(FORK_CODE)
    assert out["parent_before"] == 1
    assert out["child"] == 0
    assert out["parent_after"] == 1



ROUTES_CODE = """
import json, sys
from config import TestConfig
from app import create_app

app = create_app(TestConfig, register_routes=False)
print(json.dumps({
    "endpoints": sorted({r.endpoint for r in app.url_map.iter_rules()}),
    "routes_modules": sorted(m for m in sys.modules if m.startswith("app.routes")),
    "celery": "celery" in app.extensions,
}))
"""


def test_beat_app_has_no_routes():
    out = _run(ROUTES_CODE)
    assert out["celery"] is True
    assert out["endpoints"] == ["static"]
    assert out["routes_modules"] == []
