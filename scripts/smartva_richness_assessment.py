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
  - smartva_field_endorsement_rankings.csv
  - smartva_who_to_tariff_parameters.csv
  - smartva_who_to_tariff_parameters.md
  - smartva_richness_summary.json
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
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
from smartva import config as smartva_config
from smartva.data import (
    adult_pre_symptom_data,
    adult_symptom_data,
    adult_tariff_data,
    child_pre_symptom_data,
    child_symptom_data,
    child_tariff_data,
    neonate_pre_symptom_data,
    neonate_symptom_data,
    neonate_tariff_data,
)
from smartva.data import who_data
from smartva.tariff_prep import TARIFF_CAUSE_NUM_KEY, get_tariff_matrix

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
_AGE_GROUP_CODE_RE = re.compile(r"^s(?:299\d|499\d|8888\d)$")
TARIFF_DATA_MODULES = {
    "adult": adult_tariff_data,
    "child": child_tariff_data,
    "neonate": neonate_tariff_data,
}
PRE_SYMPTOM_DATA_MODULES = {
    "adult": adult_pre_symptom_data,
    "child": child_pre_symptom_data,
    "neonate": neonate_pre_symptom_data,
}
SYMPTOM_DATA_MODULES = {
    "adult": adult_symptom_data,
    "child": child_symptom_data,
    "neonate": neonate_symptom_data,
}


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


def _is_generic_only_field(mapped_targets: list[str]) -> bool:
    if not mapped_targets:
        return False
    return all(target.startswith("gen_") or target == "interviewdate" for target in mapped_targets)


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
            MasFieldDisplayConfig.short_label,
            MasFieldDisplayConfig.full_label,
            MasFieldDisplayConfig.category_code,
        ).where(
            MasFieldDisplayConfig.form_type_id == form_type_id,
            MasFieldDisplayConfig.is_active == True,
        )
    ).all()
    return {
        row.field_id: {
            "odk_label": row.odk_label,
            "short_label": row.short_label,
            "full_label": row.full_label,
            "category_code": row.category_code,
        }
        for row in rows
    }


