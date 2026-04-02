"""Narrative Quality Assessment API — /api/v1/va/<sid>/narrative-qa

Resources:
  POST <sid>/narrative-qa   — save/update Narrative Quality Assessment
"""

from __future__ import annotations

import logging

import sqlalchemy as sa
from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user

from app import db
from app.models import (
    VaAllocations,
    VaAllocation,
    VaStatuses,
    VaNarrativeAssessment,
    VaSubmissionsAuditlog,
)
from app.services.coding_service import get_project_for_submission
from app.services.demo_project_service import (
    get_demo_expiry_for_submission,
    is_demo_training_submission,
)
from app.services.payload_bound_coding_artifact_service import (
    deactivate_other_active_narrative_assessments,
    get_submission_with_current_payload,
)

bp = Blueprint("nqa_api", __name__)
log = logging.getLogger(__name__)

def _require_coding_access(va_sid: str):
    """Return a JSON 403 if the user lacks an active coding allocation.

    Admin users with va_actiontype == "vademo_start_coding" in the body are allowed through.
    """
    data = request.get_json(silent=True) or {}
    if data.get("va_actiontype") == "vademo_start_coding":
        if current_user.is_admin():
            return None
        if not current_user.is_coder() or not is_demo_training_submission(va_sid):
            return jsonify({"error": "Only demo/training projects allow coder demo sessions."}), 403

    alloc = db.session.scalar(
        sa.select(VaAllocations.va_sid).where(
            VaAllocations.va_allocated_to == current_user.user_id,
            VaAllocations.va_allocation_for == VaAllocation.coding,
            VaAllocations.va_allocation_status == VaStatuses.active,
            VaAllocations.va_sid == va_sid,
        )
    )
    if not alloc:
        return jsonify({"error": "Active coding allocation required."}), 403
    return None


def _nqa_score(length, pos_symptoms, neg_symptoms, chronology, doc_review, comorbidity) -> int:
    return length + pos_symptoms + neg_symptoms + chronology + doc_review + comorbidity


@bp.post("/<va_sid>/narrative-qa")
@login_required
def save_narrative_qa(va_sid: str):
    """Save or update the Narrative Quality Assessment for a coder on a submission."""
    err = _require_coding_access(va_sid)
    if err:
        return err

    project = get_project_for_submission(va_sid)
    if not project or not project.narrative_qa_enabled:
        return jsonify({"error": "Narrative QA is not enabled for this project."}), 400

    data = request.get_json(force=True) or {}
    va_actiontype = data.get("va_actiontype")

    def _int(key, min_val, max_val):
        try:
            v = int(data[key])
            if not (min_val <= v <= max_val):
                raise ValueError
            return v
        except (KeyError, TypeError, ValueError):
            return None

    length       = _int("length",       1, 3)
    pos_symptoms = _int("pos_symptoms", 1, 3)
    neg_symptoms = _int("neg_symptoms", 0, 1)
    chronology   = _int("chronology",   0, 1)
    doc_review   = _int("doc_review",   0, 1)
    comorbidity  = _int("comorbidity",  0, 1)

    missing = [k for k, v in {
        "length": length, "pos_symptoms": pos_symptoms,
        "neg_symptoms": neg_symptoms, "chronology": chronology,
        "doc_review": doc_review, "comorbidity": comorbidity,
    }.items() if v is None]
    if missing:
        return jsonify({"error": f"Invalid or missing fields: {', '.join(missing)}"}), 400

    score = _nqa_score(length, pos_symptoms, neg_symptoms, chronology, doc_review, comorbidity)
    _, active_payload_version = get_submission_with_current_payload(
        va_sid,
        for_update=True,
        created_by_role="vacoder",
        created_by=current_user.user_id,
    )

    existing = db.session.scalar(
        sa.select(VaNarrativeAssessment).where(
            VaNarrativeAssessment.va_sid == va_sid,
            VaNarrativeAssessment.va_nqa_by == current_user.user_id,
            VaNarrativeAssessment.payload_version_id
            == active_payload_version.payload_version_id,
            VaNarrativeAssessment.va_nqa_status == VaStatuses.active,
        )
    )
    if existing:
        existing.va_nqa_length       = length
        existing.va_nqa_pos_symptoms = pos_symptoms
        existing.va_nqa_neg_symptoms = neg_symptoms
        existing.va_nqa_chronology   = chronology
        existing.va_nqa_doc_review   = doc_review
        existing.va_nqa_comorbidity  = comorbidity
        existing.va_nqa_score        = score
        existing.payload_version_id  = active_payload_version.payload_version_id
        existing.demo_expires_at     = get_demo_expiry_for_submission(va_sid, va_actiontype)
        nqa = existing
        audit_operation = "u"
        audit_action = "narrative quality assessment updated"
    else:
        deactivate_other_active_narrative_assessments(
            va_sid,
            current_user.user_id,
            audit_byrole="vacoder",
            audit_by=current_user.user_id,
        )
        nqa = VaNarrativeAssessment(
            va_sid=va_sid,
            va_nqa_by=current_user.user_id,
            payload_version_id=active_payload_version.payload_version_id,
            va_nqa_length=length,
            va_nqa_pos_symptoms=pos_symptoms,
            va_nqa_neg_symptoms=neg_symptoms,
            va_nqa_chronology=chronology,
            va_nqa_doc_review=doc_review,
            va_nqa_comorbidity=comorbidity,
            va_nqa_score=score,
            va_nqa_status=VaStatuses.active,
            demo_expires_at=get_demo_expiry_for_submission(va_sid, va_actiontype),
        )
        db.session.add(nqa)
        audit_operation = "c"
        audit_action = "narrative quality assessment saved"

    if existing:
        deactivate_other_active_narrative_assessments(
            va_sid,
            current_user.user_id,
            keep_id=nqa.va_nqa_id,
            audit_byrole="vacoder",
            audit_by=current_user.user_id,
        )
    db.session.flush()
    db.session.add(
        VaSubmissionsAuditlog(
            va_sid=va_sid,
            va_audit_byrole="vacoder",
            va_audit_by=current_user.user_id,
            va_audit_operation=audit_operation,
            va_audit_action=audit_action,
            va_audit_entityid=nqa.va_nqa_id,
        )
    )
    db.session.commit()
    return jsonify({
        "saved": True,
        "score": nqa.va_nqa_score,
        "rating": nqa.rating,
        "rating_class": nqa.rating_class,
    })
