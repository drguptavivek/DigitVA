"""Coding-search demo API — /api/v1/coding-search-demo/

Lets a coder try the real coding search from the help pages, without opening
a death. No submission is involved — age group and sex come from explicit
request args rather than a va_sid — and results are identical to the coding
screen because both classifications call the same search functions the
coding screen uses. Never recorded in cod_search_telemetry: this is practice,
not a real search (docs/policy/icd-coding-search-vocabulary.md).
"""

from flask import Blueprint, jsonify, request

from app.decorators.role_required import role_required
from app.services.icd10_2019_2_service import search_icd10_2019_2_coding_choices_for_policy
from app.services.icd11_mms_service import search_icd11_mms

bp = Blueprint("coding_search_demo_api", __name__)

_CLASSIFICATIONS = ("icd10", "icd11")
_AGE_GROUPS = ("neonate", "infant", "child", "adult")
_SEXES = ("female", "male")


def _error(message: str, status_code: int = 400):
    return jsonify({"error": message}), status_code


@bp.get("/search")
@role_required("coder", "coding_tester", "reviewer", "admin")
def coding_search_demo():
    classification = (request.args.get("classification") or "").strip()
    if classification not in _CLASSIFICATIONS:
        return _error("classification must be 'icd10' or 'icd11'.")

    age_group = (request.args.get("age_group") or "").strip()
    if age_group not in _AGE_GROUPS:
        return _error("age_group must be one of: neonate, infant, child, adult.")

    sex = (request.args.get("sex") or "").strip()
    if sex not in _SEXES:
        return _error("sex must be 'female' or 'male'.")

    query = request.args.get("q", "")
    if classification == "icd10":
        payload = search_icd10_2019_2_coding_choices_for_policy(
            query, age_group=age_group, sex=sex
        )
    else:
        payload = search_icd11_mms(query, age_group=age_group, sex=sex)

    return jsonify(payload)
