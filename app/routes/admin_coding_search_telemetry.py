"""Coding-search telemetry admin CSV export (digitva-zpe.3, phase 0).

Phase 0 has no panel UI: the evidence leaves the system as one streamed CSV
of raw rows, newest first (docs/policy/coding-search-telemetry.md). The query
text is free-typed clinician input, so every text cell is neutralised against
spreadsheet formulas the same way as the vocabulary export
(``va_code_mapping_public_service.csv_cell``). GET only — no state changes,
so no CSRF token beyond the session's.
"""

from flask import current_app, stream_with_context
from flask_login import current_user

from app.decorators import role_required
from app.routes.admin import _json_error, admin
from app.services import coding_search_telemetry_service


def _admin_only():
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)
    return None


@admin.get("/api/coding-search-telemetry/export.csv")
@role_required("admin")
def admin_coding_search_telemetry_export_csv():
    if (denied := _admin_only()) is not None:
        return denied
    return current_app.response_class(
        stream_with_context(
            coding_search_telemetry_service.iter_csv_lines()
        ),
        mimetype="text/csv",
        headers={
            "Content-Disposition": 'attachment; filename="coding_search_telemetry.csv"'
        },
    )
