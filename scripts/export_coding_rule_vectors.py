"""Export golden input -> expected vectors of the coding rules the phone mirrors (digitva-r8nh.25).

Collect Plus re-implements, in TypeScript, rules the server owns: WHO 2022 age normalisation, the age group
boundaries, sex-then-age ICD-11 allowability, the age-restriction confirmation record, the "causing condition not
known" rule, the code-expression grammar and its 256-character cap, the order of the final underlying-cause checks,
and the DORIS reported age. Each case here is computed by the SERVER implementation, in-process and without a
database (the policy SQL predicate runs over one row in an in-memory SQLite). The committed file
mobile/digitva-collect/__tests__/fixtures/coding_rule_vectors.json is consumed by
tests/services/test_coding_rule_vectors.py (drift guard) and __tests__/coding-rule-vectors.test.ts (the phone).

Run: python -m scripts.export_coding_rule_vectors   (from the repo root; no database needed)

``divergences`` lists the cases where the phone is known to disagree with the server; jest skips them with the
reason. They are findings for the owner, not fixes.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import sqlalchemy as sa

from app.services.doris_certificate import _age_days
from app.services.final_cod_core import FinalCodRefusal, check_conclusive_cod
from app.services.icd_coding_policy import (
    AgeRestrictionConfirmationRequired,
    coding_age_group_for_submission,
    policy_ok_columns,
)
from app.services.icd_coding_value import (
    _ICD11_CODE_EXPRESSION_MAX_LENGTH,
    InvalidCausingConditionFlag,
    check_causing_condition_unknown,
    extract_icd11_code_expression,
    extract_icd_code,
    record_final_cod_flags,
)
from app.services.who_age_normalization import normalize_who_2022_age

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "mobile/digitva-collect/__tests__/fixtures/coding_rule_vectors.json"
SCHEMA = 1

# Known phone/server disagreements, keyed "<section>:<case name>" -> reason (found by running the jest test; the
# owner decides, nothing is fixed here). Filled by underlying_cases.
DIVERGENCES: dict[str, str] = {}
FLAG_ORDER_DIVERGENCE = (
    "server refuses 'causing condition not known' (single ICD-11 stem only) before validating the code; the phone "
    "validates the code first and answers 'Select a valid ICD-11 code.' for a value that is not an ICD-11 expression"
)

STEM = "1A00"
AGE_INPUTS = [
    ("hours only", {"age_neonate_hours": "5"}),
    ("neonate days", {"age_neonate_days": "12"}),
    ("neonatal flag + ageInDays", {"isNeonatal": "1", "ageInDays": "20", "ageInYears": "0"}),
    ("child, days win", {"isChild": "1", "ageInDays": "400", "ageInMonths": "13", "ageInYears": "1"}),
    ("child, months", {"isChild": "true", "ageInMonths": "18"}),
    ("child, years", {"isChild": "1.0", "ageInYears": "5"}),
    ("child, years2", {"isChild": "1", "ageInYears2": "7"}),
    ("child, final years", {"isChild": "1", "finalAgeInYears": "9"}),
    ("adult, years", {"isAdult": "1", "ageInYears": "45"}),
    ("adult, years2 before final", {"isAdult": "True", "ageInYears2": "50", "finalAgeInYears": "60"}),
    ("adult, final years", {"isAdult": "1", "finalAgeInYears": "70"}),
    ("no flags, years first", {"ageInYears": "3", "ageInDays": "9"}),
    ("no flags, days", {"ageInDays": "9", "ageInMonths": "2"}),
    ("no flags, months", {"ageInMonths": "2"}),
    ("no flags, years2", {"ageInYears2": "11.5"}),
    ("no flags, final years only", {"finalAgeInYears": "30"}),
    ("numeric values", {"ageInYears": 2, "isChild": 1}),
    ("padded string", {"ageInDays": "  7 "}),
    ("blank and junk are unknown", {"ageInYears": "", "ageInDays": "abc", "ageInMonths": "NaN"}),
    ("isChild flag but nothing usable", {"isChild": "1"}),
    ("neonatal flag without days falls through", {"isNeonatal": "1", "ageInMonths": "1"}),
    ("zero days", {"ageInDays": "0"}),
    ("empty", {}),
]
AGE_DAYS = ["0", "27.99", "28", "364.99", "365", "4382.99", "4383", "4383.01", "36525"]
RESTRICTION_AGES = ["all", "neonate", "infant", "neonate_infant", "child", "adult"]
RESTRICTION_SEXES = ["both", "male", "female"]
CONTEXT_AGE_GROUPS = [None, "neonate", "infant", "child", "adult"]
CONTEXT_SEXES = [None, "male", "female"]
EXPRESSIONS = [
    "1A00", "1a00 cholera", "  1A00  title", "BA00.1 x", "2C25.Z", "1G40.0&XN8Q Epilepsy", "FB80.B/2F9Z", "1G40/1G41",
    "1G40&X1/1G41&X2.3", "&1A00", "/1A00", "1A00/", "1A00&", "A00 cholera", "A00.1", "KD3B.Z", "1A0", "1A00.123", "",
    "   ", "Select a code", "1A00-x", "1A00&XN8Q.A.B",
    "1A00&" + "X" * 251,  # exactly 256 characters
    "1A00&" + "X" * 252,  # 257 characters
]
CAUSING = ["1A00 Cholera", "1G40.0&XN8Q Epilepsy", "FB80.B/2F9Z x", "A00 Cholera", "", "garbage", "1A00/"]
REPORTED_AGES = ["P65Y", "P3D", "PT5H", "PT30M", "PT90S", "P2M", "P1W", "P1Y2M", "P0D", "PT0S", "P", "", "  P7D ", "P1.5Y", "7", None]

_engine = sa.create_engine("sqlite://")


def _row_ok(age_group_selectable: str, sex_selectable: str, age_group, sex) -> tuple[bool, bool]:
    """The server's policy predicate (icd_coding_policy.policy_ok_columns) over one catalogue row."""
    columns = SimpleNamespace(
        age_group_selectable=sa.literal(age_group_selectable), sex_selectable=sa.literal(sex_selectable)
    )
    age_ok, sex_ok = policy_ok_columns(columns, age_group=age_group, sex=sex)
    with _engine.connect() as conn:
        row = conn.execute(sa.select(age_ok.label("a"), sex_ok.label("s"))).one()
    return bool(row.a), bool(row.s)


