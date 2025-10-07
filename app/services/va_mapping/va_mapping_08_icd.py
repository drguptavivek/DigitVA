import os
import traceback
import pandas as pd
import sqlalchemy as sa
from app import db
from flask import current_app
from app.models import VaIcdCodes


def va_mapping_icd():
    try:
        df = pd.read_excel(
            os.path.join(current_app.config["APP_RESOURCE"], "mapping", "icdcodes.xlsx")
        )
        db.session.execute(sa.delete(VaIcdCodes))
        for _, row in df.iterrows():
            icd_code = VaIcdCodes(
                disease_id=row["Disease_ID"],
                icd_code=str(row["Disease_Code"]),
                icd_to_display=str(row["Disease_Name"]),
                category=str(row["Chapter_Name"])
                if pd.notna(row["Chapter_Name"])
                else None,
            )
            db.session.add(icd_code)
        db.session.commit()
        print(f"Success [Mapped {len(df)} ICD Codes to DB].")
    except Exception as e:
        print(f"Failed [Could not map ICD Codes to DB: {str(e)}]")
        print(traceback.format_exc())
