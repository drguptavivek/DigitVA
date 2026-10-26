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
from datetime import UTC, datetime

import sqlalchemy as sa

from app import db

# The catalogues a code can come from.
ICD_CLASSIFICATIONS = ("icd10", "icd11")
DEFAULT_ICD_CLASSIFICATION = "icd10"
# Valid values of va_project_master.icd_classification. A tuple, so an
# unhashable JSON value fails membership instead of raising TypeError. The
# 'selectable' classification (coder picks ICD-10 or ICD-11 per death) is
# retired (digitva-0n3): a project is one classification or the other.
PROJECT_ICD_CLASSIFICATIONS = ICD_CLASSIFICATIONS

# ICD-10: one letter, two digits, optional dotted decimal (e.g. A00, A00.1).
ICD10_CODE_RE = re.compile(r"^\s*([A-Z]\d{2}(?:\.\d+)?)\b", re.IGNORECASE)
# ICD-11 stem code: digit-or-letter, letter, digit, digit-or-letter, optional
# 1-2 char dotted extension (e.g. 1A00, BA00.1, 2C25.Z).
ICD11_CODE_RE = re.compile(
    r"^\s*([0-9A-Z][A-Z][0-9][0-9A-Z](?:\.[0-9A-Z]{1,2})?)\b", re.IGNORECASE
)

# A WHO post-coordinated ICD-11 code is a sequence of stem/extension tokens.
# ``/`` separates alternative expressions and ``&`` joins an extension to a
# stem.  The local catalogue remains authoritative for the stem; this shape
# check only prevents a title or arbitrary text from being treated as part of
# the code before WHO codeinfo verifies the expression.
_ICD11_STEM_PATTERN = r"[0-9A-Z][A-Z][0-9][0-9A-Z](?:\.[0-9A-Z]{1,2})?"
_ICD11_EXTENSION_PATTERN = r"[0-9A-Z]+(?:\.[0-9A-Z]+)?"
ICD11_CODE_EXPRESSION_RE = re.compile(
    rf"(?P<stem>{_ICD11_STEM_PATTERN})"
    rf"(?:&{_ICD11_EXTENSION_PATTERN})*"
    rf"(?:/{_ICD11_STEM_PATTERN}(?:&{_ICD11_EXTENSION_PATTERN})*)*",
    re.IGNORECASE,
)
_ICD11_CODE_EXPRESSION_MAX_LENGTH = 256

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


def extract_icd11_code_expression(value: str | None) -> str | None:
    """Extract a complete leading ICD-11 code expression from a COD value.

    The stored form is ``"<CODE> <title>"``.  For a plain stem this returns
    the stem, while a post-coordinated value such as
    ``"1G40.0&XN8Q/1G41 <title>"`` returns the complete expression.  Only the
    first whitespace-delimited token is considered, and its bounded grammar
    deliberately does not decide whether the expression is a real WHO code;
    that check belongs to ``codeinfo`` validation.

    ``None`` is returned for malformed expressions.  Callers should treat a
    leading ``&`` or ``/`` as an invalid cluster rather than falling back to
    the first stem.
    """
    if not value:
        return None
    match = re.match(r"^\s*(\S+)", value)
    if not match:
        return None
    candidate = match.group(1)
    if len(candidate) > _ICD11_CODE_EXPRESSION_MAX_LENGTH:
        return None
    candidate = candidate.upper()
    if not ICD11_CODE_EXPRESSION_RE.fullmatch(candidate):
        return None
    return candidate