def _validate_for(restriction: dict | None, age_group, sex):
    """validate_icd11_mms_coding_value_for_submission for a plain stem, over one in-memory catalogue row."""

    def validate(_va_sid: str, value: str) -> None:
        code = extract_icd_code(value, "icd11")
        if code is None or extract_icd11_code_expression(value) is None:
            raise ValueError("Select a valid ICD-11 code.")
        if restriction is None or code != STEM:
            raise ValueError(f"{code} is not selectable for this submission.")
        age_ok, sex_ok = _row_ok(restriction["age"], restriction["sex"], age_group, sex)
        if not sex_ok:
            raise ValueError(f"{code} is not selectable for this submission.")
        if not age_ok:
            raise AgeRestrictionConfirmationRequired(code, restriction["age"], restriction["note"])

    return validate


def age_days_cases() -> list[dict]:
    out = []
    for name, data in AGE_INPUTS:
        days = normalize_who_2022_age(data).normalized_age_days
        out.append({"name": name, "data": data, "days": None if days is None else float(days)})
    return out


def age_group_cases() -> list[dict]:
    unknown = SimpleNamespace(va_deceased_age_normalized_days=None, va_deceased_age=None)
    out = [{"name": "unknown", "days": None, "group": coding_age_group_for_submission(unknown)}]
    for days in AGE_DAYS:
        submission = SimpleNamespace(va_deceased_age_normalized_days=Decimal(days), va_deceased_age=None)
        out.append({"name": f"{days} days", "days": float(days), "group": coding_age_group_for_submission(submission)})
    return out


def allowability_cases() -> list[dict]:
    out = [{"name": "code not in the catalogue", "restriction": None, "age_group": "adult", "sex": "male", "status": "blocked"}]
    for age in RESTRICTION_AGES:
        for sex in RESTRICTION_SEXES:
            for group in CONTEXT_AGE_GROUPS:
                for ctx_sex in CONTEXT_SEXES:
                    age_ok, sex_ok = _row_ok(age, sex, group, ctx_sex)
                    status = "ok" if age_ok and sex_ok else "blocked" if not sex_ok else "age_confirm"
                    out.append({
                        "name": f"{age}/{sex} vs {group}/{ctx_sex}",
                        "restriction": {"age": age, "sex": sex, "note": f"note {age}"},
                        "age_group": group, "sex": ctx_sex, "status": status,
                    })
    return out


def confirmation_cases() -> list[dict]:
    restriction = {"code": STEM, "age_group_selectable": "child", "restriction_note": "Paediatric only"}
    cases = [
        ("warning names the code", {"status": "completed", "result": {"warning": f"{STEM} is unusual for an adult"}}),
        ("warning names another code", {"status": "completed", "result": {"warning": "1B00 is unusual"}}),
        ("no warning", {"status": "completed", "result": {"code": STEM}}),
        ("non-string warning", {"status": "completed", "result": {"warning": 5}}),
        ("no doris result", None),
    ]
    out = []
    for name, doris in cases:
        provenance = {"conclusive": {}}
        record_final_cod_flags(
            provenance, age_restriction=dict(restriction), causing_condition_unknown=False,
            confirmed_by="user-7", doris_result=doris, field="conclusive",
        )
        record = provenance["conclusive"]["age_restriction_confirmation"]
        record.pop("confirmed_at")  # a clock reading: both sides only check it is present
        out.append({"name": name, "restriction": restriction, "confirmed_by": "user-7", "doris_result": doris, "record": record})
    return out


