#!/usr/bin/env python3
"""Run SmartVA offline for all forms in a project (no DB writes).

Usage (inside Docker):
  docker compose exec minerva_app_service \
    uv run python scripts/run_smartva_offline_by_project.py --project-code UNSW01

This script:
1. Reads active payload data for each form in the given project.
2. Prepares SmartVA input CSVs.
3. Runs smartva_cli locally.
4. Writes raw SmartVA output tree + formatted `smartva_output.csv` per form.

By design, it does not persist SmartVA results to DigitVA database tables.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import sqlalchemy as sa

from app import create_app, db
from app.models import VaForms, VaProjectSites, VaStatuses
from app.utils.va_smartva.va_smartva_02_prepdata import va_smartva_prepdata
from app.utils.va_smartva.va_smartva_03_runsmartva import va_smartva_runsmartva
from app.utils.va_smartva.va_smartva_04_formatsmartvaresult import va_smartva_formatsmartvaresult


@dataclass(frozen=True)
class RunConfig:
    project_code: str
    output_root: Path
    limit_forms: int | None
    form_ids: set[str] | None


@dataclass(frozen=True)
class OfflineFormSpec:
    form_id: str
    project_id: str
    site_id: str
    form_smartvahiv: str
    form_smartvamalaria: str
    form_smartvahce: str
    form_smartvafreetext: str
    form_smartvacountry: str


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _default_output_root(project_code: str) -> Path:
    return _repo_root() / "private" / project_code.lower() / "smartva_offline"


def _count_csv_rows(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        # drop header row
        next(reader, None)
        return sum(1 for _ in reader)


def _list_key_outputs(form_dir: Path) -> list[str]:
    files: list[str] = []
    smartva_input = form_dir / "smartva_input.csv"
    if smartva_input.exists():
        files.append("smartva_input.csv")

    formatted = form_dir / "smartva_output.csv"
    if formatted.exists():
        files.append("smartva_output.csv")

    likelihood_dir = (
        form_dir
        / "smartva_output"
        / "4-monitoring-and-quality"
        / "intermediate-files"
    )
    for name in ("adult-likelihoods.csv", "child-likelihoods.csv", "neonate-likelihoods.csv"):
        path = likelihood_dir / name
        if path.exists():
            files.append(str(path.relative_to(form_dir)))
    return files


def _load_project_forms(config: RunConfig):
    stmt = (
        sa.select(
            VaForms.form_id,
            VaForms.project_id,
            VaForms.site_id,
            VaForms.form_smartvahiv,
            VaForms.form_smartvamalaria,
            VaForms.form_smartvahce,
            VaForms.form_smartvafreetext,
            VaForms.form_smartvacountry,
        )
        .join(
            VaProjectSites,
            sa.and_(
                VaProjectSites.project_id == VaForms.project_id,
                VaProjectSites.site_id == VaForms.site_id,
            ),
        )
        .where(VaForms.project_id == config.project_code)
        .where(VaForms.form_status == VaStatuses.active)
        .where(VaProjectSites.project_site_status == VaStatuses.active)
        .order_by(VaForms.form_id)
    )
    rows = db.session.execute(stmt).all()
    forms = [
        OfflineFormSpec(
            form_id=row.form_id,
            project_id=row.project_id,
            site_id=row.site_id,
            form_smartvahiv=row.form_smartvahiv,
            form_smartvamalaria=row.form_smartvamalaria,
            form_smartvahce=row.form_smartvahce,
            form_smartvafreetext=row.form_smartvafreetext,
            form_smartvacountry=row.form_smartvacountry,
        )
        for row in rows
    ]
    if config.form_ids:
        forms = [form for form in forms if form.form_id in config.form_ids]
    if config.limit_forms is not None:
        forms = forms[: config.limit_forms]
    return forms


def _run_for_form(va_form, form_dir: Path) -> dict:
    if form_dir.exists():
        shutil.rmtree(form_dir)
    form_dir.mkdir(parents=True, exist_ok=True)

    form_flags = {
        "country": va_form.form_smartvacountry,
        "hiv": va_form.form_smartvahiv,
        "malaria": va_form.form_smartvamalaria,
        "hce": va_form.form_smartvahce,
        "freetext": va_form.form_smartvafreetext,
        "figures": "False",
    }

    entry = {
        "form_id": va_form.form_id,
        "site_id": va_form.site_id,
        "status": "started",
        "records": None,
        "error": None,
        "flags": form_flags,
        "files": [],
    }

    try:
        prep = va_smartva_prepdata(va_form, str(form_dir))
        input_path = Path(prep["input_path"])
        entry["records"] = _count_csv_rows(input_path)
        # Prevent idle-in-transaction timeouts during long local SmartVA runs.
        db.session.rollback()

        va_smartva_runsmartva(
            va_form,
            str(form_dir),
            run_options=prep.get("run_options") or {},
        )
        va_smartva_formatsmartvaresult(va_form, str(form_dir))

        entry["files"] = _list_key_outputs(form_dir)
        entry["status"] = "ok"
    except Exception as exc:  # noqa: BLE001 - keep per-form runs resilient
        entry["status"] = "failed"
        entry["error"] = str(exc)
        db.session.rollback()

    return entry


def run(config: RunConfig) -> int:
    app = create_app()
    output_root = config.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    summary: dict = {
        "project_id": config.project_code,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "output_root": str(output_root),
        "forms": [],
    }

    with app.app_context():
        forms = _load_project_forms(config)
        # Close the read transaction opened while loading forms before any
        # long-running offline compute starts.
        db.session.rollback()

        if not forms:
            print(f"No forms found for project '{config.project_code}'.")
            return 2

        for va_form in forms:
            print(f"[START] {va_form.form_id}")
            form_dir = output_root / va_form.form_id
            entry = _run_for_form(va_form, form_dir)
            summary["forms"].append(entry)
            print(
                f"[{entry['status'].upper()}] {va_form.form_id} "
                f"records={entry['records']}"
            )

    summary_path = output_root / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    total = len(summary["forms"])
    ok_count = sum(1 for row in summary["forms"] if row["status"] == "ok")
    failed_count = total - ok_count

    print("---")
    print(f"Project: {config.project_code}")
    print(f"Forms: {total}, OK: {ok_count}, Failed: {failed_count}")
    print(f"Summary: {summary_path}")

    return 0 if failed_count == 0 else 1


def parse_args() -> RunConfig:
    parser = argparse.ArgumentParser(
        description="Run SmartVA offline per form for one project (no DB writes)."
    )
    parser.add_argument(
        "--project-code",
        required=True,
        help="Project code/id (example: UNSW01).",
    )
    parser.add_argument(
        "--output-root",
        default=None,
        help=(
            "Optional output folder. "
            "Default: ./private/<project_code_lower>/smartva_offline"
        ),
    )
    parser.add_argument(
        "--limit-forms",
        type=int,
        default=None,
        help="Optional cap for number of forms (useful for smoke tests).",
    )
    parser.add_argument(
        "--form-id",
        action="append",
        default=[],
        help="Optional specific form_id to include. Repeatable.",
    )
    args = parser.parse_args()

    project_code = str(args.project_code).strip()
    if not project_code:
        raise SystemExit("--project-code cannot be blank")

    output_root = Path(args.output_root).expanduser() if args.output_root else _default_output_root(project_code)
    form_ids = {str(fid).strip() for fid in (args.form_id or []) if str(fid).strip()}

    return RunConfig(
        project_code=project_code,
        output_root=output_root,
        limit_forms=args.limit_forms,
        form_ids=form_ids or None,
    )


def main() -> None:
    config = parse_args()
    raise SystemExit(run(config))


if __name__ == "__main__":
    main()
