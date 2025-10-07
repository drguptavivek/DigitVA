import os
import traceback
import pandas as pd
from flask import current_app


def va_mapping_choice():
    mapping_name = "va_mapping_choice"
    try:
        df = pd.read_excel(
            os.path.join(
                current_app.config["APP_RESOURCE"], "mapping", "mapping_choices.xlsx"
            )
        )
        filtered_df = df[df["category"].notna()]
        categories = filtered_df["category"].unique()
        dictionaries = {}
        for category in categories:
            category_df = filtered_df[filtered_df["category"] == category]
            category_dict = dict(zip(category_df["name"], category_df["short_label"]))
            dictionaries[category] = category_dict
        save_to = os.path.join(
            current_app.config["APP_BASEDIR"],
            "app",
            "utils",
            "va_mapping",
            "va_mapping_03_choice.py",
        )
        with open(save_to, "w") as f:
            f.write(f"{mapping_name} = {{\n")
            for category, value in dictionaries.items():
                f.write(f'    "{category}": ')
                f.write("{\n")
                for name, short_label in value.items():
                    f.write(f'        "{name}": "{short_label}",\n')
                f.write("    },\n")
            f.write("}\n")
        print(f"Success [Mapped: {mapping_name}].")
    except Exception as e:
        print(f"Failed [Cound not map: {mapping_name}.]\nError: {e}")
        print(traceback.format_exc())
