"""The per-project coder recode window (va_project_master.recode_window_minutes).

How long after a coder's final COD that coder may recode it once, and when the
case becomes reviewer-eligible. Policy:
docs/policy/coding-workflow-state-machine.md ("Recode Window").
"""

from collections.abc import Iterable
from datetime import timedelta

import sqlalchemy as sa

from app import db
from app.models import VaForms, VaProjectMaster, VaSubmissions

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
