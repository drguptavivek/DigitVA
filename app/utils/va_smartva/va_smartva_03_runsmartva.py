import os
import shutil
import subprocess
from flask import current_app


def va_smartva_runsmartva(va_form):
    va_formdir = os.path.join(current_app.config["APP_DATA"], va_form.form_id)
    va_smartva_inputdir = os.path.join(va_formdir, "smartva_input")
    va_smartva_outputdir = os.path.join(va_formdir, "smartva_output")
    if os.path.exists(va_smartva_outputdir):
        shutil.rmtree(va_smartva_outputdir)
    os.makedirs(va_smartva_outputdir, exist_ok=True)
    va_smartva_inputfile = os.path.join(va_smartva_inputdir, "smartva_input.csv")
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
            va_form.form_smartvahiv,
            "--malaria",
            va_form.form_smartvamalaria,
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
