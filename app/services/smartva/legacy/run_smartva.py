import logging
import os
import subprocess
import sys

log = logging.getLogger(__name__)


def va_smartva_runsmartva(va_form, workspace_dir: str, *, run_options=None):
    va_smartva_inputfile = os.path.join(workspace_dir, "smartva_input.csv")
    va_smartva_outputdir = os.path.join(workspace_dir, "smartva_output")
    run_options = run_options or {}
    hiv_value = run_options.get("hiv", va_form.form_smartvahiv)
    malaria_value = run_options.get("malaria", va_form.form_smartvamalaria)

    os.makedirs(va_smartva_outputdir, exist_ok=True)

    if os.path.exists(va_smartva_inputfile):
        cmd = [
            sys.executable, "-m", "smartva.va_cli",
            "--country", va_form.form_smartvacountry,
            "--figures", "False",
            "--hiv", hiv_value,
            "--malaria", malaria_value,
            "--hce", va_form.form_smartvahce,
            "--freetext", va_form.form_smartvafreetext,
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
