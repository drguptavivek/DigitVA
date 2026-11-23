"""DM KPI — Sync Health.

Blueprint prefix: ``/api/v1/analytics/dm-kpi/sync``

KPIs served:
  C-03  Sync Error Rate (C-02 last run status merged)
  C-13  Sync Latency (ODK → App) — P50/P90/P99
  C-14  Attachment Health
  D-SH-01  Attachment Download Completeness
  D-SH-04  SmartVA Failure Rate

Sources:
  - va_sync_runs (system-level, no DM scoping for C-02/C-03)
  - va_submissions JOIN va_forms (C-13, scoped by site_id)
  - va_submission_attachments JOIN va_submissions JOIN va_forms (C-14)

Design notes:
  va_sync_runs and va_smartva_runs have no per-site breakdown, so C-02,
  C-03, D-SH-01 and D-SH-04 are system-level. They are served only to a
  data manager with a project or pair grant (or project_pi on a tree
  project, or admin: authz ``Lens.DM_DIRECT``, digitva-38lp); a unit-only
  data manager or In-charge sees sync runs only for forms a direct grant
  covers, so gets 403 on /status and /smartva-failure-rate and no D-SH-01.
  C-13 (sync latency) is DM-scoped via site attribution.

Retired-from-ODK submissions (docs/policy/odk-retired-submissions.md),
per KPI:
  C-13, C-14  counted over submissions — retired rows are excluded, C-13
              because its denominator is ALL-SYNCED and C-14 because a
              retired submission's attachments are archival, not a gap the
              DM can act on.
  C-02, C-03, D-SH-01  counted over va_sync_runs rows, not submissions —
              unaffected.
  D-SH-04     counted over va_smartva_runs rows, not submissions —
              unaffected.
  D-SH-03 (the "missing in ODK" count itself) is served from the analytics
  MV, not here, and deliberately keeps counting retired submissions.
"""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

from app.decorators import role_required
from app.routes.api.dm_kpi.dm_kpi_scope import (
    cached_kpi,
    dm_scope,
)
from app.routes.api.request_helpers import error as api_error
from app.services.kpi.sync import (  # noqa: F401
    compute_attachment_health,
    compute_c03,
    compute_smartva_failure_rate,
    compute_sync_latency,
)

bp = Blueprint("dm_kpi_sync", __name__)
log = logging.getLogger(__name__)


def _system_level_refused():
    return api_error("System-level sync figures need a project or site grant.", status_code=403)


@bp.get("/status")
@role_required("data_manager", "admin")
def sync_status():
    """System-level, so direct grants only (module docstring, digitva-38lp).

    KPI: C-03 (Sync Error Rate) with C-02 (Last Sync Run Status) merged in; a
    thin wrapper over ``compute_c03``. ``?period=7d|cumulative`` picks the
    headline ``rate``; both windows and ``latest_run`` are always returned.

    C-03: error or partial runs / all runs started in the window × 100.
    C-02: status, started_at, finished_at of the most recent run.
    """
    scope = dm_scope()
    if not scope.direct:
        return _system_level_refused()
    period = request.args.get("period") or None
    if period not in (None, "7d", "cumulative"):
        return api_error("Unsupported 'period'; use '7d' or 'cumulative'.", status_code=400)
    return jsonify(cached_kpi("sync_status", lambda: compute_c03(scope, period)))


@bp.get("/latency")
@role_required("data_manager", "admin")
def sync_latency():
    """KPI: C-13 — Sync Latency (ODK → App).

    Definition: For submissions synced in window: time between ODK
                submission timestamp and local DB insert.
    Formula: va_created_at − va_submission_date per submission.
    Aggregates: P50, P90, P99.
    Denominator scope: ALL-SYNCED (DM-scoped via site_id).
    Time frames: Today, 7d, by insert day on the submission's project clock.
    Source: va_submissions JOIN va_forms scoped by site_id.
    """
    scope = dm_scope()
    if not scope:
        return jsonify({"p50": None, "p90": None, "p99": None, "count": 0})

    range_param = request.args.get("range", "7d")

    return jsonify(cached_kpi(f"sync_latency:{range_param}", lambda: compute_sync_latency(scope, range_param)))


@bp.get("/attachment-health")
@role_required("data_manager", "admin")
def attachment_health():
    """KPIs: C-14 (Attachment Health) + D-SH-01 (Attachment Download Completeness).

    C-14 — Attachment Health:
      Numerator: COUNT of submissions past SmartVA gate where attachment
                 count = 0.
      Denominator: COUNT of submissions past SmartVA gate.
      Rate: N / D × 100.
      Source: va_submission_attachments JOIN va_submissions JOIN va_forms.
      Time frame: Snapshot.

    D-SH-01 — Attachment Download Completeness:
      Numerator: va_sync_runs.attachment_downloaded from latest run.
      Denominator: attachment_downloaded + attachment_skipped +
                   attachment_errors from same run.
      Rate: N / D × 100.
      Time frame: Snapshot.
    """
    scope = dm_scope()
    if not scope:
        return jsonify({"c14": {}, "d_sh_01": {}})

    return jsonify(cached_kpi("attachment_health", lambda: compute_attachment_health(scope)))


@bp.get("/smartva-failure-rate")
@role_required("data_manager", "admin")
def smartva_failure_rate():
    """KPI: D-SH-04 — SmartVA Failure Rate.

    Numerator: COUNT of va_smartva_runs where va_smartva_outcome = 'failed'
               in window.
    Denominator: COUNT of all va_smartva_runs in window.
    Rate: N / D × 100.
    Time frames: 7d, cumulative.
    Source: va_smartva_runs. System-level, so direct grants only (digitva-38lp).
    """
    if not dm_scope().direct:
        return _system_level_refused()

    return jsonify(cached_kpi("smartva_failure_rate", lambda: compute_smartva_failure_rate()))
