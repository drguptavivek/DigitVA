"""Celery tasks for KPI aggregation.

compute_daily_kpi_snapshot: Daily task to compute and cache KPI aggregates.
"""
import logging
from datetime import datetime, date, timedelta, timezone
from celery import shared_task
from celery.utils.log import get_task_logger

log = get_task_logger(__name__)


@shared_task(
    name="app.tasks.kpi_tasks.compute_daily_kpi_snapshot",
    bind=True,
    soft_time_limit=600,
    time_limit=900,
)
def compute_daily_kpi_snapshot(self, snapshot_date=None, site_ids=None):
    """Compute and upsert daily KPI aggregates for the given date.

    Args:
        snapshot_date (str, optional): Date in YYYY-MM-DD format. Defaults to yesterday.
        site_ids (list, optional): List of site IDs to compute. Defaults to all active sites.

    Computes one row per (snapshot_date, site_id) with:
      - new_from_odk: submissions created on snapshot_date
      - updated_from_odk: submissions updated from ODK on snapshot_date
      - coded_count: submissions finalized/recoded on snapshot_date
      - pending_count: end-of-day count in pending states
      - consent_refused_count: end-of-day count in consent_refused state
      - not_codeable_count: end-of-day count in not_codeable states
      - coding_duration percentiles: min/max/p50/p90 of coding duration
      - reviewer_finalized_count: forms finalized by reviewer on snapshot_date
      - upstream_changed_count: forms with upstream changes as of snapshot_date
      - reopened_count: forms reopened on snapshot_date
    """
    from app import db
    import sqlalchemy as sa
    from app.models import VaSite

    if snapshot_date is None:
        snapshot_date = (date.today() - timedelta(days=1)).isoformat()
    elif isinstance(snapshot_date, date):
        snapshot_date = snapshot_date.isoformat()

    try:
        snapshot_dt = datetime.fromisoformat(snapshot_date)
    except (ValueError, TypeError):
        log.error("Invalid snapshot_date: %s", snapshot_date)
        return {"status": "error", "reason": "invalid snapshot_date"}

    snapshot_date_obj = snapshot_dt.date()
    log.info("Computing KPI snapshot for %s", snapshot_date_obj)

    # Get list of active sites if not provided
    if not site_ids:
        site_ids = db.session.execute(
            sa.select(VaSite.site_id).where(VaSite.site_status == "active")
        ).scalars().all()
        site_ids = list(site_ids)

    if not site_ids:
        log.info("No active sites; skipping snapshot")
        return {"status": "ok", "sites_processed": 0}

    processed_count = 0
    failed_sites = []

    for site_id in site_ids:
        try:
            _compute_site_snapshot(db, snapshot_date_obj, site_id)
            processed_count += 1
        except Exception as e:
            log.exception("Error computing snapshot for site %s", site_id)
            failed_sites.append(site_id)

    if failed_sites:
        log.warning("Failed to process %d sites: %s", len(failed_sites), failed_sites)

    log.info("KPI snapshot complete: %d sites processed, %d failed", processed_count, len(failed_sites))
    return {
        "status": "ok" if not failed_sites else "partial",
        "sites_processed": processed_count,
        "sites_failed": len(failed_sites),
    }


