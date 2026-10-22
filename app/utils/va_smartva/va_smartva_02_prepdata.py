import csv
import logging
import math
import os
import re

import sqlalchemy as sa

from app import db
from app.models import VaSubmissionPayloadVersion, VaSubmissions
from app.services.pii_field_registry import PII_FIELDS, sealed_field_ids

log = logging.getLogger(__name__)


# SmartVA reads only Id####[_tag], age* and is* columns (plus sid) from a WHO
# input (vendor smartva/who_prep.py and data/who_data.py). It also classifies
# the file as WHO only when more than 80% of the headers match this pattern
# (workerthread.who_questionaire_test), so any other column, such as intake
# metadata or sa* modules, is excluded rather than denylisted: the next
# metadata key must not push a web or ingested payload over the threshold.
_SMARTVA_COLUMN = re.compile(r"^[Ii]d\d+(_\w+)?$|^age|^is")


_NAN_CHECK_COLUMNS = (
    "ageInDays",
    "ageInDays2",
    "ageInYears",
    "ageInYearsRemain",
    "ageInMonths",
    "ageInMonthsRemain",
)


def _smartva_reads(header: str) -> bool:
    # SmartVA keeps only the last "-"-separated segment of a header.
    name = header.strip().replace(":", "-").replace("/", "-").split("-")[-1]
    return name == "sid" or bool(_SMARTVA_COLUMN.match(name))


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



# Provenance labels for an option that did not come from an org unit.
SOURCE_FORM_FLAG = "form flag"
SOURCE_DEFAULT = "default"

# Area preset value -> SmartVA option. Anything else never reaches here (the
# column is check-constrained to high/low/veryl).
_PRESET_TO_OPTION = {"high": "True", "low": "False", "veryl": "False"}

# SmartVA option -> area preset field it is read from.
_OPTION_PRESET_FIELDS = (("hiv", "hiv_mortality"), ("malaria", "malaria_mortality"))


def _derive_smartva_run_options(va_form, va_sids) -> dict[str, dict]:
    """Resolve SmartVA's hiv/malaria options for each submission.

    Per option, independently: the area preset of the submission's org unit
    (nearest ancestor with a value, ``high`` -> on, ``low``/``veryl`` -> off),
    else the form's ``form_smartvahiv`` / ``form_smartvamalaria`` flag, else
    off. The submission's own Id10002/Id10003 answers are not used. See
    docs/policy/smartva-generation-policy.md ("Per-Form Execution Options").

    Two queries however many submissions there are (their org units, then one
    ltree containment query for every unit's presets), never one per row.

    Returns ``{va_sid: {"hiv": "True"|"False", "malaria": ..., "hiv_source":
    <unit id str> | "form flag" | "default", "malaria_source": ...}}``.
    """
    # Imported here: the service layer imports this util package.
    from app.services.org_grant_service import resolve_unit_va_presets

    va_sids = set(va_sids)
    if not va_sids:
        return {}

    unit_by_sid = dict(
        db.session.execute(
            sa.select(VaSubmissions.va_sid, VaSubmissions.org_unit_id).where(
                VaSubmissions.va_sid.in_(va_sids)
            )
        ).all()
    )
    unit_ids = {unit_id for unit_id in unit_by_sid.values() if unit_id is not None}
    presets = resolve_unit_va_presets(unit_ids) if unit_ids else {}

    flags = {
        "hiv": getattr(va_form, "form_smartvahiv", None),
        "malaria": getattr(va_form, "form_smartvamalaria", None),
    }
    resolved: dict[str, dict] = {}
    for va_sid in va_sids:
        fields = presets.get(unit_by_sid.get(va_sid), {})
        options: dict[str, str] = {}
        for option, preset_field in _OPTION_PRESET_FIELDS:
            entry = fields.get(preset_field)
            if entry is not None:
                options[option] = _PRESET_TO_OPTION[entry["value"]]
                options[f"{option}_source"] = str(entry["source_unit_id"])
            elif flags[option] in ("True", "False"):
                options[option] = flags[option]
                options[f"{option}_source"] = SOURCE_FORM_FLAG
            else:
                options[option] = "False"
                options[f"{option}_source"] = SOURCE_DEFAULT
        resolved[va_sid] = options
    return resolved


def group_sids_by_run_options(options_by_sid: dict[str, dict]) -> dict[tuple[str, str], set[str]]:
    """Split submissions by the (hiv, malaria) option set SmartVA runs with.

    Shared by the service and the offline runner so both split alike.
    """
    groups: dict[tuple[str, str], set[str]] = {}
    for va_sid, options in options_by_sid.items():
        groups.setdefault((options["hiv"], options["malaria"]), set()).add(va_sid)
    return groups


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


def _clean_payload_for_smartva(payload_data: dict, *, va_sid: str,
                               sealed: frozenset[str] = frozenset(PII_FIELDS)) -> dict:
    """One SmartVA input row. *sealed* fields (personal data: names, places,
    the national ID, registration details) are dropped: SmartVA scores none
    of them, it only copies Id10017/Id10018/Id10057/Id10073 into its output
    files (docs/kb/smart-va/demographic-general.md; PII policy OD7)."""
    row = {key: value for key, value in (payload_data or {}).items() if key not in sealed}

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
        if _smartva_reads(key)
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
    # Imported here, as in _derive_smartva_run_options: it reaches the service layer.
    from app.utils.va_form.va_form_02_formtyperesolution import va_get_form_type_code_from_form

    sealed = sealed_field_ids(va_get_form_type_code_from_form(va_form))

    prepared_rows: list[dict] = []
    skipped = 0
    for va_sid, payload_data in payload_rows:
        if pending_sids is not None and va_sid not in pending_sids:
            skipped += 1
            continue
        prepared_rows.append(
            _clean_payload_for_smartva(payload_data or {}, va_sid=va_sid, sealed=sealed)
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

    return {"input_path": smartva_input_path}
