"""VA cause definitions API — /api/v1/va-definitions

GET /          ?q=   active WHO VA cause definitions in code order, for the
                     coder "VA Definitions" modal and the help page.
GET /for-icd   ?code=&classification=icd10|icd11
                     the VA cause definition an ICD code maps to (through the
                     COD bucket scheme), for the floating reference panel on
                     the coding screens; 404 when there is none.
Stored HTML is already sanitized (docs/policy/va-cause-definitions.md).
"""

from flask import Blueprint, jsonify, request

from app.decorators.role_required import role_required
from app.services.icd_coding_value import ICD_CLASSIFICATIONS
from app.services.va_cause_definition_service import (
    find_va_definition_for_icd,
    list_coder_va_definitions,
)

bp = Blueprint("va_definitions_api", __name__)

_MAX_QUERY_LEN = 100
_MAX_CODE_LEN = 300  # a stored coding value is "CODE-title"


@bp.get("")
@role_required("coder", "coding_tester", "reviewer", "admin")
def va_definitions():
    query = (request.args.get("q") or "")[:_MAX_QUERY_LEN]
    return jsonify(list_coder_va_definitions(query))


@bp.get("/for-icd")
@role_required("coder", "coding_tester", "reviewer", "admin")
def va_definition_for_icd():
    code = (request.args.get("code") or "")[:_MAX_CODE_LEN]
    classification = (request.args.get("classification") or "").strip().lower() or None
    if classification is not None and classification not in ICD_CLASSIFICATIONS:
        return jsonify({"error": "classification must be icd10 or icd11."}), 400
    found = find_va_definition_for_icd(code, classification)
    if found is None:
        return jsonify({"error": "No VA definition for this code."}), 404
    return jsonify(found)
