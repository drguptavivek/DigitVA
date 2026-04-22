"""ICD-10 API — /api/v1/icd10/

Resources:
  GET search   — search ICD-10 codes by display text
"""

import sqlalchemy as sa
import json
from flask import Blueprint, current_app, jsonify, request

from app import cache, db, limiter
from app.authz.access import action_authorized
from app.authz.resources import submission_from_kwarg
from app.models import MasIcd1020192
from app.services.icd10_2019_2_service import (
    export_icd10_2019_2_policy_json,
    get_icd10_2019_2_node_details,
    get_icd10_2019_2_policy_options,
    list_icd10_2019_2_coding_detailed_children,
    search_icd10_2019_2_coding_choices,
    import_icd10_2019_2_policy_json,
    list_icd10_2019_2_children,
    update_icd10_2019_2_policy,
)
from app.utils.va_permission.va_permission_11_require_coding_access import require_coding_access

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

    display_expr = sa.func.concat(MasIcd1020192.code, sa.literal("-"), MasIcd1020192.title)
    lower_code = sa.func.lower(MasIcd1020192.code)
    lower_display = sa.func.lower(display_expr)
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
        sa.select(MasIcd1020192.code, display_expr.label("icd_to_display"))
        .where(
            MasIcd1020192.is_active.is_(True),
            MasIcd1020192.semantic_level.in_(("three_character", "detailed_code")),
            sa.or_(
                lower_code.like(code_prefix, escape=_LIKE_ESCAPE),
                lower_display.like(text_prefix, escape=_LIKE_ESCAPE),
                lower_display.like(text_contains, escape=_LIKE_ESCAPE),
                token_all_match,
            )
        )
        .order_by(rank_expr, MasIcd1020192.code)
        .limit(_ICD_MAX_RESULTS)
    ).all()

    return [{"icd_code": row[0], "icd_to_display": row[1]} for row in results]


def _error(message: str, status_code: int = 400):
    return jsonify({"error": message}), status_code


def _browser_filters_from_request() -> dict[str, str]:
    return {
        "coding_filter": (request.args.get("coding_filter") or "any").strip() or "any",
        "sex_filter": (request.args.get("sex_filter") or "any").strip() or "any",
        "age_filter": (request.args.get("age_filter") or "any").strip() or "any",
    }


@bp.get("/search")
@limiter.limit("20000 per day;5000 per hour")
@action_authorized("icd10_search")
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


@bp.get("/2019-2/coding-search/<va_sid>")
@action_authorized(
    "coding_submission_view",
    resource_resolver=submission_from_kwarg("va_sid"),
)
def icd10_2019_2_coding_search(va_sid: str):
    err = require_coding_access(va_sid)
    if err:
        return err

    try:
        payload = search_icd10_2019_2_coding_choices(
            va_sid=va_sid,
            query=request.args.get("q", ""),
        )
    except LookupError:
        return _error("Submission not found.", 404)
    return jsonify(payload)


@bp.get("/2019-2/coding-children/<va_sid>")
@action_authorized(
    "coding_submission_view",
    resource_resolver=submission_from_kwarg("va_sid"),
)
def icd10_2019_2_coding_children(va_sid: str):
    err = require_coding_access(va_sid)
    if err:
        return err

    parent_code = (request.args.get("parent_code") or "").strip()
    if not parent_code:
        return _error("parent_code is required.", 400)
    try:
        payload = list_icd10_2019_2_coding_detailed_children(va_sid, parent_code)
    except LookupError:
        return _error("Submission not found.", 404)
    return jsonify({"parent_code": parent_code, "children": payload})


@bp.get("/2019-2/children")
@action_authorized("icd10_browser_view")
def icd10_2019_2_children():
    parent_code = (request.args.get("parent_code") or "").strip() or None
    filters = _browser_filters_from_request()
    return jsonify(
        {
            "parent_code": parent_code,
            "children": list_icd10_2019_2_children(parent_code, **filters),
        }
    )


@bp.get("/2019-2/node/<code>")
@action_authorized("icd10_browser_view")
def icd10_2019_2_node(code: str):
    payload = get_icd10_2019_2_node_details(code.strip())
    if payload is None:
        return _error("ICD code not found.", 404)
    return jsonify(payload)


@bp.get("/2019-2/policy-options")
@action_authorized("icd10_browser_view")
def icd10_2019_2_policy_options():
    return jsonify(get_icd10_2019_2_policy_options())


@bp.get("/2019-2/policy-export")
@action_authorized("icd10_browser_view")
def icd10_2019_2_policy_export():
    payload = export_icd10_2019_2_policy_json()
    return current_app.response_class(
        json.dumps(payload, indent=2),
        mimetype="application/json",
        headers={
            "Content-Disposition": 'attachment; filename="icd10_2019_2_policy_export.json"'
        },
    )


@bp.post("/2019-2/policy-import")
@action_authorized("icd10_policy_import")
def icd10_2019_2_policy_import():
    uploaded = request.files.get("file")
    if uploaded is None:
        return _error("file is required.", 400)
    try:
        payload = uploaded.read().decode("utf-8")
    except UnicodeDecodeError:
        return _error("Policy import file must be UTF-8 JSON.", 400)

    try:
        result = import_icd10_2019_2_policy_json(payload)
    except ValueError as exc:
        return _error(str(exc), 400)

    return jsonify(
        {
            "message": "ICD policy import completed.",
            "total_items": result.total_items,
            "updated_items": result.updated_items,
            "reset_items": result.reset_items,
            "skipped_items": result.skipped_items,
            "failed_codes": result.skipped_items,
        }
    )


@bp.patch("/2019-2/node/<code>/policy")
@action_authorized("icd10_policy_update")
def icd10_2019_2_update_policy(code: str):
    body = request.get_json(silent=True) or {}
    try:
        payload = update_icd10_2019_2_policy(
            code=code.strip(),
            is_coding_selectable=body.get("is_coding_selectable"),
            sex_selectable=body.get("sex_selectable"),
            age_group_selectable=body.get("age_group_selectable"),
            restriction_note=body.get("restriction_note"),
        )
    except LookupError:
        return _error("ICD code not found.", 404)
    except ValueError as exc:
        return _error(str(exc), 400)
    return jsonify(payload)
