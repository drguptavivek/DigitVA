"""One-time SmartVA output backfill for current active payloads only.

Recomputes SmartVA for submissions whose current active SmartVA projection lacks
one or more of:
- likelihood_row
- a linked form run
- a persisted form-run disk path

The rerun is explicit and marked with trigger_source='backfill_recompute'.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import sqlalchemy as sa
from flask import current_app

from app import create_app, db
from app.models import (
    VaForms,
    VaSmartvaFormRun,
    VaSmartvaResults,
    VaSmartvaRun,
    VaSmartvaRunOutput,
    VaStatuses,
    VaSubmissions,
)
from app.services.smartva_service import generate_for_form


DEFAULT_EXPORT_DIR = Path("output/smartva_backfill_runs")


def _candidate_rows(limit: int | None = None) -> list[tuple[str, str, str, str]]:
    active_rows = db.session.execute(
        sa.select(
            VaSmartvaResults.va_sid,
            VaSmartvaResults.smartva_run_id,
            VaSubmissions.va_form_id,
            VaForms.project_id,
            VaForms.site_id,
        )
        .join(
            VaSubmissions,
            sa.and_(
                VaSubmissions.va_sid == VaSmartvaResults.va_sid,
                VaSubmissions.active_payload_version_id
                == VaSmartvaResults.payload_version_id,
            ),
        )
        .join(VaForms, VaForms.form_id == VaSubmissions.va_form_id)
        .where(VaSmartvaResults.va_smartva_status == VaStatuses.active)
        .order_by(
            VaForms.project_id.asc(),
            VaForms.site_id.asc(),
            VaSubmissions.va_form_id.asc(),
            VaSmartvaResults.va_smartva_addedat.asc(),
        )
    ).all()

    candidates: list[tuple[str, str, str, str]] = []
    for va_sid, smartva_run_id, form_id, project_id, site_id in active_rows:
        if smartva_run_id is None:
            candidates.append((va_sid, form_id, project_id, site_id))
            continue

        run_row = db.session.get(VaSmartvaRun, smartva_run_id)
        form_run_disk_path = None
        if run_row is not None and run_row.form_run_id is not None:
            form_run = db.session.get(VaSmartvaFormRun, run_row.form_run_id)
            form_run_disk_path = form_run.disk_path if form_run else None

        has_likelihood_row = (
            db.session.scalar(
                sa.select(VaSmartvaRunOutput.va_smartva_run_output_id).where(
                    VaSmartvaRunOutput.va_smartva_run_id == smartva_run_id,
                    VaSmartvaRunOutput.output_kind == "likelihood_row",
                )
            )
            is not None
        )
        if not has_likelihood_row or not form_run_disk_path:
            candidates.append((va_sid, form_id, project_id, site_id))

    if limit is not None:
        return candidates[:limit]
    return candidates


def _group_candidates_by_form(
    candidate_rows: list[tuple[str, str, str, str]],
) -> dict[str, dict]:
    grouped: dict[str, dict] = {}
    for va_sid, form_id, project_id, site_id in candidate_rows:
        bucket = grouped.setdefault(
            form_id,
            {
                "project_id": project_id,
                "site_id": site_id,
                "va_sids": [],
            },
        )
        bucket["va_sids"].append(va_sid)
    return grouped


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill SmartVA likelihood rows and persisted form-run outputs.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process at most N current active submissions.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List candidate submission ids without rerunning SmartVA.",
    )
    parser.add_argument(
        "--va-sid",
        action="append",
        default=[],
        help="Restrict processing to specific submission id(s).",
    )
    parser.add_argument(
        "--project-id",
        default=None,
        help="Restrict processing to a single project id.",
    )
    parser.add_argument(
        "--site-id",
        default=None,
        help="Restrict processing to a single site id.",
    )
    parser.add_argument(
        "--export-dir",
        default=str(DEFAULT_EXPORT_DIR),
        help="Directory to copy persisted form-run outputs into.",
    )
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        candidate_rows = _candidate_rows(limit=args.limit)
        if args.project_id:
            candidate_rows = [
                row for row in candidate_rows if row[2] == args.project_id
            ]
        if args.site_id:
            candidate_rows = [
                row for row in candidate_rows if row[3] == args.site_id
            ]
        if args.va_sid:
            requested = set(args.va_sid)
            candidate_rows = [
                row for row in candidate_rows if row[0] in requested
            ]

        candidate_sids = [row[0] for row in candidate_rows]
        grouped = _group_candidates_by_form(candidate_rows)

        print(f"candidate submissions: {len(candidate_sids)}")
        print(f"candidate forms: {len(grouped)}")
        for form_id, group in grouped.items():
            print(
                f"[plan] form={form_id} project={group['project_id']} "
                f"site={group['site_id']} submissions={len(group['va_sids'])}"
            )

        if args.dry_run:
            return

        export_dir = Path(args.export_dir)
        export_dir.mkdir(parents=True, exist_ok=True)

        updated = 0
        failed_forms: list[str] = []
        for form_id, group in grouped.items():
            try:
                va_form = db.session.get(VaForms, form_id)
                if va_form is None:
                    raise RuntimeError(f"Form not found: {form_id}")

                print(
                    f"[start] form={form_id} project={group['project_id']} "
                    f"site={group['site_id']} submissions={len(group['va_sids'])}"
                )
                saved = generate_for_form(
                    va_form,
                    target_sids=set(group["va_sids"]),
                    force=True,
                    trigger_source="backfill_recompute",
                )
                _export_latest_form_run(form_id, export_dir)
                updated += saved
                print(f"[ok] form={form_id}: saved={saved}")
            except Exception as exc:
                db.session.rollback()
                failed_forms.append(form_id)
                print(f"[failed] form={form_id}: {exc}")

        print(
            f"backfill complete: candidates={len(candidate_sids)} "
            f"updated={updated} failed_forms={len(failed_forms)}"
        )
        if failed_forms:
            print("failed forms:")
            for form_id in failed_forms:
                print(form_id)


def _export_latest_form_run(form_id: str, export_dir: Path) -> None:
    form_run = db.session.scalar(
        sa.select(VaSmartvaFormRun)
        .where(
            VaSmartvaFormRun.form_id == form_id,
            VaSmartvaFormRun.trigger_source == "backfill_recompute",
            VaSmartvaFormRun.disk_path.is_not(None),
        )
        .order_by(VaSmartvaFormRun.run_started_at.desc())
    )
    if form_run is None or not form_run.disk_path:
        return

    source_dir = Path(current_app.config["APP_DATA"]) / form_run.disk_path
    if not source_dir.exists():
        return

    target_dir = export_dir / form_run.project_id / form_run.form_id / str(form_run.form_run_id)
    if target_dir.exists():
        shutil.rmtree(target_dir)
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_dir, target_dir)


if __name__ == "__main__":
    main()