def _compute_site_snapshot(db, snapshot_date: date, site_id: str) -> None:
    """Compute and upsert KPI aggregates for a single site and date."""
    import sqlalchemy as sa

    # Resolve current owning project for this site
    project_id = db.session.execute(
        sa.text("""
            SELECT project_id FROM va_project_sites
            WHERE site_id = :site_id AND project_site_status = 'active'
            ORDER BY project_site_updated_at DESC
            LIMIT 1
        """),
        {"site_id": site_id},
    ).scalar()

    if not project_id:
        log.warning("Site %s has no active project assignment; skipping", site_id)
        return

    tz = "UTC"
    snapshot_start = f"{snapshot_date}T00:00:00"
    snapshot_end = f"{snapshot_date}T23:59:59"

    # Compute each column
    data = {
        "total_submissions": _count_total_submissions(db, site_id, snapshot_date),
        "new_from_odk": _count_new_from_odk(db, site_id, snapshot_date),
        "updated_from_odk": _count_updated_from_odk(db, site_id, snapshot_date),
        "coded_count": _count_coded(db, site_id, snapshot_date),
        "pending_count": _count_pending_eod(db, site_id, snapshot_date),
        "consent_refused_count": _count_consent_refused_eod(db, site_id, snapshot_date),
        "not_codeable_count": _count_not_codeable_eod(db, site_id, snapshot_date),
        "reviewer_finalized_count": _count_reviewer_finalized(db, site_id, snapshot_date),
        "upstream_changed_count": _count_upstream_changed_eod(db, site_id, snapshot_date),
        "reopened_count": _count_reopened(db, site_id, snapshot_date),
    }

    # Compute percentiles
    durations = _compute_coding_duration_percentiles(db, site_id, snapshot_date)
    data.update(durations)

    # UPSERT into va_daily_kpi_aggregates
    upsert_sql = sa.text("""
        INSERT INTO va_daily_kpi_aggregates (
            snapshot_date, site_id, project_id,
            total_submissions, new_from_odk, updated_from_odk,
            coded_count, pending_count, consent_refused_count, not_codeable_count,
            coding_duration_min, coding_duration_max, coding_duration_p50, coding_duration_p90,
            reviewer_finalized_count, upstream_changed_count, reopened_count,
            created_at
        ) VALUES (
            :snapshot_date, :site_id, :project_id,
            :total_submissions, :new_from_odk, :updated_from_odk,
            :coded_count, :pending_count, :consent_refused_count, :not_codeable_count,
            :coding_duration_min, :coding_duration_max, :coding_duration_p50, :coding_duration_p90,
            :reviewer_finalized_count, :upstream_changed_count, :reopened_count,
            NOW()
        )
        ON CONFLICT (snapshot_date, site_id) DO UPDATE SET
            project_id = EXCLUDED.project_id,
            total_submissions = EXCLUDED.total_submissions,
            new_from_odk = EXCLUDED.new_from_odk,
            updated_from_odk = EXCLUDED.updated_from_odk,
            coded_count = EXCLUDED.coded_count,
            pending_count = EXCLUDED.pending_count,
            consent_refused_count = EXCLUDED.consent_refused_count,
            not_codeable_count = EXCLUDED.not_codeable_count,
            coding_duration_min = EXCLUDED.coding_duration_min,
            coding_duration_max = EXCLUDED.coding_duration_max,
            coding_duration_p50 = EXCLUDED.coding_duration_p50,
            coding_duration_p90 = EXCLUDED.coding_duration_p90,
            reviewer_finalized_count = EXCLUDED.reviewer_finalized_count,
            upstream_changed_count = EXCLUDED.upstream_changed_count,
            reopened_count = EXCLUDED.reopened_count
    """)

    db.session.execute(upsert_sql, {
        "snapshot_date": snapshot_date,
        "site_id": site_id,
        "project_id": project_id,
        **data,
    })
    db.session.commit()
    log.debug("Upserted snapshot for %s on %s (project %s)", site_id, snapshot_date, project_id)


def _count_total_submissions(db, site_id: str, snapshot_date: date) -> int:
    """Count total submissions as of end of snapshot_date."""
    count = db.session.execute(
        sa.text("""
            SELECT COUNT(*) FROM va_submissions s
            JOIN va_forms f ON f.form_id = s.va_form_id
            WHERE f.site_id = :site_id AND DATE(s.va_created_at) <= :snapshot_date
        """),
        {"site_id": site_id, "snapshot_date": snapshot_date},
    ).scalar() or 0
    return count


def _count_new_from_odk(db, site_id: str, snapshot_date: date) -> int:
    """Count submissions created on snapshot_date."""
    count = db.session.execute(
        sa.text("""
            SELECT COUNT(*) FROM va_submissions s
            JOIN va_forms f ON f.form_id = s.va_form_id
            WHERE f.site_id = :site_id AND DATE(s.va_created_at) = :snapshot_date
        """),
        {"site_id": site_id, "snapshot_date": snapshot_date},
    ).scalar() or 0
    return count


def _count_updated_from_odk(db, site_id: str, snapshot_date: date) -> int:
    """Count submissions updated from ODK on snapshot_date (after initial creation)."""
    count = db.session.execute(
        sa.text("""
            SELECT COUNT(*) FROM va_submissions s
            JOIN va_forms f ON f.form_id = s.va_form_id
            WHERE f.site_id = :site_id
              AND DATE(s.va_odk_updatedat) = :snapshot_date
              AND s.va_odk_updatedat > s.va_created_at
        """),
        {"site_id": site_id, "snapshot_date": snapshot_date},
    ).scalar() or 0
    return count


def _count_coded(db, site_id: str, snapshot_date: date) -> int:
    """Count submissions finalized or recoded on snapshot_date."""
    count = db.session.execute(
        sa.text("""
            SELECT COUNT(*) FROM va_submission_workflow_events e
            JOIN va_submissions s ON s.va_sid = e.va_sid
            JOIN va_forms f ON f.form_id = s.va_form_id
            WHERE f.site_id = :site_id
              AND e.transition_id IN ('coder_finalized', 'recode_finalized')
              AND DATE(e.event_created_at) = :snapshot_date
        """),
        {"site_id": site_id, "snapshot_date": snapshot_date},
    ).scalar() or 0
    return count


def _count_pending_eod(db, site_id: str, snapshot_date: date) -> int:
    """Count submissions in pending states as of end of snapshot_date."""
    count = db.session.execute(
        sa.text("""
            SELECT COUNT(*) FROM va_submission_workflow w
            JOIN va_submissions s ON s.va_sid = w.va_sid
            JOIN va_forms f ON f.form_id = s.va_form_id
            WHERE f.site_id = :site_id
              AND w.workflow_state IN (
                  'ready_for_coding', 'coding_in_progress', 'coder_step1_saved',
                  'smartva_pending', 'screening_pending', 'attachment_sync_pending'
              )
        """),
        {"site_id": site_id},
    ).scalar() or 0
    return count


