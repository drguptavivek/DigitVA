import os
import traceback
import pandas as pd
from flask import current_app


def va_mapping_fieldcoder():
    mapping_name = "va_mapping_fieldcoder"
    try:
        df = pd.read_excel(
            os.path.join(
                current_app.config["APP_RESOURCE"], "mapping", "mapping_labels.xlsx"
            )
        )
        filtered_df = df[
            (df["category"].notna())
            & ((df.get("permission") != "pm") | (df.get("permission").isna()))
        ]
        categories = filtered_df["category"].unique()
        dictionaries = {}
        for category in categories:
            category_df = filtered_df[filtered_df["category"] == category]
            subcategory_dict = {}
            subcategories = category_df["sub_category"].dropna().unique()
            for subcat in subcategories:
                subcat_df = category_df[category_df["sub_category"] == subcat]
                subcat_mapping = dict(zip(subcat_df["name"], subcat_df["short_label"]))
                subcategory_dict[subcat] = subcat_mapping
            dictionaries[category] = subcategory_dict
        save_to = os.path.join(
            current_app.config["APP_BASEDIR"],
            "app",
            "utils",
            "va_mapping",
            "va_mapping_02_fieldcoder.py",
        )
        with open(save_to, "w") as f:
            f.write(f"{mapping_name} = {{\n")
            for category, value in dictionaries.items():
                f.write(f'    "{category}": ')
                f.write("{\n")
                for subcat, mapping in value.items():
                    f.write(f'        "{subcat}": {{\n')
                    for name, short_label in mapping.items():
                        f.write(f'            "{name}": "{short_label}",\n')
                    f.write("        },\n")
                f.write("    },\n")
            f.write("}\n")
        print(f"Success [Mapped :{mapping_name}].")
    except Exception as e:
        print(f"Failed [Cound not map: {mapping_name}.]\nError: {e}")
        print(traceback.format_exc())
