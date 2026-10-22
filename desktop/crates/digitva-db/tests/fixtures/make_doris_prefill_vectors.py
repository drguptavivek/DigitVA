"""Regenerate doris_prefill_vectors.json from the server's DORIS prefill builder.

The station's `doris_prefill.rs` ports `app/services/doris_prefill.py`; this writes the Python
output for a set of interview payloads so the Rust test compares against the real builder.
Run from the repository root with any Python 3.13+; only the standard library is needed (no
database, Flask app or virtualenv):

    python3 -I desktop/crates/digitva-db/tests/fixtures/make_doris_prefill_vectors.py

Only `who_icd_api` (an HTTP client the prefill never calls) is stubbed.
"""

import importlib
import json
import pathlib
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT))
stub = types.ModuleType("app.services.who_icd_api")
stub.DEFAULT_ICD11_RELEASE = "2026-01"
stub.get_icd11_codeinfo = lambda *args, **kwargs: None
for name in ("app", "app.services"):
    package = types.ModuleType(name)
    package.__path__ = [str(ROOT / name.replace(".", "/"))]
    sys.modules[name] = package
sys.modules["app.services.who_icd_api"] = stub
prefill = importlib.import_module("app.services.doris_prefill").doris_prefill_from_payload

PAYLOADS = {
    "empty": {},
    "adult_male_exact_dates": {
        "Id10019": "male", "Id10020": "yes", "Id10021": "1960-03-15", "Id10022": "yes",
        "Id10023": "2026-10-15T00:00:00+05:30", "age_group": "adult", "age_adult": "66",
        "Id10077": "no", "doris_surgery_performed": "no", "doris_autopsy_requested": "no",
    },
    "year_only_birth_over_50": {
        "Id10019": "female", "Id10020": "yes", "Id10021": "1950-01-01", "Id10022": "yes",
        "Id10023": "2026-02-01", "age_group": "adult", "age_adult": 76.0, "Id10310": "yes",
    },
    "partial_birth_and_death_year": {
        "Id10019": "Male", "Id10020": "no", "dob_precision": "month_year", "dob_month_year": "1980-07-01",
        "Id10022": "ref", "Id10024": "2025-01-01", "age_group": "adult", "age_adult": "9.5",
    },
    "maternal_within_42_days": {
        "Id10019": "female", "age_group": "adult", "age_adult": "28", "Id10305": "no", "Id10312": "no",
        "Id10314": "yes", "doris_surgery_performed": "yes", "doris_surgery_when": "10",
        "doris_surgery_when_unit": "days", "doris_surgery_type": "Caesarean section",
        "doris_surgery_reason": "obstructed labour",
    },
    "maternal_unknown_timing": {
        "Id10019": "female", "age_group": "adult", "age_adult": "31", "Id10313": "yes",
        "Id10314": "dk", "Id10306": "ref",
    },
    "maternal_all_unknown_for_male": {
        "Id10019": "male", "age_group": "adult", "age_adult": "40", "Id10305": "dk", "Id10312": "ref",
    },
    "neonate_hours": {
        "Id10019": "female", "age_group": "neonate", "age_neonate_days": "0", "age_neonate_hours": "5",
        "isNeonatal": "1", "Id10104": "yes", "Id10354": "no", "Id10366": "2500",
        "doris_pregnancy_weeks": "38", "doris_mother_age": "24",
    },
    "neonate_stillborn_months": {
        "Id10019": "male", "age_group": "neonate", "age_neonate_days": 3, "isNeonatal": 1,
        "Id10114": "yes", "Id10367": "8", "Id10366": "3", "doris_hours_survived": "4",
    },
    "child_months_injury": {
        "Id10019": "undetermined", "age_group": "child", "age_child_unit": "months", "age_child_months": "7",
        "isChild": "1", "ageInMonthsByYear": "7", "Id10077": "yes", "Id10099": "yes",
        "doris_injury_date_known": "month_year", "doris_injury_month_year": "2026-09-01",
        "doris_injury_place": "3", "Id10083": "yes", "Id10089": "yes",
    },
    "injury_unknown_intent": {
        "Id10019": "male", "age_group": "adult", "age_adult": "45", "Id10077": "yes", "Id10098": "no",
        "Id10099": "dk", "doris_injury_date_known": "full", "doris_injury_date": "2026-10-01",
    },
    "injury_force_of_nature_and_war": {
        "Id10019": "male", "age_group": "adult", "age_adult": "50", "Id10077": "yes", "Id10095": "yes",
        "doris_injury_legal_war": "war",
    },
    "injury_no_intent_answers": {"Id10019": "male", "age_group": "adult", "age_adult": "50", "Id10077": "yes"},
    "surgery_long_ago_and_autopsy": {
        "Id10019": "male", "age_group": "adult", "age_adult": "70", "doris_surgery_performed": "yes",
        "doris_surgery_when": "2", "doris_surgery_when_unit": "months", "doris_autopsy_requested": "yes",
        "doris_autopsy_findings": "dk",
    },
    "surgery_when_unknown": {
        "Id10019": "male", "age_group": "adult", "age_adult": "70", "doris_surgery_performed": "yes",
        "doris_surgery_when": "99", "doris_surgery_when_unit": "days",
    },
    "odk_hysterectomy": {
        "Id10019": "female", "age_group": "adult", "age_adult": "35", "Id10340": "yes", "Id10305": "yes",
    },
    "odk_surgery_within_month": {"Id10019": "male", "age_group": "adult", "age_adult": "60", "Id10426": "ref"},
    "out_of_range_values": {
        "Id10019": "female", "Id10020": "yes", "Id10021": "2026-02-30", "Id10022": "yes", "Id10023": "not-a-date",
        "age_group": "adult", "age_adult": "151", "Id10077": "maybe",
    },
}

vectors = []
for name, payload in PAYLOADS.items():
    certificate, provenance = prefill(payload)
    vectors.append({"name": name, "payload": payload, "certificate": certificate, "provenance": provenance})
out = pathlib.Path(__file__).with_name("doris_prefill_vectors.json")
out.write_text(json.dumps(vectors, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"wrote {len(vectors)} vectors to {out}")
