#!/usr/bin/env python3
"""Score every active case again with the server's own pipeline and current engine, without storing anything.

This is the server half of the question "is a difference the phone's, or an older server engine's?". Per form and
option set, in batches of 50 as the server runs them: va_smartva_prepdata, va_smartva_runsmartva (the engine the
container is configured for), the report's quality rejections, va_smartva_formatsmartvaresult and
_read_formatted_results, then the stored fields shaped as smartva_service.py stores them. The DB transaction is READ
ONLY and rolled back; each batch's workspace (it holds the input CSV) lives under OUT_DIR/tmp and is removed after
the batch.

Writes OUT_DIR/server-now.jsonl: {id, expected} per case, id = sha256(va_sid)[:16], expected in export.py's field
names; compare.py --expected reads it. OUT_DIR must be under /app/private/.

usage (inside Docker): uv run --no-sync python scripts/smartva-parity/rescore_server.py /app/private/smartva-parity/corpus
"""
from __future__ import annotations

import hashlib
import json
import logging
import shutil
import sys
import tempfile
from pathlib import Path

import sqlalchemy as sa

from app import create_app, db
from app.models import VaForms, VaSmartvaResults, VaSubmissions
from app.services.smartva_service import _read_formatted_results, _read_rejected_sids_from_report
from app.utils.va_smartva.va_smartva_02_prepdata import (
    _derive_smartva_run_options,
    group_sids_by_run_options,
    va_smartva_prepdata,
)
from app.utils.va_smartva.va_smartva_03_runsmartva import smartva_engine_info, va_smartva_runsmartva
from app.utils.va_smartva.va_smartva_04_formatsmartvaresult import va_smartva_formatsmartvaresult

BATCH = 50
STORED = {"gender": "sex", "cause1": "cause1", "likelihood1": "likelihood1", "keysymptom1": "key_symptom1",
          "cause2": "cause2", "likelihood2": "likelihood2", "keysymptom2": "key_symptom2", "cause3": "cause3",
          "likelihood3": "likelihood3", "keysymptom3": "key_symptom3", "allsymptoms": "all_symptoms",
          "resultfor": "result_for", "cause1icd": "cause1_icd", "cause2icd": "cause2_icd", "cause3icd": "cause3_icd"}


def stored_fields(record) -> dict:
    """The va_smartva_results fields smartva_service.py writes for a success row."""
    age = getattr(record, "age", None)
    fields = {name: getattr(record, column, None) for name, column in STORED.items()}
    fields["age"] = format(float(age), ".1f") if age is not None else None
    return fields | {"outcome": "success", "failure_stage": None}


def failed(stage: str) -> dict:
    return {name: None for name in [*STORED, "age"]} | {"outcome": "failed", "failure_stage": stage}


def score_batch(form, sids: set[str], options: dict, tmp: Path) -> dict[str, dict]:
    workspace = tempfile.mkdtemp(dir=tmp)
    try:
        va_smartva_prepdata(form, workspace, pending_sids=sids)
        try:
            va_smartva_runsmartva(form, workspace, run_options=options)
        except Exception:  # the server records an "execution" failure for the batch
            return {sid: failed("execution") for sid in sids}
        rejected = _read_rejected_sids_from_report(workspace, sids)
        results = _read_formatted_results(va_smartva_formatsmartvaresult(form, workspace))
        scored = {}
        if results is not None:
            for record in results.itertuples():
                sid = getattr(record, "sid", None)
                if sid in sids and sid not in rejected:
                    scored[sid] = stored_fields(record)
        def stage(sid: str) -> str:
            if sid in rejected:
                return "smartva_rejected"
            return "format_output" if results is None else "missing_row"

        return {sid: scored.get(sid) or failed(stage(sid)) for sid in sids}
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def main() -> None:
    out = Path(sys.argv[1]).resolve()
    if "private" not in out.parts:
        sys.exit("OUT_DIR must be under private/")
    tmp = out / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    logging.disable(logging.CRITICAL)
    app = create_app()
    with app.app_context():
        db.session.execute(sa.text("SET TRANSACTION READ ONLY"))
        rows = db.session.execute(
            sa.select(VaSmartvaResults.va_sid, VaSubmissions.va_form_id)
            .join(VaSubmissions, VaSubmissions.va_sid == VaSmartvaResults.va_sid)
            .where(VaSmartvaResults.va_smartva_status == "active")
        ).all()
        by_form: dict[str, list[str]] = {}
        for sid, form_id in rows:
            by_form.setdefault(form_id, []).append(sid)
        results: dict[str, dict] = {}
        for form_id, sids in sorted(by_form.items()):
            form = db.session.get(VaForms, form_id)
            for (hiv, malaria), group in group_sids_by_run_options(_derive_smartva_run_options(form, sids)).items():
                ordered = sorted(group)
                for start in range(0, len(ordered), BATCH):
                    batch = set(ordered[start:start + BATCH])
                    results |= score_batch(form, batch, {"hiv": hiv, "malaria": malaria}, tmp)
        with (out / "server-now.jsonl").open("w") as handle:
            for sid in sorted(results):
                handle.write(json.dumps({"id": hashlib.sha256(sid.encode()).hexdigest()[:16],
                                         "expected": results[sid]}, ensure_ascii=False) + "\n")
        print(json.dumps({"cases": len(results), "engine": smartva_engine_info()}))
        db.session.rollback()
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
