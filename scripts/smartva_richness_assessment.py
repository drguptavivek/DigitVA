#!/usr/bin/env python3
"""Assess SmartVA field coverage and richness against current payloads.

Usage (inside Docker):
  docker compose exec minerva_app_service \
    uv run python scripts/smartva_richness_assessment.py --project-code ICMR01

Outputs:
  - smartva_field_value_inventory_by_age_group.json
  - smartva_scope_summary_by_age_group.json
  - smartva_richness_per_submission.csv
  - smartva_richness_comparison.csv
  - smartva_field_differentiators.csv
  - smartva_richness_summary.json
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import sqlalchemy as sa

from app import create_app, db
from app.models import (
    MasFieldDisplayConfig,
    MasFormTypes,
    VaForms,
    VaSmartvaResults,
    VaStatuses,
    VaSubmissionPayloadVersion,
    VaSubmissions,
)
from smartva.data import who_data

AGE_GROUPS = ("adult", "child", "neonate")
DOMAIN_WEIGHTS = {
    "injury": 0.20,
    "symptoms": 0.50,
    "keywords": 0.20,
    "narration": 0.10,
}
RICHNESS_DOMAINS = tuple(DOMAIN_WEIGHTS.keys())
CONTEXT_ONLY_FIELDS = {"Id10013", "Id10019"}
NARRATION_FIELD = "Id10476"
KEYWORD_FIELDS = {"Id10477", "Id10478", "Id10479"}
INJURY_FALLBACK_FIELDS = {
    *(f"Id{num}" for num in range(10077, 10101)),
    "Id10259",
    "Id10260",
}
_BASE_FIELD_ID_RE = re.compile(r"^(Id\d+)", flags=re.IGNORECASE)


@dataclass(frozen=True)
class RunConfig:
    output_root: Path
    project_code: str | None
    site_id: str | None
    form_id: str | None
    limit: int | None


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _default_output_root() -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return _repo_root() / "private" / "smartva_richness" / timestamp


def _base_field_id(value: str | None) -> str | None:
    if not value:
        return None
    match = _BASE_FIELD_ID_RE.match(str(value).strip())
    if not match:
        return None
    base = match.group(1)
    return f"Id{base[2:]}"


def _dest_age_groups(dest: str) -> tuple[str, ...]:
    if dest.startswith("adult_"):
        return ("adult",)
    if dest.startswith("child_"):
        return ("child",)
    if dest.startswith("neonate_"):
        return ("neonate",)
    return AGE_GROUPS


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    if isinstance(value, str) and value.strip().lower() in {"", "nan", "none"}:
        return True
    return False


def _normalize_token(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _tokenize_multiselect(value: Any) -> set[str]:
    if _is_blank(value):
        return set()
    text = str(value).strip()
    if not text:
        return set()
    return {token for token in text.split() if token}


def _safe_float(value: Any) -> float | None:
    if _is_blank(value):
        return None
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    return round(statistics.median(values), 4)


def _normalize_resultfor(value: str | None) -> str | None:
    if not value:
        return None
    text = str(value).strip().lower()
    if text in {"adult", "for_adult"}:
        return "adult"
    if text in {"child", "for_child"}:
        return "child"
    if text in {"neonate", "for_neonate"}:
        return "neonate"
    return None


def _determine_age_group_from_payload(payload: dict[str, Any]) -> str | None:
    for key in ("ageInYears", "age_adult", "age_child_years"):
        years = _safe_float(payload.get(key))
        if years is None:
            continue
        if years >= 12:
            return "adult"
        if years >= 1:
            return "child"

    for key in ("ageInMonths", "age_child_months"):
        months = _safe_float(payload.get(key))
        if months is None:
            continue
        if months >= 1:
            return "child"

    for key in ("ageInDays", "ageInDaysNeonate", "age_neonate_days", "age_child_days"):
        days = _safe_float(payload.get(key))
        if days is None:
            continue
        if days <= 28:
            return "neonate"
        if days < 12 * 365:
            return "child"
        return "adult"

    for age_group, flag in (
        ("adult", ("isAdult", "isAdult1", "isAdult2")),
        ("child", ("isChild", "isChild1", "isChild2")),
        ("neonate", ("isNeonate", "isNeonate1", "isNeonate2")),
    ):
        for key in flag:
            if _safe_float(payload.get(key)) == 1:
                return age_group
    return None


def _determine_domain(field_id: str, category_code: str | None) -> tuple[str, bool]:
    if field_id == NARRATION_FIELD:
        return "narration", True
    if field_id in KEYWORD_FIELDS:
        return "keywords", True
    if field_id in CONTEXT_ONLY_FIELDS:
        return "context", False

    category_text = (category_code or "").lower()
    if "injur" in category_text or field_id in INJURY_FALLBACK_FIELDS:
        return "injury", True

    return "symptoms", True


def _new_scope_record(field_id: str, age_group: str) -> dict[str, Any]:
    return {
        "field_id": field_id,
        "age_group": age_group,
        "category_code": None,
        "odk_label": None,
        "domain": None,
        "included_in_score": False,
        "mapped_targets": set(),
        "signal_types": set(),
        "positive_values": set(),
        "rules": [],
    }


def _register_signal(
    scopes: dict[str, dict[str, dict[str, Any]]],
    *,
    src: str | None,
    dest: str,
    signal_type: str,
    positive_values: list[str] | tuple[str, ...] | set[str] | None = None,
) -> None:
    field_id = _base_field_id(src)
    if not field_id:
        return
    for age_group in _dest_age_groups(dest):
        record = scopes[age_group].setdefault(field_id, _new_scope_record(field_id, age_group))
        record["mapped_targets"].add(dest)
        record["signal_types"].add(signal_type)
        normalized_values = sorted({_normalize_token(value) for value in (positive_values or []) if _normalize_token(value)})
        record["positive_values"].update(normalized_values)
        record["rules"].append(
            {
                "signal_type": signal_type,
                "mapped_target": dest,
                "positive_values": normalized_values,
            }
        )


def _effective_yes_no_questions() -> dict[str, str]:
    effective = dict(who_data.YES_NO_QUESTIONS)
    effective.update(who_data.YES_NO_QUESTIONS_WHO_2022)
    return effective


def _positive_mapping_keys(mapping: dict[Any, Any]) -> list[str]:
    positive_values: list[str] = []
    for raw_value, recoded in mapping.items():
        if recoded in {"", None, 8, 9}:
            continue
        positive_values.append(str(raw_value))
    return sorted(set(positive_values))


def build_vendor_field_scopes() -> dict[str, dict[str, dict[str, Any]]]:
    scopes: dict[str, dict[str, dict[str, Any]]] = {age_group: {} for age_group in AGE_GROUPS}

    for dest, src in _effective_yes_no_questions().items():
        _register_signal(scopes, src=src, dest=dest, signal_type="yes_only", positive_values=("yes",))

    for (dest, src), mapping in who_data.RECODE_QUESTIONS.items():
        _register_signal(
            scopes,
            src=src,
            dest=dest,
            signal_type="mapped_choice_positive",
            positive_values=_positive_mapping_keys(mapping),
        )

    for dest, src in who_data.RENAME_QUESTIONS.items():
        _register_signal(scopes, src=src, dest=dest, signal_type="informative_value")

    for dest, mapping in who_data.REVERSE_ONE_HOT_MULTISELECT.items():
        for src in mapping.keys():
            _register_signal(scopes, src=src, dest=dest, signal_type="yes_only", positive_values=("yes",))

    for (dest, src), mapping in who_data.RECODE_MULTISELECT.items():
        _register_signal(
            scopes,
            src=src,
            dest=dest,
            signal_type="multiselect_any_positive",
            positive_values=_positive_mapping_keys(mapping),
        )

    for dest, (src, choice) in who_data.ONE_HOT_FROM_MULTISELECT.items():
        _register_signal(
            scopes,
            src=src,
            dest=dest,
            signal_type="multiselect_any_positive",
            positive_values=(choice,),
        )

    for dest, unit_data in who_data.UNIT_IF_AMOUNT.items():
        if isinstance(unit_data, dict):
            for src in unit_data.keys():
                _register_signal(scopes, src=src, dest=dest, signal_type="numeric_positive")
        else:
            src, _unit = unit_data
            _register_signal(scopes, src=src, dest=dest, signal_type="numeric_positive")

    for (unit_col, value_col, _unit), mapping in who_data.DURATION_CONVERSIONS.items():
        for src in mapping.keys():
            _register_signal(scopes, src=src, dest=unit_col, signal_type="numeric_positive")
            _register_signal(scopes, src=src, dest=value_col, signal_type="numeric_positive")

    for src, (dest1, dest2) in who_data.COMBINED_TO_MULTIPLE_WHO_2022.items():
        _register_signal(scopes, src=src, dest=dest1, signal_type="yes_only", positive_values=("yes",))
        _register_signal(scopes, src=src, dest=dest2, signal_type="yes_only", positive_values=("yes",))

    return scopes


def _load_field_metadata() -> dict[str, dict[str, Any]]:
    form_type_id = db.session.scalar(
        sa.select(MasFormTypes.form_type_id).where(MasFormTypes.form_type_code == "WHO_2022_VA")
    )
    if form_type_id is None:
        return {}

    rows = db.session.execute(
        sa.select(
            MasFieldDisplayConfig.field_id,
            MasFieldDisplayConfig.odk_label,
            MasFieldDisplayConfig.category_code,
        ).where(
            MasFieldDisplayConfig.form_type_id == form_type_id,
            MasFieldDisplayConfig.is_active == True,
        )
    ).all()
    return {
        row.field_id: {
            "odk_label": row.odk_label,
            "category_code": row.category_code,
        }
        for row in rows
    }


def build_age_group_inventory() -> dict[str, dict[str, Any]]:
    field_metadata = _load_field_metadata()
    raw_scopes = build_vendor_field_scopes()
    inventory: dict[str, dict[str, Any]] = {}

    for age_group in AGE_GROUPS:
        fields: list[dict[str, Any]] = []
        domain_counts = {domain: 0 for domain in RICHNESS_DOMAINS}
        for field_id in sorted(raw_scopes[age_group].keys()):
            record = raw_scopes[age_group][field_id]
            metadata = field_metadata.get(field_id, {})
            category_code = metadata.get("category_code")
            odk_label = metadata.get("odk_label")
            domain, included_in_score = _determine_domain(field_id, category_code)

            field_row = {
                "field_id": field_id,
                "age_group": age_group,
                "odk_label": odk_label or field_id,
                "category_code": category_code,
                "domain": domain,
                "included_in_score": included_in_score and domain in RICHNESS_DOMAINS,
                "mapped_targets": sorted(record["mapped_targets"]),
                "signal_types": sorted(record["signal_types"]),
                "positive_values": sorted(record["positive_values"]),
                "rules": sorted(
                    record["rules"],
                    key=lambda item: (item["mapped_target"], item["signal_type"]),
                ),
            }
            if field_row["included_in_score"]:
                domain_counts[domain] += 1
            fields.append(field_row)

        inventory[age_group] = {
            "fields": fields,
            "domain_expected_counts": domain_counts,
        }

    return inventory


def _value_matches(value: Any, candidates: list[str] | set[str]) -> bool:
    if _is_blank(value):
        return False
    raw = _normalize_token(value)
    lowered = raw.lower()
    normalized = {candidate.lower() for candidate in candidates}
    return raw in candidates or lowered in normalized


def signal_is_positive(value: Any, rule: dict[str, Any]) -> bool:
    signal_type = rule["signal_type"]
    positive_values = rule.get("positive_values") or []

    if signal_type == "yes_only":
        return _normalize_token(value).lower() == "yes"

    if signal_type == "mapped_choice_positive":
        return _value_matches(value, positive_values)

    if signal_type == "multiselect_any_positive":
        tokens = _tokenize_multiselect(value)
        if not tokens:
            return False
        raw_candidates = set(positive_values)
        lower_candidates = {candidate.lower() for candidate in positive_values}
        return any(token in raw_candidates or token.lower() in lower_candidates for token in tokens)

    if signal_type == "numeric_positive":
        number = _safe_float(value)
        return number is not None and number > 0

    if signal_type == "informative_value":
        if _is_blank(value):
            return False
        number = _safe_float(value)
        if number is not None:
            return number > 0
        return True

    return False


def field_is_positive(payload: dict[str, Any], field_scope: dict[str, Any]) -> bool:
    value = payload.get(field_scope["field_id"])
    return any(signal_is_positive(value, rule) for rule in field_scope["rules"])


def score_submission(payload: dict[str, Any], age_group: str, age_scope: dict[str, Any]) -> dict[str, Any]:
    counts = {domain: 0 for domain in RICHNESS_DOMAINS}
    expected = age_scope["domain_expected_counts"]

    for field_scope in age_scope["fields"]:
        if not field_scope["included_in_score"]:
            continue
        if field_is_positive(payload, field_scope):
            counts[field_scope["domain"]] += 1

    ratios: dict[str, float] = {}
    weighted_scores: dict[str, float] = {}
    total_score = 0.0
    for domain in RICHNESS_DOMAINS:
        denominator = expected.get(domain, 0)
        ratio = (counts[domain] / denominator) if denominator else 0.0
        weighted_score = ratio * DOMAIN_WEIGHTS[domain] * 100.0
        ratios[domain] = round(ratio, 4)
        weighted_scores[domain] = round(weighted_score, 4)
        total_score += weighted_score

    return {
        "age_group": age_group,
        "counts": counts,
        "expected": expected,
        "ratios": ratios,
        "weighted_scores": weighted_scores,
        "total_score": round(total_score, 4),
    }


def _classify_determination(row: dict[str, Any]) -> str:
    outcome = _normalize_token(row.get("va_smartva_outcome")).lower()
    cause1 = _normalize_token(row.get("va_smartva_cause1")).lower()

    if outcome == VaSmartvaResults.OUTCOME_FAILED:
        return "failed"
    if outcome != VaSmartvaResults.OUTCOME_SUCCESS:
        return "missing"
    if cause1 == "undetermined":
        return "undetermined"
    if cause1:
        return "determined"
    return "missing"


def build_determination_summary(score_rows: list[dict[str, Any]]) -> dict[str, Any]:
    comparison_rows: list[dict[str, Any]] = []
    summary: dict[str, Any] = {
        "overall": {},
        "by_age_group": {},
    }

    def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            if row["determination"] in {"determined", "undetermined"}:
                grouped[row["determination"]].append(row)

        result: dict[str, Any] = {}
        for determination in ("determined", "undetermined"):
            items = grouped.get(determination, [])
            domain_means = {
                domain: _mean([item[f"{domain}_ratio"] for item in items])
                for domain in RICHNESS_DOMAINS
            }
            weighted_means = {
                domain: _mean([item[f"{domain}_weighted_score"] for item in items])
                for domain in RICHNESS_DOMAINS
            }
            stats_row = {
                "count": len(items),
                "mean_total_score": _mean([item["total_score"] for item in items]),
                "median_total_score": _median([item["total_score"] for item in items]),
                "domain_ratio_means": domain_means,
                "domain_weighted_score_means": weighted_means,
            }
            result[determination] = stats_row
        return result

    summary["overall"] = summarize(score_rows)
    for age_group in AGE_GROUPS:
        age_rows = [row for row in score_rows if row["age_group"] == age_group]
        summary["by_age_group"][age_group] = summarize(age_rows)

    for scope, payload in [("overall", summary["overall"])] + list(summary["by_age_group"].items()):
        for determination in ("determined", "undetermined"):
            stats_row = payload.get(determination) or {}
            comparison_row = {
                "scope": scope,
                "determination": determination,
                "count": stats_row.get("count", 0),
                "mean_total_score": stats_row.get("mean_total_score"),
                "median_total_score": stats_row.get("median_total_score"),
            }
            for domain in RICHNESS_DOMAINS:
                comparison_row[f"{domain}_ratio_mean"] = (stats_row.get("domain_ratio_means") or {}).get(domain)
                comparison_row[f"{domain}_weighted_score_mean"] = (
                    stats_row.get("domain_weighted_score_means") or {}
                ).get(domain)
            comparison_rows.append(comparison_row)

    return {
        "summary": summary,
        "comparison_rows": comparison_rows,
    }


def build_field_differentiator_rows(
    submission_rows: list[dict[str, Any]],
    inventory: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    grouped_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in submission_rows:
        determination = _classify_determination(row)
        if determination not in {"determined", "undetermined"}:
            continue

        payload = row["payload_data"] or {}
        age_group = _normalize_resultfor(row.get("va_smartva_resultfor")) or _determine_age_group_from_payload(payload)
        if age_group not in AGE_GROUPS:
            age_group = "adult"

        grouped_rows[age_group].append(
            {
                "payload": payload,
                "determination": determination,
            }
        )

    differentiator_rows: list[dict[str, Any]] = []
    for age_group in AGE_GROUPS:
        scoped_rows = grouped_rows.get(age_group, [])
        determined_rows = [row for row in scoped_rows if row["determination"] == "determined"]
        undetermined_rows = [row for row in scoped_rows if row["determination"] == "undetermined"]

        for field_scope in inventory[age_group]["fields"]:
            if not field_scope["included_in_score"]:
                continue

            determined_positive = sum(
                1 for row in determined_rows if field_is_positive(row["payload"], field_scope)
            )
            undetermined_positive = sum(
                1 for row in undetermined_rows if field_is_positive(row["payload"], field_scope)
            )

            determined_rate = (
                determined_positive / len(determined_rows) if determined_rows else None
            )
            undetermined_rate = (
                undetermined_positive / len(undetermined_rows) if undetermined_rows else None
            )
            rate_delta = None
            abs_rate_delta = None
            if determined_rate is not None and undetermined_rate is not None:
                rate_delta = round(determined_rate - undetermined_rate, 4)
                abs_rate_delta = round(abs(rate_delta), 4)

            differentiator_rows.append(
                {
                    "age_group": age_group,
                    "domain": field_scope["domain"],
                    "field_id": field_scope["field_id"],
                    "odk_label": field_scope["odk_label"],
                    "determined_count": len(determined_rows),
                    "determined_positive_count": determined_positive,
                    "determined_positive_rate": (
                        round(determined_rate, 4) if determined_rate is not None else None
                    ),
                    "undetermined_count": len(undetermined_rows),
                    "undetermined_positive_count": undetermined_positive,
                    "undetermined_positive_rate": (
                        round(undetermined_rate, 4) if undetermined_rate is not None else None
                    ),
                    "rate_delta": rate_delta,
                    "abs_rate_delta": abs_rate_delta,
                }
            )

    differentiator_rows.sort(
        key=lambda row: (
            row["age_group"],
            -(row["abs_rate_delta"] or -1.0),
            row["domain"],
            row["field_id"],
        )
    )
    return differentiator_rows


def build_field_differentiator_summary(
    differentiator_rows: list[dict[str, Any]],
    *,
    top_n: int = 10,
) -> dict[str, Any]:
    summary = {
        "overall_top_fields": [],
        "by_age_group": {},
    }
    ranked_rows = [row for row in differentiator_rows if row["abs_rate_delta"] is not None]
    summary["overall_top_fields"] = ranked_rows[:top_n]
    for age_group in AGE_GROUPS:
        scoped = [row for row in ranked_rows if row["age_group"] == age_group]
        summary["by_age_group"][age_group] = scoped[:top_n]
    return summary


def _latest_active_smartva_subquery():
    ranked = (
        sa.select(
            VaSmartvaResults.va_sid.label("va_sid"),
            VaSmartvaResults.va_smartva_outcome.label("va_smartva_outcome"),
            VaSmartvaResults.va_smartva_resultfor.label("va_smartva_resultfor"),
            VaSmartvaResults.va_smartva_cause1.label("va_smartva_cause1"),
            VaSmartvaResults.va_smartva_updatedat.label("va_smartva_updatedat"),
            sa.func.row_number().over(
                partition_by=VaSmartvaResults.va_sid,
                order_by=(VaSmartvaResults.va_smartva_updatedat.desc(), VaSmartvaResults.va_smartva_addedat.desc()),
            ).label("rn"),
        )
        .where(VaSmartvaResults.va_smartva_status == VaStatuses.active)
        .subquery()
    )
    return sa.select(ranked).where(ranked.c.rn == 1).subquery()


def load_submission_rows(config: RunConfig) -> list[dict[str, Any]]:
    smartva_sq = _latest_active_smartva_subquery()
    stmt = (
        sa.select(
            VaSubmissions.va_sid,
            VaSubmissions.va_form_id,
            VaForms.project_id,
            VaForms.site_id,
            VaSubmissionPayloadVersion.payload_data,
            smartva_sq.c.va_smartva_outcome,
            smartva_sq.c.va_smartva_resultfor,
            smartva_sq.c.va_smartva_cause1,
        )
        .join(VaForms, VaForms.form_id == VaSubmissions.va_form_id)
        .join(
            VaSubmissionPayloadVersion,
            VaSubmissionPayloadVersion.payload_version_id == VaSubmissions.active_payload_version_id,
        )
        .outerjoin(smartva_sq, smartva_sq.c.va_sid == VaSubmissions.va_sid)
        .order_by(VaSubmissions.va_sid)
    )

    if config.project_code:
        stmt = stmt.where(VaForms.project_id == config.project_code)
    if config.site_id:
        stmt = stmt.where(VaForms.site_id == config.site_id)
    if config.form_id:
        stmt = stmt.where(VaForms.form_id == config.form_id)
    if config.limit is not None:
        stmt = stmt.limit(config.limit)

    rows = db.session.execute(stmt).all()
    return [
        {
            "va_sid": row.va_sid,
            "form_id": row.va_form_id,
            "project_id": row.project_id,
            "site_id": row.site_id,
            "payload_data": row.payload_data or {},
            "va_smartva_outcome": row.va_smartva_outcome,
            "va_smartva_resultfor": row.va_smartva_resultfor,
            "va_smartva_cause1": row.va_smartva_cause1,
        }
        for row in rows
    ]


def build_submission_scores(rows: list[dict[str, Any]], inventory: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    score_rows: list[dict[str, Any]] = []

    for row in rows:
        payload = row["payload_data"] or {}
        age_group = _normalize_resultfor(row.get("va_smartva_resultfor")) or _determine_age_group_from_payload(payload)
        if age_group not in AGE_GROUPS:
            age_group = "adult"

        scored = score_submission(payload, age_group, inventory[age_group])
        output_row = {
            "va_sid": row["va_sid"],
            "project_id": row["project_id"],
            "site_id": row["site_id"],
            "form_id": row["form_id"],
            "age_group": age_group,
            "va_smartva_outcome": row.get("va_smartva_outcome"),
            "va_smartva_cause1": row.get("va_smartva_cause1"),
            "determination": _classify_determination(row),
            "total_score": scored["total_score"],
        }

        for domain in RICHNESS_DOMAINS:
            output_row[f"{domain}_positive_count"] = scored["counts"][domain]
            output_row[f"{domain}_expected_count"] = scored["expected"][domain]
            output_row[f"{domain}_ratio"] = scored["ratios"][domain]
            output_row[f"{domain}_weighted_score"] = scored["weighted_scores"][domain]

        score_rows.append(output_row)

    return score_rows


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=False), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    headers = list(rows[0].keys()) if rows else []
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def run(config: RunConfig) -> dict[str, Any]:
    app = create_app()
    output_root = config.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    with app.app_context():
        inventory = build_age_group_inventory()
        submission_rows = load_submission_rows(config)
        score_rows = build_submission_scores(submission_rows, inventory)
        comparison = build_determination_summary(score_rows)
        differentiators = build_field_differentiator_rows(submission_rows, inventory)
        differentiator_summary = build_field_differentiator_summary(differentiators)

    scope_summary = {
        "generated_at_utc": _utcnow_iso(),
        "filters": {
            "project_code": config.project_code,
            "site_id": config.site_id,
            "form_id": config.form_id,
            "limit": config.limit,
        },
        "domain_weights": DOMAIN_WEIGHTS,
        "age_groups": {
            age_group: {
                "expected_field_counts": inventory[age_group]["domain_expected_counts"],
                "field_count": len(inventory[age_group]["fields"]),
            }
            for age_group in AGE_GROUPS
        },
    }
    inventory_payload = {
        "generated_at_utc": _utcnow_iso(),
        "filters": scope_summary["filters"],
        "domain_weights": DOMAIN_WEIGHTS,
        "age_groups": inventory,
    }
    summary_payload = {
        "generated_at_utc": _utcnow_iso(),
        "filters": scope_summary["filters"],
        "domain_weights": DOMAIN_WEIGHTS,
        "submission_count": len(score_rows),
        "determination_summary": comparison["summary"],
        "field_differentiator_summary": differentiator_summary,
    }

    inventory_path = output_root / "smartva_field_value_inventory_by_age_group.json"
    scope_summary_path = output_root / "smartva_scope_summary_by_age_group.json"
    score_csv_path = output_root / "smartva_richness_per_submission.csv"
    comparison_csv_path = output_root / "smartva_richness_comparison.csv"
    differentiator_csv_path = output_root / "smartva_field_differentiators.csv"
    summary_path = output_root / "smartva_richness_summary.json"

    _write_json(inventory_path, inventory_payload)
    _write_json(scope_summary_path, scope_summary)
    _write_csv(score_csv_path, score_rows)
    _write_csv(comparison_csv_path, comparison["comparison_rows"])
    _write_csv(differentiator_csv_path, differentiators)
    _write_json(summary_path, summary_payload)

    return {
        "inventory_path": str(inventory_path),
        "scope_summary_path": str(scope_summary_path),
        "score_csv_path": str(score_csv_path),
        "comparison_csv_path": str(comparison_csv_path),
        "differentiator_csv_path": str(differentiator_csv_path),
        "summary_path": str(summary_path),
        "submission_count": len(score_rows),
    }


def parse_args() -> RunConfig:
    parser = argparse.ArgumentParser(
        description="Assess SmartVA richness from current payloads and active SmartVA results."
    )
    parser.add_argument("--project-code", default=None, help="Optional project code filter.")
    parser.add_argument("--site-id", default=None, help="Optional site id filter.")
    parser.add_argument("--form-id", default=None, help="Optional form id filter.")
    parser.add_argument("--limit", type=int, default=None, help="Optional row limit for smoke runs.")
    parser.add_argument(
        "--output-root",
        default=None,
        help="Optional output folder. Default: ./private/smartva_richness/<timestamp>",
    )
    args = parser.parse_args()

    output_root = Path(args.output_root).expanduser() if args.output_root else _default_output_root()
    return RunConfig(
        output_root=output_root,
        project_code=(str(args.project_code).strip() or None) if args.project_code else None,
        site_id=(str(args.site_id).strip() or None) if args.site_id else None,
        form_id=(str(args.form_id).strip() or None) if args.form_id else None,
        limit=args.limit,
    )


def main() -> int:
    config = parse_args()
    result = run(config)
    print(f"Submission rows scored: {result['submission_count']}")
    print(f"Inventory: {result['inventory_path']}")
    print(f"Scope summary: {result['scope_summary_path']}")
    print(f"Per-submission scores: {result['score_csv_path']}")
    print(f"Determined vs undetermined comparison: {result['comparison_csv_path']}")
    print(f"Field differentiators: {result['differentiator_csv_path']}")
    print(f"Summary: {result['summary_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
