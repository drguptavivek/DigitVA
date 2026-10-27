"""AI analytics questions page — /data-management/ai-questions.

docs/policy/ai-analytics-questions.md (digitva-qwvt). Hangs off the
``data_management`` blueprint, as app/routes/admin_translations.py does off
``admin``. Plain htmx: every POST returns an HTML partial, CSRF through the
``X-CSRFToken`` header the page sets with ``hx-headers``. The same users as
``/api/v1/analytics``: data managers (``dm_grant_scope``) and admin. Rules
live in app/services/ai_analytics_planner.py.

The page honours ``?saved=<id>`` (the caller's own saved query) and
``?catalog=<key>``, the links search suggestions carry: it renders a POST
that fires on load and drops the parameter from the address, so a refresh
does not run it again.
"""

import json
import logging

from flask import render_template, request
from flask_login import current_user

from app import limiter
from app.decorators import role_required
from app.routes.data_management import data_management
from app.services import ai_analytics_catalog as catalog
from app.services import ai_analytics_planner as planner
from app.services import ai_analytics_providers as providers
from app.services.ai_analytics_render import render
from app.services.ai_analytics_sandbox import DRILL_BY
from app.services.data_management_service import dm_grant_scope
from app.utils.va_permission.va_permission_01_abortwithflash import (
    va_permission_abortwithflash,
)

log = logging.getLogger(__name__)

QUESTION_WARNING = (
    "Do not type names, phone numbers or other personal details; "
    "this question is sent to an external AI service"
)
DRILL_LABELS = {"sex": "Sex", "analytics_age_band": "Age band", "workflow_state": "Workflow state"}

_ERROR_STATUS = {
    "not_found": 404,
    "quota": 429,
    "model_busy": 429,
    "disabled": 403,
    "not_configured": 503,
    "model_error": 502,
}


def _require_scope():
    if not current_user.is_admin() and not dm_grant_scope(current_user):
        va_permission_abortwithflash("No data-manager scope has been assigned.", 403)


def _error(exc: planner.AiQuestionsError):
    return (
        render_template("va_frontpages/ai_questions_partials/_error.html", message=exc.message),
        _ERROR_STATUS.get(exc.code, 400),
    )


def _int_form(name, default=None):
    try:
        return int(request.form.get(name, ""))
    except ValueError:
        return default


def _result_partial(*, title, question, sql, chart, result, audit_id=None, turn=None,
                    earlier_questions=(), saved=None, follow_ups=(), source=None, not_captured=None):
    return render_template(
        "va_frontpages/ai_questions_partials/_result.html",
        title=title,
        question=question,
        sql=sql,
        chart=chart,
        view=render(result.columns, result.rows, chart),
        truncated=result.truncated,
        audit_id=audit_id,
        next_turn=(turn + 1) if turn else None,
        max_turns=planner.MAX_TURNS,
        earlier_questions=list(earlier_questions),
        saved=saved,
        follow_ups=list(follow_ups),
        source=source,
        not_captured=not_captured,
    )


def _initial_run():
    """The run a ``?saved=`` / ``?catalog=`` link asks for, validated, or None."""
    saved = request.args.get("saved", "")
    if saved.isdigit():
        return {"kind": "saved", "id": int(saved)}
    entry = catalog.catalog_entry(request.args.get("catalog"))
    if entry is not None:
        return {"kind": "catalog", "key": entry["key"]}
    return None


@data_management.get("/ai-questions")
@role_required("data_manager", "admin")
def ai_questions_page():
    _require_scope()
    enabled = planner.enabled_providers()
    return render_template(
        "va_frontpages/va_ai_questions.html",
        enabled=planner.is_enabled(),
        providers=[(name, providers.PROVIDER_LABELS[name]) for name in enabled],
        quota_left=planner.quota_left(current_user),
        saved_queries=planner.list_saved(current_user),
        built_in_reports=catalog.BUILT_IN_REPORTS,
        catalog_questions=catalog.load_catalog(),
        initial_run=_initial_run(),
        question_warning=QUESTION_WARNING,
        max_question_length=planner.MAX_QUESTION_LENGTH,
    )


