"""Reviewer secondary-coding workflow service."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import sqlalchemy as sa
from flask import current_app

from app import db
from app.models import (
    VaAllocation,
    VaAllocations,
    VaFinalAssessments,
    VaReviewerFinalAssessments,
    VaReviewerInitialAssessments,
    VaStatuses,
    VaSubmissions,
    VaSubmissionsAuditlog,
)
from app.services.doris_certificate import DorisCertificateError
from app.services.doris_process_proof import (
    ProcessProofCertificateChanged,
    ProcessProofContextMismatch,
    ProcessProofExpired,
    ProcessProofInvalid,
    ProcessProofResultMismatch,
    generate_process_proof,
    verify_process_submission,
)
from app.services.doris_processing import process_certificate
from app.services.final_cod_authority_service import upsert_reviewer_final_cod_authority
from app.services.icd_coding_value import (
    build_icd11_provenance_for_values,
    validate_coding_value_for_submission,
)
from app.services.odk_retirement_service import RETIRED_MESSAGE, is_submission_retired
from app.services.payload_bound_coding_artifact_service import (
    get_current_payload_social_autopsy_analysis,
)
from app.services.reviewer_final_assessment_service import (
    create_reviewer_final_assessment,
    create_reviewer_initial_assessment,
    get_latest_active_reviewer_final_assessment,
    get_latest_active_reviewer_initial_assessment,
)
from app.services.who_icd_api import DEFAULT_ICD11_RELEASE, WhoIcdApiUnavailable
from app.services.workflow.definition import (
    WORKFLOW_REVIEWER_CODING_IN_PROGRESS,
    WORKFLOW_REVIEWER_ELIGIBLE,
)
from app.services.workflow.state_store import get_submission_workflow_state
from app.services.workflow.transitions import (
    mark_reviewer_coding_started,
    mark_reviewer_finalized,
    reviewer_actor,
)


@dataclass(frozen=True)
class ReviewerCodingResult:
    va_sid: str
    actiontype: str


class ReviewerCodingError(Exception):
    """Raised when reviewer coding cannot proceed."""

    def __init__(
        self,
        message: str,
        status_code: int = 403,
        *,
        code: str | None = None,
        processing: dict | None = None,
    ):
        self.message = message
        self.status_code = status_code
        self.code = code
        self.processing = processing
        super().__init__(message)


def _project_mode(project) -> str:
    if project.masked_cod_required:
        return "masked_simple"
    if project.cod_entry_mode == "doris":
        return "unmasked_doris"
    return "unmasked_simple"


def _mode_snapshot(project, who_image_digest: str) -> dict:
    return {
        "masked_cod_required": project.masked_cod_required,
        "cod_entry_mode": project.cod_entry_mode,
        "icd_release": DEFAULT_ICD11_RELEASE,
        "who_image_digest": who_image_digest,
    }


def _reviewer_social_autopsy_required(va_sid: str, submission: VaSubmissions) -> bool:
    from app.services.category_rendering_service import (
        get_category_rendering_service,
        get_visible_category_codes,
    )
    from app.services.coding_service import get_project_for_submission
    from app.services.submission_payload_version_service import get_active_payload_version
    from app.utils.va_form.va_form_02_formtyperesolution import (
        va_get_form_type_code_for_form,
    )

    project = get_project_for_submission(va_sid)
    if not project or not project.reviewer_social_autopsy_enabled:
        return False

    active_payload = get_active_payload_version(va_sid)
    visible_category_codes = get_visible_category_codes(
        active_payload.payload_data if active_payload else None,
        submission.va_form_id,
    )
    form_type_code = va_get_form_type_code_for_form(submission.va_form_id)
    return get_category_rendering_service().is_category_enabled(
        form_type_code,
        "vareview",
        visible_category_codes,
        "social_autopsy",
    )


def get_active_reviewing_allocation(user_id) -> str | None:
    return db.session.scalar(
        sa.select(VaAllocations.va_sid).where(
            VaAllocations.va_allocated_to == user_id,
            VaAllocations.va_allocation_for == VaAllocation.reviewing,
            VaAllocations.va_allocation_status == VaStatuses.active,
        )
    )


def start_reviewer_coding(user, va_sid: str) -> ReviewerCodingResult:
    from app.services.coding_allocation_service import release_stale_reviewer_allocations

    release_stale_reviewer_allocations(timeout_hours=1)

    submission = db.session.get(VaSubmissions, va_sid)
    if not submission:
        raise ReviewerCodingError("Submission not found.", 404)
    if not user.has_va_form_access(submission.va_form_id, "reviewer"):
        raise ReviewerCodingError("Reviewer access is required.", 403)
    if submission.va_narration_language not in user.vacode_language:
        raise ReviewerCodingError(
            f"Your profile does not support reviewing forms in {submission.va_narration_language}.",
            403,
        )
    current_state = get_submission_workflow_state(va_sid)
    if current_state != WORKFLOW_REVIEWER_ELIGIBLE:
        raise ReviewerCodingError(
            "Only reviewer-eligible submissions can start reviewer coding."
        )
    if get_latest_active_reviewer_final_assessment(va_sid):
        raise ReviewerCodingError(
            "A reviewer final COD already exists for this submission."
        )

    active_sid = get_active_reviewing_allocation(user.user_id)
    if active_sid:
        if active_sid != va_sid:
            raise ReviewerCodingError(
                "You already have an active reviewer allocation.", 409
            )
        return ReviewerCodingResult(va_sid=va_sid, actiontype="varesumereviewing")

    # A retired submission never enters a new reviewer allocation; an existing
    # active allocation above still resumes.
    # See docs/policy/odk-retired-submissions.md.
    if is_submission_retired(va_sid):
        raise ReviewerCodingError(RETIRED_MESSAGE, 409)

    allocation_id = uuid.uuid4()
    db.session.add(
        VaAllocations(
            va_allocation_id=allocation_id,
            va_sid=va_sid,
            va_allocated_to=user.user_id,
            va_allocation_for=VaAllocation.reviewing,
        )
    )
    db.session.add(
        VaSubmissionsAuditlog(
            va_sid=va_sid,
            va_audit_byrole="reviewer",
            va_audit_by=user.user_id,
            va_audit_operation="c",
            va_audit_action="form allocated to reviewer for coding",
            va_audit_entityid=allocation_id,
        )
    )
    mark_reviewer_coding_started(
        va_sid,
        reason="reviewer_allocation_created",
        actor=reviewer_actor(user.user_id),
    )
    db.session.commit()
    return ReviewerCodingResult(va_sid=va_sid, actiontype="vastartreviewing")


def submit_reviewer_final_cod(
    user,
    va_sid: str,
    *,
    conclusive_cod: str,
    remark: str | None = None,
    immediate_cod: str | None = None,
    other_conditions: str | None = None,
    doris_certificate: dict | None = None,
    doris_result: dict | None = None,
    codedit_result: dict | None = None,
    doris_process_token: str | None = None,
    doris_result_digest: str | None = None,
    doris_client_revision: int = 0,
) -> VaReviewerFinalAssessments:
    from app.services.coding_service import get_project_for_submission

    # Reviewer final replacement is a single-writer operation per
    # submission.  Lock the existing row before checking the allocation and
    # active final so concurrent requests cannot both pass the check-then-
    # insert window.
    submission = db.session.scalar(
        sa.select(VaSubmissions)
        .where(VaSubmissions.va_sid == va_sid)
        .with_for_update()
    )
    if not submission:
        raise ReviewerCodingError("Submission not found.", 404)
    if not user.has_va_form_access(submission.va_form_id, "reviewer"):
        raise ReviewerCodingError("Reviewer access is required.", 403)
    current_state = get_submission_workflow_state(va_sid)
    if current_state != WORKFLOW_REVIEWER_CODING_IN_PROGRESS:
        raise ReviewerCodingError(
            "Reviewer final COD can only be submitted from reviewer_coding_in_progress."
        )
    try:
        validate_coding_value_for_submission(va_sid, conclusive_cod)
    except (LookupError, ValueError) as exc:
        raise ReviewerCodingError(str(exc), 400) from exc

    active_allocation = db.session.scalar(
        sa.select(VaAllocations).where(
            VaAllocations.va_sid == va_sid,
            VaAllocations.va_allocated_to == user.user_id,
            VaAllocations.va_allocation_for == VaAllocation.reviewing,
            VaAllocations.va_allocation_status == VaStatuses.active,
        )
    )
    if not active_allocation:
        raise ReviewerCodingError(
            "An active reviewer allocation is required to submit reviewer final COD."
        )

    project = get_project_for_submission(va_sid)
    if project is None:
        raise ReviewerCodingError("Project not found.", 404)
    project_mode = _project_mode(project)

    reviewer_initial = get_latest_active_reviewer_initial_assessment(
        va_sid,
        user.user_id,
    )
    if project_mode == "masked_simple" and not reviewer_initial:
        raise ReviewerCodingError(
            "Reviewer initial COD assessment must be completed before submitting reviewer final COD.",
            400,
        )

    immediate_provenance = None
    verified_certificate = None
    verified_doris = None
    verified_codedit = None
    who_image_digest = str(
        current_app.config.get("DORIS_WHO_IMAGE_DIGEST") or ""
    ).strip()
    if project_mode == "unmasked_simple":
        if not immediate_cod:
            raise ReviewerCodingError("immediate_cod is required.", 400)
        try:
            validate_coding_value_for_submission(va_sid, immediate_cod)
            immediate_provenance = build_icd11_provenance_for_values(
                va_sid, {"immediate": immediate_cod}
            )
        except (LookupError, ValueError) as exc:
            raise ReviewerCodingError(str(exc), 400) from exc
    elif project_mode == "unmasked_doris":
        if not who_image_digest:
            raise ReviewerCodingError(
                "The pinned WHO processing image is not configured.", 503
            )
        try:
            verified = verify_process_submission(
                doris_process_token or "",
                certificate=doris_certificate,
                doris_result=doris_result,
                codedit_result=codedit_result,
                submitted_result_digest=doris_result_digest or "",
                va_sid=va_sid,
                role="reviewer",
                user_id=user.user_id,
                allocation_id=active_allocation.va_allocation_id,
                payload_version_id=submission.active_payload_version_id,
                icd_release=DEFAULT_ICD11_RELEASE,
                who_image_digest=who_image_digest,
            )
        except ProcessProofCertificateChanged:
            try:
                processing = process_certificate(
                    {
                        "schema_version": 1,
                        "client_revision": doris_client_revision,
                        "certificate": doris_certificate,
                    },
                    release=DEFAULT_ICD11_RELEASE,
                    who_image_digest=who_image_digest,
                )
            except (DorisCertificateError, TypeError, ValueError) as exc:
                raise ReviewerCodingError(str(exc), 422) from exc
            except WhoIcdApiUnavailable as exc:
                raise ReviewerCodingError("WHO ICD-11 service unavailable.", 503) from exc
            processing["process_token"] = generate_process_proof(
                certificate_digest=processing["certificate_digest"],
                result_digest=processing["result_digest"],
                va_sid=va_sid,
                role="reviewer",
                user_id=user.user_id,
                allocation_id=active_allocation.va_allocation_id,
                payload_version_id=submission.active_payload_version_id,
                icd_release=DEFAULT_ICD11_RELEASE,
                who_image_digest=who_image_digest,
            )
            raise ReviewerCodingError(
                "DORIS form changed; reprocessed. Review the result and confirm your final UCOD again.",
                409,
                code="DORIS_CERTIFICATE_CHANGED",
                processing=processing,
            )
        except ProcessProofResultMismatch as exc:
            raise ReviewerCodingError(
                "DORIS processor results changed. Process the form again.",
                409,
                code="DORIS_PROCESS_MISMATCH",
            ) from exc
        except (ProcessProofExpired, ProcessProofInvalid, ProcessProofContextMismatch) as exc:
            raise ReviewerCodingError(
                "DORIS processing confirmation expired or no longer matches this case. Process the form again.",
                409,
                code="DORIS_PROCESS_EXPIRED",
            ) from exc
        except (DorisCertificateError, ValueError) as exc:
            raise ReviewerCodingError(str(exc), 422) from exc
        verified_certificate = verified["certificate"]
        verified_doris = verified["doris"]
        verified_codedit = verified["codedit"]

    try:
        final_provenance = build_icd11_provenance_for_values(
            va_sid, {"conclusive": conclusive_cod}
        )
    except (LookupError, ValueError) as exc:
        raise ReviewerCodingError(str(exc), 400) from exc

    if _reviewer_social_autopsy_required(va_sid, submission):
        social_autopsy_analysis = get_current_payload_social_autopsy_analysis(
            va_sid,
            user.user_id,
        )
        if not social_autopsy_analysis:
            raise ReviewerCodingError(
                "Social Autopsy Analysis must be completed before submitting the reviewer final COD.",
                400,
            )

    active_payload_version_id = submission.active_payload_version_id
    prior_active_reviewer_finals = db.session.scalars(
        sa.select(VaReviewerFinalAssessments).where(
            VaReviewerFinalAssessments.va_sid == va_sid,
            VaReviewerFinalAssessments.payload_version_id == active_payload_version_id,
            VaReviewerFinalAssessments.va_rfinassess_status == VaStatuses.active,
        )
    ).all()
    for existing in prior_active_reviewer_finals:
        existing.va_rfinassess_status = VaStatuses.deactive
        db.session.add(
            VaSubmissionsAuditlog(
                va_sid=va_sid,
                va_audit_byrole="reviewer",
                va_audit_by=user.user_id,
                va_audit_operation="d",
                va_audit_action="deactivated superseded reviewer final cod",
                va_audit_entityid=existing.va_rfinassess_id,
            )
        )

    supersedes_coder_final = db.session.scalar(
        sa.select(VaFinalAssessments)
        .where(
            VaFinalAssessments.va_sid == va_sid,
            VaFinalAssessments.payload_version_id == active_payload_version_id,
            VaFinalAssessments.va_finassess_status == VaStatuses.active,
        )
        .order_by(VaFinalAssessments.va_finassess_createdat.desc())
    )
    try:
        reviewer_final = create_reviewer_final_assessment(
            va_sid=va_sid,
            reviewer_user_id=user.user_id,
            conclusive_cod=conclusive_cod,
            remark=remark,
            supersedes_coder_final_assessment=supersedes_coder_final,
            source_reviewer_initial_assessment=(
                reviewer_initial if project_mode == "masked_simple" else None
            ),
            immediate_cod=immediate_cod if project_mode == "unmasked_simple" else None,
            immediate_icd11_provenance=immediate_provenance,
            other_conditions=other_conditions if project_mode == "unmasked_simple" else None,
            doris_certificate=verified_certificate,
            doris_result=verified_doris,
            codedit_result=verified_codedit,
            cod_entry_mode_snapshot=_mode_snapshot(project, who_image_digest),
            icd11_provenance=final_provenance,
        )
    except (LookupError, ValueError) as exc:
        raise ReviewerCodingError(str(exc), 400) from exc
    db.session.add(
        VaSubmissionsAuditlog(
            va_sid=va_sid,
            va_audit_byrole="reviewer",
            va_audit_by=user.user_id,
            va_audit_operation="c",
            va_audit_action="reviewer final cod submitted",
            va_audit_entityid=reviewer_final.va_rfinassess_id,
        )
    )

    active_allocation.va_allocation_status = VaStatuses.deactive
    db.session.add(
        VaSubmissionsAuditlog(
            va_sid=va_sid,
            va_audit_byrole="reviewer",
            va_audit_by=user.user_id,
            va_audit_operation="d",
            va_audit_action="allocated form released from reviewer",
            va_audit_entityid=active_allocation.va_allocation_id,
        )
    )
    mark_reviewer_finalized(
        va_sid,
        reason="reviewer_final_cod_submitted",
        actor=reviewer_actor(user.user_id),
    )
    upsert_reviewer_final_cod_authority(
        va_sid,
        reviewer_final,
        reason="reviewer_final_cod_submitted",
        updated_by=user.user_id,
    )
    db.session.commit()
    return reviewer_final


def submit_reviewer_initial_cod(
    user,
    va_sid: str,
    *,
    immediate_cod: str,
    antecedent_cod: str,
    other_conditions: str | None = None,
) -> VaReviewerInitialAssessments:
    from app.services.coding_service import get_project_for_submission

    submission = db.session.get(VaSubmissions, va_sid)
    if not submission:
        raise ReviewerCodingError("Submission not found.", 404)
    if not user.has_va_form_access(submission.va_form_id, "reviewer"):
        raise ReviewerCodingError("Reviewer access is required.", 403)
    project = get_project_for_submission(va_sid)
    if project is None:
        raise ReviewerCodingError("Project not found.", 404)
    if _project_mode(project) != "masked_simple":
        raise ReviewerCodingError(
            "This project uses one final COD assessment; reviewer Step 1 is not available.",
            409,
        )
    current_state = get_submission_workflow_state(va_sid)
    if current_state != WORKFLOW_REVIEWER_CODING_IN_PROGRESS:
        raise ReviewerCodingError(
            "Reviewer initial COD can only be submitted from reviewer_coding_in_progress."
        )
    active_allocation = db.session.scalar(
        sa.select(VaAllocations).where(
            VaAllocations.va_sid == va_sid,
            VaAllocations.va_allocated_to == user.user_id,
            VaAllocations.va_allocation_for == VaAllocation.reviewing,
            VaAllocations.va_allocation_status == VaStatuses.active,
        )
    )
    if not active_allocation:
        raise ReviewerCodingError(
            "An active reviewer allocation is required to submit reviewer initial COD."
        )

    classifications = set()
    for coding_value in (immediate_cod, antecedent_cod):
        try:
            classifications.add(
                validate_coding_value_for_submission(va_sid, coding_value)
            )
        except (LookupError, ValueError) as exc:
            raise ReviewerCodingError(str(exc), 400) from exc
    # One classification per save, even in a selectable project.
    if len(classifications) > 1:
        raise ReviewerCodingError(
            "Immediate and antecedent causes must both be ICD-10 or both be ICD-11.",
            400,
        )

    try:
        reviewer_initial = create_reviewer_initial_assessment(
            va_sid=va_sid,
            reviewer_user_id=user.user_id,
            immediate_cod=immediate_cod,
            antecedent_cod=antecedent_cod,
            other_conditions=other_conditions,
        )
    except (LookupError, ValueError) as exc:
        raise ReviewerCodingError(str(exc), 400) from exc
    db.session.add(
        VaSubmissionsAuditlog(
            va_sid=va_sid,
            va_audit_byrole="reviewer",
            va_audit_by=user.user_id,
            va_audit_operation="c",
            va_audit_action="reviewer initial cod submitted",
            va_audit_entityid=reviewer_initial.va_riniassess_id,
        )
    )
    db.session.commit()
    return reviewer_initial
