"""The per-project coder recode window (va_project_master.recode_window_minutes).

How long after a coder's first final COD of the current coding round that
coder may recode it (any number of times; a recode never extends the window),
and when the case becomes reviewer-eligible. Policy: docs/policy/coding-workflow-state-machine.md
("Recode Window").
"""

from collections.abc import Iterable
from datetime import datetime, timedelta

import sqlalchemy as sa

from app import db
from app.models import (
    VaCoderReview,
    VaFinalAssessments,
    VaForms,
    VaProjectMaster,
    VaSubmissions,
)
from app.models.va_submission_workflow_events import VaSubmissionWorkflowEvent
from app.services.workflow.definition import (
    TRANSITION_ADMIN_OVERRIDE_TO_RECODE,
    TRANSITION_UPSTREAM_CHANGE_ACCEPTED,
)

DEFAULT_RECODE_WINDOW_MINUTES = 1440
MAX_RECODE_WINDOW_MINUTES = 10080


def recode_window(project: VaProjectMaster | None) -> timedelta:
    """The project's recode window; the 24-hour default when there is no project."""
    minutes = project.recode_window_minutes if project else DEFAULT_RECODE_WINDOW_MINUTES
    return timedelta(minutes=minutes)


def recode_window_label(window: timedelta) -> str:
    """'24 hours', '1 hour' or '60 minutes'... for coder-facing messages.

    Whole hours read as hours except 60, which the owner phrased as minutes.
    """
    minutes = int(window.total_seconds() // 60)
    if minutes % 60 == 0 and minutes != 60:
        hours = minutes // 60
        return f"{hours} hour" if hours == 1 else f"{hours} hours"
    return f"{minutes} minute" if minutes == 1 else f"{minutes} minutes"


def recode_window_for_submission(va_sid: str) -> timedelta:
    """The recode window of *va_sid*'s project, in one query."""
    return recode_window(
        db.session.scalar(
            sa.select(VaProjectMaster)
            .join(VaForms, VaForms.project_id == VaProjectMaster.project_id)
            .join(VaSubmissions, VaSubmissions.va_form_id == VaForms.form_id)
            .where(VaSubmissions.va_sid == va_sid)
        )
    )


def recode_windows_by_project(project_ids: Iterable[str]) -> dict[str, timedelta]:
    """``{project_id: window}`` for *project_ids*, in one query."""
    ids = set(project_ids)
    if not ids:
        return {}
    rows = db.session.execute(
        sa.select(VaProjectMaster.project_id, VaProjectMaster.recode_window_minutes).where(
            VaProjectMaster.project_id.in_(ids)
        )
    ).all()
    return {project_id: timedelta(minutes=minutes) for project_id, minutes in rows}


def recode_window_interval():
    """SQL interval for ``VaProjectMaster.recode_window_minutes``; the query joins the project."""
    return VaProjectMaster.recode_window_minutes * sa.literal_column("interval '1 minute'")


#: Transitions that open a new coding round: the case is reopened for a full
#: new coding (an upstream data change accepted for recode, the interviewer's
#: revision and the supervisor's choice included, or an admin reopen). A
#: coder's own recode (``recode_started``) never does.
ROUND_BOUNDARY_TRANSITIONS = (
    TRANSITION_UPSTREAM_CHANGE_ACCEPTED,
    TRANSITION_ADMIN_OVERRIDE_TO_RECODE,
)


def _round_started_at(sid_col):
    """SQL: naive-UTC time of *sid_col*'s latest round boundary, '-infinity' if none.

    Events are timestamptz, finals and reviews naive UTC; the event side is
    cast so the comparison never depends on the session TimeZone. Served by
    ix_va_submission_workflow_events_sid_created.
    """
    event = sa.orm.aliased(VaSubmissionWorkflowEvent, name="round_event")
    return sa.func.coalesce(
        sa.select(sa.func.max(sa.func.timezone("UTC", event.event_created_at)))
        .where(
            event.va_sid == sid_col,
            event.transition_id.in_(ROUND_BOUNDARY_TRANSITIONS),
        )
        .scalar_subquery(),
        sa.literal_column("'-infinity'::timestamp"),
    )


def first_coding_at_expr(sid_col, user_id):
    """SQL: when *user_id* first finalized *sid_col* in the current coding round
    -- the start of the recode window.

    The earliest of the user's final CODs and not-codeable reviews on the
    submission created after the latest round boundary
    (``ROUND_BOUNDARY_TRANSITIONS``), any status, tester output excluded
    (digitva-ggc3); NULL when there is none. *sid_col* may be a column of the
    enclosing query (the subqueries correlate to it) or a literal sid.
    """
    final = sa.orm.aliased(VaFinalAssessments, name="first_final")
    review = sa.orm.aliased(VaCoderReview, name="first_review")
    return sa.func.least(
        sa.select(sa.func.min(final.va_finassess_createdat))
        .where(
            final.va_sid == sid_col,
            final.va_finassess_by == user_id,
            final.is_tester.is_(False),
            final.va_finassess_createdat > _round_started_at(sid_col),
        )
        .scalar_subquery(),
        sa.select(sa.func.min(review.va_creview_createdat))
        .where(
            review.va_sid == sid_col,
            review.va_creview_by == user_id,
            review.is_tester.is_(False),
            review.va_creview_createdat > _round_started_at(sid_col),
        )
        .scalar_subquery(),
    )


def first_coding_times(pairs: Iterable[tuple[str, object]]) -> dict[tuple[str, object], datetime]:
    """``{(va_sid, user_id): first finalized at}`` (naive UTC) for *pairs*, one query.

    The batch form of ``first_coding_at_expr``, current round only; pairs with
    no coding in the current round are absent.
    """
    pairs = set(pairs)
    if not pairs:
        return {}
    sids = {sid for sid, _ in pairs}
    users = {user_id for _, user_id in pairs}
    codings = sa.union_all(
        sa.select(
            VaFinalAssessments.va_sid.label("va_sid"),
            VaFinalAssessments.va_finassess_by.label("by"),
            VaFinalAssessments.va_finassess_createdat.label("at"),
        ).where(
            VaFinalAssessments.va_sid.in_(sids),
            VaFinalAssessments.va_finassess_by.in_(users),
            VaFinalAssessments.is_tester.is_(False),
        ),
        sa.select(
            VaCoderReview.va_sid, VaCoderReview.va_creview_by, VaCoderReview.va_creview_createdat
        ).where(
            VaCoderReview.va_sid.in_(sids),
            VaCoderReview.va_creview_by.in_(users),
            VaCoderReview.is_tester.is_(False),
        ),
    ).subquery()
    rounds = (
        sa.select(
            VaSubmissionWorkflowEvent.va_sid.label("va_sid"),
            sa.func.max(sa.func.timezone("UTC", VaSubmissionWorkflowEvent.event_created_at)).label(
                "started_at"
            ),
        )
        .where(
            VaSubmissionWorkflowEvent.va_sid.in_(sids),
            VaSubmissionWorkflowEvent.transition_id.in_(ROUND_BOUNDARY_TRANSITIONS),
        )
        .group_by(VaSubmissionWorkflowEvent.va_sid)
        .subquery()
    )
    rows = db.session.execute(
        sa.select(codings.c.va_sid, codings.c.by, sa.func.min(codings.c.at))
        .outerjoin(rounds, rounds.c.va_sid == codings.c.va_sid)
        .where(sa.or_(rounds.c.started_at.is_(None), codings.c.at > rounds.c.started_at))
        .group_by(codings.c.va_sid, codings.c.by)
    ).all()
    return {(sid, by): at for sid, by, at in rows if (sid, by) in pairs}
