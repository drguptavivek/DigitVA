"""ICD-10 API — /api/v1/icd10/

Resources:
  GET search   — search ICD-10 codes by display text
"""

import sqlalchemy as sa
from flask import Blueprint, jsonify, request
from flask_login import login_required

from app import db
from app.models import VaIcdCodes

bp = Blueprint("icd10_api", __name__)


@bp.get("/search")
@login_required
def icd10_search():
    query = request.args.get("q", "")
    results = db.session.execute(
        sa.select(VaIcdCodes.icd_code, VaIcdCodes.icd_to_display)
        .where(VaIcdCodes.icd_to_display.ilike(f"%{query}%"))
        .limit(20)
    ).all()
    return jsonify([{"icd_code": r[0], "icd_to_display": r[1]} for r in results])
