"""Seed for the send-back vs ODK-change split (digitva-jcll).

One form's worth of submissions in ``finalized_upstream_changed`` (fuc) for
different reasons, so the SQL helpers and the DM KPI endpoints are tested
against the same cases. ``seed_revision_cases`` adds rows only; the caller owns
the ``VaForms`` row and the commit.
"""

from datetime import datetime, timedelta

from app import db
from app.models import (
    VaSubmissions,
    VaSubmissionUpstreamChange,
    VaSubmissionWorkflow,
    VaSubmissionWorkflowEvent,
)

FUC = "finalized_upstream_changed"

#: name -> (workflow state, [(hours ago, transition_id, previous, current, reason)])
_CODED = (3, "coder_finalized", "coding_in_progress", "coder_finalized", "test_seed")
_CASES = {
    # ODK data changed after coding.
    "odk": (FUC, [_CODED, (2, "upstream_change_detected", "coder_finalized", FUC, "upstream_odk_data_changed")]),
    # A coder's send-back, a supervisor's reopen.
    "sent_back": (FUC, [_CODED, (2, "upstream_change_detected", "coder_finalized", FUC, "sent_back_for_revision")]),
    "reopened": (FUC, [_CODED, (2, "upstream_change_detected", "coder_finalized", FUC, "reopened_for_revision")]),
    # Legacy row: fuc with no workflow events at all (reads as ODK).
    "legacy": (FUC, []),
    # Sent back, then ODK data changed: the later event wins, ODK.
    "odk_after": (
        FUC,
        [
            (4, "coder_finalized", "coding_in_progress", "coder_finalized", "test_seed"),
            (3, "upstream_change_detected", "coder_finalized", FUC, "sent_back_for_revision"),
            (1, "upstream_change_detected", FUC, FUC, "upstream_odk_data_changed"),
        ],
    ),
    # Coded and untouched: the control.
    "coded": ("coder_finalized", [_CODED]),
    # The interviewer revised a send-back: coding restarted by the system.
    "restarted": (
        "smartva_pending",
        [
            _CODED,
            (2, "upstream_change_detected", "coder_finalized", FUC, "sent_back_for_revision"),
            (1, "upstream_change_accepted", FUC, "smartva_pending", "interviewer_revision"),
        ],
    ),
    # A data manager accepted an ODK change and reopened coding (D-WT-04).
    "dm_reopen": (
        "ready_for_coding",
        [
            _CODED,
            (2, "upstream_change_detected", "coder_finalized", FUC, "upstream_odk_data_changed"),
            (1, "upstream_change_accepted", FUC, "ready_for_coding", "data_manager_accepted_upstream_change"),
        ],
    ),
}


def _seed_case(form_id: str, sid: str, state: str, events: list, coder_user_id, now: datetime) -> None:
    db.session.add(
        VaSubmissions(
            va_sid=sid,
            va_form_id=form_id,
            va_submission_date=now - timedelta(hours=6),
            va_odk_updatedat=now,
            va_data_collector="Collector",
            va_instance_name=sid,
            va_uniqueid_real=sid,
            va_uniqueid_masked=f"masked-{sid[-12:]}",
            va_consent="yes",
            va_narration_language="English",
            va_deceased_age=55,
            va_deceased_gender="female",
            va_summary=[],
            va_catcount={},
            va_category_list=[],
        )
    )
    db.session.flush()
    db.session.add(
        VaSubmissionWorkflow(
            va_sid=sid,
            workflow_state=state,
            workflow_reason="test_seed",
            workflow_updated_by_role="vasystem",
        )
    )
    for hours_ago, transition_id, previous, current, reason in events:
        db.session.add(
            VaSubmissionWorkflowEvent(
                va_sid=sid,
                transition_id=transition_id,
                previous_state=previous,
                current_state=current,
                actor_kind="user" if transition_id == "coder_finalized" else "system",
                actor_role="vacoder" if transition_id == "coder_finalized" else "vasystem",
                actor_user_id=coder_user_id if transition_id == "coder_finalized" else None,
                transition_reason=reason,
                event_created_at=now - timedelta(hours=hours_ago),
            )
        )
    db.session.flush()


def seed_stale_fuc_case(form_id: str, coder_user_id, now: datetime, sid: str) -> str:
    """A row still reading ``finalized_upstream_changed`` (a stale analytics-MV
    reading) whose latest event, an interviewer's revision, already left it."""
    _seed_case(
        form_id, sid, FUC,
        [
            _CODED,
            (2, "upstream_change_detected", "coder_finalized", FUC, "sent_back_for_revision"),
            (1, "upstream_change_accepted", FUC, "smartva_pending", "interviewer_revision"),
        ],
        coder_user_id, now,
    )
    return sid


def seed_revision_cases(form_id: str, coder_user_id, now: datetime, prefix: str = "rev") -> dict[str, str]:
    """Add the cases above to *form_id*; returns {case name: va_sid}."""
    sids = {name: f"uuid:{prefix}-{name.replace('_', '-')}" for name in _CASES}
    for name, (state, events) in _CASES.items():
        _seed_case(form_id, sids[name], state, events, coder_user_id, now)
    # The one ODK change that is still pending carries its upstream row.
    db.session.add(
        VaSubmissionUpstreamChange(
            va_sid=sids["odk"],
            workflow_state_before="coder_finalized",
            previous_va_data={},
            incoming_va_data={},
            resolution_status="pending",
        )
    )
    db.session.flush()
    return sids
