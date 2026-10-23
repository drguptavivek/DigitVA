"""The rust engine runs in-process through libsmartva_rust.so (SMARTVA_RS_LIB);
an empty SMARTVA_RS_LIB runs the smartva-rs CLI instead."""

import ctypes
import glob
import os
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from app.utils.va_smartva import va_smartva_03_runsmartva as runner
from tests.base import BaseTestCase


def test_bool_flag_accepts_the_cli_spellings():
    for raw in ("true", "True", "T", "yes", "Y", " 1 "):
        assert runner._bool_flag("hce", raw) == 1, raw
    for raw in ("false", "False", "f", "no", "N", " 0 "):
        assert runner._bool_flag("hce", raw) == 0, raw


def test_bool_flag_refuses_anything_else():
    for raw in ("", "maybe", "2", None):
        try:
            runner._bool_flag("hce", raw)
        except ValueError as exc:
            assert "hce" in str(exc)
        else:
            raise AssertionError(f"{raw!r} was accepted")


class FakeLib:
    """Stands in for the loaded library: records the call, writes a file."""

    def __init__(self, rc=0, message=None):
        self.rc, self.message = rc, message
        self.calls, self.freed = [], []

    def smartva_run_directory(self, inp, out, country, hiv, malaria, hce, freetext, figures, error_out):
        self.calls.append((inp, out, country, hiv, malaria, hce, freetext, figures))
        if self.message is not None:
            self.buf = ctypes.create_string_buffer(self.message)
            error_out._obj.value = ctypes.addressof(self.buf)
        with open(os.path.join(os.fsdecode(out), "report.txt"), "w") as handle:
            handle.write("ok")
        return self.rc

    def smartva_free_string(self, ptr):
        self.freed.append(ptr)


def _form(**over):
    fields = dict(
        form_id="F1", form_smartvacountry="IND", form_smartvahiv="False",
        form_smartvamalaria="False", form_smartvahce="True", form_smartvafreetext="false",
    )
    return SimpleNamespace(**{**fields, **over})


class InProcessRunTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        for key in ("SMARTVA_CHARTS", "SMARTVA_ENGINE", "SMARTVA_RS_LIB"):
            self.addCleanup(self.app.config.__setitem__, key, self.app.config.get(key))
        self.app.config["SMARTVA_ENGINE"] = "rust"
        self.app.config["SMARTVA_CHARTS"] = False
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.ws = tmp.name
        with open(os.path.join(self.ws, "smartva_input.csv"), "w") as handle:
            handle.write("sid\n")
        # Any existing file will do as the library path: _rs_lib is faked.
        self.app.config["SMARTVA_RS_LIB"] = os.path.join(self.ws, "smartva_input.csv")

    def _run(self, lib, form=None, **kwargs):
        with mock.patch.object(runner, "_rs_lib", return_value=lib), \
                mock.patch.object(runner.subprocess, "run") as run:
            result = runner.va_smartva_runsmartva(form or _form(), self.ws, **kwargs)
        run.assert_not_called()
        return result

    def test_calls_the_library_with_encoded_paths_and_int_flags(self):
        lib = FakeLib()
        out = self._run(lib, run_options={"hiv": "True", "malaria": "no"})
        self.assertEqual(out, os.path.join(self.ws, "smartva_output"))
        self.assertEqual(
            lib.calls,
            [(
                os.fsencode(os.path.join(self.ws, "smartva_input.csv")),
                os.fsencode(out),
                b"IND", 1, 0, 1, 0, 0,
            )],
        )

    def test_figures_follow_smartva_charts(self):
        self.app.config["SMARTVA_CHARTS"] = True
        lib = FakeLib()
        self._run(lib)
        self.assertEqual(lib.calls[0][-1], 1)

    def test_bad_flag_fails_the_run_before_the_library_is_called(self):
        lib = FakeLib()
        with self.assertRaises(Exception) as caught:
            self._run(lib, form=_form(form_smartvahce="maybe"))
        self.assertIn("hce", str(caught.exception))
        self.assertEqual(lib.calls, [])

    def test_non_zero_rc_raises_with_the_error_text_and_frees_it(self):
        lib = FakeLib(rc=3, message=b"bad input csv")
        with self.assertRaises(Exception) as caught:
            self._run(lib)
        text = str(caught.exception)
        self.assertIn("SmartVA execution failed with code 3", text)
        self.assertIn("bad input csv", text)
        self.assertEqual(lib.freed, [ctypes.addressof(lib.buf)])  # the library's own string, once

    def test_non_zero_rc_without_a_message_still_raises(self):
        with self.assertRaises(Exception) as caught:
            self._run(FakeLib(rc=1))
        self.assertIn("failed with code 1", str(caught.exception))

    def test_missing_library_fails_the_run_without_fallback(self):
        self.app.config["SMARTVA_RS_LIB"] = "/missing/libsmartva_rust.so"
        with mock.patch.object(runner.subprocess, "run") as run:
            with self.assertRaises(RuntimeError) as caught:
                runner.va_smartva_runsmartva(_form(), self.ws)
        run.assert_not_called()
        self.assertIn("/missing/libsmartva_rust.so", str(caught.exception))
        self.assertIn('SMARTVA_RS_LIB=""', str(caught.exception))

    def test_empty_library_path_runs_the_cli_subprocess(self):
        self.app.config["SMARTVA_RS_LIB"] = ""
        self.app.config["SMARTVA_RS_BIN"] = os.path.join(self.ws, "smartva_input.csv")
        with mock.patch.object(runner.os, "access", return_value=True), \
                mock.patch.object(runner.os, "listdir", return_value=["x"]), \
                mock.patch.object(runner.subprocess, "run") as run:
            runner.va_smartva_runsmartva(_form(), self.ws)
        self.assertEqual(run.call_args.args[0][1], "--no-charts")

    def test_python_engine_ignores_the_library(self):
        self.app.config["SMARTVA_ENGINE"] = "python"
        with mock.patch.object(runner, "_rs_lib") as load, \
                mock.patch.object(runner.os, "listdir", return_value=["x"]), \
                mock.patch.object(runner.subprocess, "run") as run:
            runner.va_smartva_runsmartva(_form(), self.ws)
        load.assert_not_called()
        run.assert_called_once()


