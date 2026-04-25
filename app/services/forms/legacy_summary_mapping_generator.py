import os
import traceback
import pandas as pd
from flask import current_app


def va_mapping_summary():
    va_summary_var = "va_mapping_summary"
    try:
        df = pd.read_excel(
            os.path.join(
                current_app.config["APP_RESOURCE"], "mapping", "mapping_labels.xlsx"
            )
        )
        filtered_df = df[df.get("summary_include") == "yes"]
        categories = filtered_df["category"].unique()
        dictionaries = {}
        for category in categories:
            category_df = filtered_df[filtered_df["category"] == category]
            category_dict = dict(zip(category_df["name"], category_df["summary_label"]))
            dictionaries[category] = category_dict
        va_summary_file = os.path.join(
            current_app.config["APP_BASEDIR"],
            "app",
            "utils",
            "va_mapping",
            "va_mapping_04_summary.py",
        )
        with open(va_summary_file, "w") as f:
            f.write(f"{va_summary_var} = {{\n")
            for category, value in dictionaries.items():
                f.write(f'    "{category}": ')
                f.write("{\n")
                for name, va_summary_label in value.items():
                    f.write(f'        "{name}": "{va_summary_label}",\n')
                f.write("    },\n")
            f.write("}\n")
        print(f"Success [Mapped: {va_summary_var}].")
    except Exception as e:
        print(f"Failed [Cound not map: {va_summary_var}.]\nError: {e}")
        print(traceback.format_exc())
