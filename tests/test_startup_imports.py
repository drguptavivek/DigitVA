"""Process startup must not import the heavy data libraries.

pandas, numpy, pyodk and openpyxl cost tens of MB per process. Every web and
Celery process runs ``create_app()`` at startup (gunicorn through ``run``,
Celery through ``make_celery``), so they must be imported only by the code
paths that use them. Runs in a subprocess because this process has
long since imported them.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest import TestCase

REPO_ROOT = Path(__file__).resolve().parents[1]
HEAVY = ("pandas", "numpy", "pyodk", "openpyxl")

# Each entry point runs in its own process: create_app() cannot run twice.
ENTRY_POINTS = {
    "make_celery": "import make_celery; assert make_celery.flask_app is not None",
    "run": "import run; assert run.app is not None",
}
CODE = """
import json, sys
{entry}
print("APP_CREATED")
print(json.dumps([m for m in {heavy!r} if m in sys.modules]))
"""


class StartupImportTests(TestCase):
    def test_create_app_does_not_import_heavy_libraries(self):
        for name, entry in ENTRY_POINTS.items():
            with self.subTest(entry_point=name):
                done = subprocess.run(
                    [sys.executable, "-c", CODE.format(entry=entry, heavy=HEAVY)],
                    env=os.environ.copy(),
                    cwd=REPO_ROOT,
                    capture_output=True,
                    text=True,
                    timeout=180,
                )
                self.assertEqual(done.returncode, 0, done.stderr)
                lines = done.stdout.strip().splitlines()
                self.assertIn("APP_CREATED", lines, done.stdout + done.stderr)
                self.assertEqual(json.loads(lines[-1]), [])
