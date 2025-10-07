import os
import shutil
import zipfile
from flask import current_app
from pydub import AudioSegment
from app.utils.va_odk.va_odk_01_clientsetup import va_odk_clientsetup


def va_odk_downloadformdata(va_form):
    client = va_odk_clientsetup()
    va_formdir = os.path.join(current_app.config["APP_DATA"], va_form.form_id)
    if os.path.exists(va_formdir):
        shutil.rmtree(va_formdir)
    os.makedirs(va_formdir, exist_ok=True)
    try:
        params = {}
        params["groupPaths"] = "false"
        zip_response = client.get(
            f"projects/{va_form.odk_project_id}/forms/{va_form.odk_form_id}/submissions.csv.zip",
            params=params,
        )
        if zip_response.status_code != 200:
            raise Exception(
                f"Failed to download VA submissions .zip file for {va_form.form_id}: {zip_response.status_code}, {zip_response.text}"
            )
        zip_path = os.path.join(va_formdir, "submissions.zip")
        with open(zip_path, "wb") as file:
            file.write(zip_response.content)
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(va_formdir)
        os.remove(zip_path)
        va_formmediadir = os.path.join(va_formdir, "media")
        if not os.path.exists(va_formmediadir):
            return va_formdir
        # .amr -> .mp3
        print(f"VA Form {va_form.form_id}: Converting .amr files to .mp3 files")
        total_amr_files = 0
        converted_amr_files = 0
        error_amr_files = 0
        for filename in os.listdir(va_formmediadir):
            if filename.lower().endswith(".amr"):
                total_amr_files += 1
                amr_path = os.path.join(va_formmediadir, filename)
                mp3_path = os.path.join(
                    va_formmediadir, filename.rsplit(".", 1)[0] + ".mp3"
                )
                if os.path.exists(mp3_path) and os.path.getmtime(
                    mp3_path
                ) > os.path.getmtime(amr_path):
                    continue
                try:
                    print(f"DataSync Process [VA form {va_form.form_id}: Converting {filename} to .mp3].")
                    audio = AudioSegment.from_file(amr_path, format="amr")
                    audio.export(mp3_path, format="mp3")
                    converted_amr_files += 1
                    os.remove(amr_path)
                except Exception as e:
                    error_amr_files += 1
                    print(
                        f"VA Form {va_form.form_id}: Error converting {filename} to mp3: {str(e)}"
                    )
        print(
            f"VA Form {va_form.form_id} .amr to .mp3 conversions complete (total .amr files: {total_amr_files}, converted to .mp3: {converted_amr_files}, failed to convert: {error_amr_files}"
        )
        return va_formdir

    except Exception as e:
        raise Exception(
            f"VA Form {va_form.form_id} -> failed to download / extract submissions or convert .amrs to .mp3 for some unknown reason: {str(e)}"
        )
