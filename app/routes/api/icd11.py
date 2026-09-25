"""ICD-11 API — /api/v1/icd11/

Resources:
  GET coding-search/<va_sid>?q=   selectable ICD-11 MMS categories for one
                                  death's coding screen, filtered by its age
                                  and sex policy. Refused for a project whose
                                  ICD classification is icd10
                                  (docs/policy/va-form-project-configuration.md,
                                  "5. ICD classification").
"""

import time

from flask import Blueprint, jsonify, request
from flask_login import current_user

from app.decorators.role_required import role_required
from app.routes.api.icd10 import _error, _require_coding_or_reviewing_access
from app.services import coding_search_telemetry_service
from app.services.icd11_mms_service import search_icd11_mms
from app.services.icd_coding_value import get_icd_classification_for_submission

bp = Blueprint("icd11_api", __name__)


@bp.get("/coding-search/<va_sid>")
@role_required("coder", "coding_tester", "reviewer", "admin")
def icd11_coding_search(va_sid: str):
    err = _require_coding_or_reviewing_access(va_sid)
    if err:
        return err
    if get_icd_classification_for_submission(va_sid) == "icd10":
        return _error("This project codes in ICD-11.", 400)

    search_id = coding_search_telemetry_service.resolve_search_id(
        request.args.get("search_id")
    )
    try:
        started = time.perf_counter()
        payload = search_icd11_mms(request.args.get("q", ""), va_sid=va_sid)
        latency_ms = round((time.perf_counter() - started) * 1000)
    except LookupError:
        return _error("Submission not found.", 404)
    # Response payload is built: recording happens now and cannot alter it.
    coding_search_telemetry_service.record_search_request(
        search_id=search_id,
        surface=coding_search_telemetry_service.SURFACE_ICD11,
        query_text=request.args.get("q", ""),
        payload=payload,
        latency_ms=latency_ms,
        user=current_user,
    )
    response = jsonify(payload)
    # The browser learns the id even when it did not send one, so the COD
    # save can forward it and the choice lands on the right search row.
    response.headers["X-Search-Id"] = str(search_id)
    return response
