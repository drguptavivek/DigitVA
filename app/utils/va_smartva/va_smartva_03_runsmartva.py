import glob
import logging
import os
import shutil
import subprocess
from flask import current_app

logger = logging.getLogger(__name__)


def _cleanup_smartva_tmp():
    """Remove orphaned PyInstaller _MEI dirs from /tmp.

    SmartVA is a PyInstaller binary that extracts to /tmp/_MEIxxxxxx on each
    run.  If the process crashes or is killed, these dirs are left behind and
    accumulate indefinitely.  Sweeping them before each run keeps /tmp small.
    """
    mei_dirs = glob.glob("/tmp/_MEI*")
    if not mei_dirs:
        return
    removed = 0
    for d in mei_dirs:
        try:
            shutil.rmtree(d, ignore_errors=True)
            removed += 1
        except Exception:
            pass
    if removed:
        logger.info("Cleaned up %d orphaned SmartVA /tmp/_MEI* dirs", removed)


def va_smartva_runsmartva(va_form, workspace_dir: str, *, run_options=None):
    _cleanup_smartva_tmp()

    va_smartva_inputfile = os.path.join(workspace_dir, "smartva_input.csv")
    va_smartva_outputdir = os.path.join(workspace_dir, "smartva_output")
    run_options = run_options or {}
    hiv_value = run_options.get("hiv", va_form.form_smartvahiv)
    malaria_value = run_options.get("malaria", va_form.form_smartvamalaria)
    
    os.makedirs(va_smartva_outputdir, exist_ok=True)
    
    if os.path.exists(va_smartva_inputfile):
        va_smartva_binary = os.path.join(current_app.config["APP_RESOURCE"], "smartva")
        # ! in case the permission issue occurs, un-comment this piece of code from stackoverflow
        # if not os.access(smartva_binary, os.X_OK):
        #    os.chmod(smartva_binary, 0o755)
        cmd = [
            va_smartva_binary,
            "--country",
            va_form.form_smartvacountry,
            "--figures",
            "False",
            "--hiv",
            hiv_value,
            "--malaria",
            malaria_value,
            "--hce",
            va_form.form_smartvahce,
            "--freetext",
            va_form.form_smartvafreetext,
            va_smartva_inputfile,
            va_smartva_outputdir,
        ]
        try:
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
            error_message = f"VA Form ({va_form.form_id}): SmartVA execution failed with code {e.returncode}.\n"
            error_message += f"Command: {' '.join(e.cmd)}\n"
            if e.stdout:
                error_message += f"Stdout: {e.stdout}\n"
            if e.stderr:
                error_message += f"Stderr: {e.stderr}"
            raise Exception(error_message)

        except Exception as e:
            raise Exception(
                f"VA Form ({va_form.form_id}): Failed to run SmartVA. Error: {str(e)}"
            )
