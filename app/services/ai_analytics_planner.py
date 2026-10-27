"""Turn a question into SQL over ``ai_cube`` with a model, run it, keep it.

docs/policy/ai-analytics-questions.md. What leaves DigitVA is only the fixed
``SYSTEM_INSTRUCTION``, the question (with, on a follow-up, the previous SQL
and up to five earlier questions) and, on the one retry, the SQLSTATE and
primary message of the database error for the model's own SQL with every
quoted value redacted. No result row is ever sent to the model. The provider
(Claude or Gemini, app/services/ai_analytics_providers.py) is the user's
choice among the enabled ones.

Every model call writes one ``ai_llm`` audit row with its provider, model
and token usage; those rows since the start of the ISO week are the user's
quota (admins exempt). A saved-query rerun makes no model call, uses no quota
and writes a ``saved_query_rerun`` row. Built-in reports and catalog entries
run fixed SQL with no model call, no quota and no audit row. Saved queries
belong to one user: every lookup filters on the owner.

ponytail: the quota is read, then the call is made: two concurrent asks can
both pass at the last remaining call. A row lock or counter fixes it if the
overshoot (one call per concurrent request) ever matters.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

import sqlalchemy as sa
from flask import current_app

from app import db
from app.models.va_ai_analytics import (
    AI_MODE_LLM,
    AI_MODE_SAVED_RERUN,
    VaAiQueryAuditLog,
    VaAiSavedQuery,
)
from app.services import ai_analytics_catalog as catalog
from app.services import ai_analytics_providers as providers
from app.services import ai_analytics_sandbox as sandbox
from app.services import ai_search_service

log = logging.getLogger(__name__)

MAX_TURNS = 6
MAX_EARLIER_QUESTIONS = 5
MAX_QUESTION_LENGTH = 1000
MAX_FOLLOW_UPS = 3
MAX_NOT_CAPTURED_LENGTH = 500
SAVED_LIST_LIMIT = 100
CHART_TYPES = ("bar", "stacked_bar", "horizontal_bar", "line", "doughnut", "comparison", "table")

NOT_CAPTURED_PREFIX = "This data is not captured in DigitVA: "

SYSTEM_INSTRUCTION = """You write one PostgreSQL query that answers a question about verbal autopsy (VA) data, or say that DigitVA does not hold the data.

You can read four tables. Every table holds aggregates already limited to what the user may see.

Table ai_cube: each row is a count of VA cases (deaths) sharing the same values of every dimension column.
- project_id varchar: project code.
- site_id varchar: site code.
- submission_month date: first day of the month the interview was submitted.
- sex varchar: 'male', 'female', 'undetermined', 'unknown' (case varies: compare with lower(sex)).
- analytics_age_band text: 'neonate', 'child', '15_49y', '50_64y', '65_plus', 'unknown'.
- workflow_state varchar: 'screening_pending', 'attachment_sync_pending', 'smartva_pending', 'ready_for_coding', 'coding_in_progress', 'coder_finalized', 'reviewer_eligible', 'reviewer_coding_in_progress', 'reviewer_finalized', 'finalized_upstream_changed', 'not_codeable_by_coder', 'not_codeable_by_data_manager', 'consent_refused'. The coding backlog is ready_for_coding plus coding_in_progress.
- authoritative_source text: who gave the final cause: 'coder', 'reviewer', or NULL when there is no final cause yet.
- authoritative_who_bucket_section varchar: WHO 2026 VA cause section of the final cause, e.g. 'Infectious and parasitic diseases', 'Neoplasms', 'Diseases of the circulatory system', 'Respiratory disorders', 'External causes of death', 'Neonatal causes of death', 'Stillbirths', 'Pregnancy-, childbirth and puerperium-related disorders', 'Cause of death unknown'. NULL when uncoded.
- authoritative_who_bucket varchar: WHO 2026 VA cause of the final cause. NULL when uncoded.
- authoritative_icd text: ICD-10 code of the final cause. NULL when uncoded or ICD-11.
- smartva_cause1_who_bucket varchar: WHO 2026 VA cause of SmartVA's top cause. NULL when SmartVA has none.
- nqa_rating text: narrative quality rating: 'Good', 'Fair', 'Poor', 'Cannot Grade', or NULL when not rated.
- narration_language varchar: language of the narrative, lower case, e.g. 'hindi', 'tamil', 'odia', 'khasi', 'english'.
- consent_mode varchar: 'yes' (in person), 'telephonic_consent', 'no' (refused).
- odk_sync_issue_code varchar: ODK sync problem code, NULL when none.
- dm_not_codeable_reason varchar: the data manager's reason when the case was marked not codeable, else NULL.
- org_l1_name .. org_l7_name text: name of the case's organization unit and its ancestors at each level depth of the project's hierarchy (ai_org_levels names the levels; for example depth 1 is a district and 5 a sub-centre in some projects). NULL when the case has no unit or the unit sits above that depth.
- final_saved_month date, final_saved_week date: first day of the month and of the ISO week (Monday) the final cause was saved. NULL when uncoded.
- n bigint: number of cases in the row.
- nqa_score_sum bigint, nqa_scored_n bigint: sum of narrative quality scores and number of scored cases in the row.

