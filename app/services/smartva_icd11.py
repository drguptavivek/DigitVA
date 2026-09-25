"""Read-only WHO ICD-10 to ICD-11 display mapping for SmartVA results."""

from functools import lru_cache

from app.services.icd11_policy_draft_service import load_icd10_to_icd11


@lru_cache(maxsize=1)
def _crosswalk():
    return load_icd10_to_icd11()


def smartva_icd11_mapping(icd10_code):
    """Return the full WHO target expression, without choosing an alternative."""
    if not icd10_code or not isinstance(icd10_code, str):
        return None
    code = icd10_code.strip().upper()
    if not code or code == "NAN":
        return None
    return _crosswalk().get(code)
