"""Classification-aware helpers for stored ICD coding values.

COD values are stored as free text ``"<CODE> <title>"`` in the assessment
tables. ICD-10 and ICD-11 codes have different shapes, so extracting the
code and deciding which catalog a form uses must be classification-aware.
See docs/planning/icd11-coding-screen-integration-plan.md.
"""

from __future__ import annotations

import re

import sqlalchemy as sa

from app import db

ICD_CLASSIFICATIONS = ("icd10", "icd11")
DEFAULT_ICD_CLASSIFICATION = "icd10"

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


def get_icd_classification_for_submission(va_sid: str) -> str:
    """Resolve the ICD classification a submission's form is configured for.

    Path: submission -> va_forms.form_id -> project/site ->
    map_project_site_odk.icd_classification. Defaults to ``icd10`` when the
    submission, its form, or the project-site ODK mapping cannot be found.
    """
    from app.models import MapProjectSiteOdk, VaForms, VaSubmissions

    submission = db.session.get(VaSubmissions, va_sid)
    if submission is None:
        return DEFAULT_ICD_CLASSIFICATION

    form = db.session.get(VaForms, submission.va_form_id)
    if form is None:
        return DEFAULT_ICD_CLASSIFICATION

    mapping = db.session.scalar(
        sa.select(MapProjectSiteOdk).where(
            MapProjectSiteOdk.project_id == form.project_id,
            MapProjectSiteOdk.site_id == form.site_id,
        )
    )
    if mapping is None:
        return DEFAULT_ICD_CLASSIFICATION

    return mapping.icd_classification or DEFAULT_ICD_CLASSIFICATION
