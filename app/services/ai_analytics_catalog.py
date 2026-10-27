"""Built-in reports and the question catalog: fixed SQL over the AI tables.

docs/policy/ai-analytics-questions.md, "Phase 2". Neither makes a model call
or uses quota; both run through ``ai_analytics_sandbox.run_query`` and so
through the same parser check as model SQL (tests check every entry).

Built-in reports live here. The catalog is ``app/data/ai_question_catalog.json``
(``{"questions": [...]}``), written by ``flask ai-catalog generate`` or by
hand, each entry with ``key``, ``question``, ``description``, ``keywords``,
``sql`` and ``chart``; ``ai_search_service`` indexes the same fields.
``docs/kb/ai-question-catalog.md`` is rendered from it.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date
from pathlib import Path

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = _REPO_ROOT / "app" / "data" / "ai_question_catalog.json"
CATALOG_DOC_PATH = _REPO_ROOT / "docs" / "kb" / "ai-question-catalog.md"
KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,62}$")


def _chart(kind, x, series, dimension=None, reference=None):
    return {
        "type": kind, "x_column": x, "series_columns": list(series),
        "value_column": series[0] if len(series) == 1 else None, "x_dimension": dimension,
        "reference_column": reference,
    }


# Category columns keep their ai_cube name, so a chart segment can open the
# breakdown drawer (``x_dimension``).
BUILT_IN_REPORTS = (
    {
        "key": "workflow_funnel",
        "title": "Workflow funnel by state",
        "sql": "SELECT workflow_state, sum(n) AS cases FROM ai_cube GROUP BY workflow_state ORDER BY cases DESC",
        "chart": _chart("horizontal_bar", "workflow_state", ["cases"], "workflow_state"),
    },
    {
        "key": "cases_by_month",
        "title": "Cases by month",
        "sql": (
            "SELECT submission_month, sum(n) AS cases FROM ai_cube WHERE submission_month IS NOT NULL "
            "GROUP BY submission_month ORDER BY submission_month"
        ),
        "chart": _chart("line", "submission_month", ["cases"], "submission_month"),
    },
    {
        "key": "sex_by_age_band",
        "title": "Cases by sex and age band",
        "sql": (
            "SELECT analytics_age_band, "
            "sum(n) FILTER (WHERE lower(sex) = 'male') AS male, "
            "sum(n) FILTER (WHERE lower(sex) = 'female') AS female, "
            "sum(n) FILTER (WHERE sex IS NULL OR lower(sex) NOT IN ('male', 'female')) AS other_or_unknown "
            "FROM ai_cube GROUP BY analytics_age_band ORDER BY analytics_age_band"
        ),
        "chart": _chart("stacked_bar", "analytics_age_band", ["male", "female", "other_or_unknown"],
                        "analytics_age_band"),
    },
    {
        "key": "nqa_rating_mix",
        "title": "Narrative quality rating mix",
        "sql": "SELECT nqa_rating, sum(n) AS cases FROM ai_cube GROUP BY nqa_rating ORDER BY cases DESC",
        "chart": _chart("doughnut", "nqa_rating", ["cases"], "nqa_rating"),
    },
    {
        "key": "cause_section_share",
        "title": "Share of deaths by WHO 2026 VA cause section",
        "sql": (
            "SELECT authoritative_who_bucket_section, sum(n) AS deaths, "
            "round(100.0 * sum(n) / NULLIF(sum(sum(n)) OVER (), 0), 1) AS share_pct "
            "FROM ai_cube WHERE authoritative_who_bucket_section IS NOT NULL "
            "GROUP BY authoritative_who_bucket_section ORDER BY deaths DESC"
        ),
        "chart": _chart("horizontal_bar", "authoritative_who_bucket_section", ["deaths"],
                        "authoritative_who_bucket_section"),
    },
    {
        "key": "top_icd_codes",
        "title": "Top 15 ICD codes of the final cause",
        "sql": (
            "SELECT authoritative_icd, sum(n) AS deaths FROM ai_cube WHERE authoritative_icd IS NOT NULL "
            "GROUP BY authoritative_icd ORDER BY deaths DESC LIMIT 15"
        ),
        "chart": _chart("horizontal_bar", "authoritative_icd", ["deaths"], "authoritative_icd"),
    },
    {
        "key": "smartva_agreement",
        "title": "SmartVA top cause vs final cause, by cause",
        "sql": (
            "SELECT authoritative_who_bucket, sum(n) AS coded, "
            "sum(n) FILTER (WHERE smartva_cause1_who_bucket = authoritative_who_bucket) AS smartva_agrees, "
            "round(100.0 * sum(n) FILTER (WHERE smartva_cause1_who_bucket = authoritative_who_bucket) "
            "/ NULLIF(sum(n) FILTER (WHERE smartva_cause1_who_bucket IS NOT NULL), 0), 1) AS agreement_pct "
            "FROM ai_cube WHERE authoritative_who_bucket IS NOT NULL "
            "GROUP BY authoritative_who_bucket ORDER BY coded DESC LIMIT 20"
        ),
        "chart": _chart("bar", "authoritative_who_bucket", ["coded", "smartva_agrees"], "authoritative_who_bucket"),
    },
    {
        "key": "cases_by_site",
        "title": "Cases by site",
        "sql": "SELECT site_id, sum(n) AS cases FROM ai_cube GROUP BY site_id ORDER BY cases DESC",
        "chart": _chart("bar", "site_id", ["cases"], "site_id"),
    },
    # Comparative reports: each row against its peers or its own past.
    {
        "key": "intake_vs_recent_average",
        "title": "Cases this month against each site's 3-month average",
        "sql": (
            "WITH m AS (SELECT site_id, "
            "sum(n) FILTER (WHERE submission_month = date_trunc('month', CURRENT_DATE)::date) AS this_month, "
            "round(sum(n) FILTER (WHERE submission_month >= (date_trunc('month', CURRENT_DATE) - interval '3 months')::date "
            "AND submission_month < date_trunc('month', CURRENT_DATE)::date) / 3.0, 1) AS avg_last_3_months "
            "FROM ai_cube GROUP BY site_id) "
            "SELECT site_id, coalesce(this_month, 0) AS this_month, avg_last_3_months, "
            "round(100.0 * (coalesce(this_month, 0) - avg_last_3_months) / NULLIF(avg_last_3_months, 0), 1) AS change_pct "
            "FROM m WHERE avg_last_3_months > 0 ORDER BY change_pct"
        ),
        "chart": _chart("comparison", "site_id", ["this_month"], "site_id", "avg_last_3_months"),
    },
    {
        "key": "coded_share_vs_all_sites",
        "title": "Coded share per site against all sites",
        "sql": (
            "WITH s AS (SELECT site_id, sum(n) AS cases, sum(n) FILTER (WHERE authoritative_source IS NOT NULL) AS coded "
            "FROM ai_cube GROUP BY site_id) "
            "SELECT site_id, cases, round(100.0 * coded / NULLIF(cases, 0), 1) AS coded_pct, "
            "round(100.0 * sum(coded) OVER () / NULLIF(sum(cases) OVER (), 0), 1) AS all_sites_pct, "
            "rank() OVER (ORDER BY coded::numeric / NULLIF(cases, 0) DESC NULLS LAST) AS rank "
            "FROM s ORDER BY coded_pct DESC NULLS LAST"
        ),
        "chart": _chart("comparison", "site_id", ["coded_pct"], "site_id", "all_sites_pct"),
    },
    {
        "key": "backlog_vs_coders_by_language",
        "title": "Coding backlog per language against coders in that language",
        "sql": (
            "WITH b AS (SELECT narration_language AS lang, sum(n) AS backlog FROM ai_cube "
            "WHERE workflow_state IN ('ready_for_coding', 'coding_in_progress') GROUP BY narration_language), "
            "c AS (SELECT coding_language AS lang, sum(signed_in_30d) AS active_coders FROM ai_staff "
            "WHERE role = 'coder' AND coding_language IS NOT NULL GROUP BY coding_language) "
            "SELECT b.lang AS narration_language, b.backlog, coalesce(c.active_coders, 0) AS coders_signed_in_30d "
            "FROM b LEFT JOIN c ON c.lang = b.lang ORDER BY b.backlog DESC"
        ),
        "chart": _chart("bar", "narration_language", ["backlog", "coders_signed_in_30d"], "narration_language"),
    },
    {
        "key": "coder_smartva_agreement_vs_peers",
        "title": "Coder agreement with SmartVA against the project average",
        "sql": (
            "WITH c AS (SELECT coder_number, coder_name, project_id, sum(finals) AS finals, "
            "round(100.0 * sum(smartva_match) / NULLIF(sum(smartva_compared), 0), 1) AS match_pct, "
            "round(100.0 * sum(smartva_match_low_likelihood) / NULLIF(sum(smartva_low_likelihood), 0), 1) AS match_when_unlikely_pct "
            "FROM ai_coder GROUP BY coder_number, coder_name, project_id HAVING sum(smartva_compared) >= 10) "
            "SELECT c.*, round(avg(match_pct) OVER (PARTITION BY project_id), 1) AS peer_average_pct "
            "FROM c ORDER BY match_when_unlikely_pct DESC NULLS LAST"
        ),
        "chart": _chart("comparison", "coder_name", ["match_pct", "match_when_unlikely_pct"], None, "peer_average_pct"),
    },
)
_BUILT_IN = {report["key"]: report for report in BUILT_IN_REPORTS}

_cache: dict = {"mtime": None, "entries": []}


def builtin(key) -> dict | None:
    return _BUILT_IN.get(key) if isinstance(key, str) else None


def load_catalog() -> list[dict]:
    """Catalog entries from the shipped JSON (reread when the file changes);
    an absent or unreadable file means none."""
    try:
        mtime = CATALOG_PATH.stat().st_mtime
    except OSError:
        return []
    if _cache["mtime"] != mtime:
        try:
            raw = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            log.warning("AI question catalog is unreadable", exc_info=True)
            raw = {}
        entries = raw.get("questions", []) if isinstance(raw, dict) else []
        _cache.update(mtime=mtime, entries=[e for e in entries if _well_formed(e)])
    return _cache["entries"]


def catalog_entry(key) -> dict | None:
    if not isinstance(key, str):
        return None
    return next((e for e in load_catalog() if e["key"] == key), None)


def _well_formed(entry) -> bool:
    return (
        isinstance(entry, dict)
        and isinstance(entry.get("key"), str) and bool(KEY_PATTERN.match(entry["key"]))
        and isinstance(entry.get("question"), str) and bool(entry["question"].strip())
        and isinstance(entry.get("sql"), str)
        and isinstance(entry.get("chart"), dict)
    )


def write_catalog(entries: list[dict], *, source: str) -> None:
    """Write *entries* to the JSON catalog and its KB page (``docs/kb``)."""
    CATALOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CATALOG_PATH.write_text(
        json.dumps({"source": source, "questions": entries}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    lines = [
        "---",
        "title: AI question catalog",
        "doc_type: kb",
        "status: active",
        "owner: engineering",
        f"last_updated: {date.today().isoformat()}",
        "---",
        "",
        "# AI question catalog",
        "",
        "Fixed questions with SQL over the AI tables (`ai_cube`, `ai_org_levels`, `ai_staff`,",
        "`ai_coder`), offered on the AI questions page",
        "(docs/policy/ai-analytics-questions.md). Choosing one runs its stored SQL",
        "with no model call and no quota. Generated from",
        "`app/data/ai_question_catalog.json`; regenerate with",
        "`flask ai-catalog generate`, never edit this page by hand.",
        "",
        f"Source: {source}. Questions: {len(entries)}.",
        "",
    ]
    for entry in entries:
        lines += [
            f"## {entry['question']}",
            "",
            f"Key `{entry['key']}`. {entry.get('description') or ''}".rstrip(),
            "",
            "```sql",
            entry["sql"],
            "```",
            "",
        ]
    CATALOG_DOC_PATH.write_text("\n".join(lines), encoding="utf-8")
