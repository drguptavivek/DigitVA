"""The one rule that keeps confirmed-duplicate cases out of coding readers.

A web case confirmed as a duplicate (``va_death_register.status =
'duplicate'``) is a case-level mark: its submission's coding workflow state
is untouched (no new state, no reuse of ``not_codeable_by_data_manager``).
Every reader of coding state -- allocation, pick-and-choose, queue and
dashboard counts, SmartVA generation, reviewer and recode queues, exports,
analytics over the materialized views -- ANDs this predicate into its own
query instead of re-deriving it. A supervisor ``reopen`` changes the case
status, so the submission comes back everywhere with the coding state it had.

Policy: docs/policy/coding-workflow-state-machine.md, "Confirmed duplicate
cases"; decisions 10 and 14 of .tasks/2026-09-28-interviewer-worklist.md.
tests/test_duplicate_exclusion_coverage.py fails when a new reader of coding
state skips it.

The same predicate also keeps out a DigitVA interview held outside its
collection period, or rejected (``va_web_intake_drafts.collection_hold``;
docs/policy/project-clock-and-gates.md, "Uploads outside the collection
period are accepted and held"), so every one of those readers excludes it
too. A release or a gate save that covers it clears the hold and it comes
back everywhere, as a reopened duplicate does. ODK submissions have no draft
and are never held.

This module imports no service: readers everywhere (models, services, tasks,
routes) import it, so it must not be able to close an import cycle.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import aliased

DUPLICATE_CASE_STATUS = "duplicate"

#: What a coding or reviewing action on a confirmed duplicate answers.
DUPLICATE_MESSAGE = (
    "This submission's case was confirmed as a duplicate and is not available "
    "for coding or review."
)


#: ``collection_hold`` values that keep an interview out (``released`` and NULL do not).
EXCLUDED_HOLDS = ("held", "rejected")

#: What a coding or reviewing action on a held or rejected interview answers.
HELD_MESSAGE = (
    "This interview is held outside the collection period and is not available "
    "for coding or review."
)


def not_confirmed_duplicate_condition(va_sid_expr):
    """SQL predicate: *va_sid_expr* is not the submission of a confirmed
    duplicate, nor a DigitVA interview held or rejected outside its
    collection period.

    Two correlated ``NOT EXISTS``, against ``va_death_register`` and
    ``va_web_intake_drafts`` (served by their ``va_sid`` indexes); ODK and
    tabular submissions have neither row and always pass.
    """
    from app.models import VaWebIntakeDraft

    # Aliased so a caller selecting from va_web_intake_drafts itself does not
    # auto-correlate this subquery to its own row.
    hold_draft = aliased(VaWebIntakeDraft, name="hold_draft")
    return sa.and_(
        not_duplicate_condition(va_sid_expr),
        sa.not_(
            sa.exists(
                sa.select(1).where(
                    hold_draft.va_sid == va_sid_expr,
                    hold_draft.collection_hold.in_(EXCLUDED_HOLDS),
                )
            )
        ),
    )


def not_duplicate_condition(va_sid_expr):
    """SQL predicate: *va_sid_expr* is not the submission of a confirmed
    duplicate. For the interviewer's own counts, where a held or rejected
    interview must stay visible to its author."""
    from app.models import VaDeathRegister

    return sa.not_(
        sa.exists(
            sa.select(1).where(
                VaDeathRegister.va_sid == va_sid_expr,
                VaDeathRegister.status == DUPLICATE_CASE_STATUS,
            )
        )
    )


def not_confirmed_duplicate_sql(va_sid_column: str) -> str:
    """The same predicate rendered for a raw ``sa.text`` query.

    *va_sid_column* is a hardcoded column reference such as ``"s.va_sid"``,
    never user input. Rendered from ``not_confirmed_duplicate_condition`` so
    raw-SQL readers cannot drift from the ORM ones.
    """
    return str(
        not_confirmed_duplicate_condition(sa.literal_column(va_sid_column)).compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )


def is_held(va_sid: str) -> bool:
    """Whether *va_sid* is a held or rejected DigitVA interview (one read),
    to pick the right refusal message after ``is_confirmed_duplicate``."""
    from app import db
    from app.models import VaWebIntakeDraft

    return db.session.scalar(sa.select(sa.exists().where(
        VaWebIntakeDraft.va_sid == va_sid, VaWebIntakeDraft.collection_hold.in_(EXCLUDED_HOLDS),
    )))


def excluded_message(va_sid: str) -> str:
    """The refusal for an excluded *va_sid*: held, else duplicate."""
    return HELD_MESSAGE if is_held(va_sid) else DUPLICATE_MESSAGE


def is_confirmed_duplicate(va_sid: str) -> bool:
    """Whether *va_sid* belongs to a confirmed-duplicate case, or is a held or
    rejected interview (one read; ``excluded_message`` says which).

    For paths that act on one submission named in a request (pick, recode,
    reviewer start): the id is a claim, so they ask the same predicate.
    """
    from app import db

    return not db.session.scalar(sa.select(not_confirmed_duplicate_condition(sa.literal(va_sid))))
