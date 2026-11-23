"""Importing a KPI service first in a fresh interpreter (worker, script) must
not hit a circular import through the route package (digitva-r8nh.16)."""

import pathlib
import subprocess
import sys

import pytest

KPI_DIR = pathlib.Path(__file__).resolve().parent.parent / "app" / "services" / "kpi"
MODULES = sorted(p.stem for p in KPI_DIR.glob("*.py") if p.stem != "__init__")


@pytest.mark.parametrize("module", MODULES)
def test_kpi_service_imports_first_in_fresh_interpreter(module):
    result = subprocess.run(
        [sys.executable, "-c", f"import app.services.kpi.{module}"],
        capture_output=True,
        text=True,
        cwd=KPI_DIR.parent.parent.parent,
    )
    assert result.returncode == 0, result.stderr[-2000:]
