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


def _command(app, charts, engine="python", rs_present=True):
    """The argv the runner passes to subprocess.run for *engine*."""
    from app.utils.va_smartva import va_smartva_03_runsmartva as runner

    form = SimpleNamespace(
        form_id="F1", form_smartvacountry="IND", form_smartvahiv="False", form_smartvamalaria="False",
        form_smartvahce="True", form_smartvafreetext="True",
    )
    app.config["SMARTVA_CHARTS"] = charts
    app.config["SMARTVA_ENGINE"] = engine
    app.config["SMARTVA_RS_BIN"] = "/opt/bin/smartva-rs"
    with mock.patch.object(runner.os.path, "exists", return_value=True), \
            mock.patch.object(runner.os.path, "isfile", return_value=rs_present), \
            mock.patch.object(runner.os, "access", return_value=rs_present), \
            mock.patch.object(runner.os, "makedirs"), \
            mock.patch.object(runner.os, "listdir", return_value=["x"]), \
            mock.patch.object(runner.subprocess, "run") as run:
        runner.va_smartva_runsmartva(form, "/tmp/ws")
    return run.call_args.args[0]


def _restore_runner_config(case):
    for key in ("SMARTVA_CHARTS", "SMARTVA_ENGINE", "SMARTVA_RS_BIN"):
        case.addCleanup(case.app.config.__setitem__, key, case.app.config.get(key))


class RunnerChartsSwitchTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        _restore_runner_config(self)

    def test_charts_only_when_switched_on(self):
        off = _command(self.app, False)
        on = _command(self.app, True)
        self.assertEqual(off[1], LAUNCHER)
        self.assertEqual(off[off.index("--figures") + 1], "False")
        self.assertEqual(on[1:3], ["-m", "smartva.va_cli"])
        self.assertEqual(on[on.index("--figures") + 1], "True")


class RunnerEngineTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        _restore_runner_config(self)

    def test_engine_defaults_to_rust(self):
        from config import Config

        if "SMARTVA_ENGINE" in os.environ or "SMARTVA_RS_BIN" in os.environ:
            self.skipTest("engine overridden in the environment")
        self.assertEqual(Config.SMARTVA_ENGINE, "rust")
        self.assertEqual(Config.SMARTVA_RS_BIN, "/usr/local/bin/smartva-rs")

    def test_rust_engine_runs_smartva_rs_with_the_same_arguments(self):
        python_cmd = _command(self.app, False, engine="python")
        off = _command(self.app, False, engine="rust")
        on = _command(self.app, True, engine="rust")
        self.assertEqual(off[:2], ["/opt/bin/smartva-rs", "--no-charts"])
        self.assertEqual(on[:3], ["/opt/bin/smartva-rs", "--charts", "True"])
        # Same va_cli flags, input and output dir as the Python engine.
        tail = python_cmd[python_cmd.index("--country"):]
        self.assertEqual(off[2:], tail)
        self.assertEqual(tail[-2:], ["/tmp/ws/smartva_input.csv", "/tmp/ws/smartva_output"])

    def test_missing_rust_binary_fails_the_run_without_fallback(self):
        from app.utils.va_smartva import va_smartva_03_runsmartva as runner

        with mock.patch.object(runner.subprocess, "run") as run:
            with self.assertRaises(Exception) as caught:
                _command(self.app, False, engine="rust", rs_present=False)
        run.assert_not_called()
        self.assertIn("/opt/bin/smartva-rs", str(caught.exception))
        self.assertIn("SMARTVA_ENGINE=python", str(caught.exception))

    def test_unknown_engine_is_refused(self):
        with self.assertRaises(Exception) as caught:
            _command(self.app, False, engine="java")
        self.assertIn("SMARTVA_ENGINE", str(caught.exception))

    def test_engine_info_reports_name_and_version(self):
        from app.utils.va_smartva import va_smartva_03_runsmartva as runner

        runner._engine_version.cache_clear()
        self.addCleanup(runner._engine_version.cache_clear)
        self.app.config["SMARTVA_ENGINE"] = "rust"
        self.app.config["SMARTVA_RS_BIN"] = "/opt/bin/smartva-rs"
        done = subprocess.CompletedProcess([], 0, stdout="smartva-rs 0.2.0\n", stderr="")
        with mock.patch.object(runner.subprocess, "run", return_value=done) as run:
            self.assertEqual(runner.smartva_engine_info(), {"name": "rust", "version": "smartva-rs 0.2.0"})
        self.assertEqual(run.call_args.args[0], ["/opt/bin/smartva-rs", "--version"])

        with mock.patch.object(runner.subprocess, "run", side_effect=FileNotFoundError):
            self.app.config["SMARTVA_RS_BIN"] = "/missing/smartva-rs"
            self.assertEqual(runner.smartva_engine_info(), {"name": "rust", "version": None})

        self.app.config["SMARTVA_ENGINE"] = "python"
        python_info = runner.smartva_engine_info()
        self.assertEqual(python_info["name"], "python")
        self.assertTrue(python_info["version"])
