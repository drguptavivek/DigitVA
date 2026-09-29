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

This module imports no service: readers everywhere (models, services, tasks,
routes) import it, so it must not be able to close an import cycle.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

DUPLICATE_CASE_STATUS = "duplicate"

#: What a coding or reviewing action on a confirmed duplicate answers.
DUPLICATE_MESSAGE = (
    "This submission's case was confirmed as a duplicate and is not available "
    "for coding or review."
)


def not_confirmed_duplicate_condition(va_sid_expr):
    """SQL predicate: *va_sid_expr* is not the submission of a confirmed duplicate.

    A correlated ``NOT EXISTS`` against ``va_death_register``; ODK and
    tabular submissions have no register row and always pass.
    """
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


def is_confirmed_duplicate(va_sid: str) -> bool:
    """Whether *va_sid* belongs to a confirmed-duplicate case (one read).

    For paths that act on one submission named in a request (pick, recode,
    reviewer start): the id is a claim, so they ask the same predicate.
    """
    from app import db

    return not db.session.scalar(sa.select(not_confirmed_duplicate_condition(sa.literal(va_sid))))
