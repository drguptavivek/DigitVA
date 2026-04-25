from __future__ import annotations

from app import limiter
from app.routes.api import data_management as dm_routes
from app.authz.access import action_authorized
from app.services.data_management.dashboard import dm_submissions_export_csv

from . import bp
from .helpers import serve_cached_export_csv


@bp.get("/submissions/export.csv")
@action_authorized("dm_export_view")
@limiter.limit("30 per minute")
def submissions_export_csv():
    return serve_cached_export_csv(
        export_kind="submissions",
        filename_prefix="data-management-submissions",
        export_fn=dm_submissions_export_csv,
    )


@bp.get("/submissions/export-smartva-input.csv")
@action_authorized("dm_export_view")
@limiter.limit("30 per minute")
def submissions_export_smartva_input_csv():
    return serve_cached_export_csv(
        export_kind="smartva_input",
        filename_prefix="data-management-smartva-input",
        export_fn=dm_routes.dm_smartva_input_export_csv,
    )


@bp.get("/submissions/export-smartva-results.csv")
@action_authorized("dm_export_view")
@limiter.limit("30 per minute")
def submissions_export_smartva_results_csv():
    return serve_cached_export_csv(
        export_kind="smartva_results",
        filename_prefix="data-management-smartva-results",
        export_fn=dm_routes.dm_smartva_results_export_csv,
    )


@bp.get("/submissions/export-smartva-likelihoods.csv")
@action_authorized("dm_export_view")
@limiter.limit("30 per minute")
def submissions_export_smartva_likelihoods_csv():
    return serve_cached_export_csv(
        export_kind="smartva_likelihoods",
        filename_prefix="data-management-smartva-likelihoods",
        export_fn=dm_routes.dm_smartva_likelihoods_export_csv,
    )
