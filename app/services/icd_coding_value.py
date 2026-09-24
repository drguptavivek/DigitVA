"""Classification-aware helpers for stored ICD coding values.

COD values are stored as free text ``"<CODE> <title>"`` in the assessment
tables. ICD-10 and ICD-11 codes have different shapes, so extracting the
code and deciding which catalog a death is coded in must be
classification-aware. The project decides which catalogues its coders may use
(``va_project_master.icd_classification``); a stored value records its own
classification through its code shape. Policy:
docs/policy/va-form-project-configuration.md ("5. ICD classification").
"""

from __future__ import annotations

import re

import sqlalchemy as sa

from app import db

# The catalogues a code can come from.
ICD_CLASSIFICATIONS = ("icd10", "icd11")
DEFAULT_ICD_CLASSIFICATION = "icd10"
# A project setting, not a catalogue: the coder picks ICD-10 or ICD-11 per death.
ICD_CLASSIFICATION_SELECTABLE = "selectable"
# Valid values of va_project_master.icd_classification. A tuple, so an
# unhashable JSON value fails membership instead of raising TypeError.
PROJECT_ICD_CLASSIFICATIONS = ICD_CLASSIFICATIONS + (ICD_CLASSIFICATION_SELECTABLE,)

# ICD-10: one letter, two digits, optional dotted decimal (e.g. A00, A00.1).
ICD10_CODE_RE = re.compile(r"^\s*([A-Z]\d{2}(?:\.\d+)?)\b", re.IGNORECASE)
# ICD-11 stem code: digit-or-letter, letter, digit, digit-or-letter, optional
# 1-2 char dotted extension (e.g. 1A00, BA00.1, 2C25.Z).
ICD11_CODE_RE = re.compile(
    r"^\s*([0-9A-Z][A-Z][0-9][0-9A-Z](?:\.[0-9A-Z]{1,2})?)\b", re.IGNORECASE
)

_CODE_RE_BY_CLASSIFICATION = {
    "icd10": ICD10_CODE_RE,
    "icd11": ICD11_CODE_RE,
}


def extract_icd_code(value: str | None, classification: str) -> str | None:
    """Extract the leading ICD code from a stored coding value.

    ``classification`` must be one of ``ICD_CLASSIFICATIONS``. Returns the
    upper-cased code, or ``None`` if ``value`` is empty or does not match the
    classification's code shape.
    """
    if classification not in _CODE_RE_BY_CLASSIFICATION:
        raise ValueError(f"Unknown ICD classification: {classification!r}")
    if not value:
        return None
    match = _CODE_RE_BY_CLASSIFICATION[classification].match(value)
    if not match:
        return None
    return match.group(1).upper()


def classification_of_value(value: str | None) -> str | None:
    """The classification a stored coding value's code shape names, or None.

    ICD-10 (``A00.1``) and ICD-11 (``1A00``, ``BA00.1``) shapes do not
    overlap, so an already-coded value never needs the project setting.
    """
    for classification in ICD_CLASSIFICATIONS:
        if extract_icd_code(value, classification):
            return classification
    return None


def get_icd_classification_for_submission(va_sid: str) -> str:
    """The ICD classification setting of a submission's project.

    Path: submission -> va_forms.project_id -> va_project_master. Returns one
    of ``PROJECT_ICD_CLASSIFICATIONS`` (``selectable`` included), so ODK and
    web-form submissions resolve alike. Defaults to ``icd10`` when the
    submission, its form or its project cannot be found. The per-form
    ``map_project_site_odk.icd_classification`` is deprecated and not read.
    """
    from app.models import VaForms, VaProjectMaster, VaSubmissions

    setting = db.session.scalar(
        sa.select(VaProjectMaster.icd_classification)
        .join(VaForms, VaForms.project_id == VaProjectMaster.project_id)
        .join(VaSubmissions, VaSubmissions.va_form_id == VaForms.form_id)
        .where(VaSubmissions.va_sid == va_sid)
    )
    return setting or DEFAULT_ICD_CLASSIFICATION


def validate_coding_value_for_submission(va_sid: str, value: str | None) -> str:
    """Check a COD value against the catalogue its project allows.

    A project set to ``icd10`` or ``icd11`` checks against that catalogue; a
    ``selectable`` project checks against the catalogue the value's code
    shape names. Returns the value's classification. Raises ``ValueError``
    when the value is not a selectable code for this submission and
    ``LookupError`` when the submission does not exist.
    """
    from app.services.icd10_2019_2_service import (
        validate_icd10_2019_2_coding_value_for_submission,
    )
    from app.services.icd11_mms_service import (
        validate_icd11_mms_coding_value_for_submission,
    )

    setting = get_icd_classification_for_submission(va_sid)
    classification = (
        classification_of_value(value)
        if setting == ICD_CLASSIFICATION_SELECTABLE
        else setting
    )
    if classification == "icd10":
        validate_icd10_2019_2_coding_value_for_submission(va_sid, value)
    elif classification == "icd11":
        validate_icd11_mms_coding_value_for_submission(va_sid, value)
    else:
        raise ValueError("Select a valid ICD-10 or ICD-11 code.")
    return classification
