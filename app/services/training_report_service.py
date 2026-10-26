"""Trainer report of a training session (Training & demo project, TRN01).

Policy: docs/policy/training-demo-project.md ("Trainer report"). The report
holds the answer key (the source case's ICD-10 cause), so it is read only by an
administrator or by a user with an active ``reviewer_data_manager``
participation in that very session; coders and the other roles never reach it.
It carries trainee names and emails and the cause codes; never the source
case's id or any case content.

``training_session_report`` runs a fixed number of aggregate queries however
many participants the session has.
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import UTC

import sqlalchemy as sa

from app import db
from app.models import (
    MapCaseTransition,
    MapTrainingCase,
    MapTrainingParticipant,
    MasOrgUnit,
    MasTrainingSession,
    VaDeathRegister,
    VaFinalAssessments,
    VaStatuses,
    VaSubmissionWorkflow,
    VaUsers,
    VaWebIntakeDraft,
)
from app.models.mas_training import CASES_PER_SLOT
from app.services import training_demo_service as sessions
from app.services.icd_coding_value import (
    classification_of_value,
    extract_icd11_code_expression,
    extract_icd_code,
    icd11_primary_stem_of,
)
from app.services.organization_service import _spreadsheet_safe
from app.services.training_cause_groups import va_cause_of, va_cause_title
from app.services.training_demo_service import TrainingDemoError

#: Workflow states that mean a coder has opened a case but not finished it.
_IN_CODING_STATES = ("coding_in_progress", "coder_step1_saved")
STAFF_ROLES = ("death_reporter", "interviewer", "interview_supervisor", "reviewer_data_manager")

NOTES = (
    "Agreement compares the WHO 2022 VA cause of the trainee's final cause with that of the source "
    "case's original ICD-10 cause. A case is 'unmappable' when either cause is missing from, or "
    "ambiguous in, the WHO cause list; it is left out of the percentage.",
    "Supervisor actions are case moves that relied on a supervisor grant. Other supervisor "
    "activity (for example reviewing a list) leaves no record and is not counted.",
)


def _aware(value):
    return value.replace(tzinfo=UTC) if value is not None and value.tzinfo is None else value


def _iso(value):
    value = _aware(value)
    return value.isoformat() if value else None


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------

def _session_match(ref):
    text = str(ref or "").strip()
    try:
        return MasTrainingSession.training_session_id == uuid.UUID(text)
    except ValueError:
        return MasTrainingSession.session_code == text.upper()


def _reviewer_session_ids(viewer_id) -> sa.Select:
    return sa.select(MapTrainingParticipant.training_session_id).where(
        MapTrainingParticipant.user_id == viewer_id,
        MapTrainingParticipant.role == "reviewer_data_manager",
        MapTrainingParticipant.status == "active",
    )


def authorized_session(ref, viewer) -> MasTrainingSession:
    """The session *ref* if *viewer* may read its report, else an error.

    Admin: any session (an unknown one is "not found"). Anyone else: only a
    session where they hold an active ``reviewer_data_manager`` participation;
    every other case, an unknown session included, is the same refusal so a
    session's existence is not probed.
    """
    if viewer is None or not viewer.is_active:
        raise TrainingDemoError("report_forbidden")
    if viewer.is_admin():
        return sessions._find_session(ref)
    found = db.session.scalar(
        sa.select(MasTrainingSession).where(
            MasTrainingSession.project_id == sessions.TRAINING_PROJECT_ID,
            _session_match(ref),
            MasTrainingSession.training_session_id.in_(_reviewer_session_ids(viewer.user_id)),
        )
    )
    if found is None:
        raise TrainingDemoError("report_forbidden")
    return found


def sessions_for_viewer(viewer) -> list[dict]:
    """The sessions *viewer* may report on (all for an admin), newest first."""
    if viewer is None or not viewer.is_active:
        return []
    everything = sessions.list_training_sessions()
    if viewer.is_admin():
        return everything
    allowed = {str(i) for i in db.session.scalars(_reviewer_session_ids(viewer.user_id))}
    return [row for row in everything if row["training_session_id"] in allowed]


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------

def _cause_view(value, provenance_item=None):
    """``(code, title)`` of a stored ``"<CODE> <title>"`` value. An ICD-11
    value shows its primary stem (``icd11_primary_stem_of``), the stem its VA
    cause group comes from; the title follows the whole code expression."""
    classification = classification_of_value(value)
    if classification is None:
        return None, None
    text = (value or "").strip()
    if classification == "icd10":
        code = extract_icd_code(text, "icd10")
        return code, text[len(code):].strip() or None
    code = icd11_primary_stem_of(text, provenance_item)
    lead = extract_icd11_code_expression(text) or extract_icd_code(text, "icd11")
    return code, text[len(lead):].strip() or None


def _staff_counts(session_row) -> dict:
    """Per user: deaths registered, interviews started and submitted, supervisor
    actions, within the session's units (its root and the coder slots). Four queries."""
    root = session_row.org_unit_id
    units = sa.select(MasOrgUnit.org_unit_id).where(
        sa.or_(MasOrgUnit.org_unit_id == root, MasOrgUnit.parent_org_unit_id == root)
    )
    in_units = VaDeathRegister.org_unit_id.in_(units)
    started = VaDeathRegister.status != "draft_identity"
    counts: dict = {}

    def add(key, rows):
        for user_id, number in rows:
            counts.setdefault(user_id, {})[key] = number

    add("deaths_registered", db.session.execute(
        sa.select(VaDeathRegister.registered_by, sa.func.count())
        .where(in_units, started).group_by(VaDeathRegister.registered_by)))
    add("interviews_started", db.session.execute(
        sa.select(VaDeathRegister.started_by_user_id, sa.func.count())
        .where(in_units, VaDeathRegister.started_by_user_id.is_not(None))
        .group_by(VaDeathRegister.started_by_user_id)))
    add("interviews_submitted", db.session.execute(
        sa.select(VaWebIntakeDraft.user_id, sa.func.count())
        .join(VaDeathRegister, VaDeathRegister.death_id == VaWebIntakeDraft.death_id)
        .where(in_units, VaWebIntakeDraft.status == "submitted")
        .group_by(VaWebIntakeDraft.user_id)))
    add("supervisor_actions", db.session.execute(
        sa.select(MapCaseTransition.actor_user_id, sa.func.count())
        .join(VaDeathRegister, VaDeathRegister.death_id == MapCaseTransition.death_id)
        .where(in_units, MapCaseTransition.authorizing_grant_id.is_not(None))
        .group_by(MapCaseTransition.actor_user_id)))
    return counts