def expression_cases() -> list[dict]:
    return [{"name": value[:40] or "(empty)", "value": value, "length": len(value), "expression": extract_icd11_code_expression(value)}
            for value in EXPRESSIONS]


def _causing_error(value: str) -> str | None:
    try:
        check_causing_condition_unknown(value)
    except InvalidCausingConditionFlag as exc:
        return str(exc)
    return None


def causing_cases() -> list[dict]:
    return [{"name": value or "(empty)", "value": value, "error": _causing_error(value)} for value in CAUSING]


def underlying_cases() -> list[dict]:
    """check_conclusive_cod outcomes, in the server's own order (flag, then code, then sex, then age)."""
    restrictions = {
        "open": {"age": "all", "sex": "both", "note": None},
        "adult only": {"age": "adult", "sex": "both", "note": "Adults only"},
        "female only": {"age": "all", "sex": "female", "note": None},
        "neonate or infant": {"age": "neonate_infant", "sex": "both", "note": "Neonate/infant"},
        "absent": None,
    }
    values = {"stem": f"{STEM} Cholera", "extension": f"{STEM}&XN8Q Cholera", "other stem": "1B00 Other", "icd10": "A00 Cholera",
              "garbage": "hello world"}
    contexts = [("adult", "male"), ("child", "female"), ("infant", "male"), ("neonate", "female"), (None, None)]
    out = []
    for r_name, restriction in restrictions.items():
        for v_name, value in values.items():
            for group, sex in contexts:
                for unknown in (False, True):
                    for confirmed in (False, True):
                        try:
                            details, block = check_conclusive_cod(
                                "sid", value, causing_condition_unknown=unknown, age_restriction_confirmed=confirmed,
                                validate=_validate_for(restriction, group, sex))
                        except FinalCodRefusal as refusal:
                            if refusal.code == "AGE_RESTRICTION_CONFIRMATION_REQUIRED":
                                expected = {"outcome": "age_confirm", "message": refusal.message,
                                            "restriction": refusal.details["age_restriction"]}
                            else:
                                expected = {"outcome": "blocked", "message": refusal.message}
                        else:
                            if block:
                                expected = {"outcome": "blocked", "message": block.message}
                            else:
                                expected = {"outcome": "ok", "restriction": details}
                        name = f"{r_name} | {v_name} | {group}/{sex} | unknown={unknown} confirmed={confirmed}"
                        if unknown and v_name in ("icd10", "garbage"):
                            DIVERGENCES[f"underlying_cause:{name}"] = FLAG_ORDER_DIVERGENCE
                        out.append({
                            "name": f"{r_name} | {v_name} | {group}/{sex} | unknown={unknown} confirmed={confirmed}",
                            "restriction": restriction, "value": value, "age_group": group, "sex": sex,
                            "causing_condition_unknown": unknown, "age_restriction_confirmed": confirmed,
                            "expected": expected,
                        })
    return out


def reported_age_cases() -> list[dict]:
    return [{"name": repr(value), "estimated_age": value, "days": _age_days(value)} for value in REPORTED_AGES]


def build_vectors() -> dict:
    DIVERGENCES.clear()
    vectors = {
        "schema": SCHEMA,
        "limits": {
            "expression_max_length": _ICD11_CODE_EXPRESSION_MAX_LENGTH,
            "causing_condition_message": _causing_error("A00"),
        },
        "divergences": DIVERGENCES,
        "age_days": age_days_cases(),
        "age_group": age_group_cases(),
        "allowability": allowability_cases(),
        "age_confirmation": confirmation_cases(),
        "expression": expression_cases(),
        "causing_condition_unknown": causing_cases(),
        "underlying_cause": underlying_cases(),
        "reported_age": reported_age_cases(),
    }
    return vectors


def dump_vectors(vectors: dict) -> str:
    return json.dumps(vectors, indent=1, ensure_ascii=False) + "\n"


def main() -> int:
    vectors = build_vectors()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(dump_vectors(vectors), encoding="utf-8")
    counts = {k: len(v) for k, v in vectors.items() if isinstance(v, list)}
    print(f"{OUTPUT.relative_to(ROOT)}: {counts}, {OUTPUT.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
