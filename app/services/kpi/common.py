"""SQL fragments every DM KPI query shares (digitva-r8nh.16).

Each KPI module used to declare these two on its own; the strings are the
same, so they live here once.
"""

from app.services.duplicate_exclusion import not_confirmed_duplicate_sql
from app.services.odk_retirement_service import in_odk_sql

# Retired submissions are not counted (docs/policy/odk-retired-submissions.md).
IN_ODK_SQL = in_odk_sql("s")
# Confirmed-duplicate web cases leave every count (app/services/duplicate_exclusion.py).
NOT_DUPLICATE_SQL = not_confirmed_duplicate_sql("s.va_sid")
