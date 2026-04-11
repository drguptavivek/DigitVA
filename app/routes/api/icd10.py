"""ICD-10 API — /api/v1/icd10/

Resources:
  GET search   — search ICD-10 codes by display text
"""

import sqlalchemy as sa
from flask import Blueprint, current_app, jsonify, request
from flask_login import login_required

from app import cache, db, limiter
from app.models import VaIcdCodes

bp = Blueprint("icd10_api", __name__)

_ICD_MIN_QUERY_LEN = 2
_ICD_MAX_RESULTS = 20
_LIKE_ESCAPE = "\\"
_ICD_CACHE_KEY_PREFIX = "icd_search:v2:"


def _normalize_query(raw_query: str) -> str:
    return " ".join((raw_query or "").strip().lower().split())


def _escape_like(value: str) -> str:
    return (
        value.replace(_LIKE_ESCAPE, _LIKE_ESCAPE * 2)
        .replace("%", f"{_LIKE_ESCAPE}%")
        .replace("_", f"{_LIKE_ESCAPE}_")
    )


def _search_icd_cached(normalized_query: str) -> list[dict[str, str]]:
    tokens = [token for token in normalized_query.split(" ") if token]
    escaped_tokens = [_escape_like(token) for token in tokens]
    escaped_query = _escape_like(normalized_query)
    code_prefix = f"{escaped_tokens[0]}%" if escaped_tokens else f"{escaped_query}%"
    text_prefix = f"{escaped_query}%"
    text_contains = f"%{escaped_query}%"

    lower_code = sa.func.lower(VaIcdCodes.icd_code)
    lower_display = sa.func.lower(VaIcdCodes.icd_to_display)
    token_contains_clauses = [
        lower_display.like(f"%{token}%", escape=_LIKE_ESCAPE) for token in escaped_tokens
    ]
    token_all_match = sa.and_(*token_contains_clauses) if token_contains_clauses else sa.false()

    rank_expr = sa.case(
        (lower_code == normalized_query, 0),
        (lower_code.like(code_prefix, escape=_LIKE_ESCAPE), 1),
        (lower_display.like(text_prefix, escape=_LIKE_ESCAPE), 2),
        (lower_display.like(text_contains, escape=_LIKE_ESCAPE), 3),
        (token_all_match, 4),
        else_=5,
    )

    results = db.session.execute(
        sa.select(VaIcdCodes.icd_code, VaIcdCodes.icd_to_display)
        .where(
            sa.or_(
                lower_code.like(code_prefix, escape=_LIKE_ESCAPE),
                lower_display.like(text_prefix, escape=_LIKE_ESCAPE),
                lower_display.like(text_contains, escape=_LIKE_ESCAPE),
                token_all_match,
            )
        )
        .order_by(rank_expr, VaIcdCodes.icd_code)
        .limit(_ICD_MAX_RESULTS)
    ).all()

    return [{"icd_code": row[0], "icd_to_display": row[1]} for row in results]


@bp.get("/search")
@limiter.limit("20000 per day;5000 per hour")
@login_required
def icd10_search():
    normalized_query = _normalize_query(request.args.get("q", ""))
    if len(normalized_query) < _ICD_MIN_QUERY_LEN:
        return jsonify([])

    cache_key = f"{_ICD_CACHE_KEY_PREFIX}{normalized_query}"
    cached = cache.get(cache_key)
    if cached is not None:
        return jsonify(cached)

    payload = _search_icd_cached(normalized_query)
    cache.set(
        cache_key,
        payload,
        timeout=current_app.config.get("ICD_SEARCH_CACHE_TIMEOUT", 60 * 60 * 24 * 7),
    )
    return jsonify(payload)
