import os
import traceback
import pandas as pd
from flask import current_app


def va_mapping_summaryflip():
    flip_var = "va_mapping_summaryflip"
    try:
        df = pd.read_excel(
            os.path.join(
                current_app.config["APP_RESOURCE"], "mapping", "mapping_labels.xlsx"
            )
        )
        flip_names = (
            df[df.get("flip_color") == "flip"]["summary_label"]
            .dropna()
            .unique()
            .tolist()
        )
        flip_file = os.path.join(
            current_app.config["APP_BASEDIR"],
            "app",
            "utils",
            "va_mapping",
            "va_mapping_05_summaryflip.py",
        )
        with open(flip_file, "w") as f:
            f.write(f"{flip_var} = {flip_names}\n")
        print(f"Success [Mapped: {flip_var}].")
    except Exception as e:
        print(f"Failed [Cound not map: {flip_var}.]\nError: {e}")
        print(traceback.format_exc())
