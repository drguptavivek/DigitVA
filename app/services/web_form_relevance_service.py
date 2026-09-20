"""Server-side relevance and constraint re-derivation for the WHO VA 2022 web
form, over ``vendor/who-va-2022/src/generated/who-va-2022.server-instrument.json``
(``tooling/who-va-2022/build-server-instrument.mjs``): the composed
instrument's (WHO base plus every DigitVA extension) ``relevant``/
``constraint``/``calculation`` source strings, parsed here with
``app/services/xform_expression_evaluator.py`` rather than trusting a second,
independently-shaped AST out of the TypeScript build.

Why this exists: the browser (``vendor/who-va-2022/src/engine/session.ts`` /
``validation.ts``) is the only place that has ever evaluated ``relevant`` and
``constraint`` against a live submission. ``app/services/web_intake_service.py``
accepted the browser's own ``valid`` boolean as-is (beads digitva-cal.2) and
never cleared an answer that became irrelevant (beads digitva-aiy.1). This
module ports ``isQuestionRelevantWithCalculatedData`` / ``applyCalculations``
/ the constraint half of ``validateAnswer`` from ``validation.ts``, node for
node, for both beads to share -- one re-derivation, not two.

Two behaviours callers must not conflate:

* :func:`strip_irrelevant_answers` -- used at final submit only (never on a
  draft) to remove answers to questions that are not relevant. Resolves the
  cascade to a fixed point (see its docstring): a single pass is not enough
  when one answer's removal changes what else is relevant, which is exactly
  the ``md_available`` -> ``md_count`` -> ``md_im*`` chain digitva-aiy.1 was
  filed over.
* :func:`derive_validation_errors` -- used at final submit to record, not
  enforce, a disagreement between the client's ``valid: true`` and the
  server's own re-derivation. Never raises and never blocks a submission;
  see docs/policy/... (the owner's accept-and-record decision, digitva-cal.2).
  Carries no answer values -- these entries are stored as PII-free metadata.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.services.xform_expression_evaluator import (
    ExpressionError,
    ExpressionEvaluationOptions,
    evaluate_expression,
    is_empty,
    parse_expression,
)

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER_INSTRUMENT_PATH = (
    REPO_ROOT / "vendor/who-va-2022/src/generated/who-va-2022.server-instrument.json"
)

#: Controls whose value is not a real answer (audit trail, device metadata,
#: start/today timestamps) -- mirrors validateSubmission's own exception
#: ("if (question.control !== 'system') delete ...").
_NON_ANSWER_CONTROLS = frozenset({"system"})

#: Controls ``validateAnswer`` itself never evaluates
#: (``if (["note", "calculated"].includes(question.control)) return [];``),
#: plus "system" (audit/start/today, never something a client marks
#: valid/invalid over). A calculated question's formula commonly evaluates
#: to NaN when its own inputs are unanswered -- NaN is not ``is_empty``, so
#: without this exclusion an untouched, irrelevant calculated field would
#: read as a false "relevant" disagreement on almost every submission.
_NON_ANSWER_CONTROLS_FOR_VALIDATION = frozenset({"note", "calculated", "system"})


class ServerInstrumentUnavailable(RuntimeError):
    """The generated server-instrument artifact is missing or unreadable."""


@lru_cache(maxsize=1)
def _load_instrument(path: str) -> dict[str, Any]:
    text_path = Path(path)
    if not text_path.exists():
        raise ServerInstrumentUnavailable(
            f"{text_path} does not exist; run "
            "`cd tooling/who-va-2022 && npm run build:server-instrument`."
        )
    try:
        return json.loads(text_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ServerInstrumentUnavailable(f"{text_path} could not be read: {exc}") from exc


@lru_cache(maxsize=1)
def _parsed_expressions(path: str) -> dict[str, dict]:
    """Every distinct source expression in the instrument, parsed once."""
    doc = _load_instrument(path)
    sources: set[str] = set()
    for section in doc["sections"]:
        if section.get("relevant"):
            sources.add(section["relevant"])
    for question in doc["questions"]:
        for field in ("relevant", "constraint", "calculation"):
            if question.get(field):
                sources.add(question[field])
    parsed: dict[str, dict] = {}
    for source in sources:
        try:
            parsed[source] = parse_expression(source)
        except ExpressionError:
            log.exception("web_form_relevance: could not parse expression %r", source)
    return parsed


def _instrument() -> dict[str, Any]:
    return _load_instrument(str(SERVER_INSTRUMENT_PATH))


def _asts() -> dict[str, dict]:
    return _parsed_expressions(str(SERVER_INSTRUMENT_PATH))


def _ast_for(source: str | None) -> dict | None:
    if not source:
        return None
    return _asts().get(source)


def apply_calculations(data: dict, *, now: datetime) -> dict:
    """Return ``data`` with every ``calculation`` expression applied, in the
    instrument's own declaration order -- mirrors ``applyCalculations`` in
    ``validation.ts``, a single left-to-right pass (a calculated question's
    formula may reference an earlier calculated question, never a later
    one)."""
    calculated = dict(data)
    options = ExpressionEvaluationOptions(now=now)
    for question in _instrument()["questions"]:
        source = question.get("calculation")
        if not source:
            continue
        ast = _ast_for(source)
        if ast is None:
            continue
        try:
            calculated[question["name"]] = evaluate_expression(ast, calculated, options)
        except ExpressionError:
            log.exception(
                "web_form_relevance: calculation for %s failed", question["name"]
            )
    return calculated


def _is_question_relevant(question: dict, calculated: dict, *, now: datetime) -> bool:
    """Mirrors ``isQuestionRelevantWithCalculatedData``: every ancestor
    section's ``relevant`` must hold, then the question's own."""
    sections_by_name = {s["name"]: s for s in _instrument()["sections"]}
    options = ExpressionEvaluationOptions(now=now)
    for section_name in question["sectionPath"]:
        section = sections_by_name.get(section_name)
        section_relevant_source = section.get("relevant") if section else None
        if section_relevant_source:
            ast = _ast_for(section_relevant_source)
            if ast is not None and not evaluate_expression(ast, calculated, options):
                return False
    relevant_source = question.get("relevant")
    if relevant_source:
        ast = _ast_for(relevant_source)
        if ast is not None and not evaluate_expression(ast, calculated, options):
            return False
    return True


def strip_irrelevant_answers(data: dict, *, now: datetime) -> tuple[dict, set[str]]:
    """Remove answers to questions the server considers not relevant, over
    the submitted answers only -- never called on a draft.

    Resolved to a fixed point, not one level: stripping an answer can itself
    change what else is relevant. The instrument's own
    ``md_available`` -> ``md_count`` -> ``md_im1..30`` chain needs exactly
    this -- ``md_im1``'s ``relevant`` is ``${md_count} >= 1``, read directly
    off ``md_count``'s submitted value, not off whether ``md_count`` is
    itself relevant. Only once ``md_count`` is stripped (pass 1, because
    ``md_available`` says no) does ``${md_count}`` evaluate to the missing
    value (pass 2), making ``md_im1`` irrelevant in turn. A single pass
    would leave the photographs the bug report describes still in the
    payload.

    Returns ``(stripped_data, removed_question_names)``.
    """
    questions = _instrument()["questions"]
    current = dict(data)
    removed: set[str] = set()
    while True:
        calculated = apply_calculations(current, now=now)
        pass_removed: list[str] = []
        for question in questions:
            name = question["name"]
            if question.get("control") in _NON_ANSWER_CONTROLS:
                continue
            if name not in current:
                continue
            try:
                relevant = _is_question_relevant(question, calculated, now=now)
            except ExpressionError:
                # Fail safe: an evaluation error keeps the answer rather than
                # silently deleting it (this only strips, never rejects).
                log.exception("web_form_relevance: relevance check for %s failed", name)
                continue
            if not relevant:
                pass_removed.append(name)
        if not pass_removed:
            return current, removed
        for name in pass_removed:
            del current[name]
        removed.update(pass_removed)


def derive_validation_errors(data: dict, *, now: datetime) -> list[dict]:
    """Re-derive relevance and constraint over the client's raw submitted
    answers and report every disagreement -- never raises, never mutates
    ``data``, and never blocks a submission (the owner's accept-and-record
    decision, beads digitva-cal.2: a server that starts refusing what the
    client accepted strands a field interviewer with no recourse).

    Each entry is
    ``{"question": <name>, "rule": "relevant" | "constraint" | "evaluation_error"}``
    -- no answer value, by design: these are stored as PII-free metadata on
    ``va_submission_payload_versions.validation_err``.

    ``evaluation_error`` means the server could not judge that question at all
    (``"*"`` for a failure that stopped the whole re-derivation). It is recorded
    rather than swallowed so that "nothing was checked" never reads as
    "everything agreed" in the data this release is collecting.

    * ``"relevant"``: the server considers the question not relevant, yet the
      client submitted a non-empty answer for it.
    * ``"constraint"``: the server considers the question relevant, and its
      ``constraint`` expression evaluates false against the submitted value.
    """
    try:
        calculated = apply_calculations(data, now=now)
    except Exception:
        # Record the failure rather than returning []. This release exists to
        # measure how often the two engines disagree; an empty list reads as
        # "checked, agreed", so a crash that silently produced one would be
        # indistinguishable from agreement in exactly the data being collected.
        log.exception("web_form_relevance: apply_calculations failed; recording it")
        return [{"question": "*", "rule": "evaluation_error"}]

    entries: list[dict] = []
    for question in _instrument()["questions"]:
        if question.get("control") in _NON_ANSWER_CONTROLS_FOR_VALIDATION:
            continue
        name = question["name"]
        value = calculated.get(name)
        try:
            relevant = _is_question_relevant(question, calculated, now=now)
        except ExpressionError:
            log.exception("web_form_relevance: relevance check for %s failed", name)
            entries.append({"question": name, "rule": "evaluation_error"})
            continue
        if not relevant:
            if not is_empty(value):
                entries.append({"question": name, "rule": "relevant"})
            continue
        constraint_source = question.get("constraint")
        if not constraint_source or is_empty(value):
            continue
        ast = _ast_for(constraint_source)
        if ast is None:
            continue
        try:
            constraint_options = ExpressionEvaluationOptions(current_value=value, now=now)
            if not evaluate_expression(ast, calculated, constraint_options):
                entries.append({"question": name, "rule": "constraint"})
        except ExpressionError:
            log.exception("web_form_relevance: constraint check for %s failed", name)
            entries.append({"question": name, "rule": "evaluation_error"})
            continue
    return entries
