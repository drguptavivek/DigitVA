import os
import pandas as pd
from datetime import datetime
from flask import current_app
from app.utils.va_odk.va_odk_03_submissionupdatedate import va_odk_submissionupdatedate


def va_preprocess_prepdata(va_form):
    va_formdir = os.path.join(current_app.config["APP_DATA"], va_form.form_id)
    csv_path = os.path.join(va_formdir, f"{va_form.odk_form_id}.csv")
    if os.path.exists(csv_path):
        try:
            df = pd.read_csv(csv_path)
            df = df.replace({pd.NA: None, float("nan"): None})
            submissions = df.to_dict("records")
            update_dates = va_odk_submissionupdatedate(va_form)
            processed_data = []
            for submission in submissions:
                if "form_def" not in submission:
                    submission["form_def"] = va_form.form_id
                if "sid" not in submission:
                    submission["sid"] = (
                        f"{submission.get('KEY')}-{va_form.form_id.lower()}"
                    )
                if "updatedAt" not in submission:
                    submission["updatedAt"] = update_dates.get(submission.get("KEY"))
                if "unique_id2" not in submission and submission.get("unique_id"):
                    submission["unique_id2"] = (
                        submission.get("unique_id").rsplit("_", 1)[0]
                        + "_"
                        + datetime.fromisoformat(submission.get("start")).strftime(
                            "%H%M%S"
                        )
                        + f"{int(datetime.fromisoformat(submission.get('start')).microsecond / 1000):03}"
                    )
                else:
                    submission["unique_id2"] = "Unavailable"
                processed_data.append(submission)
            return processed_data

        except Exception as e:
            raise Exception(
                f"VA Form {va_form.form_id}: Error reading form's .csv data or failed attempt to prepare cleaned data for database with new columns: {str(e)}"
            )
