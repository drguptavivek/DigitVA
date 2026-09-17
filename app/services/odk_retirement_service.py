"""Retired-from-ODK submissions: the single predicate every surface uses.

Policy: docs/policy/odk-retired-submissions.md. A submission whose
``va_sync_issue_code`` is ``missing_in_odk`` is retired: kept with its history,
but not codeable and not counted by default. Sync owns the flag; this module
only interprets it.
"""

from __future__ import annotations

import sqlalchemy as sa

from app import db
from app.models import VaSubmissions

MISSING_IN_ODK = "missing_in_odk"

RETIRED_MESSAGE = (
    "This submission is no longer present in ODK Central and cannot be coded."
)


def submission_is_in_odk(submissions=VaSubmissions):
    """SQL predicate: the submission is not retired from ODK.

    ``submissions`` may be the model or an alias of it; use the same object
    that the surrounding query selects from.
    """
    code = submissions.va_sync_issue_code
    return sa.or_(code.is_(None), code != MISSING_IN_ODK)


def submission_is_retired(submissions=VaSubmissions):
    """SQL predicate: the submission is retired from ODK."""
    return submissions.va_sync_issue_code == MISSING_IN_ODK


def is_submission_retired(va_sid: str) -> bool:
    """Return whether one submission is currently retired from ODK."""
    code = db.session.scalar(
        sa.select(VaSubmissions.va_sync_issue_code).where(VaSubmissions.va_sid == va_sid)
    )
    return code == MISSING_IN_ODK


# Raw-SQL form of the same predicate, for the reporting queries that are
# written as sa.text() rather than as a Core expression. Callers splice the
# fragment into their statement and merge IN_ODK_BIND into their parameters.
IN_ODK_BIND = {"odk_missing_code": MISSING_IN_ODK}


def in_odk_sql(alias: str = "s") -> str:
    """Return ``submission_is_in_odk()`` as a SQL fragment for raw-text queries.

    ``alias`` is the ``va_submissions`` alias used by the surrounding
    statement. It is interpolated, so it must be a literal written by the
    calling query — never a value from a request. The retired code itself is
    bound as ``:odk_missing_code`` (see ``IN_ODK_BIND``).
    """
    return (
        f"({alias}.va_sync_issue_code IS NULL"
        f" OR {alias}.va_sync_issue_code <> :odk_missing_code)"
    )
