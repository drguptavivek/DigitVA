"""Narrative Quality Assessment API — /api/v1/va/<sid>/narrative-qa

Resources:
  POST <sid>/narrative-qa   — save/update Narrative Quality Assessment
"""

from __future__ import annotations

import logging

import sqlalchemy as sa
from flask import Blueprint, jsonify, request
from flask_login import current_user

from app import db
from app.decorators import role_required
from app.models import (
    VaAllocation,
    VaAllocations,
    VaStatuses,
    VaNarrativeAssessment,
    VaSubmissions,
    VaSubmissionsAuditlog,
)
from app.services.authz import Action, can
from app.services.coding_service import get_project_for_submission
from app.services.demo_project_service import (
    get_demo_expiry_for_submission,
)
from app.services.narrative_qa_service import narrative_qa_allowed_values
from app.services.payload_bound_coding_artifact_service import (
    deactivate_other_active_narrative_assessments,
    get_submission_with_current_payload,
)
from app.utils.va_permission.va_permission_11_require_coding_access import require_coding_access

bp = Blueprint("nqa_api", __name__)
log = logging.getLogger(__name__)


def _error(message: str, status_code: int, code: str):
    return jsonify({"error": message, "code": code}), status_code


def _nqa_score(length, pos_symptoms, neg_symptoms, chronology, doc_review, comorbidity) -> int:
    return length + pos_symptoms + neg_symptoms + chronology + doc_review + comorbidity


@bp.post("/<va_sid>/narrative-qa")
@role_required("coder", "coding_tester", "reviewer", "admin")
def save_narrative_qa(va_sid: str):
    """Save or update the Narrative Quality Assessment for the current user."""
    data = request.get_json(force=True, silent=True)
    if not isinstance(data, dict):
        return _error("A JSON object is required.", 400, "invalid_request")
    va_actiontype = data.get("va_actiontype")
    is_reviewer_session = va_actiontype in {
        "vastartreviewing",
        "varesumereviewing",
    }

    audit_byrole = "reviewer" if is_reviewer_session else "vacoder"
    if is_reviewer_session:
        submission = db.session.get(VaSubmissions, va_sid)
        if not submission:
            return _error("Submission not found.", 404, "not_found")
        # REVIEW scope as well as the allocation: an allocation that outlived
        # a re-routing or a narrowed grant does not carry the save.
        if not can(current_user, Action.REVIEW, va_sid):
            return _error("Reviewer access is required.", 403, "forbidden")
        active_reviewing_allocation = db.session.scalar(
            sa.select(VaAllocations.va_allocation_id).where(
                VaAllocations.va_sid == va_sid,
                VaAllocations.va_allocated_to == current_user.user_id,
                VaAllocations.va_allocation_for == VaAllocation.reviewing,
                VaAllocations.va_allocation_status == VaStatuses.active,
            )
        )
        if not active_reviewing_allocation:
            return _error("Active reviewer allocation required.", 403, "no_allocation")
    else:
        err = require_coding_access(va_sid)
        if err:
            return err

    project = get_project_for_submission(va_sid)
    if not project or not project.narrative_qa_enabled:
        return _error("Narrative QA is not enabled for this project.", 400, "invalid_request")

    cannot_grade = bool(data.get("cannot_grade"))

    if cannot_grade:
        length = pos_symptoms = neg_symptoms = chronology = doc_review = comorbidity = 0
        score = 0
    else:
        values = {}
        for key, allowed in narrative_qa_allowed_values().items():
            try:
                value = int(data[key])
            except (KeyError, TypeError, ValueError, OverflowError):
                value = None
            values[key] = value if value in allowed else None

        missing = [k for k, v in values.items() if v is None]
        if missing:
            return _error(
                f"Invalid or missing fields: {', '.join(missing)}", 400, "invalid_request"
            )

        length = values["length"]
        pos_symptoms = values["pos_symptoms"]
        neg_symptoms = values["neg_symptoms"]
        chronology = values["chronology"]
        doc_review = values["doc_review"]
        comorbidity = values["comorbidity"]
        score = _nqa_score(length, pos_symptoms, neg_symptoms, chronology, doc_review, comorbidity)
    _, active_payload_version = get_submission_with_current_payload(
        va_sid,
        for_update=True,
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
        existing.va_nqa_cannot_grade = cannot_grade
        existing.payload_version_id  = active_payload_version.payload_version_id
        existing.demo_expires_at     = get_demo_expiry_for_submission(va_sid, va_actiontype)
        nqa = existing
        audit_operation = "u"
        audit_action = "narrative quality assessment updated"
    else:
        deactivate_other_active_narrative_assessments(
            va_sid,
            current_user.user_id,
            audit_byrole=audit_byrole,
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
            va_nqa_cannot_grade=cannot_grade,
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
            audit_byrole=audit_byrole,
            audit_by=current_user.user_id,
        )
    db.session.flush()
    db.session.add(
        VaSubmissionsAuditlog(
            va_sid=va_sid,
            va_audit_byrole=audit_byrole,
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
