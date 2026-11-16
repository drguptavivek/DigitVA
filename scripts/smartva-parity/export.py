#!/usr/bin/env python3
"""Stream, for every va_sid with an active va_smartva_results row, what the server scored and what it stored.

Read-only (the transaction is READ ONLY and rolled back). Writes JSON lines to stdout, each prefixed "SVP\\t" so log
output cannot be mistaken for data; build_requests.js reads them from a pipe. The lines hold raw payloads (PII):
never redirect this script to a file. scripts/smartva-parity/run.sh is the only intended caller.

Lines: one {"kind": "icds", ...} (the server's VA_SMARTVA_ICDS), then one {"kind": "case", ...} per sid with its
payload, the row the server's own _clean_payload_for_smartva makes of it (the values SmartVA read), the options, the
engine bucket and the stored result.

Usage (inside Docker): uv run --no-sync python scripts/smartva-parity/export.py | node .../build_requests.js OUT_DIR
"""
from __future__ import annotations

import json
import logging
import sys

import sqlalchemy as sa

from app import create_app, db
from app.models import (
    VaForms,
    VaSmartvaResults,
    VaSmartvaRun,
    VaSubmissionPayloadVersion,
    VaSubmissions,
)
from app.services.pii_field_registry import sealed_field_ids
from app.utils.va_form.va_form_02_formtyperesolution import va_get_form_type_code_from_form
from app.utils.va_smartva.va_smartva_01_icdcodes import VA_SMARTVA_ICDS
from app.utils.va_smartva.va_smartva_02_prepdata import (
    _clean_payload_for_smartva,
    _derive_smartva_run_options,
)
from app.utils.va_smartva.va_smartva_03_runsmartva import _bool_flag, smartva_country

RESULT_FIELDS = (
    "age", "gender", "cause1", "likelihood1", "keysymptom1", "cause2", "likelihood2", "keysymptom2",
    "cause3", "likelihood3", "keysymptom3", "allsymptoms", "resultfor", "cause1icd", "cause2icd", "cause3icd",
    "outcome", "failure_stage",
)


def emit(record: dict) -> None:
    sys.stdout.write("SVP\t" + json.dumps(record, ensure_ascii=False) + "\n")


def engine_bucket(metadata: dict | None) -> str:
    version = ((metadata or {}).get("smartva_engine") or {}).get("version")
    if version:
        return version
    return "unrecorded, options recorded" if (metadata or {}).get("smartva_options") else "unrecorded (before 2026-10-22)"


def main() -> None:
    logging.disable(logging.CRITICAL)
    app = create_app()
    with app.app_context():
        db.session.execute(sa.text("SET TRANSACTION READ ONLY"))
        emit({"kind": "icds", "icds": VA_SMARTVA_ICDS})
        forms = {form.form_id: form for form in db.session.scalars(sa.select(VaForms))}
        stmt = (
            sa.select(VaSmartvaResults, VaSubmissions.va_form_id, VaSubmissionPayloadVersion.payload_data,
                      VaSmartvaRun.run_metadata)
            .join(VaSubmissions, VaSubmissions.va_sid == VaSmartvaResults.va_sid)
            .join(VaSubmissionPayloadVersion,
                  VaSubmissionPayloadVersion.payload_version_id == VaSmartvaResults.payload_version_id)
            .outerjoin(VaSmartvaRun, VaSmartvaRun.va_smartva_run_id == VaSmartvaResults.smartva_run_id)
            .where(VaSmartvaResults.va_smartva_status == "active")
            .order_by(VaSmartvaResults.va_sid)
        )
        rows = db.session.execute(stmt).all()
        sids_by_form: dict[str, list[str]] = {}
        for result, form_id, _, _ in rows:
            sids_by_form.setdefault(form_id, []).append(result.va_sid)
        derived = {}
        sealed_by_form = {}
        for form_id, sids in sids_by_form.items():
            derived.update(_derive_smartva_run_options(forms[form_id], sids))
            sealed_by_form[form_id] = sorted(sealed_field_ids(va_get_form_type_code_from_form(forms[form_id])))
        for result, form_id, payload, metadata in rows:
            form = forms[form_id]
            recorded = (metadata or {}).get("smartva_options") or {}
            options_source = "run_metadata" if recorded else "derived now"
            hiv = recorded.get("hiv", {}).get("value") or derived[result.va_sid]["hiv"]
            malaria = recorded.get("malaria", {}).get("value") or derived[result.va_sid]["malaria"]
            sealed = sealed_by_form[form_id]
            emit({
                "kind": "case",
                "sid": result.va_sid,
                "payload": payload or {},
                "sealed": sealed,
                "server_row": _clean_payload_for_smartva(payload or {}, va_sid=result.va_sid, sealed=frozenset(sealed)),
                # The flag spellings the server's own runner accepts (_bool_flag), as booleans for the phone's request.
                "options": {"country": smartva_country(form), "hiv": bool(_bool_flag("hiv", hiv)),
                            "malaria": bool(_bool_flag("malaria", malaria)),
                            "hce": bool(_bool_flag("hce", form.form_smartvahce)),
                            "freetext": bool(_bool_flag("freetext", form.form_smartvafreetext))},
                "options_source": options_source,
                "engine": engine_bucket(metadata),
                "expected": {name: getattr(result, f"va_smartva_{name}") for name in RESULT_FIELDS},
            })
        db.session.rollback()


if __name__ == "__main__":
    main()