def has_icd11_cluster_marker(value: str | None) -> bool:
    """Whether the leading token attempts ICD-11 post-coordination."""
    if not value:
        return False
    match = re.match(r"^\s*(\S+)", value)
    return bool(match and ("&" in match.group(1) or "/" in match.group(1)))


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
    of ``PROJECT_ICD_CLASSIFICATIONS``, so ODK and web-form submissions
    resolve alike. Defaults to ``icd10`` when the submission, its form or its
    project cannot be found. The per-form
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

    The project's ``icd_classification`` setting (``icd10`` or ``icd11``) is
    the classification checked against. Returns the value's classification.
    Raises ``ValueError`` when the value is not a selectable code for this
    submission and ``LookupError`` when the submission does not exist.
    """
    from app.services.icd10_2019_2_service import (
        validate_icd10_2019_2_coding_value_for_submission,
    )
    from app.services.icd11_mms_service import (
        validate_icd11_mms_coding_value_for_submission,
    )

    classification = get_icd_classification_for_submission(va_sid)
    if classification == "icd10":
        validate_icd10_2019_2_coding_value_for_submission(va_sid, value)
    elif classification == "icd11":
        validate_icd11_mms_coding_value_for_submission(va_sid, value)
    else:
        raise ValueError("Select a valid ICD-10 or ICD-11 code.")
    return classification


def build_icd11_provenance_for_values(
    va_sid: str,
    values: dict[str, str | None],
) -> dict[str, dict] | None:
    """Build server-derived provenance for ICD-11 fields in one assessment.

    ICD-10 values intentionally produce no provenance. The resolver is
    imported lazily to avoid the existing service import cycle.
    """
    from app.services.icd11_mms_service import build_icd11_provenance

    provenance: dict[str, dict] = {}
    for field, value in values.items():
        if classification_of_value(value) != "icd11":
            continue
        item = build_icd11_provenance(va_sid, value)
        if item is not None:
            provenance[field] = item
    return provenance or None


class InvalidCausingConditionFlag(ValueError):
    """``causing_condition_unknown`` sent with a value that is not one ICD-11 stem."""


def check_causing_condition_unknown(value: str | None) -> None:
    """Refuse ``causing_condition_unknown`` unless ``value`` is one ICD-11 stem.

    The flag says WHO's causing condition was not known, so it belongs on a
    stem alone: no ``/`` (``&`` extensions are fine). An ICD-10 value has
    nowhere to record it. Raises ``InvalidCausingConditionFlag``
    (``digitva-xmpx``).
    """
    expression = extract_icd11_code_expression(value)
    if classification_of_value(value) != "icd11" or not expression or "/" in expression:
        raise InvalidCausingConditionFlag(
            "Causing condition not known applies to a single ICD-11 stem code only."
        )


def record_final_cod_flags(
    provenance: dict | None,
    *,
    age_restriction: dict | None,
    causing_condition_unknown: bool,
    confirmed_by,
    doris_result: dict | None,
    field: str = "conclusive",
) -> dict | None:
    """Add a COD pick's confirmation flags to its ``field`` provenance item.

    ``field`` is ``conclusive`` for a final and ``antecedent`` for a masked
    Step 1 underlying cause. ``age_restriction`` is the ``details()`` of the
    ``AgeRestrictionConfirmationRequired`` the coder confirmed, or None.
    ``doris_result`` is the case's processed DORIS envelope
    (``{"status", "result": {"warning", ...}}``) or None; its plausibility
    warning is kept only when it names this code. Both flags only exist for
    ICD-11 values, so an ICD-10 save (``provenance`` None) is returned as is.
    """
    item = (provenance or {}).get(field)
    if item is None:
        return provenance
    if causing_condition_unknown:
        item["causing_condition_unknown"] = True
    if age_restriction is not None:
        warning = ((doris_result or {}).get("result") or {}).get("warning")
        if not (isinstance(warning, str) and age_restriction["code"] in warning):
            warning = None
        item["age_restriction_confirmation"] = {
            "confirmed_by": str(confirmed_by),
            "confirmed_at": datetime.now(UTC).isoformat(),
            "code": age_restriction["code"],
            "age_group_selectable": age_restriction["age_group_selectable"],
            "restriction_note": age_restriction["restriction_note"],
            "doris_warning": warning,
        }
    return provenance


def icd11_primary_stem_of(value: str | None, provenance_item: dict | None = None) -> str | None:
    """The ICD-11 stem a saved value buckets by (``digitva-443q``), or None.

    ``provenance_item`` is the value's own ``icd11_provenance`` entry (for a
    final, ``icd11_provenance["conclusive"]``). Its recorded ``primary_stem``
    (WHO's causing condition) wins when it has the stem shape; otherwise the
    first stem of ``value``, as for rows saved before ``primary_stem``
    existed. The Python twin of ``icd11_primary_stem_sql`` in
    ``submission_analytics_mv``; reads only what it is given, never WHO.
    """
    if isinstance(provenance_item, dict) and isinstance(provenance_item.get("primary_stem"), str):
        stem = extract_icd_code(provenance_item["primary_stem"], "icd11")
        if stem:
            return stem
    return extract_icd_code(value, "icd11")
