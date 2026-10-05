"""Age/sex coding policy shared by ICD-10 and ICD-11 coding.

One submission yields one (age_group, sex) pair; both classifications filter
their catalog rows with the same predicate over the same policy columns
(`is_coding_selectable`, `age_group_selectable`, `sex_selectable`).
"""

from __future__ import annotations

from decimal import Decimal

import sqlalchemy as sa

from app import db
from app.models import VaSubmissions

# `neonate_infant` matches a neonate or an infant submission (owner, 2026-09-29).
NEONATE_INFANT_GROUPS = ("neonate", "infant")
_DAYS_PER_YEAR = Decimal("365.25")


def coding_age_group_for_submission(submission: VaSubmissions | None) -> str | None:
    """Return neonate/infant/child/adult (WHO 2022 boundaries), or None if age is unknown."""
    if submission is None:
        return None
    normalized_days = submission.va_deceased_age_normalized_days
    if normalized_days is not None:
        if normalized_days < Decimal("28"):
            return "neonate"
        if normalized_days < Decimal("365"):
            return "infant"
        if normalized_days < (Decimal("12") * _DAYS_PER_YEAR):
            return "child"
        return "adult"

    legacy_age = submission.va_deceased_age
    if legacy_age is None:
        return None
    if legacy_age < 12:
        return "child"
    return "adult"


def coding_sex_for_submission(submission: VaSubmissions | None) -> str | None:
    """Return "male" or "female"; None (no sex filter) for any other value."""
    if submission is None:
        return None
    normalized = (submission.va_deceased_gender or "").strip().lower()
    if normalized in {"male", "female"}:
        return normalized
    return None


def coding_context_for_submission(va_sid: str) -> dict | None:
    """Return {va_sid, age_group, sex} for a submission, or None if it does not exist."""
    submission = db.session.get(VaSubmissions, va_sid)
    if submission is None:
        return None
    return {
        "va_sid": submission.va_sid,
        "age_group": coding_age_group_for_submission(submission),
        "sex": coding_sex_for_submission(submission),
    }


def _age_clause(model, age_group: str):
    return sa.or_(
        model.age_group_selectable == "all",
        model.age_group_selectable == age_group,
        *(
            (model.age_group_selectable == "neonate_infant",)
            if age_group in NEONATE_INFANT_GROUPS
            else ()
        ),
    )


def _sex_clause(model, sex: str):
    return sa.or_(model.sex_selectable == "both", model.sex_selectable == sex)


def coding_policy_clause(model, *, age_group: str | None, sex: str | None):
    """Selectable-row predicate for ``model`` (a mas_icd* model with the policy columns).

    A falsy ``age_group``/``sex`` adds no condition for that dimension.
    """
    clause = model.is_coding_selectable.is_(True)
    if age_group:
        clause = sa.and_(clause, _age_clause(model, age_group))
    if sex:
        clause = sa.and_(clause, _sex_clause(model, sex))
    return clause


# Wording for the "why is this code not offered" explanation (digitva-e5j).
_AGE_RESTRICTION_LABELS = {
    "neonate": "neonate only",
    "infant": "infant only",
    "neonate_infant": "neonate or infant only",
    "child": "child only",
    "adult": "adult only",
}
_SEX_RESTRICTION_LABELS = {"female": "female only", "male": "male only"}
EXCLUDED_EXAMPLE_LIMIT = 3


def _restriction_reason(row, *, age_group, sex) -> str:
    """Labels of the restrictions on ``row`` that rejected this age/sex."""
    parts = []
    if age_group and row.age_ok is False:
        parts.append(_AGE_RESTRICTION_LABELS.get(row.age_selectable, "not for this age group"))
    if sex and row.sex_ok is False:
        parts.append(_SEX_RESTRICTION_LABELS.get(row.sex_selectable, "not for this sex"))
    return ", ".join(parts)


def _excluded_message(count, examples, *, age_group, sex) -> str:
    who = " ".join(part for part in (age_group, sex) if part) or "this case"
    if age_group:
        who = ("an " if age_group[0] in "aeiou" else "a ") + who
    elif sex:
        who = "a " + who
    shown = ", ".join(f"{e['code']} ({e['reason']})" for e in examples)
    more = f", and {count - len(examples)} more" if count > len(examples) else ""
    noun = "code matches but is" if count == 1 else "codes match but are"
    return f"{count} {noun} not selectable for {who}: {shown}{more}"


def policy_excluded_matches(
    model, match_filters, order_by, *, age_group: str | None, sex: str | None
) -> dict | None:
    """Rows that match the typed query but fail only the age/sex rule.

    ``match_filters`` are the search's own text/active/level filters, so the
    rows are exactly those ``coding_policy_clause`` removed from the
    selectable results. Admin-disabled rows (``is_coding_selectable`` false)
    are not reported: that is not an age/sex restriction. One LIMITed query:
    the total comes from a window count, the examples from the LIMIT.
    Returns ``{"count", "examples": [{"code","title","reason"}], "age_group",
    "sex", "message"}`` or None when nothing was excluded (or neither age nor
    sex is known). These rows must never be offered for selection.
    """
    if not (age_group or sex):
        return None
    age_ok = _age_clause(model, age_group) if age_group else sa.true()
    sex_ok = _sex_clause(model, sex) if sex else sa.true()
    rows = db.session.execute(
        sa.select(
            model.code,
            model.title,
            model.age_group_selectable.label("age_selectable"),
            model.sex_selectable.label("sex_selectable"),
            age_ok.label("age_ok"),
            sex_ok.label("sex_ok"),
            sa.func.count().over().label("total"),
        )
        .where(
            *match_filters,
            model.is_coding_selectable.is_(True),
            sa.not_(sa.and_(age_ok, sex_ok)),
        )
        .order_by(*order_by)
        .limit(EXCLUDED_EXAMPLE_LIMIT)
    ).all()
    if not rows:
        return None
    examples = [
        {
            "code": row.code or "",
            "title": row.title,
            "reason": _restriction_reason(row, age_group=age_group, sex=sex),
        }
        for row in rows
    ]
    count = rows[0].total
    return {
        "count": count,
        "examples": examples,
        "age_group": age_group,
        "sex": sex,
        "message": _excluded_message(count, examples, age_group=age_group, sex=sex),
    }