def _count_consent_refused_eod(db, site_id: str, snapshot_date: date) -> int:
    """Count submissions in consent_refused state as of end of snapshot_date."""
    count = db.session.execute(
        sa.text("""
            SELECT COUNT(*) FROM va_submission_workflow w
            JOIN va_submissions s ON s.va_sid = w.va_sid
            JOIN va_forms f ON f.form_id = s.va_form_id
            WHERE f.site_id = :site_id AND w.workflow_state = 'consent_refused'
        """),
        {"site_id": site_id},
    ).scalar() or 0
    return count


def _count_not_codeable_eod(db, site_id: str, snapshot_date: date) -> int:
    """Count submissions in not_codeable states as of end of snapshot_date."""
    count = db.session.execute(
        sa.text("""
            SELECT COUNT(*) FROM va_submission_workflow w
            JOIN va_submissions s ON s.va_sid = w.va_sid
            JOIN va_forms f ON f.form_id = s.va_form_id
            WHERE f.site_id = :site_id
              AND w.workflow_state IN (
                  'not_codeable_by_coder', 'not_codeable_by_data_manager'
              )
        """),
        {"site_id": site_id},
    ).scalar() or 0
    return count


def _count_reviewer_finalized(db, site_id: str, snapshot_date: date) -> int:
    """Count submissions finalized by reviewer on snapshot_date."""
    count = db.session.execute(
        sa.text("""
            SELECT COUNT(*) FROM va_submission_workflow_events e
            JOIN va_submissions s ON s.va_sid = e.va_sid
            JOIN va_forms f ON f.form_id = s.va_form_id
            WHERE f.site_id = :site_id
              AND e.transition_id = 'reviewer_finalized'
              AND DATE(e.event_created_at) = :snapshot_date
        """),
        {"site_id": site_id, "snapshot_date": snapshot_date},
    ).scalar() or 0
    return count


def _count_upstream_changed_eod(db, site_id: str, snapshot_date: date) -> int:
    """Count submissions with upstream changes as of end of snapshot_date."""
    count = db.session.execute(
        sa.text("""
            SELECT COUNT(*) FROM va_submission_workflow w
            JOIN va_submissions s ON s.va_sid = w.va_sid
            JOIN va_forms f ON f.form_id = s.va_form_id
            WHERE f.site_id = :site_id
              AND w.workflow_state = 'finalized_upstream_changed'
        """),
        {"site_id": site_id},
    ).scalar() or 0
    return count


def _count_reopened(db, site_id: str, snapshot_date: date) -> int:
    """Count submissions reopened on snapshot_date."""
    count = db.session.execute(
        sa.text("""
            SELECT COUNT(*) FROM va_submission_workflow_events e
            JOIN va_submissions s ON s.va_sid = e.va_sid
            JOIN va_forms f ON f.form_id = s.va_form_id
            WHERE f.site_id = :site_id
              AND e.transition_id = 'reopened'
              AND DATE(e.event_created_at) = :snapshot_date
        """),
        {"site_id": site_id, "snapshot_date": snapshot_date},
    ).scalar() or 0
    return count


def _compute_coding_duration_percentiles(db, site_id: str, snapshot_date: date) -> dict:
    """Compute min, max, p50, p90 of coding duration for snapshot_date."""
    result = db.session.execute(
        sa.text("""
            SELECT
                MIN(e2.event_created_at - e1.event_created_at) AS min_duration,
                MAX(e2.event_created_at - e1.event_created_at) AS max_duration,
                PERCENTILE_CONT(0.5) WITHIN GROUP (
                    ORDER BY e2.event_created_at - e1.event_created_at
                ) AS p50_duration,
                PERCENTILE_CONT(0.9) WITHIN GROUP (
                    ORDER BY e2.event_created_at - e1.event_created_at
                ) AS p90_duration
            FROM va_submission_workflow_events e2
            JOIN va_submission_workflow_events e1
                ON e1.va_sid = e2.va_sid
                AND e1.transition_id = 'coding_started'
            JOIN va_submissions s ON s.va_sid = e2.va_sid
            JOIN va_forms f ON f.form_id = s.va_form_id
            WHERE f.site_id = :site_id
              AND e2.transition_id IN ('coder_finalized', 'recode_finalized')
              AND DATE(e2.event_created_at) = :snapshot_date
              AND NOT EXISTS (
                  SELECT 1 FROM va_submission_workflow_events d
                  WHERE d.va_sid = e2.va_sid AND d.transition_id = 'demo_started'
              )
        """),
        {"site_id": site_id, "snapshot_date": snapshot_date},
    ).mappings().first()

    return {
        "coding_duration_min": result["min_duration"] if result else None,
        "coding_duration_max": result["max_duration"] if result else None,
        "coding_duration_p50": result["p50_duration"] if result else None,
        "coding_duration_p90": result["p90_duration"] if result else None,
    }