class EngineVersionTests(BaseTestCase):
    """smartva_engine_info reads the library's own version when the library is
    in use, the binary's --version otherwise."""

    def setUp(self):
        super().setUp()
        for key in ("SMARTVA_ENGINE", "SMARTVA_RS_LIB", "SMARTVA_RS_BIN"):
            self.addCleanup(self.app.config.__setitem__, key, self.app.config.get(key))
        runner._engine_version.cache_clear()
        self.addCleanup(runner._engine_version.cache_clear)
        self.app.config["SMARTVA_ENGINE"] = "rust"
        self.app.config["SMARTVA_RS_BIN"] = "/opt/bin/smartva-rs"
        self.app.config["SMARTVA_RS_LIB"] = "/opt/lib/libsmartva_rust.so"
        self.cli = subprocess.CompletedProcess([], 0, stdout="binary 3.0.1\n", stderr="")

    def test_library_version_is_used_and_no_subprocess_runs(self):
        fn = mock.Mock(return_value=b"SmartVA-Analyze 3.0.1-rust (smartva-rust 3.0.2)\n")
        lib = SimpleNamespace(smartva_version=fn)
        with mock.patch.object(runner, "_rs_lib", return_value=lib) as load, \
                mock.patch.object(runner.subprocess, "run") as run:
            info = runner.smartva_engine_info()
        load.assert_called_once_with("/opt/lib/libsmartva_rust.so")
        fn.assert_called_once_with()
        self.assertEqual(fn.restype, ctypes.c_char_p)
        self.assertEqual(fn.argtypes, [])
        self.assertEqual(
            info, {"name": "rust", "version": "SmartVA-Analyze 3.0.1-rust (smartva-rust 3.0.2)"}
        )
        run.assert_not_called()

    def test_library_without_the_symbol_falls_back_to_the_binary(self):
        lib = SimpleNamespace()  # attribute access raises AttributeError, like a 3.0.1 .so
        with mock.patch.object(runner, "_rs_lib", return_value=lib), \
                mock.patch.object(runner.subprocess, "run", return_value=self.cli) as run, \
                self.assertLogs(runner.log, "WARNING") as logs:
            info = runner.smartva_engine_info()
        self.assertEqual(run.call_args.args[0], ["/opt/bin/smartva-rs", "--version"])
        self.assertEqual(info, {"name": "rust", "version": "binary 3.0.1"})
        self.assertIn("predates smartva_version", logs.output[0])

    def test_library_load_failure_returns_none_without_raising(self):
        with mock.patch.object(runner, "_rs_lib", side_effect=OSError("bad elf")), \
                mock.patch.object(runner.subprocess, "run") as run, \
                self.assertLogs(runner.log, "WARNING"):
            info = runner.smartva_engine_info()
        self.assertEqual(info, {"name": "rust", "version": None})
        run.assert_not_called()

    def test_empty_library_path_reads_the_binary(self):
        self.app.config["SMARTVA_RS_LIB"] = ""
        with mock.patch.object(runner, "_rs_lib") as load, \
                mock.patch.object(runner.subprocess, "run", return_value=self.cli) as run:
            info = runner.smartva_engine_info()
        self.assertEqual(run.call_args.args[0], ["/opt/bin/smartva-rs", "--version"])
        self.assertEqual(info, {"name": "rust", "version": "binary 3.0.1"})
        load.assert_not_called()


