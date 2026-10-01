"""The data-manager KPI bucket "Not analysable" and its three reasons.

A submission in the ``consent_refused`` workflow state (the one state that is
outside coding and blocked from SmartVA) can never be analysed. Web intake
routes every refused, respondent-unavailable and partially completed
interview there (docs/policy/web-intake.md, "Submission"); ODK routes real
consent = no there. The reason is read from the active payload's
``interview_outcome``; a payload without one (every ODK submission) counts as
Refused. Nothing is stored for it: no schema change.

Imports nothing, like ``duplicate_exclusion``: routes and services share it.
"""

REASONS = ("refused", "respondent_unavailable", "partially_completed")

#: Joined as ``pv`` over the submission alias ``s`` in raw-SQL KPI queries.
PAYLOAD_JOIN_SQL = (
    "LEFT JOIN va_submission_payload_versions pv "
    "ON pv.payload_version_id = s.active_payload_version_id"
)

#: The reason of a ``consent_refused`` row; any other or missing outcome is Refused.
REASON_SQL = (
    "CASE WHEN pv.payload_data->>'interview_outcome' IN "
    "('respondent_unavailable', 'partially_completed') "
    "THEN pv.payload_data->>'interview_outcome' ELSE 'refused' END"
)


def by_reason(rows) -> dict:
    """``{reason: count}`` for every reason (zero when absent) from ``(reason, count)`` rows."""
    counts = {reason: 0 for reason in REASONS}
    for reason, count in rows:
        counts[reason] = count or 0
    return counts
