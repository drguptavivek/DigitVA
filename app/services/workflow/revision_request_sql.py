"""Tell a send-back or reopen apart from an ODK upstream change, in SQL.

A coder/reviewer send-back and a supervisor reopen of a web or device interview
reuse workflow state ``finalized_upstream_changed`` (fuc); only the latest
workflow event's ``transition_reason`` (``sent_back_for_revision`` /
``reopened_for_revision``) on the latest workflow event, which must also be the
event that moved the case into fuc, says it is not an ODK change. This module is that
one definition for counts, labels and filters, the set-based twin of
``get_open_revision_request``. One probe per fuc row on
``ix_va_submission_workflow_events_sid_created``; no migration, no stored flag.

``sent_back_for_revision`` here is a *virtual* display/count key. It is never a
workflow state and is never persisted. ``finalized_upstream_changed`` in a
count or filter means the ODK kind only once the effective state is used.

Rows without events (legacy fuc) read as ODK: the reason is NULL, never a
revision reason. Per-event sites (C-11, D-WT-04, SitePI event counts) use the
event row's own reason instead; ``odk_detected_event_sql`` and
``dm_reopen_event_sql`` are those predicates.

This module imports no service at load time (models and the transitions
constants import lazily) so any reader may import it without a cycle.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import aliased

#: Virtual state key for an open revision request; never stored.
SENT_BACK_FOR_REVISION = "sent_back_for_revision"

_FUC = "finalized_upstream_changed"


def revision_reasons_sql() -> str:
    """The revision-request reasons as a SQL literal list, e.g. ``('a', 'b')``."""
    from app.services.workflow.transitions import REVISION_REQUEST_REASONS

    return "(" + ", ".join(f"'{r}'" for r in sorted(REVISION_REQUEST_REASONS)) + ")"


def odk_detected_event_sql(alias: str) -> str:
    """Per-event predicate: *alias* is an ODK upstream-change detection.

    Its own reason is neither a revision request nor the supervisor's choice
    of the other interview. NULL reason tolerated (reads as ODK).
    """
    from app.services.workflow.transitions import INTERVIEW_CHOSEN_REASON, REVISION_REQUEST_REASONS

    reasons = sorted(REVISION_REQUEST_REASONS | {INTERVIEW_CHOSEN_REASON})
    return f"COALESCE({alias}.transition_reason, '') NOT IN (" + ", ".join(f"'{r}'" for r in reasons) + ")"


def dm_reopen_event_sql(alias: str) -> str:
    """Per-event predicate: *alias* is a data manager reopening an ODK change.

    An accept event restarting coding is that unless its reason is the
    interviewer's revision or a supervisor's chosen interview (D-WT-04).
    """
    from app.services.workflow.transitions import INTERVIEW_CHOSEN_REASON, REVISION_RESTART_REASON

    reasons = sorted({REVISION_RESTART_REASON, INTERVIEW_CHOSEN_REASON})
    return f"COALESCE({alias}.transition_reason, '') NOT IN (" + ", ".join(f"'{r}'" for r in reasons) + ")"


def revision_request_open_condition(va_sid_expr):
    """SQL predicate: the latest workflow event of *va_sid_expr* is an open revision request.

    Same definition as ``get_open_revision_request``: the latest event (by
    ``event_created_at``, limit 1) moved the case into
    ``finalized_upstream_changed`` with a revision-request reason. One
    correlated scalar subquery returning one boolean from that row, so a stale
    ``finalized_upstream_changed`` reading (the analytics MV) whose latest
    event has since left the state is not open. Null-safe: no events means
    False, so ``not_()`` of it is still true. Callers AND
    ``workflow_state = 'finalized_upstream_changed'`` themselves.
    """
    from app.models import VaSubmissionWorkflowEvent
    from app.services.workflow.transitions import REVISION_REQUEST_REASONS

    ev = aliased(VaSubmissionWorkflowEvent)
    latest_is_open = (
        sa.select(
            sa.and_(
                ev.current_state == _FUC,
                sa.func.coalesce(ev.transition_reason, "").in_(sorted(REVISION_REQUEST_REASONS)),
            )
        )
        .where(ev.va_sid == va_sid_expr)
        .order_by(ev.event_created_at.desc())
        .limit(1)
        .scalar_subquery()
    )
    return sa.func.coalesce(latest_is_open, sa.false())


def revision_request_open_sql(va_sid_sql: str) -> str:
    """The same predicate rendered for a raw ``sa.text`` query.

    *va_sid_sql* is a hardcoded column reference such as ``"w.va_sid"``, never
    user input. Rendered from ``revision_request_open_condition`` so raw-SQL
    readers cannot drift from the ORM ones.
    """
    return str(
        revision_request_open_condition(sa.literal_column(va_sid_sql)).compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )


def effective_workflow_state_sql(alias: str) -> str:
    """SQL expression: the workflow state with open revision requests split out.

    ``finalized_upstream_changed`` rows whose latest event is a revision
    request read as ``sent_back_for_revision``; every other row keeps its
    state. The probe runs only on fuc rows (CASE short-circuits). *alias* is a
    hardcoded table alias.
    """
    return (
        f"(CASE WHEN {alias}.workflow_state = '{_FUC}' "
        f"AND {revision_request_open_sql(f'{alias}.va_sid')} "
        f"THEN '{SENT_BACK_FOR_REVISION}' ELSE {alias}.workflow_state END)"
    )


def odk_changed_sql(alias: str) -> str:
    """SQL predicate: *alias* is in fuc because of an ODK change (not a revision request)."""
    return (
        f"({alias}.workflow_state = '{_FUC}' "
        f"AND NOT {revision_request_open_sql(f'{alias}.va_sid')})"
    )


def sent_back_sql(alias: str) -> str:
    """SQL predicate: *alias* is in fuc because of an open revision request."""
    return (
        f"({alias}.workflow_state = '{_FUC}' "
        f"AND {revision_request_open_sql(f'{alias}.va_sid')})"
    )


def workflow_filter_conditions(workflow: str, state_col, va_sid_col) -> list:
    """Conditions for one DM workflow filter value.

    ``finalized_upstream_changed`` means the ODK kind only and the virtual
    ``sent_back_for_revision`` means fuc with an open revision request; any
    other value is a plain stored-state match. *state_col* / *va_sid_col* are
    the caller's workflow-state and submission-id columns (ORM or Core).
    """
    if workflow == _FUC:
        return [state_col == _FUC, sa.not_(revision_request_open_condition(va_sid_col))]
    if workflow == SENT_BACK_FOR_REVISION:
        return [state_col == _FUC, revision_request_open_condition(va_sid_col)]
    return [state_col == workflow]


def open_revision_request_sids(sids) -> set[str]:
    """Which of *sids* hold an open revision request: one query for a page.

    Callers pass one page of ids (already bounded); returns a set so a row
    lookup is O(1). Empty input costs no query.
    """
    from app import db
    from app.models import VaSubmissionWorkflow

    sids = list(dict.fromkeys(sids))
    if not sids:
        return set()
    return set(
        db.session.scalars(
            sa.select(VaSubmissionWorkflow.va_sid).where(
                VaSubmissionWorkflow.va_sid.in_(sids),
                VaSubmissionWorkflow.workflow_state == _FUC,
                revision_request_open_condition(VaSubmissionWorkflow.va_sid),
            )
        )
    )
