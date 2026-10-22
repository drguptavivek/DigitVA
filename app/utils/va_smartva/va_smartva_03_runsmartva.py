import ctypes
import functools
import importlib.metadata
import logging
import os
import subprocess
import sys

from flask import current_app, has_app_context

log = logging.getLogger(__name__)

ENGINES = ("rust", "python")
DEFAULT_RS_BIN = "/usr/local/bin/smartva-rs"
DEFAULT_RS_LIB = "/usr/local/lib/libsmartva_rust.so"
_TRUE_FLAGS = {"true", "t", "yes", "y", "1"}
_FALSE_FLAGS = {"false", "f", "no", "n", "0"}


def _engine_settings() -> tuple[str, str]:
    """(engine, smartva-rs path) from config; rust and its default path
    outside an app context. An unknown engine raises: a typo must not pick
    an engine silently."""
    config = current_app.config if has_app_context() else {}
    engine = config.get("SMARTVA_ENGINE", "rust")
    if engine not in ENGINES:
        raise ValueError(f"SMARTVA_ENGINE must be one of {ENGINES}, got {engine!r}.")
    return engine, config.get("SMARTVA_RS_BIN", DEFAULT_RS_BIN)


def _rs_lib_path() -> str:
    """Path of libsmartva_rust.so for the in-process rust engine; "" means run
    the smartva-rs CLI subprocess instead (the rollback)."""
    config = current_app.config if has_app_context() else {}
    return config.get("SMARTVA_RS_LIB", DEFAULT_RS_LIB)


def _charts_enabled() -> bool:
    # Charts only when SMARTVA_CHARTS is on (debugging).
    return bool(has_app_context() and current_app.config.get("SMARTVA_CHARTS", False))


