"""Opt-in explanation of age/sex-excluded matches for the coding searches (digitva-e5j).

The coding-search endpoints answer a bare JSON list; a client that sends
``explain=1`` gets ``{"results": [...], "excluded": {...}}`` instead, so
existing clients (mobile included) keep the list shape. ``excluded`` appears
only when matches were removed by the age/sex policy and the selectable
results do not fill a page; it is informational and never selectable.
"""

from __future__ import annotations

from app.services.icd10_2019_2_service import excluded_icd10_2019_2_matches
from app.services.icd11_mms_service import excluded_icd11_mms_matches


def explained_payload(
    results: list,
    *,
    classification: str,
    query: str,
    age_group: str | None,
    sex: str | None,
) -> dict:
    """Wrap ``results`` with the policy-excluded matches, when there are any."""
    find_excluded = (
        excluded_icd10_2019_2_matches if classification == "icd10" else excluded_icd11_mms_matches
    )
    body: dict = {"results": results}
    excluded = find_excluded(
        query, age_group=age_group, sex=sex, selectable_count=len(results)
    )
    if excluded:
        body["excluded"] = excluded
    return body
