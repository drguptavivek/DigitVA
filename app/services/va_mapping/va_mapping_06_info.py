import os
import traceback
import pandas as pd
from flask import current_app


def va_mapping_info():
    info_var = "va_mapping_info"
    try:
        df = pd.read_excel(
            os.path.join(
                current_app.config["APP_RESOURCE"], "mapping", "mapping_labels.xlsx"
            )
        )
        info_names = (
            df[df.get("is_info") == "info"]["short_label"].dropna().unique().tolist()
        )
        info_file = os.path.join(
            current_app.config["APP_BASEDIR"],
            "app",
            "utils",
            "va_mapping",
            "va_mapping_06_info.py",
        )
        with open(info_file, "w") as f:
            f.write(f"{info_var} = {info_names}\n")
        print(f"Success [Mapped: {info_var}].")
    except Exception as e:
        print(f"Failed [Cound not map: {info_var}.]\nError: {e}")
        print(traceback.format_exc())
