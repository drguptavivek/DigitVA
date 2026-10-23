"""Per-pass memoisation of section relevance (beads digitva-9m11) must not
change any result: compare against an un-memoised reference built from the
same rules, and check it evaluates fewer expressions."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest import mock

import pytest

from app.services import web_form_relevance_service as svc
from app.services.xform_expression_evaluator import ExpressionError

NOW = datetime(2024, 6, 15, 9, 0, 0, tzinfo=timezone.utc)

ANSWER_SETS = {
    "empty": {},
    "adult": {"Id10013": "yes", "Id10019": "male", "ageInYears": "40", "Id10022": "yes"},
    "child": {"Id10013": "yes", "ageInYears": "5", "ageInDays": "1800", "Id10019": "female"},
    "neonate": {"Id10013": "yes", "ageInDays": "3", "Id10019": "female", "Id10104": "yes"},
    "irrelevant": {
        "Id10013": "yes",
        "md_available": "no",
        "md_count": "4",
        "md_im1": "who-va-attachment:slot1",
        "Id10104": "yes",
        "Id10120": "yes",
        "Id10139": "yes",
    },
}


def _reference_relevant(question, calculated, *, now, rules, options=None, section_memo=None):
    """The pre-memo implementation, verbatim."""
    options = svc.ExpressionEvaluationOptions(now=now)
    for section_name in question["sectionPath"]:
        section = rules.sections.get(section_name)
        src = section["relevant"] if section else None
        if src:
            ast = rules.asts.get(src)
            if ast is not None and not svc.evaluate_expression(ast, calculated, options):
                return False
    src = question["relevant"]
    if src:
        ast = rules.asts.get(src)
        if ast is not None and not svc.evaluate_expression(ast, calculated, options):
            return False
    return True


def _run_both(fn, data):
    rules = svc._current_rules()
    counts = {}
    for label, patch in (("new", None), ("old", _reference_relevant)):
        real = svc.evaluate_expression
        n = [0]

        def counting(*a, **k):
            n[0] += 1
            return real(*a, **k)

        with mock.patch.object(svc, "evaluate_expression", counting):
            if patch is None:
                out = fn(data, now=NOW)
            else:
                with mock.patch.object(svc, "_is_question_relevant", patch):
                    out = fn(data, now=NOW)
        counts[label] = (out, n[0])
    return counts


@pytest.mark.parametrize("name", sorted(ANSWER_SETS))
@pytest.mark.parametrize("fn", [svc.derive_validation_errors, svc.strip_irrelevant_answers])
def test_memoised_output_matches_reference(name, fn):
    counts = _run_both(fn, ANSWER_SETS[name])
    assert counts["new"][0] == counts["old"][0]
    # strip only checks answered questions, so an empty payload evaluates nothing extra.
    assert counts["new"][1] <= counts["old"][1]
    if fn is svc.derive_validation_errors:
        assert counts["new"][1] < counts["old"][1]


def test_failing_section_is_not_memoised_and_still_raises():
    rules = svc._current_rules()
    section = next(n for n, s in rules.sections.items() if s["relevant"])
    question = {"name": "q", "sectionPath": [section], "relevant": None}
    memo: dict[str, bool] = {}
    with mock.patch.object(svc, "evaluate_expression", side_effect=ExpressionError("boom")):
        with pytest.raises(ExpressionError):
            svc._is_question_relevant(question, {}, now=NOW, rules=rules, section_memo=memo)
    assert memo == {}
