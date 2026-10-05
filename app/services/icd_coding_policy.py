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


def coding_policy_clause(model, *, age_group: str | None, sex: str | None):
    """Selectable-row predicate for ``model`` (a mas_icd* model with the policy columns).

    A falsy ``age_group``/``sex`` adds no condition for that dimension.
    """
    clause = model.is_coding_selectable.is_(True)
    if age_group:
        clause = sa.and_(
            clause,
            sa.or_(
                model.age_group_selectable == "all",
                model.age_group_selectable == age_group,
                *(
                    (model.age_group_selectable == "neonate_infant",)
                    if age_group in NEONATE_INFANT_GROUPS
                    else ()
                ),
            ),
        )
    if sex:
        clause = sa.and_(
            clause,
            sa.or_(
                model.sex_selectable == "both",
                model.sex_selectable == sex,
            ),
        )
    return clause
