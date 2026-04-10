import io
import os
import pandas as pd
from flask import current_app
from app.utils.va_smartva.va_smartva_01_icdcodes import VA_SMARTVA_ICDS


def _read_csv_no_nulls(file_path: str) -> pd.DataFrame:
    """Read CSV stripping null bytes first — pandas C parser truncates at \\x00."""
    with open(file_path, "rb") as fh:
        raw = fh.read()
    if b"\x00" in raw:
        raw = raw.replace(b"\x00", b"")
    return pd.read_csv(io.BytesIO(raw))


def va_smartva_formatsmartvaresult(va_form, workspace_dir: str):
    va_smartva_outputdir = os.path.join(workspace_dir, "smartva_output")
    va_smartva_outputfile = os.path.join(workspace_dir, "smartva_output.csv")
    if os.path.exists(va_smartva_outputdir) or os.listdir(va_smartva_outputdir):
        try:
            va_smartva_icddict = (
                VA_SMARTVA_ICDS.get("NEONATE") | VA_SMARTVA_ICDS.get("CHILD") | VA_SMARTVA_ICDS.get("ADULT")
            )
            va_smartva_resultfiles = {
                "for_adult": os.path.join(
                    va_smartva_outputdir,
                    "4-monitoring-and-quality",
                    "intermediate-files",
                    "adult-likelihoods.csv",
                ),
                "for_child": os.path.join(
                    va_smartva_outputdir,
                    "4-monitoring-and-quality",
                    "intermediate-files",
                    "child-likelihoods.csv",
                ),
                "for_neonate": os.path.join(
                    va_smartva_outputdir,
                    "4-monitoring-and-quality",
                    "intermediate-files",
                    "neonate-likelihoods.csv",
                ),
            }
            va_smartva_allresults = []
            for result_for, file_path in va_smartva_resultfiles.items():
                if os.path.exists(file_path):
                    df = _read_csv_no_nulls(file_path)
                    df["result_for"] = result_for
                    df["cause1_icd"] = df["cause1"].map(va_smartva_icddict)
                    df["cause2_icd"] = df["cause2"].map(va_smartva_icddict)
                    df["cause3_icd"] = df["cause3"].map(va_smartva_icddict)
                    va_smartva_allresults.append(df)
            if va_smartva_allresults:
                va_smartva_combinedresults = pd.concat(
                    va_smartva_allresults, ignore_index=True
                )
                va_smartva_combinedresults.to_csv(va_smartva_outputfile, index=False)
                return va_smartva_outputfile
            return None
        except Exception as e:
            raise Exception(
                f"VA Form ({va_form.form_id}): Could not format the SmartVA output into the format required for the VA coding platform. Error: {e}"
            )
    else:
        raise Exception(
            f"VA Form ({va_form.form_id}): Could not find the SmartVA result for the VA form. Please re-check."
        )
