"""ICD search vocabulary admin panel and JSON API (digitva-zpe.1).

Admin-managed table of clinician shorthand and diagnosis synonyms wired into
the coding-search endpoints (docs/policy/icd-coding-search-vocabulary.md).
Extends the ``admin`` blueprint the same way ``app/routes/admin_icd11.py``
does. There is no delete: deactivation keeps audit history. Admin notes are
reviewed text, so CSV export neutralises spreadsheet formulas like the other
exports (``va_code_mapping_public_service.csv_cell``).
"""

import csv
import io
import uuid

from flask import current_app, jsonify, render_template, request
from flask_login import current_user

from app.decorators import role_required
from app.routes.admin import _json_error, admin
from app.services.icd_search_vocabulary_service import (
    DEFAULT_PAGE_SIZE,
    code_in_catalogue,
    create_term,
    get_term,
    list_terms,
    serialize_term,
    set_active,
    update_term,
    vocabulary_stats,
)
from app.services.va_code_mapping_public_service import csv_cell

CSV_HEADERS = (
    "term",
    "term_normalized",
    "icd_classification",
    "icd_code",
    "source",
    "note",
    "sort_order",
    "is_active",
    "created_at",
    "updated_at",
)


def _admin_only():
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)
    return None


def _term_id_arg(term_id: str):
    """``(uuid, error_response)``; ids travel as path segments."""
    try:
        return uuid.UUID(term_id), None
    except (ValueError, AttributeError):
        return None, _json_error("term_id must be a UUID.", 400)


def _body():
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else None


def _classification_label(classification: str) -> str:
    return "ICD-10" if classification == "icd10" else "ICD-11"


def _code_warning(classification: str, icd_code: str) -> str | None:
    """Soft warning when the target code is absent from its catalogue; the
    save itself always goes through."""
    if code_in_catalogue(classification, icd_code):
        return None
    return (
        f"{_classification_label(classification)} code {icd_code} was not found in the "
        "active catalogue. Saved anyway — it may arrive with the next catalogue refresh."
    )


@admin.get("/panels/icd-search-vocabulary")
@role_required("admin")
def admin_panel_icd_search_vocabulary():
    return render_template(
        "admin/panels/icd_search_vocabulary.html",
        stats=vocabulary_stats(),
    )


@admin.get("/api/icd-search-vocabulary")
@role_required("admin")
def admin_icd_search_vocabulary_list():
    if (denied := _admin_only()) is not None:
        return denied
    search = (request.args.get("q") or "").strip()
    try:
        page = int(request.args.get("page") or 1)
        per_page = int(request.args.get("per_page") or DEFAULT_PAGE_SIZE)
    except ValueError:
        return _json_error("page and per_page must be integers.", 400)
    return jsonify(list_terms(search=search, page=page, per_page=per_page))


@admin.get("/api/icd-search-vocabulary/term/<term_id>")
@role_required("admin")
def admin_icd_search_vocabulary_get(term_id: str):
    """One vocabulary row, for the edit modal."""
    if (denied := _admin_only()) is not None:
        return denied
    key, error = _term_id_arg(term_id)
    if error is not None:
        return error
    try:
        row = get_term(key)
    except LookupError:
        return _json_error("Vocabulary term not found.", 404)
    return jsonify(serialize_term(row))


@admin.post("/api/icd-search-vocabulary")
@role_required("admin")
def admin_icd_search_vocabulary_create():
    if (denied := _admin_only()) is not None:
        return denied
    body = _body()
    if body is None:
        return _json_error("A JSON object body is required.", 400)
    try:
        row = create_term(
            term=body.get("term"),
            icd_classification=body.get("icd_classification"),
            icd_code=body.get("icd_code"),
            note=body.get("note"),
            sort_order=body.get("sort_order"),
        )
    except ValueError as exc:
        return _json_error(str(exc), 400)

    current_app.logger.info(
        "ICD search vocabulary term created by user %s: term=%r -> %s %s",
        current_user.user_id,
        row.term,
        row.icd_classification,
        row.icd_code,
    )
    return jsonify(
        {
            "term": serialize_term(row),
            "code_warning": _code_warning(row.icd_classification, row.icd_code),
        }
    )


@admin.patch("/api/icd-search-vocabulary/term/<term_id>")
@role_required("admin")
def admin_icd_search_vocabulary_update(term_id: str):
    if (denied := _admin_only()) is not None:
        return denied
    key, error = _term_id_arg(term_id)
    if error is not None:
        return error
    body = _body()
    if body is None:
        return _json_error("A JSON object body is required.", 400)
    try:
        row = update_term(
            term_id,
            term=body.get("term"),
            icd_classification=body.get("icd_classification"),
            icd_code=body.get("icd_code"),
            note=body.get("note"),
            sort_order=body.get("sort_order"),
        )
    except LookupError:
        return _json_error("Vocabulary term not found.", 404)
    except ValueError as exc:
        return _json_error(str(exc), 400)

    current_app.logger.info(
        "ICD search vocabulary term updated by user %s: term=%r -> %s %s",
        current_user.user_id,
        row.term,
        row.icd_classification,
        row.icd_code,
    )
    return jsonify(
        {
            "term": serialize_term(row),
            "code_warning": _code_warning(row.icd_classification, row.icd_code),
        }
    )


@admin.post("/api/icd-search-vocabulary/term/<term_id>/set-active")
@role_required("admin")
def admin_icd_search_vocabulary_set_active(term_id: str):
    if (denied := _admin_only()) is not None:
        return denied
    key, error = _term_id_arg(term_id)
    if error is not None:
        return error
    body = _body()
    if body is None or not isinstance(body.get("is_active"), bool):
        return _json_error("A JSON body with boolean is_active is required.", 400)
    try:
        row = set_active(str(key), body["is_active"])
    except LookupError:
        return _json_error("Vocabulary term not found.", 404)
    except ValueError as exc:
        return _json_error(str(exc), 400)

    current_app.logger.info(
        "ICD search vocabulary term %s by user %s: term=%r",
        "activated" if row.is_active else "deactivated",
        current_user.user_id,
        row.term,
    )
    return jsonify({"term": serialize_term(row)})


@admin.get("/api/icd-search-vocabulary/export.csv")
@role_required("admin")
def admin_icd_search_vocabulary_export_csv():
    if (denied := _admin_only()) is not None:
        return denied
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(CSV_HEADERS)
    # Export everything, active and not: deactivation is the audit trail.
    page = list_terms(per_page=1_000_000)
    for row in page["rows"]:
        writer.writerow(
            [
                csv_cell(row["term"]),
                csv_cell(row["term_normalized"]),
                csv_cell(row["icd_classification"]),
                csv_cell(row["icd_code"]),
                csv_cell(row["source"]),
                csv_cell(row["note"] or ""),
                row["sort_order"],
                "true" if row["is_active"] else "false",
                csv_cell(row["created_at"]),
                csv_cell(row["updated_at"]),
            ]
        )
    return current_app.response_class(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": 'attachment; filename="icd_search_vocabulary.csv"'},
    )