Table ai_org_levels: project_id varchar, depth int, level_name varchar. The names of each project's hierarchy levels.

Table ai_staff: counts of active users with active role grants, per place and role. No names.
- project_id, site_id (NULL unless the grant is for one site), org_l1_name .. org_l7_name (the granted unit and its ancestors; NULL for project or site grants), role ('coder', 'reviewer', 'data_manager', 'interviewer', 'interview_supervisor', 'death_reporter', 'site_pi', 'project_pi', 'collaborator', 'collaborator_pii', 'coding_tester').
- coding_language varchar: NULL on headcount rows. Coders also appear once per coding language with coding_language set. For headcounts always filter coding_language IS NULL; for language questions filter role = 'coder' AND coding_language IS NOT NULL.
- staff, signed_in_7d, signed_in_30d, never_signed_in, granted_30d (grant given in the last 30 days), dormant_30d (granted over 30 days ago and not signed in for 30 days), unverified_email, no_coding_language (coders with no coding language), in_training (added to a training session), training_started (started a training session): bigint user counts.
- A place with no grants has no row: compare with ai_cube to find units with cases but no staff of a role.

Table ai_coder: one row per coder, project and month. Shown to the user by name; you never see the rows.
- project_id, coder_number bigint, coder_name text, coder_site_id, org_l1_name .. org_l7_name (the coder's unit), month date (first day of the month).
- finals: finals saved (each case's latest coder final, counted once).
- median_alloc_to_final_min float8: median elapsed minutes from allocation to final save in the month (elapsed, not time on screen); alloc_to_final_min_sum float8 and timed_finals: for averages across months; finals_under_3_min.
- smartva_compared (finals where SmartVA has a cause), smartva_match (final WHO cause equals SmartVA's top cause), smartva_low_likelihood (SmartVA's top likelihood 'Somewhat Likely' or 'Possible'), smartva_match_low_likelihood, exact_icd_match (final ICD-10 code equals SmartVA's).
- reviewer_finals (a reviewer also gave a final), reviewer_changed (the reviewer's code differs).
- unknown_cause (final in 'Cause of death unknown'), neonate_finals, neonate_unknown_cause.
- doris_checked, doris_rejections, doris_warnings, age_sex_confirmations, causing_condition_unknown: DORIS (ICD-11 projects only) counts on the coder's Step 1 and final; doris_overridden: finals whose code differs from DORIS's underlying cause.
- not_codeable: cases the coder marked not codeable.
All bigint unless stated. Shares are sums divided by sums, e.g. round(100.0 * sum(smartva_match) / NULLIF(sum(smartva_compared), 0), 1).

NOT CAPTURED: DigitVA does not store population, catchment or expected deaths; time actually spent on screen; the interviewer of a case as a user (ODK records only a free-text submitter name); training completion or training scores; targets.
NOT AVAILABLE HERE: stored in DigitVA but not in these tables: time spent in each workflow state, allocation releases and timeouts, recode episodes, the reason a coder marked a case not codeable, cases retired from ODK or confirmed duplicates (excluded from every table), and any individual case or deceased detail.
If the question needs any of these, set answerable to false, set not_captured to "This data is not captured in DigitVA: " (or, for the second list, "This data is not available to AI questions: ") followed by what is missing, and set sql to an empty string. Otherwise answerable is true and not_captured is null. If only part of the question needs missing data, answer the rest and name what is missing in not_captured.

Rules:
- Write a single SELECT (a WITH ... SELECT is allowed, not WITH RECURSIVE). No semicolon, no comments.
- Read only ai_cube, ai_org_levels, ai_staff and ai_coder. Do not reference any other table, view, schema, system catalog or function in FROM. At most 4 table references in FROM in total, counting WITH names and subqueries.
- Use only these functions: count, sum, avg, min, max, bool_and, bool_or, percentile_cont and percentile_disc (WITHIN GROUP), round, abs, coalesce, nullif, greatest, least, date_trunc, extract, date_part, to_char (with a constant format), lower, upper, and the window functions rank, dense_rank, row_number, lag, lead, ntile. Use CASE, FILTER, OVER, CURRENT_DATE and interval arithmetic freely.
- Do not use the || operator or concat. Casts only to int, bigint, numeric, float8, text, varchar, date, bool or interval. Text constants are at most 200 characters.
- When the x axis is one ai_cube dimension, keep that column's name as its output column (e.g. SELECT site_id, ...) and give it as x_dimension; otherwise x_dimension is null.
- Case counts are always sum(n), never count(*). Average narrative score is sum(nqa_score_sum)::numeric / NULLIF(sum(nqa_scored_n), 0).
- Prefer comparative answers: each unit against its peers' average or median (avg(x) OVER () or percentile_cont in a WITH), its rank, this period against the previous one and the same month last year (lag over months), with the change and percent change. Use chart type comparison with reference_column naming the peer value column.
- Return at most 500 rows; order the result in a useful way.
- Give every output column a short snake_case alias.
- For a chart with several series, return one row per x value and one numeric column per series, using sum(n) FILTER (WHERE ...).

Answer as JSON with: answerable; not_captured; sql; title (a short chart title); chart with type (bar, stacked_bar, horizontal_bar, line, doughnut, comparison or table), x_column (the category or month column), series_columns (numeric columns, one series each), value_column (the single numeric column when there is one series), x_dimension and reference_column (the peer or target column drawn as a line on a comparison chart, else null); follow_ups (up to 3 short follow-up questions the user might ask next about this result).

Examples:
Question: How many deaths by age band?
{"answerable": true, "not_captured": null, "sql": "SELECT analytics_age_band, sum(n) AS deaths FROM ai_cube GROUP BY analytics_age_band ORDER BY deaths DESC", "title": "Deaths by age band", "chart": {"type": "bar", "x_column": "analytics_age_band", "series_columns": ["deaths"], "value_column": "deaths", "x_dimension": "analytics_age_band", "reference_column": null}, "follow_ups": ["Deaths by age band and sex", "Top causes among neonates"]}

Question: Monthly submissions by sex
{"answerable": true, "not_captured": null, "sql": "SELECT submission_month, sum(n) FILTER (WHERE lower(sex) = 'male') AS male, sum(n) FILTER (WHERE lower(sex) = 'female') AS female FROM ai_cube GROUP BY submission_month ORDER BY submission_month", "title": "Monthly submissions by sex", "chart": {"type": "line", "x_column": "submission_month", "series_columns": ["male", "female"], "value_column": null, "x_dimension": "submission_month", "reference_column": null}, "follow_ups": ["Monthly submissions by site"]}

Question: Which sites sent fewer cases this month than their peers?
{"answerable": true, "not_captured": null, "sql": "WITH t AS (SELECT site_id, sum(n) AS cases FROM ai_cube WHERE submission_month = date_trunc('month', CURRENT_DATE)::date GROUP BY site_id) SELECT site_id, cases, round(avg(cases) OVER (), 1) AS peer_average, rank() OVER (ORDER BY cases DESC) AS rank FROM t ORDER BY cases", "title": "Cases this month against the site average", "chart": {"type": "comparison", "x_column": "site_id", "series_columns": ["cases"], "value_column": "cases", "x_dimension": "site_id", "reference_column": "peer_average"}, "follow_ups": ["Compare with each site's last three months"]}

Question: Which coders appear to copy SmartVA?
{"answerable": true, "not_captured": null, "sql": "WITH c AS (SELECT coder_name, sum(finals) AS finals, round(100.0 * sum(smartva_match) / NULLIF(sum(smartva_compared), 0), 1) AS smartva_match_pct, round(100.0 * sum(smartva_match_low_likelihood) / NULLIF(sum(smartva_low_likelihood), 0), 1) AS match_when_unlikely_pct FROM ai_coder GROUP BY coder_name HAVING sum(finals) >= 20) SELECT coder_name, finals, smartva_match_pct, match_when_unlikely_pct, round(avg(smartva_match_pct) OVER (), 1) AS peer_average_pct FROM c ORDER BY match_when_unlikely_pct DESC NULLS LAST", "title": "Agreement with SmartVA by coder", "chart": {"type": "comparison", "x_column": "coder_name", "series_columns": ["smartva_match_pct", "match_when_unlikely_pct"], "value_column": null, "x_dimension": null, "reference_column": "peer_average_pct"}, "follow_ups": ["How fast are these coders?"]}

Question: How many deaths per 1,000 population in each district?
{"answerable": false, "not_captured": "This data is not captured in DigitVA: population or catchment figures for organization units.", "sql": "", "title": "Deaths per 1,000 population", "chart": {"type": "table", "x_column": null, "series_columns": [], "value_column": null, "x_dimension": null, "reference_column": null}, "follow_ups": ["Deaths per district against the district median"]}
"""


_NULLABLE_STRING = {"anyOf": [{"type": "string"}, {"type": "null"}]}
CHART_SCHEMA = {
    "type": "object",
    "properties": {
        "type": {"type": "string", "enum": list(CHART_TYPES)},
        "x_column": _NULLABLE_STRING,
        "series_columns": {"type": "array", "items": {"type": "string"}},
        "value_column": _NULLABLE_STRING,
        "x_dimension": {"anyOf": [
            {"type": "string", "enum": list(sandbox.DRILL_COLUMNS)}, {"type": "null"},
        ]},
        "reference_column": _NULLABLE_STRING,
    },
    "required": ["type", "x_column", "series_columns", "value_column", "x_dimension", "reference_column"],
    "additionalProperties": False,
}
# Strict JSON Schema (every object closed, every property required) so the
# same schema serves Claude's structured output and Gemini's.
RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "answerable": {"type": "boolean"},
        "not_captured": _NULLABLE_STRING,
        "sql": {"type": "string"},
        "title": {"type": "string"},
        "chart": CHART_SCHEMA,
        "follow_ups": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["answerable", "not_captured", "sql", "title", "chart", "follow_ups"],
    "additionalProperties": False,
}


class AiQuestionsError(Exception):
    """A request refused or failed; ``message`` is safe to show the user."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def is_enabled() -> bool:
    return bool(current_app.config.get("AI_ANALYTICS_ENABLED"))


def enabled_providers() -> list[str]:
    return providers.enabled_providers()


def _resolve_provider(provider) -> str:
    """*provider* if enabled, the default when None or empty; refuses others."""
    enabled = providers.enabled_providers()
    if not enabled:
        raise AiQuestionsError("not_configured", "AI questions are not configured on this server.")
    if not provider:
        return enabled[0]
    if provider not in enabled:
        raise AiQuestionsError("bad_provider", "That AI provider is not available.")
    return provider


# ---------------------------------------------------------------------------
# Validation of untrusted input (the browser and the model)
# ---------------------------------------------------------------------------

def _clean_column(value) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > 63:
        raise AiQuestionsError("bad_chart", "The chart recipe is not valid.")
    return value


def parse_chart(raw) -> dict:
    """Validate a chart recipe from the model or the browser.

    ``x_dimension`` (the ai_cube column the x axis is, for the breakdown
    drawer) is kept only when it is one of ``sandbox.DRILL_COLUMNS``.
    """
    if not isinstance(raw, dict) or raw.get("type") not in CHART_TYPES:
        raise AiQuestionsError("bad_chart", "The chart recipe is not valid.")
    series = raw.get("series_columns") or []
    if not isinstance(series, list) or len(series) > 12:
        raise AiQuestionsError("bad_chart", "The chart recipe is not valid.")
    dimension = raw.get("x_dimension")
    return {
        "type": raw["type"],
        "x_column": _clean_column(raw.get("x_column")),
        "series_columns": [_clean_column(col) for col in series],
        "value_column": _clean_column(raw.get("value_column")),
        "x_dimension": dimension if dimension in sandbox.DRILL_COLUMNS else None,
        # Recipes saved before comparison charts have no reference column.
        "reference_column": _clean_column(raw.get("reference_column")),
    }


def _table_chart() -> dict:
    return {"type": "table", "x_column": None, "series_columns": [], "value_column": None,
            "x_dimension": None, "reference_column": None}


def _clean_follow_ups(raw) -> list[str]:
    if not isinstance(raw, list):
        return []
    cleaned = [q.strip()[:200] for q in raw if isinstance(q, str) and q.strip()]
    return cleaned[:MAX_FOLLOW_UPS]


def _parse_plan(text) -> dict:
    try:
        raw = json.loads(text or "")
    except ValueError:
        raise AiQuestionsError("bad_model_output", "The model gave an answer that could not be read.") from None
    if not isinstance(raw, dict) or not isinstance(raw.get("sql"), str):
        raise AiQuestionsError("bad_model_output", "The model gave an answer that could not be read.")
    title = raw.get("title") if isinstance(raw.get("title"), str) else ""
    try:
        chart = parse_chart(raw.get("chart"))
    except AiQuestionsError:
        chart = _table_chart()
    return {
        # Absent means answerable: the flag came with the not-captured rule.
        "answerable": raw.get("answerable") is not False,
        "not_captured": _clean_not_captured(raw.get("not_captured")),
        "sql": raw["sql"].strip(),
        "title": title.strip()[:160] or "Result",
        "chart": chart,
        "follow_ups": _clean_follow_ups(raw.get("follow_ups")),
    }


_NOT_CAPTURED_PREFIXES = (NOT_CAPTURED_PREFIX, "This data is not available to AI questions: ")


def _clean_not_captured(raw) -> str | None:
    """The model's not-captured sentence, bounded and always in the policy's
    wording; None when it gave none."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip()[:MAX_NOT_CAPTURED_LENGTH]
    return text if text.startswith(_NOT_CAPTURED_PREFIXES) else NOT_CAPTURED_PREFIX + text


def _clean_question(question) -> str:
    if not isinstance(question, str) or not question.strip():
        raise AiQuestionsError("bad_question", "Type a question first.")
    question = question.strip()
    if len(question) > MAX_QUESTION_LENGTH:
        raise AiQuestionsError("bad_question", f"Keep the question under {MAX_QUESTION_LENGTH} characters.")
    return question


# ---------------------------------------------------------------------------
# Quota and audit
# ---------------------------------------------------------------------------

def weekly_model_calls(user) -> int:
    """``ai_llm`` calls by *user* since the start of this ISO week (index-backed)."""
    return db.session.scalar(
        sa.select(sa.func.count())
        .select_from(VaAiQueryAuditLog)
        .where(
            VaAiQueryAuditLog.user_id == user.user_id,
            VaAiQueryAuditLog.created_at >= sa.func.date_trunc("week", sa.func.now()),
            VaAiQueryAuditLog.mode == AI_MODE_LLM,
        )
    )


def quota_left(user) -> int | None:
    """Model calls left this week; None for an admin (no limit)."""
    if user.is_admin():
        return None
    quota = int(current_app.config.get("AI_ANALYTICS_WEEKLY_QUOTA", 50))
    return max(quota - weekly_model_calls(user), 0)


def _audit(user, *, mode, prompt, sql, turn=1, used_retry=False, usage=None, error_code=None,
           provider=None, model=None):
    row = VaAiQueryAuditLog(
        user_id=user.user_id,
        mode=mode,
        prompt=prompt,
        generated_sql=sql,
        turn=turn,
        used_retry=used_retry,
        error_code=error_code,
        provider=provider,
        model=model,
        **(usage or {}),
    )
    db.session.add(row)
    db.session.commit()
    return row


# ---------------------------------------------------------------------------
# Model call
# ---------------------------------------------------------------------------

def _model_call_audited(user, provider, payload, *, question, turn, used_retry):
    """Call the model and write its audit row; returns (plan, audit_row)."""
    audit = {"mode": AI_MODE_LLM, "prompt": question, "turn": turn, "used_retry": used_retry,
             "provider": provider, "model": providers.model_name(provider)}
    try:
        reply = providers.plan(provider, SYSTEM_INSTRUCTION, json.dumps(payload), RESPONSE_SCHEMA,
                               retry=used_retry)
    except providers.ProviderError as exc:
        _audit(user, sql=None, error_code=exc.code, **audit)
        raise AiQuestionsError(exc.code, exc.message) from None
    except Exception:
        log.exception("AI analytics model call failed: user=%s provider=%s", user.user_id, provider)
        _audit(user, sql=None, error_code="model_error", **audit)
        raise AiQuestionsError("model_error", "The AI service did not answer. Try again later.") from None
    audit["model"] = reply.model
    try:
        plan = _parse_plan(reply.text)
    except AiQuestionsError as exc:
        _audit(user, sql=None, usage=reply.usage, error_code=exc.code, **audit)
        raise
    row = _audit(user, sql=plan["sql"], usage=reply.usage, **audit)
    return plan, row


def ask(user, question, *, provider=None, previous_sql=None, earlier_questions=(), turn=1):
    """Answer *question* for *user*: plan with the model, run in the sandbox.

    *provider* is one of the enabled providers (None means the default).
    *previous_sql* and *earlier_questions* come from the browser (a follow-up)
    and are only passed to the model. Retries once, thinking harder, when the
    model's SQL fails; the retry carries only the redacted error. Returns
    (plan, result, audit_id) where audit_id names the call whose SQL ran, for
    saving. When the model says the data is not captured, nothing runs:
    result is None and ``plan["not_captured"]`` holds the answer. Raises
    ``AiQuestionsError``.
    """
    if not is_enabled():
        raise AiQuestionsError("disabled", "AI questions are turned off. Saved queries still run.")
    question = _clean_question(question)
    provider = _resolve_provider(provider)
    if not isinstance(turn, int) or turn < 1:
        turn = 1
    if turn > MAX_TURNS:
        raise AiQuestionsError(
            "turn_cap", f"A conversation has at most {MAX_TURNS} questions. Start a new question."
        )
    left = quota_left(user)
    if left is not None and left <= 0:
        raise AiQuestionsError("quota", "You have used this week's AI questions. Saved queries still run.")

    payload = {"question": question}
    if turn > 1 and isinstance(previous_sql, str) and previous_sql.strip():
        payload["previous_sql"] = previous_sql.strip()[: sandbox.MAX_SQL_LENGTH]
        payload["earlier_questions"] = [
            q.strip()[:MAX_QUESTION_LENGTH]
            for q in earlier_questions if isinstance(q, str) and q.strip()
        ][-MAX_EARLIER_QUESTIONS:]

    plan, row = _model_call_audited(user, provider, payload, question=question, turn=turn, used_retry=False)
    if not plan["answerable"]:
        return _not_captured(plan, row)
    try:
        return plan, sandbox.run_query(plan["sql"], user), row.id
    except sandbox.SandboxError as exc:
        row.error_code = exc.code
        db.session.commit()
        # A rewrite would not make these smaller or faster: no retry.
        if exc.code in ("timeout", "result_too_large"):
            raise AiQuestionsError(exc.code, exc.message) from None
        retry_payload = {**payload, "failed_sql": plan["sql"], "database_error": exc.model_message}

    if left is not None and left <= 1:
        raise AiQuestionsError("quota", "The query failed and no AI questions are left this week.")
    plan, row = _model_call_audited(user, provider, retry_payload, question=question, turn=turn, used_retry=True)
    if not plan["answerable"]:
        return _not_captured(plan, row)
    try:
        return plan, sandbox.run_query(plan["sql"], user), row.id
    except sandbox.SandboxError as exc:
        row.error_code = exc.code
        db.session.commit()
        raise AiQuestionsError(exc.code, f"The query could not run: {exc.message}") from None


def _not_captured(plan, row):
    """No SQL runs: the audit row keeps no SQL (so it cannot be saved) and the
    error code ``not_captured``. Returns (plan, None, audit_id)."""
    plan["sql"] = ""
    plan["not_captured"] = plan["not_captured"] or NOT_CAPTURED_PREFIX + "the data this question needs."
    row.generated_sql = None
    row.error_code = "not_captured"
    db.session.commit()
    return plan, None, row.id


# ---------------------------------------------------------------------------
# Built-in reports and catalog questions (fixed SQL, no model, no quota)
# ---------------------------------------------------------------------------

def _run_fixed(user, sql):
    try:
        return sandbox.run_query(sql, user)
    except sandbox.SandboxError as exc:
        raise AiQuestionsError(exc.code, f"The query could not run: {exc.message}") from None


def run_builtin(user, key):
    """Run built-in report *key* for *user*. Returns (report, result)."""
    report = catalog.builtin(key)
    if report is None:
        raise AiQuestionsError("not_found", "That report was not found.")
    return report, _run_fixed(user, report["sql"])


def run_catalog(user, key):
    """Run catalog question *key* for *user*. Returns (entry, result, chart)."""
    entry = catalog.catalog_entry(key)
    if entry is None:
        raise AiQuestionsError("not_found", "That catalog question was not found.")
    try:
        chart = parse_chart(entry["chart"])
    except AiQuestionsError:
        chart = _table_chart()
    return entry, _run_fixed(user, entry["sql"]), chart


def breakdown(user, column, value):
    """The drawer's counts of one chart category (``sandbox.breakdown``)."""
    if column not in sandbox.DRILL_COLUMNS or not isinstance(value, str) or len(value) > 200:
        raise AiQuestionsError("bad_breakdown", "That breakdown is not available.")
    try:
        return sandbox.breakdown(user, column, value)
    except sa.exc.DBAPIError:
        log.warning("AI analytics breakdown failed: user=%s column=%s", user.user_id, column)
        raise AiQuestionsError("db_error", "The breakdown could not run.") from None


# ---------------------------------------------------------------------------
# Saved queries (the owner's own only)
# ---------------------------------------------------------------------------

def list_saved(user) -> list[VaAiSavedQuery]:
    # ponytail: newest SAVED_LIST_LIMIT only; paginate if users keep more.
    return db.session.scalars(
        sa.select(VaAiSavedQuery)
        .where(VaAiSavedQuery.owner_user_id == user.user_id)
        .order_by(VaAiSavedQuery.created_at.desc(), VaAiSavedQuery.id.desc())
        .limit(SAVED_LIST_LIMIT)
    ).all()


def _own_saved(user, saved_id) -> VaAiSavedQuery:
    saved = db.session.scalar(
        sa.select(VaAiSavedQuery).where(
            VaAiSavedQuery.id == saved_id,
            VaAiSavedQuery.owner_user_id == user.user_id,
        )
    )
    if saved is None:
        raise AiQuestionsError("not_found", "That saved query was not found.")
    return saved


def save_query(user, *, audit_id, title, chart, description=None) -> VaAiSavedQuery:
    """Save the SQL of *user*'s own successful model call *audit_id*.

    The SQL comes from the audit row, never from the browser; *chart* is
    validated as a recipe.
    """
    if not isinstance(title, str) or not title.strip():
        raise AiQuestionsError("bad_title", "Give the query a title.")
    row = db.session.scalar(
        sa.select(VaAiQueryAuditLog).where(
            VaAiQueryAuditLog.id == audit_id,
            VaAiQueryAuditLog.user_id == user.user_id,
            VaAiQueryAuditLog.mode == AI_MODE_LLM,
            VaAiQueryAuditLog.error_code.is_(None),
            VaAiQueryAuditLog.generated_sql.is_not(None),
        )
    )
    if row is None:
        raise AiQuestionsError("not_found", "That answer can no longer be saved.")
    saved = VaAiSavedQuery(
        owner_user_id=user.user_id,
        title=title.strip()[:160],
        description=(description or "").strip()[:500] or None,
        original_prompt=row.prompt or "",
        validated_sql=row.generated_sql,
        layout_recipe=parse_chart(chart),
    )
    db.session.add(saved)
    db.session.commit()
    ai_search_service.upsert_saved_query(saved.id, user.user_id, saved.title, saved.description or "")
    return saved


def rerun_saved(user, saved_id):
    """Run *user*'s own saved query: no model call, no quota. Returns (saved, result)."""
    saved = _own_saved(user, saved_id)
    try:
        result = sandbox.run_query(saved.validated_sql, user)
    except sandbox.SandboxError as exc:
        _audit(user, mode=AI_MODE_SAVED_RERUN, prompt=saved.original_prompt,
               sql=saved.validated_sql, error_code=exc.code)
        raise AiQuestionsError(exc.code, f"The query could not run: {exc.message}") from None
    saved.run_count = VaAiSavedQuery.run_count + 1
    saved.last_run_at = datetime.now(UTC)
    _audit(user, mode=AI_MODE_SAVED_RERUN, prompt=saved.original_prompt, sql=saved.validated_sql)
    db.session.refresh(saved)
    return saved, result


def delete_saved(user, saved_id) -> None:
    saved = _own_saved(user, saved_id)
    db.session.delete(saved)
    db.session.commit()
    ai_search_service.delete_saved_query(saved_id)