def _likelihoods(root):
    pattern = os.path.join(root, "4-monitoring-and-quality", "intermediate-files", "*-likelihoods.csv")
    return {os.path.basename(p): open(p, "rb").read() for p in sorted(glob.glob(pattern))}


def _installed_lib():
    """The real library: SMARTVA_RS_LIB_TEST, else the image's default path."""
    for path in (os.environ.get("SMARTVA_RS_LIB_TEST", ""), runner.DEFAULT_RS_LIB):
        if path and os.path.isfile(path):
            return path
    return None


class RealLibraryErrorTests(unittest.TestCase):
    """Through the real argtypes and error pointer: a missing input makes the
    library fail with its own message, which reaches the caller."""

    def test_library_failure_raises_with_its_message(self):
        lib_path = _installed_lib()
        if lib_path is None:
            self.skipTest("libsmartva_rust.so not installed")
        with tempfile.TemporaryDirectory() as out:
            with self.assertRaises(subprocess.CalledProcessError) as caught:
                runner._run_in_process(
                    _form(), "False", "False", os.path.join(out, "missing.csv"), out, lib_path
                )
        self.assertNotEqual(caught.exception.returncode, 0)
        self.assertTrue(caught.exception.stderr, "the library's error message was lost")


class RealLibraryParityTests(unittest.TestCase):
    """Needs a built library, the CLI binary and a SmartVA input CSV:
    SMARTVA_RS_LIB_TEST, SMARTVA_RS_BIN_TEST, SMARTVA_INPUT_TEST."""

    def test_library_and_cli_write_identical_likelihoods(self):
        lib_path = os.environ.get("SMARTVA_RS_LIB_TEST", "")
        cli = os.environ.get("SMARTVA_RS_BIN_TEST", "")
        csv_in = os.environ.get("SMARTVA_INPUT_TEST", "")
        if not all(os.path.isfile(p) for p in (lib_path, cli, csv_in)):
            self.skipTest("SMARTVA_RS_LIB_TEST / SMARTVA_RS_BIN_TEST / SMARTVA_INPUT_TEST not set")
        with tempfile.TemporaryDirectory() as lib_out, tempfile.TemporaryDirectory() as cli_out:
            lib = runner._rs_lib(lib_path)
            err = ctypes.c_void_p()
            rc = lib.smartva_run_directory(
                csv_in.encode(), lib_out.encode(), b"IND", 0, 0, 1, 1, 0, ctypes.byref(err)
            )
            self.assertEqual(rc, 0, ctypes.string_at(err.value) if err.value else b"")
            subprocess.run(
                [cli, "--no-charts", "--country", "IND", "--hiv", "False", "--malaria", "False",
                 "--hce", "True", "--freetext", "True", csv_in, cli_out],
                check=True, capture_output=True,
            )
            from_lib, from_cli = _likelihoods(lib_out), _likelihoods(cli_out)
        self.assertTrue(from_cli, "the CLI wrote no likelihood files")
        self.assertEqual(from_lib, from_cli)
