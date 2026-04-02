import csv
import logging
import math
import os

import sqlalchemy as sa

from app import db
from app.models import MasChoiceMappings, MasFormTypes, VaSubmissionPayloadVersion, VaSubmissions

log = logging.getLogger(__name__)


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

_HIV_REGION_FIELD = "Id10002"
_MALARIA_REGION_FIELD = "Id10003"
_TRUE_LIKE = {"yes", "y", "true", "1", "high"}
_FALSE_LIKE = {"no", "n", "false", "0", "low", "very low", "verylow"}


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


def _normalize_smartva_flag(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "True" if value else "False"
    normalized = str(value).strip().casefold()
    if not normalized:
        return None
    if normalized in _TRUE_LIKE:
        return "True"
    if normalized in _FALSE_LIKE:
        return "False"
    return None


def _choice_labels_for_form(va_form, field_ids: tuple[str, ...]) -> dict[tuple[str, str], str]:
    if va_form.form_type_id is not None:
        form_type_id = va_form.form_type_id
    else:
        form_type_id = db.session.scalar(
            sa.select(MasFormTypes.form_type_id).where(
                MasFormTypes.form_type_code == "WHO_2022_VA"
            )
        )
    if form_type_id is None:
        return {}

    rows = db.session.execute(
        sa.select(
            MasChoiceMappings.field_id,
            MasChoiceMappings.choice_value,
            MasChoiceMappings.choice_label,
        ).where(
            MasChoiceMappings.form_type_id == form_type_id,
            MasChoiceMappings.field_id.in_(field_ids),
            MasChoiceMappings.is_active.is_(True),
        )
    ).all()
    return {
        (field_id, str(choice_value)): choice_label
        for field_id, choice_value, choice_label in rows
        if choice_value is not None and choice_label is not None
    }


def _derive_run_option(
    payload_rows,
    field_name: str,
    fallback: str,
    *,
    choice_labels: dict[tuple[str, str], str],
) -> tuple[str, bool]:
    seen = {
        normalized
        for _va_sid, payload_data in payload_rows
        for raw_value in [(payload_data or {}).get(field_name)]
        for display_value in [choice_labels.get((field_name, str(raw_value)), raw_value)]
        for normalized in [_normalize_smartva_flag(display_value)]
        if normalized is not None
    }
    if not seen:
        return fallback, False
    if len(seen) == 1:
        return next(iter(seen)), True
    return fallback, False


def _derive_smartva_run_options(va_form, payload_rows) -> dict[str, str | bool]:
    choice_labels = _choice_labels_for_form(
        va_form,
        (_HIV_REGION_FIELD, _MALARIA_REGION_FIELD),
    )
    hiv_value, hiv_overridden = _derive_run_option(
        payload_rows,
        _HIV_REGION_FIELD,
        va_form.form_smartvahiv,
        choice_labels=choice_labels,
    )
    malaria_value, malaria_overridden = _derive_run_option(
        payload_rows,
        _MALARIA_REGION_FIELD,
        va_form.form_smartvamalaria,
        choice_labels=choice_labels,
    )
    return {
        "hiv": hiv_value,
        "malaria": malaria_value,
        "hiv_overridden": hiv_overridden,
        "malaria_overridden": malaria_overridden,
    }


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
    run_options = _derive_smartva_run_options(va_form, payload_rows)

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
        log.info(
            "SmartVA prep [%s]: prepared %d row(s); skipped %d already-complete row(s).",
            va_form.form_id,
            len(prepared_rows),
            skipped,
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

    return {
        "input_path": smartva_input_path,
        "run_options": run_options,
    }
