"""Public demo dashboard (digitva-77v5.4; docs/policy/public-demo.md section 7).

Aggregates over the demo project only, readable with no sign-in: the numbers
of accounts, submissions, coded and reviewed cases; the fractions of the
SmartVA cause and of the coder's ICD-11 underlying cause (top causes plus
"other"); counts by age band and sex. Nothing per case or per person is read
or returned: no ids, no usernames, no text a person typed (a coder's cause is
named by the ICD-11 code and title stored in the provenance, never by the text
after the code).

Five aggregate queries whatever the amount of data (accounts; workflow state
counts; SmartVA causes; coder causes; age band by sex), all keyed on the demo
project's forms (``ix_va_submissions_va_form_id``) and on the active rows'
partial indexes. The result is cached for ``PUBLIC_DEMO_DASHBOARD_CACHE_SECONDS``
(default 5 minutes) under ``CACHE_KEY`` (the cache's key prefix namespaces it
per deployment).
"""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
from flask import current_app

from app import cache, db
from app.models import (
    VaFinalAssessments,
    VaForms,
    VaSmartvaResults,
    VaStatuses,
    VaSubmissions,
    VaSubmissionWorkflow,
)
from app.services import public_demo_service as demo
from app.services.duplicate_exclusion import not_confirmed_duplicate_condition
from app.services.workflow import definition as wf

CACHE_KEY = "public_demo:dashboard:v1"
DEFAULT_CACHE_SECONDS = 300
#: Named causes shown per chart; the rest is "other".
TOP_N = 10
#: (label, lower bound in years inclusive, upper bound exclusive), in order.
AGE_BANDS = (
    ("Under 1 year", 0, 1), ("1-4 years", 1, 5), ("5-14 years", 5, 15), ("15-29 years", 15, 30),
    ("30-44 years", 30, 45), ("45-59 years", 45, 60), ("60-69 years", 60, 70), ("70 years and over", 70, None),
)
UNKNOWN_AGE = "Not stated"
SEXES = (("male", "Male"), ("female", "Female"))
OTHER_SEX = "Other or not stated"

_CODED_STATES = frozenset(
    state for state, bucket in wf.WORKFLOW_CODING_BUCKETS.items() if bucket == wf.CODING_BUCKET_CODED
)


def _cache_seconds() -> int:
    return int(current_app.config.get("PUBLIC_DEMO_DASHBOARD_CACHE_SECONDS", DEFAULT_CACHE_SECONDS))


def _in_demo():
    """VaSubmissions predicate: a case of the demo project's forms that is not
    a confirmed duplicate (it would be counted twice)."""
    return sa.and_(
        VaSubmissions.va_form_id.in_(
            sa.select(VaForms.form_id).where(VaForms.project_id == demo.demo_project_id())
        ),
        not_confirmed_duplicate_condition(VaSubmissions.va_sid),
    )


def _percent(count: int, total: int) -> float:
    return round(100.0 * count / total, 1) if total else 0.0


def _share(rows, total: int, label) -> dict:
    """``{"total", "causes": [...], "other": {...}}`` from ``rows`` of
    ``(cause key, count, title)`` (named causes only, most frequent first)."""
    named = rows[:TOP_N]
    causes = [{**label(key, title), "count": count, "percent": _percent(count, total)}
              for key, count, title in named]
    rest = total - sum(count for _key, count, _title in named)
    return {"total": total, "causes": causes, "other": {"count": rest, "percent": _percent(rest, total)}}


def _smartva_causes() -> dict:
    count = sa.func.count()
    rows = db.session.execute(
        sa.select(VaSmartvaResults.va_smartva_cause1, count, sa.func.sum(count).over())
        .select_from(VaSmartvaResults)
        .join(VaSubmissions, VaSubmissions.va_sid == VaSmartvaResults.va_sid)
        .where(
            VaSmartvaResults.va_smartva_status == VaStatuses.active,
            VaSmartvaResults.va_smartva_outcome == VaSmartvaResults.OUTCOME_SUCCESS,
            VaSmartvaResults.va_smartva_cause1.is_not(None),
            _in_demo(),
        )
        .group_by(VaSmartvaResults.va_smartva_cause1)
        .order_by(count.desc(), VaSmartvaResults.va_smartva_cause1)
        .limit(TOP_N)
    ).all()
    total = int(rows[0][2]) if rows else 0
    return _share([(cause, n, None) for cause, n, _t in rows], total, lambda key, _t: {"cause": key})