def training_session_report(session_ref, viewer) -> dict:
    """The trainer report of one session, for *viewer* (admin or the session's
    reviewer_data_manager). Raises ``TrainingDemoError('report_forbidden')``.
    Seven queries (plus the viewer lookup), whatever the participant count."""
    row = authorized_session(session_ref, viewer)
    participants = db.session.execute(
        sa.select(MapTrainingParticipant, VaUsers)
        .join(VaUsers, VaUsers.user_id == MapTrainingParticipant.user_id)
        .where(MapTrainingParticipant.training_session_id == row.training_session_id)
        .order_by(MapTrainingParticipant.coder_slot, VaUsers.name, MapTrainingParticipant.added_at)
    ).all()
    case_rows = db.session.execute(
        sa.select(
            MapTrainingCase.case_number, MapTrainingCase.coder_slot, MapTrainingCase.source_final_cod,
            VaFinalAssessments.va_conclusive_cod, VaFinalAssessments.icd11_provenance,
            VaFinalAssessments.va_finassess_createdat, VaSubmissionWorkflow.workflow_state, VaSubmissionWorkflow.workflow_updated_at,
        )
        .outerjoin(
            VaFinalAssessments,
            sa.and_(
                VaFinalAssessments.va_sid == MapTrainingCase.va_sid,
                VaFinalAssessments.va_finassess_status == VaStatuses.active,
                VaFinalAssessments.is_tester.is_(False),
            ),
        )
        .outerjoin(VaSubmissionWorkflow, VaSubmissionWorkflow.va_sid == MapTrainingCase.va_sid)
        .where(MapTrainingCase.training_session_id == row.training_session_id)
        .order_by(MapTrainingCase.case_number)
    ).all()

    coder_of = {p.coder_slot: u for p, u in participants if p.role == "coder"}
    slots: dict = {}
    cases = []
    for number, slot, source_cod, trainee_cod, provenance, final_at, state, state_at in case_rows:
        # The trainee's recorded primary stem; the reference text has none.
        trainee_item = provenance.get("conclusive") if isinstance(provenance, dict) else None
        stat = slots.setdefault(slot, {
            "total": 0, "coded": 0, "in_progress": 0, "last": None, "compared": 0, "matched": 0,
            "unmappable": 0,
        })
        stat["total"] += 1
        touched = [final_at] if final_at else []
        if state and state != "ready_for_coding" and state_at:
            touched.append(state_at)
        if touched:
            stat["last"] = max([stat["last"], *touched]) if stat["last"] else max(touched)
        if trainee_cod is None:
            if state in _IN_CODING_STATES:
                stat["in_progress"] += 1
            continue
        stat["coded"] += 1
        trainee_group, reference_group = va_cause_of(trainee_cod, trainee_item), va_cause_of(source_cod)
        if trainee_group is None or reference_group is None:
            match = "unmappable"
            stat["unmappable"] += 1
        else:
            match = "yes" if trainee_group == reference_group else "no"
            stat["compared"] += 1
            stat["matched"] += match == "yes"
        code, title = _cause_view(trainee_cod, trainee_item)
        coder = coder_of.get(slot)
        cases.append({
            "case_number": number, "coder_slot": slot,
            "coder_name": coder.name if coder else None,
            "trainee_code": code, "trainee_title": title,
            "trainee_group": trainee_group, "trainee_group_title": va_cause_title(trainee_group),
            "reference_cause": (source_cod or "").strip() or None,
            "reference_group": reference_group, "reference_group_title": va_cause_title(reference_group),
            "match": match,
        })

    coders = []
    for p, user in participants:
        if p.role != "coder":
            continue
        stat = slots.get(p.coder_slot, {})
        total, coded = stat.get("total", 0), stat.get("coded", 0)
        in_progress = stat.get("in_progress", 0)
        compared = stat.get("compared", 0)
        coders.append({
            "name": user.name, "email": sessions._contact(user), "slot": p.coder_slot, "status": p.status,
            "cases_total": total, "coded": coded, "in_progress": in_progress,
            "not_started": total - coded - in_progress,
            "last_activity": _iso(stat.get("last")),
            "completed": coded >= CASES_PER_SLOT,
            "compared": compared, "matched": stat.get("matched", 0),
            "unmappable": stat.get("unmappable", 0),
            "agreement_pct": round(100 * stat.get("matched", 0) / compared, 1) if compared else None,
        })

    activity = _staff_counts(row)
    staff = [
        {
            "name": user.name, "email": sessions._contact(user), "role": p.role, "status": p.status,
            **{key: activity.get(user.user_id, {}).get(key, 0) for key in (
                "deaths_registered", "interviews_started", "interviews_submitted", "supervisor_actions")},
        }
        for p, user in participants
        if p.role in STAFF_ROLES
    ]

    # Totals cover every case of the session, a slot without a coder included.
    compared = sum(s["compared"] for s in slots.values())
    matched = sum(s["matched"] for s in slots.values())
    totals = {
        "coders": len(coders),
        "coders_completed": sum(c["completed"] for c in coders),
        "cases_total": len(case_rows),
        "coded": sum(s["coded"] for s in slots.values()),
        "in_progress": sum(s["in_progress"] for s in slots.values()),
        "compared": compared, "matched": matched,
        "unmappable": sum(s["unmappable"] for s in slots.values()),
        "agreement_pct": round(100 * matched / compared, 1) if compared else None,
        "deaths_registered": sum(s["deaths_registered"] for s in staff),
        "interviews_started": sum(s["interviews_started"] for s in staff),
        "interviews_submitted": sum(s["interviews_submitted"] for s in staff),
        "supervisor_actions": sum(s["supervisor_actions"] for s in staff),
    }
    return {
        "session": sessions._session_fields(row),
        "target_per_coder": CASES_PER_SLOT,
        "totals": totals, "coders": coders, "cases": cases, "staff": staff, "notes": list(NOTES),
    }


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------

def _csv(header, rows) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(header)
    for values in rows:
        writer.writerow([_spreadsheet_safe(v) if isinstance(v, str) else ("" if v is None else v) for v in values])
    return out.getvalue()


def coders_csv(report: dict) -> str:
    return _csv(
        ("name", "email", "slot", "status", "coded", "target", "in_progress", "not_started",
         "last_activity", "completed", "compared", "matched", "unmappable", "agreement_pct"),
        [(c["name"], c["email"], c["slot"], c["status"], c["coded"], report["target_per_coder"],
          c["in_progress"], c["not_started"], c["last_activity"], "yes" if c["completed"] else "no",
          c["compared"], c["matched"], c["unmappable"], c["agreement_pct"]) for c in report["coders"]],
    )


def cases_csv(report: dict) -> str:
    return _csv(
        ("case_number", "slot", "coder", "trainee_code", "trainee_title", "trainee_va_cause",
         "reference_cause", "reference_va_cause", "match"),
        [(c["case_number"], c["coder_slot"], c["coder_name"], c["trainee_code"], c["trainee_title"],
          c["trainee_group"], c["reference_cause"], c["reference_group"], c["match"])
         for c in report["cases"]],
    )
