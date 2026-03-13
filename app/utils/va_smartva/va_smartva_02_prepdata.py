import os
import csv
import shutil
from flask import current_app

# Columns that SmartVA does not understand and must be excluded from input.
# Social-autopsy (sa*) modules and telephonic-consent fields added by some
# ICMR training forms cause SmartVA's header mapper to fail with
# "Cannot process data without: gen_5_4*".
_SMARTVA_DROP_PREFIXES = ("sa01", "sa02", "sa03", "sa04", "sa05", "sa06",
                          "sa07", "sa08", "sa09", "sa10", "sa11", "sa12",
                          "sa13", "sa14", "sa15", "sa16", "sa17", "sa18",
                          "sa19", "sa_", "sa_note", "sa_tu",
                          "survey_block", "telephonic_consent")


def _should_drop(header: str) -> bool:
    h = header.strip()
    return any(
        h == p or h.startswith(p)
        for p in _SMARTVA_DROP_PREFIXES
    )


def va_smartva_prepdata(va_form, pending_sids=None):
    """Prepare the SmartVA input CSV for va_form.

    Args:
        va_form: VAForm instance.
        pending_sids: Optional set of sid strings. When provided, only rows
            whose computed sid is in this set are written to the input file.
            Pass None (default) to include all rows (e.g. full re-analysis).
    """
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

                # ── Locate columns of interest (original indices) ──────────
                key_index = next(
                    (i for i, h in enumerate(headers) if h == "KEY"), -1
                )
                nan_check_indices = []
                for col_name in nan_check_columns:
                    try:
                        nan_check_indices.append(headers.index(col_name))
                    except ValueError:
                        print(
                            f"Warning: could not find column '{col_name}' while "
                            f"preparing SmartVA input file for VA Form - {va_form.form_id}."
                        )
                try:
                    age_in_days_idx = headers.index("ageInDays")
                    final_age_years_idx = headers.index("finalAgeInYears")
                except ValueError:
                    age_in_days_idx = -1
                    final_age_years_idx = -1

                # ── Decide which columns to keep (drop SA / non-standard) ──
                keep_mask = [not _should_drop(h) for h in headers]
                keep_indices = [i for i, keep in enumerate(keep_mask) if keep]
                filtered_headers = [headers[i] for i in keep_indices]

                # Remap key_index to filtered position
                filtered_key_index = (
                    keep_indices.index(key_index)
                    if key_index >= 0 and key_index in keep_indices
                    else -1
                )

                # ── Process rows ───────────────────────────────────────────
                original_rows = list(reader)
                new_rows = []
                skipped = 0
                for row in original_rows:
                    # 1. Replace "nan" strings with "" in age columns
                    for idx in nan_check_indices:
                        if idx < len(row) and row[idx].lower() in nan_values:
                            row[idx] = ""

                    # 2. Derive ageInDays from finalAgeInYears when missing.
                    #    SmartVA needs ageInDays to compute gen_5_4* age-group
                    #    flags. Some form versions (e.g. training forms where
                    #    birth/death dates are unknown) omit ageInDays but still
                    #    capture finalAgeInYears.
                    if (
                        age_in_days_idx >= 0
                        and final_age_years_idx >= 0
                        and age_in_days_idx < len(row)
                        and final_age_years_idx < len(row)
                        and row[age_in_days_idx] == ""
                        and row[final_age_years_idx] not in ("", "nan")
                    ):
                        try:
                            row[age_in_days_idx] = str(
                                round(float(row[final_age_years_idx]) * 365)
                            )
                        except (ValueError, TypeError):
                            pass

                    # 3. Drop non-standard columns
                    filtered_row = [row[i] if i < len(row) else "" for i in keep_indices]

                    # 4. Compute sid
                    if filtered_key_index >= 0:
                        sid_value = (
                            f"{filtered_row[filtered_key_index]}-{va_form.form_id.lower()}"
                        )
                    else:
                        sid_value = ""

                    # 5. Skip rows that already have an active SmartVA result
                    if pending_sids is not None and sid_value not in pending_sids:
                        skipped += 1
                        continue

                    new_rows.append(filtered_row + [sid_value])

                if pending_sids is not None:
                    print(
                        f"SmartVA prep [{va_form.form_id}]: "
                        f"{len(new_rows)} pending, {skipped} already complete — skipped."
                    )

            with open(va_smartvainputfile_path, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(filtered_headers + ["sid"])
                writer.writerows(new_rows)

            return va_smartvainputfile_path

        except Exception as e:
            raise Exception(
                f"VA Form ({va_form.form_id}): Could not prepare the input .csv file for SmartVA. Error: {e}"
            )
