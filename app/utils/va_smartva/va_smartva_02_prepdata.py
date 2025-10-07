import os
import csv
import shutil
from flask import current_app


def va_smartva_prepdata(va_form):
    va_formdir = os.path.join(current_app.config["APP_DATA"], va_form.form_id)
    vacsv_path = os.path.join(va_formdir, f"{va_form.odk_form_id}.csv")
    va_smartvainputdir_path = os.path.join(va_formdir, "smartva_input")
    if os.path.exists(va_smartvainputdir_path):
        shutil.rmtree(va_smartvainputdir_path)
    os.makedirs(va_smartvainputdir_path, exist_ok=True)
    va_smartvainputfile_path = os.path.join(
        va_smartvainputdir_path, "smartva_input.csv"
    )
    if os.path.exists(vacsv_path):
        try:
            nan_check_columns = [
                "ageInDays",
                "ageInDays2",
                "ageInYears",
                "ageInYearsRemain",
                "ageInMonths",
                "ageInMonthsRemain",
            ]
            nan_values = ["nan"]
            with open(vacsv_path, "r", newline="") as f:
                reader = csv.reader(f)
                headers = next(reader)
                key_index = -1
                for i, header in enumerate(headers):
                    if header == "KEY":
                        key_index = i
                        break
                nan_check_indices = []
                for col_name in nan_check_columns:
                    try:
                        col_index = headers.index(col_name)
                        nan_check_indices.append(col_index)
                    except ValueError:
                        print(
                            f"Warning: could not find column '{col_name}' while preparing SmartVA input file for VA Form - {va_form.form_id}."
                        )
                new_headers = headers + ["sid"]
                original_rows = list(reader)
                new_rows = []
                for row in original_rows:
                    for idx in nan_check_indices:
                        if idx < len(row) and row[idx].lower() in nan_values:
                            row[idx] = ""
                    if key_index >= 0 and key_index < len(row):
                        sid_value = f"{row[key_index]}-{va_form.form_id.lower()}"
                        new_row = row + [sid_value]
                    else:
                        new_row = row + [""]
                    new_rows.append(new_row)
            with open(va_smartvainputfile_path, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(new_headers)
                writer.writerows(new_rows)

            return va_smartvainputfile_path

        except Exception as e:
            raise Exception(
                f"VA Form ({va_form.form_id}): Could not prepare the input .csv file for SmartVA. Error: {e}"
            )
