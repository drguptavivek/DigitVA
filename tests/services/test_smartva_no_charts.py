"""SmartVA without charts or matplotlib unless SMARTVA_CHARTS is on
(app/utils/va_smartva/smartva_cli_no_charts.py). The launcher replaces
matplotlib for its whole process, so it is checked in a child process."""

import os
import subprocess
import sys
from types import SimpleNamespace
from unittest import mock

from tests.base import BaseTestCase

LAUNCHER = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "app", "utils", "va_smartva", "smartva_cli_no_charts.py"
))

_PROBE = f"""
import runpy, sys
runpy.run_path({LAUNCHER!r}, run_name="probe")
from smartva import output_prep
m = sys.modules["matplotlib"]
assert type(m).__name__ == "_NoMatplotlib" and not hasattr(m, "__file__")
for name in ("_graph_gbd_csmf", "_graph_all_csmf"):
    assert getattr(output_prep.OutputPrep, name)(object()) is None
try:
    m.pyplot.subplots()
except RuntimeError:
    print("ok")
"""


def test_the_launcher_runs_smartva_without_matplotlib_or_its_charts():
    result = subprocess.run([sys.executable, "-c", _PROBE], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def _command(app, charts):
    from app.utils.va_smartva import va_smartva_03_runsmartva as runner

    form = SimpleNamespace(
        form_id="F1", form_smartvacountry="IND", form_smartvahiv="False", form_smartvamalaria="False",
        form_smartvahce="True", form_smartvafreetext="True",
    )
    app.config["SMARTVA_CHARTS"] = charts
    with mock.patch.object(runner.os.path, "exists", return_value=True), \
            mock.patch.object(runner.os, "makedirs"), \
            mock.patch.object(runner.os, "listdir", return_value=["x"]), \
            mock.patch.object(runner.subprocess, "run") as run:
        runner.va_smartva_runsmartva(form, "/tmp/ws")
    return run.call_args.args[0]


class RunnerChartsSwitchTests(BaseTestCase):
    def test_charts_only_when_switched_on(self):
        original = self.app.config.get("SMARTVA_CHARTS")
        self.addCleanup(self.app.config.__setitem__, "SMARTVA_CHARTS", original)
        off = _command(self.app, False)
        on = _command(self.app, True)
        self.assertEqual(off[1], LAUNCHER)
        self.assertEqual(off[off.index("--figures") + 1], "False")
        self.assertEqual(on[1:3], ["-m", "smartva.va_cli"])
        self.assertEqual(on[on.index("--figures") + 1], "True")
