"""ICD-11 API — /api/v1/icd11/

Resources:
  GET coding-search/<va_sid>?q=   selectable ICD-11 MMS categories for one
                                  death's coding screen, filtered by its age
                                  and sex policy. Refused for a project whose
                                  ICD classification is icd10
                                  (docs/policy/va-form-project-configuration.md,
                                  "5. ICD classification").
"""

from flask import Blueprint, jsonify, request

from app.decorators.role_required import role_required
from app.routes.api.icd10 import _error, _require_coding_or_reviewing_access
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
        return _error("This project codes in ICD-10.", 400)

    try:
        payload = search_icd11_mms(request.args.get("q", ""), va_sid=va_sid)
    except LookupError:
        return _error("Submission not found.", 404)
    return jsonify(payload)
