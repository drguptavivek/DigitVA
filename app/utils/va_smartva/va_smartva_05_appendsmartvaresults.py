import os
import shutil
import pandas as pd
import sqlalchemy as sa
from flask import current_app
from app.models import VaSmartvaResults, VaStatuses


def va_smartva_appendsmartvaresults(dbsession, va_smartvaoutput_files):
    va_smartva_appendedresults_outputdir = os.path.join(
        current_app.config["APP_DATA"], "SMARTVA_OUTPUT"
    )
    va_smartva_appendedresults_outputfile = os.path.join(
        va_smartva_appendedresults_outputdir, "smartva_output.csv"
    )
    if os.path.exists(va_smartva_appendedresults_outputdir):
        shutil.rmtree(va_smartva_appendedresults_outputdir)
    os.makedirs(va_smartva_appendedresults_outputdir, exist_ok=True)
    va_allsmartvaresults = []
    for va_form, va_smartvaoutput_file in va_smartvaoutput_files.items():
        try:
            df = pd.read_csv(va_smartvaoutput_file)
            df = df.replace({pd.NA: None, float("nan"): None})
            va_allsmartvaresults.append(df)
        except Exception as e:
            raise Exception(
                f"Could not find / format SmartVA output file for '{va_form}'. Error: {e}."
            )
    va_smartvaexistingactiveresults = {
        result.va_sid : result
        for result in dbsession.scalars(
            sa.select(VaSmartvaResults).where(
                VaSmartvaResults.va_smartva_status == VaStatuses.active,
            )
        ).all()
    }
    if va_allsmartvaresults:
        try:
            va_smartvaappendedresults = pd.concat(
                va_allsmartvaresults, ignore_index=True
            )
            va_smartvaappendedresults = va_smartvaappendedresults[
                va_smartvaappendedresults["sid"].notna()
            ]
            va_smartvaappendedresults.to_csv(
                va_smartva_appendedresults_outputfile, index=False
            )
            return va_smartvaappendedresults, va_smartvaexistingactiveresults
        except Exception as e:
            raise Exception(
                f"Could not append / analyse SmartVA output files. Error: {e}."
            )
    return None, va_smartvaexistingactiveresults
