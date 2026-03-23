import csv
import math
import os

import sqlalchemy as sa

from app import db
from app.models import VaSubmissionPayloadVersion, VaSubmissions


# Columns that SmartVA does not understand and must be excluded from input.
# Social-autopsy (sa*) modules and telephonic-consent fields added by some
# ICMR training forms cause SmartVA's header mapper to fail with
# "Cannot process data without: gen_5_4*".
_SMARTVA_DROP_PREFIXES = (
    "sa01",
    "sa02",
    "sa03",
    "sa04",
    "sa05",
    "sa06",
    "sa07",
    "sa08",
    "sa09",
    "sa10",
    "sa11",
    "sa12",
    "sa13",
    "sa14",
    "sa15",
    "sa16",
    "sa17",
    "sa18",
    "sa19",
    "sa_",
    "sa_note",
    "sa_tu",
    "survey_block",
    "telephonic_consent",
)

_NAN_CHECK_COLUMNS = (
    "ageInDays",
    "ageInDays2",
    "ageInYears",
    "ageInYearsRemain",
    "ageInMonths",
    "ageInMonthsRemain",
)


def _should_drop(header: str) -> bool:
    clean_header = header.strip()
    return any(clean_header == prefix or clean_header.startswith(prefix)
               for prefix in _SMARTVA_DROP_PREFIXES)


def _is_blank(value) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    if isinstance(value, str) and value.strip().lower() in {"", "nan"}:
        return True
    return False


def _stringify(value) -> str:
    if _is_blank(value):
        return ""
    return str(value)


def _prepared_payload_rows(va_form, pending_sids=None) -> list[tuple[str, dict]]:
    stmt = (
        sa.select(
            VaSubmissions.va_sid,
            VaSubmissionPayloadVersion.payload_data,
        )
        .join(
            VaSubmissionPayloadVersion,
            VaSubmissionPayloadVersion.payload_version_id
            == VaSubmissions.active_payload_version_id,
        )
        .where(VaSubmissions.va_form_id == va_form.form_id)
        .order_by(VaSubmissions.va_sid)
    )
    if pending_sids is not None:
        if not pending_sids:
            return []
        stmt = stmt.where(VaSubmissions.va_sid.in_(pending_sids))

    return list(db.session.execute(stmt).all())


def _clean_payload_for_smartva(payload_data: dict, *, va_sid: str) -> dict:
    row = dict(payload_data or {})

    for column_name in _NAN_CHECK_COLUMNS:
        if column_name in row and _is_blank(row[column_name]):
            row[column_name] = ""

    if (
        "ageInDays" in row
        and "finalAgeInYears" in row
        and _is_blank(row.get("ageInDays"))
        and not _is_blank(row.get("finalAgeInYears"))
    ):
        try:
            row["ageInDays"] = str(round(float(row["finalAgeInYears"]) * 365))
        except (ValueError, TypeError):
            pass

    if (
        not _is_blank(row.get("ageInDays"))
        and _is_blank(row.get("age_neonate_days"))
        and _is_blank(row.get("age_group"))
        and _is_blank(row.get("age_adult"))
    ):
        try:
            age_in_days = float(row["ageInDays"])
            if age_in_days <= 28:
                row["age_neonate_days"] = str(int(age_in_days))
        except (ValueError, TypeError):
            pass

    filtered_row = {
        key: _stringify(value)
        for key, value in row.items()
        if not _should_drop(key)
    }
    filtered_row["sid"] = va_sid
    return filtered_row


def va_smartva_prepdata(va_form, workspace_dir: str, pending_sids=None):
    """Prepare SmartVA input CSV from active payload versions.

    Args:
        va_form: VaForms instance.
        workspace_dir: Path to the ephemeral workspace directory.
        pending_sids: Optional set of submission ids to include.
    """
    smartva_input_path = os.path.join(workspace_dir, "smartva_input.csv")
    payload_rows = _prepared_payload_rows(va_form, pending_sids=pending_sids)

    prepared_rows: list[dict] = []
    skipped = 0
    for va_sid, payload_data in payload_rows:
        if pending_sids is not None and va_sid not in pending_sids:
            skipped += 1
            continue
        prepared_rows.append(
            _clean_payload_for_smartva(payload_data or {}, va_sid=va_sid)
        )

    if pending_sids is not None:
        print(
            f"SmartVA prep [{va_form.form_id}]: "
            f"{len(prepared_rows)} pending, {skipped} already complete — skipped."
        )

    headers: list[str] = []
    for row in prepared_rows:
        for key in row.keys():
            if key not in headers and key != "sid":
                headers.append(key)

    with open(smartva_input_path, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers + ["sid"])
        writer.writeheader()
        for row in prepared_rows:
            writer.writerow(row)

    return smartva_input_path