def _coder_causes() -> dict:
    """The coder's final ICD-11 underlying cause of each coded case, by code.
    A final with no stored provenance code has no named cause: it counts under
    "other"."""
    code = VaFinalAssessments.icd11_provenance["conclusive"]["code"].astext
    title = sa.func.max(VaFinalAssessments.icd11_provenance["conclusive"]["title"].astext)
    count = sa.func.count()
    rows = db.session.execute(
        sa.select(code, count, sa.func.sum(count).over(), title)
        .select_from(VaFinalAssessments)
        .join(VaSubmissions, VaSubmissions.va_sid == VaFinalAssessments.va_sid)
        .where(
            VaFinalAssessments.va_finassess_status == VaStatuses.active,
            VaFinalAssessments.is_tester.is_(False),
            sa.or_(
                VaSubmissions.active_payload_version_id.is_(None),
                VaFinalAssessments.payload_version_id == VaSubmissions.active_payload_version_id,
            ),
            _in_demo(),
        )
        .group_by(code)
        .order_by(count.desc(), code)
        .limit(TOP_N + 1)  # one spare: the unnamed group may sit among the top
    ).all()
    total = int(rows[0][2]) if rows else 0
    named = [(c, n, t) for c, n, _total, t in rows if c]
    return _share(named, total, lambda key, t: {"code": key, "title": t})


def _age_sex_counts() -> tuple[list[dict], list[dict]]:
    years = VaSubmissions.va_deceased_age_normalized_years
    band = sa.case(
        *[(sa.and_(years >= low, years < high) if high is not None else years >= low, label)
          for label, low, high in AGE_BANDS],
        else_=UNKNOWN_AGE,
    )
    sex = sa.func.lower(VaSubmissions.va_deceased_gender)
    rows = db.session.execute(
        sa.select(band, sex, sa.func.count()).where(_in_demo()).group_by(band, sex)
    ).all()
    by_band = {label: 0 for label, _lo, _hi in AGE_BANDS} | {UNKNOWN_AGE: 0}
    by_sex = {key: 0 for key, _label in SEXES} | {"other": 0}
    for age_label, sex_value, n in rows:
        by_band[age_label] += n
        by_sex[sex_value if sex_value in by_sex else "other"] += n
    labels = dict(SEXES) | {"other": OTHER_SEX}
    return (
        [{"band": label, "count": n} for label, n in by_band.items()],
        [{"sex": labels[key], "count": n} for key, n in by_sex.items()],
    )


def compute() -> dict:
    """The dashboard figures, uncached: five aggregate queries."""
    states = db.session.execute(
        sa.select(VaSubmissionWorkflow.workflow_state, sa.func.count())
        .select_from(VaSubmissions)
        .outerjoin(VaSubmissionWorkflow, VaSubmissionWorkflow.va_sid == VaSubmissions.va_sid)
        .where(_in_demo())
        .group_by(VaSubmissionWorkflow.workflow_state)
    ).all()
    bands, sexes = _age_sex_counts()
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "totals": {
            "accounts": demo.active_account_count(),
            "submissions": sum(n for _s, n in states),
            "coded": sum(n for state, n in states if state in _CODED_STATES),
            "reviewed": sum(n for state, n in states if state == wf.WORKFLOW_REVIEWER_FINALIZED),
        },
        "smartva": _smartva_causes(),
        "coder": _coder_causes(),
        "age_bands": bands,
        "sex": sexes,
    }


def dashboard() -> dict:
    """The cached figures; recomputed after the cache lifetime."""
    data = cache.get(CACHE_KEY)
    if data is None:
        data = compute()
        cache.set(CACHE_KEY, data, timeout=_cache_seconds())
    return data