@functools.cache
def _rs_lib(path: str):
    """The loaded library, with C signatures set; loaded once per process so
    the engine's trained-model cache lives as long as the worker."""
    lib = ctypes.CDLL(path)
    lib.smartva_run_directory.argtypes = [
        ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    lib.smartva_run_directory.restype = ctypes.c_int
    # c_void_p, not c_char_p: ctypes would copy a c_char_p result and drop the
    # pointer that smartva_free_string needs.
    lib.smartva_free_string.argtypes = [ctypes.c_void_p]
    lib.smartva_free_string.restype = None
    return lib


def _bool_flag(option: str, raw: str) -> int:
    """1/0 for the spellings the smartva-rs CLI accepts (its parse_bool_flag);
    anything else raises, so the library cannot read a flag differently."""
    value = str(raw).strip().lower()
    if value in _TRUE_FLAGS:
        return 1
    if value in _FALSE_FLAGS:
        return 0
    raise ValueError(f"{option} must be true or false, got {raw!r}.")


def _run_in_process(va_form, hiv_value, malaria_value, inputfile, outputdir, lib_path) -> None:
    """Run the rust engine through libsmartva_rust.so: the same directory
    pipeline as the CLI, writing the same tree into *outputdir*. A failure is
    raised as CalledProcessError so it is reported like a CLI failure."""
    lib = _rs_lib(lib_path)
    error_out = ctypes.c_void_p()
    rc = lib.smartva_run_directory(
        os.fsencode(inputfile),
        os.fsencode(outputdir),
        va_form.form_smartvacountry.encode(),
        _bool_flag("hiv", hiv_value),
        _bool_flag("malaria", malaria_value),
        _bool_flag("hce", va_form.form_smartvahce),
        _bool_flag("freetext", va_form.form_smartvafreetext),
        int(_charts_enabled()),
        ctypes.byref(error_out),
    )
    message = ""
    if error_out.value:
        message = ctypes.string_at(error_out.value).decode(errors="replace")
        lib.smartva_free_string(error_out.value)
    if rc != 0:
        raise subprocess.CalledProcessError(rc, "smartva_run_directory", stderr=message)


@functools.lru_cache(maxsize=4)
def _engine_version(engine: str, rs_bin: str) -> str | None:
    """The engine's version string, or None when it cannot be read (never raises)."""
    try:
        if engine == "python":
            return importlib.metadata.version("smartva")
        result = subprocess.run(
            [rs_bin, "--version"], capture_output=True, text=True, timeout=10, check=True
        )
        return result.stdout.strip() or None
    except Exception:
        log.warning("SmartVA: could not read the %s engine version.", engine, exc_info=True)
        return None


def smartva_engine_info() -> dict:
    """``{"name": "rust"|"python", "version": str|None}`` recorded on each run.
    The rust version is read from the binary; the library ships in the same
    verified release tarball, so it is the version the library runs too."""
    engine, rs_bin = _engine_settings()
    return {"name": engine, "version": _engine_version(engine, rs_bin)}


def _smartva_command(va_form, hiv_value, malaria_value, inputfile, outputdir) -> list[str]:
    """The SmartVA command line for the configured engine. Both engines take
    the same va_cli flags and write the same CSV tree into *outputdir*.
    Raises when the rust engine is selected and its binary is missing: no
    silent fallback, so the engine recorded on the run is the one that ran."""
    engine, rs_bin = _engine_settings()
    charts = _charts_enabled()
    if engine == "rust":
        if not (os.path.isfile(rs_bin) and os.access(rs_bin, os.X_OK)):
            raise RuntimeError(
                f"VA Form ({va_form.form_id}): SMARTVA_ENGINE is rust but the "
                f"smartva-rs binary is missing at {rs_bin}. Install it, or set "
                "SMARTVA_ENGINE=python to roll back."
            )
        # smartva-rs draws charts by default in directory mode: always say which.
        prefix = [rs_bin, *(["--charts", "True"] if charts else ["--no-charts"])]
    else:
        # Python: SmartVA's own CLI with figures when charts are on; otherwise
        # the launcher, which runs SmartVA without matplotlib at all (no
        # charts, no font cache).
        launcher = (
            ["-m", "smartva.va_cli"] if charts
            else [os.path.join(os.path.dirname(__file__), "smartva_cli_no_charts.py")]
        )
        prefix = [sys.executable, *launcher, "--figures", "True" if charts else "False"]
    return [
        *prefix,
        "--country", va_form.form_smartvacountry,
        "--hiv", hiv_value,
        "--malaria", malaria_value,
        "--hce", va_form.form_smartvahce,
        "--freetext", va_form.form_smartvafreetext,
        inputfile,
        outputdir,
    ]


def va_smartva_runsmartva(va_form, workspace_dir: str, *, run_options=None):
    va_smartva_inputfile = os.path.join(workspace_dir, "smartva_input.csv")
    va_smartva_outputdir = os.path.join(workspace_dir, "smartva_output")
    run_options = run_options or {}
    hiv_value = run_options.get("hiv", va_form.form_smartvahiv)
    malaria_value = run_options.get("malaria", va_form.form_smartvamalaria)

    os.makedirs(va_smartva_outputdir, exist_ok=True)

    if os.path.exists(va_smartva_inputfile):
        engine, _ = _engine_settings()
        lib_path = _rs_lib_path() if engine == "rust" else ""
        if lib_path:
            if not os.path.isfile(lib_path):
                raise RuntimeError(
                    f"VA Form ({va_form.form_id}): SMARTVA_ENGINE is rust but the "
                    f"libsmartva_rust.so library is missing at {lib_path}. Install it, "
                    'or set SMARTVA_RS_LIB="" to run the smartva-rs CLI.'
                )
        else:
            cmd = _smartva_command(
                va_form, hiv_value, malaria_value, va_smartva_inputfile, va_smartva_outputdir
            )
        try:
            if lib_path:
                _run_in_process(
                    va_form, hiv_value, malaria_value,
                    va_smartva_inputfile, va_smartva_outputdir, lib_path,
                )
            else:
                subprocess.run(
                    cmd,
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
            if not os.path.exists(va_smartva_outputdir) or not os.listdir(
                va_smartva_outputdir
            ):
                raise Exception(
                    f"VA Form ({va_form.form_id}): SmartVA processed succesfully yet did not produce any output files."
                )
            return va_smartva_outputdir
        except subprocess.CalledProcessError as e:
            stderr_tail = (e.stderr or "")[-500:]
            log.error(
                "SmartVA [%s]: process exited %d — stderr: %s",
                va_form.form_id, e.returncode, stderr_tail,
            )
            error_message = (
                f"VA Form ({va_form.form_id}): SmartVA execution failed with code {e.returncode}."
                + (f"\nStdout: {e.stdout}" if e.stdout else "")
                + (f"\nStderr: {e.stderr}" if e.stderr else "")
            )
            raise Exception(error_message)

        except Exception as e:
            log.error("SmartVA [%s]: unexpected error — %s", va_form.form_id, e, exc_info=True)
            raise Exception(
                f"VA Form ({va_form.form_id}): Failed to run SmartVA. Error: {str(e)}"
            )