@data_management.post("/ai-questions/ask")
@role_required("data_manager", "admin")
@limiter.limit("10 per minute")
def ai_questions_ask():
    _require_scope()
    question = request.form.get("question", "")
    turn = _int_form("turn", 1)
    earlier = request.form.getlist("earlier_question")[-planner.MAX_EARLIER_QUESTIONS:]
    try:
        plan, result, audit_id = planner.ask(
            current_user,
            question,
            provider=request.form.get("provider") or None,
            previous_sql=request.form.get("previous_sql") or None,
            earlier_questions=earlier,
            turn=turn,
        )
    except planner.AiQuestionsError as exc:
        return _error(exc)
    if result is None:
        return render_template(
            "va_frontpages/ai_questions_partials/_not_captured.html",
            title=plan["title"], question=question.strip(), message=plan["not_captured"],
            follow_ups=plan["follow_ups"],
        )
    return _result_partial(
        title=plan["title"],
        question=question.strip(),
        sql=plan["sql"],
        chart=plan["chart"],
        result=result,
        audit_id=audit_id,
        turn=turn,
        earlier_questions=[*earlier, question.strip()][-planner.MAX_EARLIER_QUESTIONS:],
        follow_ups=plan["follow_ups"],
        source="ai",
        not_captured=plan["not_captured"],
    )


@data_management.post("/ai-questions/builtin/<key>/run")
@role_required("data_manager", "admin")
@limiter.limit("30 per minute")
def ai_questions_run_builtin(key):
    _require_scope()
    try:
        report, result = planner.run_builtin(current_user, key)
    except planner.AiQuestionsError as exc:
        return _error(exc)
    return _result_partial(title=report["title"], question=None, sql=report["sql"],
                           chart=report["chart"], result=result, source="builtin")


@data_management.post("/ai-questions/catalog/<key>/run")
@role_required("data_manager", "admin")
@limiter.limit("30 per minute")
def ai_questions_run_catalog(key):
    _require_scope()
    try:
        entry, result, chart = planner.run_catalog(current_user, key)
    except planner.AiQuestionsError as exc:
        return _error(exc)
    return _result_partial(title=entry["question"], question=entry.get("description"),
                           sql=entry["sql"], chart=chart, result=result, source="catalog")


@data_management.post("/ai-questions/breakdown")
@role_required("data_manager", "admin")
@limiter.limit("60 per minute")
def ai_questions_breakdown():
    """The side drawer: one chart category's counts by sex, age band and state."""
    _require_scope()
    column = request.form.get("column", "")
    value = request.form.get("value", "")
    try:
        groups = planner.breakdown(current_user, column, value)
    except planner.AiQuestionsError as exc:
        return _error(exc)
    return render_template(
        "va_frontpages/ai_questions_partials/_breakdown.html",
        column=column,
        value=value,
        groups=[(DRILL_LABELS[dim], groups[dim]) for dim in DRILL_BY],
    )


@data_management.post("/ai-questions/saved")
@role_required("data_manager", "admin")
@limiter.limit("30 per minute")
def ai_questions_save():
    _require_scope()
    try:
        chart = json.loads(request.form.get("chart") or "null")
    except ValueError:
        chart = None
    try:
        planner.save_query(
            current_user,
            audit_id=_int_form("audit_id"),
            title=request.form.get("title", ""),
            description=request.form.get("description"),
            chart=chart,
        )
    except planner.AiQuestionsError as exc:
        return _error(exc)
    return render_template(
        "va_frontpages/ai_questions_partials/_saved_list.html",
        saved_queries=planner.list_saved(current_user),
        just_saved=True,
    )


@data_management.post("/ai-questions/saved/<int:saved_id>/run")
@role_required("data_manager", "admin")
@limiter.limit("30 per minute")
def ai_questions_run_saved(saved_id):
    _require_scope()
    try:
        saved, result = planner.rerun_saved(current_user, saved_id)
    except planner.AiQuestionsError as exc:
        return _error(exc)
    return _result_partial(
        title=saved.title,
        question=saved.original_prompt,
        sql=saved.validated_sql,
        chart=saved.layout_recipe,
        result=result,
        saved=saved,
        source="saved",
    )


@data_management.post("/ai-questions/saved/<int:saved_id>/delete")
@role_required("data_manager", "admin")
@limiter.limit("30 per minute")
def ai_questions_delete_saved(saved_id):
    _require_scope()
    try:
        planner.delete_saved(current_user, saved_id)
    except planner.AiQuestionsError as exc:
        return _error(exc)
    return render_template(
        "va_frontpages/ai_questions_partials/_saved_list.html",
        saved_queries=planner.list_saved(current_user),
    )