def _preferred_field_label(field_id: str, metadata: dict[str, Any]) -> str:
    return (
        metadata.get("short_label")
        or metadata.get("odk_label")
        or metadata.get("full_label")
        or field_id
    )


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
            short_label = metadata.get("short_label")
            full_label = metadata.get("full_label")
            domain, included_in_score = _determine_domain(field_id, category_code)
            mapped_targets = sorted(record["mapped_targets"])
            if _is_generic_only_field(mapped_targets):
                included_in_score = False

            field_row = {
                "field_id": field_id,
                "age_group": age_group,
                "field_label": _preferred_field_label(field_id, metadata),
                "short_label": short_label,
                "odk_label": odk_label,
                "full_label": full_label,
                "category_code": category_code,
                "domain": domain,
                "included_in_score": included_in_score and domain in RICHNESS_DOMAINS,
                "mapped_targets": mapped_targets,
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


def _as_bool_string(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "1", "yes"}:
        return True
    if text in {"false", "0", "no"}:
        return False
    return default


def _tariffs_filename(age_group: str) -> str:
    return os.path.join(smartva_config.basedir, "data", f"tariffs-{age_group}.csv")


def _normalize_feature_target(target: Any) -> str | None:
    if isinstance(target, tuple):
        if not target:
            return None
        return str(target[0])
    if target is None:
        return None
    return str(target)


def _build_feature_derivation_graph(age_group: str) -> dict[str, set[str]]:
    symptom_module = SYMPTOM_DATA_MODULES[age_group]
    graph: dict[str, set[str]] = defaultdict(set)

    for read_header, write_header in symptom_module.COPY_VARS.items():
        graph[str(read_header)].add(str(write_header))

    for read_header, mapping in symptom_module.BINARY_CONVERSION_MAP.items():
        if isinstance(mapping, dict):
            for write_header in mapping.values():
                graph[str(read_header)].add(str(write_header))

    for read_header, items in symptom_module.AGE_QUARTILE_BINARY_VARS.items():
        for _threshold, write_header in items:
            normalized = _normalize_feature_target(write_header)
            if normalized:
                graph[str(read_header)].add(normalized)

    return graph


def _expand_feature_targets(age_group: str, initial_targets: set[str]) -> set[str]:
    graph = _build_feature_derivation_graph(age_group)
    seen = set(initial_targets)
    queue = list(initial_targets)
    while queue:
        current = queue.pop()
        for nxt in graph.get(current, set()):
            if nxt in seen:
                continue
            seen.add(nxt)
            queue.append(nxt)
    return seen


def _map_dest_to_effective_features(age_group: str, dest: str) -> set[str]:
    pre_module = PRE_SYMPTOM_DATA_MODULES[age_group]
    symptom_module = SYMPTOM_DATA_MODULES[age_group]

    pre_var = pre_module.VAR_CONVERSION_MAP.get(dest)
    if not pre_var:
        return set()

    initial_targets: set[str] = set()

    duration_base = None
    if pre_var.endswith("a") or pre_var.endswith("b"):
        candidate = pre_var[:-1]
        if candidate in getattr(pre_module, "DURATION_VARS", []):
            duration_base = candidate
    if duration_base:
        pre_var = duration_base

    if pre_var in symptom_module.VAR_CONVERSION_MAP:
        initial_targets.add(str(symptom_module.VAR_CONVERSION_MAP[pre_var]))
    elif pre_var.startswith("s") or pre_var in {"age", "sex", "real_age", "real_gender"}:
        initial_targets.add(pre_var)

    if pre_var in getattr(pre_module, "FREE_TEXT_VARS", []):
        initial_targets.update(str(value) for value in pre_module.WORDS_TO_VARS.values())

    return _expand_feature_targets(age_group, initial_targets)


def build_field_to_effective_feature_rows(
    inventory: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for age_group in AGE_GROUPS:
        tariff_module = TARIFF_DATA_MODULES[age_group]
        symptom_descriptions = tariff_module.SYMPTOM_DESCRIPTIONS
        for field_scope in inventory[age_group]["fields"]:
            feature_rows: dict[str, dict[str, Any]] = {}
            for dest in field_scope["mapped_targets"]:
                for feature in _map_dest_to_effective_features(age_group, dest):
                    feature_label = symptom_descriptions.get(feature)
                    if not feature_label:
                        continue
                    feature_rows.setdefault(
                        feature,
                        {
                            "age_group": age_group,
                            "field_id": field_scope["field_id"],
                            "field_label": field_scope["field_label"],
                            "short_label": field_scope.get("short_label"),
                            "domain": field_scope["domain"],
                            "smartva_parameter": feature,
                            "smartva_parameter_label": feature_label,
                        },
                    )
            rows.extend(feature_rows.values())

    rows.sort(
        key=lambda row: (
            row["age_group"],
            row["field_id"],
            row["smartva_parameter"],
        )
    )
    return rows


def _active_tariff_feature_set(
    age_group: str,
    *,
    hce: bool,
    free_text: bool,
    short_form: bool = False,
) -> set[str]:
    tariff_module = TARIFF_DATA_MODULES[age_group]
    drop_headers = {TARIFF_CAUSE_NUM_KEY}
    if not hce:
        drop_headers.update(tariff_module.HCE_DROP_LIST)
    if not free_text:
        drop_headers.update(tariff_module.FREE_TEXT)
    if short_form:
        drop_headers.update(tariff_module.SHORT_FORM_DROP_LIST)

    tariffs = get_tariff_matrix(
        _tariffs_filename(age_group),
        drop_headers,
        tariff_module.SPURIOUS_ASSOCIATIONS,
    )
    return {
        symptom
        for features in tariffs.values()
        for symptom, _tariff in features
    }


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
                    "field_label": field_scope["field_label"],
                    "short_label": field_scope.get("short_label"),
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


def build_field_endorsement_rows(
    submission_rows: list[dict[str, Any]],
    inventory: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    grouped_rows: dict[str, dict[str, list[dict[str, Any]]]] = {
        age_group: {"all": [], "determined": [], "undetermined": []}
        for age_group in AGE_GROUPS
    }

    for row in submission_rows:
        payload = row["payload_data"] or {}
        age_group = _normalize_resultfor(row.get("va_smartva_resultfor")) or _determine_age_group_from_payload(payload)
        if age_group not in AGE_GROUPS:
            age_group = "adult"

        determination = _classify_determination(row)
        grouped_rows[age_group]["all"].append(payload)
        if determination in {"determined", "undetermined"}:
            grouped_rows[age_group][determination].append(payload)

    endorsement_rows: list[dict[str, Any]] = []
    for age_group in AGE_GROUPS:
        for scope_name, payloads in grouped_rows[age_group].items():
            total_count = len(payloads)
            for field_scope in inventory[age_group]["fields"]:
                if not field_scope["included_in_score"]:
                    continue

                positive_count = sum(
                    1 for payload in payloads if field_is_positive(payload, field_scope)
                )
                positive_rate = (positive_count / total_count) if total_count else None
                endorsement_rows.append(
                    {
                        "age_group": age_group,
                        "scope": scope_name,
                        "domain": field_scope["domain"],
                        "field_id": field_scope["field_id"],
                        "field_label": field_scope["field_label"],
                        "short_label": field_scope.get("short_label"),
                        "positive_count": positive_count,
                        "total_count": total_count,
                        "positive_rate": round(positive_rate, 4) if positive_rate is not None else None,
                    }
                )

    endorsement_rows.sort(
        key=lambda row: (
            row["age_group"],
            row["scope"],
            -(row["positive_rate"] or -1.0),
            row["domain"],
            row["field_id"],
        )
    )
    return endorsement_rows


def build_field_endorsement_summary(
    endorsement_rows: list[dict[str, Any]],
    *,
    top_n: int = 10,
) -> dict[str, Any]:
    summary = {
        "overall_top_fields": [],
        "by_age_group": {},
    }
    ranked_rows = [row for row in endorsement_rows if row["scope"] == "all" and row["positive_rate"] is not None]
    summary["overall_top_fields"] = ranked_rows[:top_n]
    for age_group in AGE_GROUPS:
        scoped = [row for row in ranked_rows if row["age_group"] == age_group]
        summary["by_age_group"][age_group] = scoped[:top_n]
    return summary


def build_who_to_tariff_parameter_rows(
    submission_rows: list[dict[str, Any]],
    inventory: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    field_feature_rows = build_field_to_effective_feature_rows(inventory)
    field_scope_by_age_group = {
        age_group: {field["field_id"]: field for field in scope["fields"]}
        for age_group, scope in inventory.items()
    }
    active_feature_cache: dict[tuple[str, bool, bool], set[str]] = {}

    def active_features(age_group: str, hce: bool, free_text: bool) -> set[str]:
        key = (age_group, hce, free_text)
        if key not in active_feature_cache:
            active_feature_cache[key] = _active_tariff_feature_set(
                age_group,
                hce=hce,
                free_text=free_text,
                short_form=False,
            )
        return active_feature_cache[key]

    grouped_rows: dict[tuple[str, str, str], dict[str, Any]] = {}

    for mapping_row in field_feature_rows:
        key = (
            mapping_row["age_group"],
            mapping_row["field_id"],
            mapping_row["smartva_parameter"],
        )
        grouped_rows[key] = {
            **mapping_row,
            "positive_count": 0,
            "total_count": 0,
            "positive_rate": None,
        }

    for submission_row in submission_rows:
        payload = submission_row["payload_data"] or {}
        age_group = _normalize_resultfor(submission_row.get("va_smartva_resultfor")) or _determine_age_group_from_payload(payload)
        if age_group not in AGE_GROUPS:
            age_group = "adult"

        hce = _as_bool_string(submission_row.get("form_smartvahce"), default=True)
        free_text = _as_bool_string(submission_row.get("form_smartvafreetext"), default=True)
        active_for_row = active_features(age_group, hce, free_text)
        scopes_for_age = field_scope_by_age_group[age_group]

        for key, row in grouped_rows.items():
            row_age_group, field_id, smartva_parameter = key
            if row_age_group != age_group:
                continue
            if smartva_parameter not in active_for_row:
                continue
            field_scope = scopes_for_age.get(field_id)
            if not field_scope:
                continue
            row["total_count"] += 1
            if field_is_positive(payload, field_scope):
                row["positive_count"] += 1

    output_rows: list[dict[str, Any]] = []
    for row in grouped_rows.values():
        if row["total_count"] == 0:
            continue
        output_row = dict(row)
        output_row["positive_rate"] = round(
            output_row["positive_count"] / output_row["total_count"], 4
        )
        output_rows.append(output_row)

    output_rows.sort(
        key=lambda row: (
            row["age_group"],
            row["positive_rate"],
            row["field_id"],
            row["smartva_parameter"],
        )
    )
    return output_rows


def build_who_to_tariff_markdown(
    rows: list[dict[str, Any]],
    *,
    filters: dict[str, Any],
) -> str:
    lines = [
        "# WHO To SmartVA Tariff Mapping",
        "",
        f"- Generated at UTC: {_utcnow_iso()}",
        f"- Project filter: {filters.get('project_code') or 'ALL'}",
        f"- Site filter: {filters.get('site_id') or 'ALL'}",
        f"- Form filter: {filters.get('form_id') or 'ALL'}",
        f"- Row limit: {filters.get('limit') or 'ALL'}",
        "",
        "Only WHO fields that map to at least one tariff-applied SmartVA parameter are listed.",
        "Endorsement percent is calculated on selected submissions where that SmartVA parameter is active for the form's current SmartVA flags.",
        "",
    ]

    for age_group in AGE_GROUPS:
        age_rows = [row for row in rows if row["age_group"] == age_group]
        if not age_rows:
            continue
        lines.extend(
            [
                f"## {age_group.capitalize()}",
                "",
                "| WHO Field ID | WHO Short Label | SmartVA Parameter | SmartVA Parameter Label | Endorsement % | Positive / Total |",
                "| --- | --- | --- | --- | ---: | ---: |",
            ]
        )
        for row in age_rows:
            field_label = (row.get("short_label") or row.get("field_label") or "").replace("|", "\\|")
            parameter_label = (row.get("smartva_parameter_label") or "").replace("|", "\\|")
            lines.append(
                "| {field_id} | {field_label} | {smartva_parameter} | {parameter_label} | {percent:.1f}% | {positive_count} / {total_count} |".format(
                    field_id=row["field_id"],
                    field_label=field_label,
                    smartva_parameter=row["smartva_parameter"],
                    parameter_label=parameter_label,
                    percent=(row["positive_rate"] or 0.0) * 100.0,
                    positive_count=row["positive_count"],
                    total_count=row["total_count"],
                )
            )
        lines.append("")

    lines.extend(
        [
            "## SmartVA Handling Notes",
            "",
            "### Retained",
            "- A WHO field is retained in this report only if it can reach at least one SmartVA symptom parameter that survives into the cleaned tariff matrix for the selected run settings.",
            "- In practice, that means the downstream parameter is still present after symptom preparation, module drop lists, HCE/free-text gating, zero-tariff removal, spurious-association removal, and top-40 tariff pruning per cause.",
            "",
            "### Collapsed",
            "- Many WHO fields do not survive one-to-one. Unit/value pairs are collapsed into one duration feature before tariffing.",
            "- Category questions often collapse into derived binary symptom flags. Examples in vendor code include rash-location splits such as `s23991` to `s23994`, breathing-position splits such as `s56991` to `s56994`, and several child/neonate delivery or severity flags.",
            "- Some symptom parameters are duplicated or copied forward. Neonate processing explicitly copies some abnormality features, so more than one WHO question can feed the same final tariff feature.",
            "",
            "### Transformed",
            "- Structured WHO responses are transformed by recodes, one-hot conversions from multiselect answers, duration normalization, numeric cutoffs, age-binning, and binary thresholding before tariff scoring.",
            "- The tariff engine scores the post-symptom `s...` features, not the original WHO field ids.",
            "",
            "### HCE Option",
            "- When HCE is disabled, the module-specific `HCE_DROP_LIST` features are removed from the tariff matrix before scoring.",
            "- When HCE is enabled, those HCE-listed features remain eligible, unless another setting removes them later.",
            "",
            "### Free-Text Option",
            "- Free text is converted in pre-symptom preparation by stemming words from module free-text fields and mapping them to `s9999...` word indicators.",
            "- When the CLI `--freetext` option is disabled, those `s9999...` word indicators are removed from tariff scoring.",
            "- When `--freetext` is enabled, the word indicators remain eligible, but they can still be filtered out later by spurious-association logic or by tariff top-N pruning.",
            "",
        ]
    )

    return "\n".join(lines)


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
            VaForms.form_smartvahce,
            VaForms.form_smartvafreetext,
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
            "form_smartvahce": row.form_smartvahce,
            "form_smartvafreetext": row.form_smartvafreetext,
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
        db.session.rollback()
        score_rows = build_submission_scores(submission_rows, inventory)
        comparison = build_determination_summary(score_rows)
        differentiators = build_field_differentiator_rows(submission_rows, inventory)
        differentiator_summary = build_field_differentiator_summary(differentiators)
        endorsements = build_field_endorsement_rows(submission_rows, inventory)
        endorsement_summary = build_field_endorsement_summary(endorsements)
        who_to_tariff_rows = build_who_to_tariff_parameter_rows(submission_rows, inventory)

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
        "field_endorsement_summary": endorsement_summary,
    }

    inventory_path = output_root / "smartva_field_value_inventory_by_age_group.json"
    scope_summary_path = output_root / "smartva_scope_summary_by_age_group.json"
    score_csv_path = output_root / "smartva_richness_per_submission.csv"
    comparison_csv_path = output_root / "smartva_richness_comparison.csv"
    differentiator_csv_path = output_root / "smartva_field_differentiators.csv"
    endorsement_csv_path = output_root / "smartva_field_endorsement_rankings.csv"
    who_to_tariff_csv_path = output_root / "smartva_who_to_tariff_parameters.csv"
    who_to_tariff_md_path = output_root / "smartva_who_to_tariff_parameters.md"
    summary_path = output_root / "smartva_richness_summary.json"

    _write_json(inventory_path, inventory_payload)
    _write_json(scope_summary_path, scope_summary)
    _write_csv(score_csv_path, score_rows)
    _write_csv(comparison_csv_path, comparison["comparison_rows"])
    _write_csv(differentiator_csv_path, differentiators)
    _write_csv(endorsement_csv_path, endorsements)
    _write_csv(who_to_tariff_csv_path, who_to_tariff_rows)
    who_to_tariff_md_path.write_text(
        build_who_to_tariff_markdown(
            who_to_tariff_rows,
            filters=scope_summary["filters"],
        ),
        encoding="utf-8",
    )
    _write_json(summary_path, summary_payload)

    return {
        "inventory_path": str(inventory_path),
        "scope_summary_path": str(scope_summary_path),
        "score_csv_path": str(score_csv_path),
        "comparison_csv_path": str(comparison_csv_path),
        "differentiator_csv_path": str(differentiator_csv_path),
        "endorsement_csv_path": str(endorsement_csv_path),
        "who_to_tariff_csv_path": str(who_to_tariff_csv_path),
        "who_to_tariff_md_path": str(who_to_tariff_md_path),
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
    print(f"Field endorsement rankings: {result['endorsement_csv_path']}")
    print(f"WHO to tariff mapping CSV: {result['who_to_tariff_csv_path']}")
    print(f"WHO to tariff mapping Markdown: {result['who_to_tariff_md_path']}")
    print(f"Summary: {result['summary_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
