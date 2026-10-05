"""Coder COD writes: Step 1, the final COD and Not Codeable.

One source of truth for the web partials (``va_form.renderpartial``) and the
``/api/v1/coding/initial|finalize|not-codeable`` routes. Mirrors
``reviewer_coding_service``. Each function authorizes (CODE, or RECODE for a
recode, plus the caller's active coding allocation on the submission), checks
the workflow state, validates, writes and commits. A refusal raises
``CoderCodingError`` (HTTP status, stable ``code``, optional blocking
``messages``) before anything is written.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

import sqlalchemy as sa
from flask import current_app

from app import db
from app.models import (
    VaAllocation,
    VaAllocations,
    VaCoderReview,
    VaFinalAssessments,
    VaInitialAssessments,
    VaSmartvaResults,
    VaStatuses,
    VaSubmissions,
    VaSubmissionsAuditlog,
)
from app.services import coding_search_telemetry_service
from app.services.authz import Action, Reason, can, codes_as_tester
from app.services.cod_entry_mode import (
    cod_entry_mode_snapshot,
    final_ucod_source,
    is_masked,
    part1_line1_cod,
    project_mode,
    smartva_icd11_alternatives,
)
from app.services.coder_dashboard_service import bust_coder_dashboard_cache
from app.services.coding_allocation_service import return_tester_coding_to_pool
from app.services.coding_service import get_project_for_submission
from app.services.demo_project_service import (
    get_demo_expiry_for_submission,
    is_demo_training_submission,
    should_use_demo_actiontype_for_submission,
)
from app.services.doris_prefill import doris_prefill_record
from app.services.final_cod_authority_service import (
    complete_recode_episode,
    get_active_recode_episode,
    get_authoritative_final_assessment,
    upsert_final_cod_authority,
)
from app.services.icd_coding_value import (
    build_icd11_provenance_for_values,
    validate_coding_value_for_submission,
)
from app.services.odk_review_service import sync_not_codeable_review_state
from app.services.payload_bound_coding_artifact_service import (
    get_current_payload_narrative_assessment,
    get_current_payload_social_autopsy_analysis,
)
from app.services.reviewer_coding_service import (
    ReviewerCodingError,
    verify_doris_submission,
)
from app.services.submission_payload_version_service import get_active_payload_version
from app.services.workflow.definition import (
    WORKFLOW_CODER_STEP1_SAVED,
    WORKFLOW_CODING_IN_PROGRESS,
)
from app.services.workflow.state_store import get_submission_workflow_state
from app.services.workflow.transitions import (
    WorkflowTransitionError,
    coder_actor,
    mark_coder_finalized,
    mark_coder_not_codeable,
    mark_coder_step1_saved,
    mark_recode_finalized,
    mark_reviewer_eligible_after_recode_window,
    system_actor,
)

log = logging.getLogger(__name__)

DEMO_ACTIONTYPE = "vademo_start_coding"
RECODE_ACTIONTYPE = "varecode"

# The reasons a coder may give; the web form validates against this tuple.
NOT_CODEABLE_REASONS = (
    "narration_language",
    "narration_doesnt_match",
    "no_info",
    "form_is_empty",
    "others",
)

STEP1_REQUIRED_MESSAGE = "Save Step 1 first."

TESTER_SAVED_MESSAGE = (
    "Test coding saved. It does not count as a result; "
    "the case has returned to the coding pool."
)

_STEP1_STATES = {WORKFLOW_CODING_IN_PROGRESS, WORKFLOW_CODER_STEP1_SAVED}
_DORIS_ENVELOPE_NAMES = (
    "doris_certificate",
    "doris_result",
    "codedit_result",
    "doris_process_token",
    "doris_result_digest",
)
# Codes for DORIS refusals that carry none of their own.
_DORIS_FALLBACK_CODES = {422: "invalid_doris", 503: "who_unavailable"}

# Other significant conditions offered on Step 1, by the deceased's age group.
ADULT_OTHER_CONDITIONS = [
    "I10 - Essential Hypertension",
    "E11 - Type 2 Diabetes Mellitus",
    "E10 - Type 1 Diabetes Mellitus",
    "E66 - Obesity",
    "N18 - Chronic Kidney Disease",
    "K74 - Chronic Liver Disease",
    "J44 - Chronic Obstructive Pulmonary Disease",
    "J45 - Asthma",
    "E78 - Dyslipidemia",
    "I50 - Congestive Heart Failure",
    "I25 - Coronary Artery Disease",
    "D64 - Chronic Anaemia",
    "F03 - Dementia",
    "I25.2 - Previous Myocardial Infarction",
    "I69 - Previous Stroke/CVA",
    "C80 - Cancer (non-primary, metastasis, history)",
    "B24 - HIV/AIDS",
    "Z86.1 - Past history of tuberculosis",
    "D89 - Immunosuppression",
    "E03 - Hypothyroidism",
    "E05 - Hyperthyroidism",
    "B18 - Chronic Viral Infections (Hepatitis)",
    "I73.9 - Peripheral Vascular Disease",
    "I09 - Chronic Rheumatic Heart Disease",
    "Z98.8 - History of Major Surgery",
    "Z79.3 - Long-term use of Immunosuppressants",
]

NEONATE_OTHER_CONDITIONS = [
    "P07 - Preterm birth",
    "P07.0, P07.1 - Low Birth Weight",
    "P05 - Intrauterine Growth Restriction",
    "P21 - Birth Asphyxia",
    "P36 - Neonatal Sepsis",
    "P23 - Neonatal Pneumonia",
    "P22 - Hyaline Membrane Disease / Respiratory Distress Syndrome",
    "P24.0 - Meconium Aspiration Syndrome",
    "P59 - Neonatal Jaundice",
    "P90 - Neonatal Convulsions",
    "P91.6 - Hypoxic Ischemic Encephalopathy",
    "P80 - Hypothermia of Newborn",
    "P70.4 - Hypoglycemia of Newborn",
    "P52 - Neonatal Hemorrhage",
    "Q20 - Q28 - Congenital Heart Disease",
    "Q00 - Q99 - Congenital Malformations",
    "Q90 - Chromosomal Abnormalities",
    "A33 - Neonatal Tetanus",
    "P37.9 - Neonatal Meningitis",
    "P77 - Necrotizing Enterocolitis",
    "P00.1 - Maternal Diabetes",
    "P00.0 - Maternal Hypertension",
    "P02.7 - Chorioamnionitis",
    "P01.5 - Twin/Multiple Gestation",
    "P35, P37 - Congenital Infections (TORCH)",
    "P58, P59 - Hyperbilirubinemia",
    "P92 - Feeding Problems of Newborn",
    "P04 - Maternal drug use affecting newborn",
]

CHILD_OTHER_CONDITIONS = [
    "J06, J20, J21 - Acute Respiratory Infections",
    "J45 - Asthma",
    "D50 - D53 - Anemia",
    "E40 - E46 - Malnutrition",
    "E66 - Obesity",
    "E10, E11 - Diabetes Mellitus (Type 1/2)",
    "G40 - Epilepsy",
    "Q20 - Q28 - Congenital Heart Disease",
    "D57 - Sickle Cell Disease",
    "D56 - Thalassemia",
    "Q90 - Down Syndrome",
    "E84 - Cystic Fibrosis",
    "N18, N04 - Renal Disease",
    "A15 - A19 - Tuberculosis",
    "B20 - B24 - HIV/AIDS",
    "D80 - D89 - Immunodeficiency",
    "I05 - I09 - Rheumatic Heart Disease",
    "G80 - Cerebral Palsy",
    "F84 - Autism Spectrum Disorders",
    "F70 - F79 - Intellectual Disability",
    "C91 - C95, C81 - C85, C00 - C80 - Cancer",
    "D57.3 - Sickle Cell Trait",
    "D56.3 - Thalassemia Trait",
    "Z98.8 - Previous Major Surgery",
    "P07 - History of Prematurity/Low Birth Weight",
    "Z28.3 - Incomplete immunization Status",
]


def other_conditions_choices(payload_data) -> list[str]:
    """The Step 1 other-conditions list for the interview's age group.

    The payload flags ``isNeonatal``, ``isChild`` and ``isAdult`` are "1" for
    the deceased's group; no flag means the adult list.
    """
    payload = payload_data or {}
    for flag, choices in (
        ("isNeonatal", NEONATE_OTHER_CONDITIONS),
        ("isChild", CHILD_OTHER_CONDITIONS),
        ("isAdult", ADULT_OTHER_CONDITIONS),
    ):
        if str(payload.get(flag)).strip() in ("1", "1.0"):
            return choices
    return ADULT_OTHER_CONDITIONS


class CoderCodingError(Exception):
    """A coder write was refused.

    ``code`` is the stable machine code. ``messages`` lists every blocking
    message when several apply (``final_blocked``, ``invalid_cod``);
    ``fields`` names the Step 1 field (``immediate_cod`` or
    ``antecedent_cod``) each ``invalid_cod`` message belongs to.
    ``processing`` carries the reprocessed DORIS result of a changed
    certificate.
    """

    def __init__(
        self,
        message: str,
        status_code: int = 403,
        *,
        code: str,
        processing: dict | None = None,
        messages: list[str] | None = None,
        fields: list[str] | None = None,
    ):
        self.message = message
        self.status_code = status_code
        self.code = code
        self.processing = processing
        self.messages = messages or [message]
        self.fields = fields or []
        super().__init__(message)


@dataclass(frozen=True)
class CoderInitialResult:
    assessment: VaInitialAssessments
    resaved: bool  # Step 1 was already saved before this save


@dataclass(frozen=True)
class CoderFinalResult:
    assessment: VaFinalAssessments
    tester: bool  # coding_tester output: stored deactive, the case returned to the pool


@dataclass(frozen=True)
class CoderNotCodeableResult:
    tester: bool
    odk_synced: bool
    odk_error: str | None


def derive_actiontype(va_sid: str) -> str:
    """The web's ``actiontype`` for a client that sends none (the JSON API).

    Demo practice (``vademo_start_coding``) stamps the saved rows with an
    expiry; a case in a recode episode is coded as RECODE.
    """
    if should_use_demo_actiontype_for_submission(va_sid):
        return DEMO_ACTIONTYPE
    return RECODE_ACTIONTYPE if get_active_recode_episode(va_sid) else ""


def _require_coding_write(user, va_sid: str, actiontype: str) -> VaAllocations:
    """The caller's active coding allocation, once authz allows the write.

    CODE, or RECODE for ``varecode``; an admin's demo session is its own path
    (no grant), as in ``va_form._require_partial_write``. A missing
    allocation is refused: tester and coder alike must hold the case.
    """
    if not (actiontype == DEMO_ACTIONTYPE and user.is_admin()):
        action = Action.RECODE if actiontype == RECODE_ACTIONTYPE else Action.CODE
        decision = can(user, action, va_sid)
        if not decision:
            if decision.reason is Reason.NOT_FOUND:
                raise CoderCodingError(decision.message, 404, code="not_found")
            raise CoderCodingError(decision.message, 403, code="forbidden")
    allocation = db.session.scalar(
        sa.select(VaAllocations).where(
            VaAllocations.va_sid == va_sid,
            VaAllocations.va_allocated_to == user.user_id,
            VaAllocations.va_allocation_for == VaAllocation.coding,
            VaAllocations.va_allocation_status == VaStatuses.active,
        )
    )
    if allocation is None:
        raise CoderCodingError(
            "You do not have an active coding allocation for this submission.",
            403,
            code="no_allocation",
        )
    return allocation


def _is_tester_coding(user, va_sid: str, actiontype: str) -> bool:
    """True when this save is coding_tester output (digitva-ggc3).

    Demo saves (an expiry) keep the demo path; otherwise authz decides: only
    the tester lane reaches the case. Tester output is stored deactive with
    ``is_tester`` and the case returns to the coding pool.
    """
    if get_demo_expiry_for_submission(va_sid, actiontype) is not None:
        return False
    return codes_as_tester(user, va_sid)


def _who_image_digest() -> str:
    digest = str(current_app.config.get("DORIS_WHO_IMAGE_DIGEST") or "").strip()
    if not digest:
        raise CoderCodingError(
            "The pinned WHO processing image is not configured.",
            503,
            code="who_not_configured",
        )
    return digest


def _verify_doris(
    user,
    va_sid,
    allocation,
    payload_version,
    who_image_digest,
    *,
    certificate,
    doris_result,
    codedit_result,
    doris_process_token,
    doris_result_digest,
    doris_client_revision,
    doris_input_error,
) -> dict:
    """The server-normalized DORIS envelopes, or a ``CoderCodingError``.

    A changed certificate is reprocessed and refused as a 409 carrying a
    fresh proof (nothing is saved). *doris_input_error* is the caller's
    note that an envelope was not valid JSON: a 422 here, where the proof
    would have been checked.
    """
    if doris_input_error:
        raise CoderCodingError(doris_input_error, 422, code="invalid_doris")
    try:
        return verify_doris_submission(
            user,
            va_sid,
            allocation.va_allocation_id,
            payload_version.payload_version_id,
            who_image_digest,
            certificate=certificate,
            doris_result=doris_result,
            codedit_result=codedit_result,
            process_token=doris_process_token,
            result_digest=doris_result_digest,
            client_revision=doris_client_revision,
            role="coder",
        )
    except ReviewerCodingError as exc:
        raise CoderCodingError(
            exc.message,
            exc.status_code,
            code=exc.code or _DORIS_FALLBACK_CODES.get(exc.status_code, "invalid_doris"),
            processing=exc.processing,
        ) from exc


def _load_project(va_sid: str):
    project = get_project_for_submission(va_sid)
    if project is None:
        raise CoderCodingError("Project not found.", 404, code="not_found")
    return project


def submit_coder_initial_cod(
    user,
    va_sid: str,
    *,
    immediate_cod: str | None = None,
    antecedent_cod: str,
    other_conditions: list[str] | None = None,
    doris_certificate: dict | None = None,
    doris_result: dict | None = None,
    codedit_result: dict | None = None,
    doris_process_token: str | None = None,
    doris_result_digest: str | None = None,
    doris_client_revision: int | str = 0,
    doris_input_error: str | None = None,
    actiontype: str | None = None,
    payload_data: dict | None = None,
) -> CoderInitialResult:
    """Save the coder's masked Step 1 and move the case to coder_step1_saved.

    Masked simple takes the immediate and antecedent causes as typed, both
    validated, one classification per save; *other_conditions* (a list) must
    come from the age group's list (``other_conditions_choices``, built from
    *payload_data* when the caller has it loaded). Masked DORIS takes the
    coder's own processed certificate: the proof is verified (or the
    certificate reprocessed), the immediate cause is Part I line 1 and the
    antecedent is the coder's confirmed underlying cause. An earlier active
    Step 1 of the coder is superseded. Raises ``CoderCodingError``: 404/403
    authz or no allocation, 409 ``not_masked`` / ``wrong_state`` /
    ``no_payload``, 400 ``invalid_request`` / ``invalid_cod`` (every message
    in ``messages``, each with its ``fields``) / ``invalid_other_conditions``,
    the DORIS codes of ``verify_doris_submission``.
    """
    actiontype = derive_actiontype(va_sid) if actiontype is None else actiontype
    if db.session.get(VaSubmissions, va_sid) is None:
        raise CoderCodingError("Submission not found.", 404, code="not_found")
    allocation = _require_coding_write(user, va_sid, actiontype)
    project = _load_project(va_sid)
    mode = project_mode(project)
    if not is_masked(mode):
        raise CoderCodingError(
            "This project uses one final COD assessment; Step 1 is not available.",
            409,
            code="not_masked",
        )
    current_state = get_submission_workflow_state(va_sid)
    if current_state not in _STEP1_STATES:
        raise CoderCodingError(
            "This submission is not open for Step 1.", 409, code="wrong_state"
        )

    if mode == "masked_doris":
        step1_fields = _masked_doris_step1_fields(
            user, va_sid, project, allocation, antecedent_cod,
            certificate=doris_certificate,
            doris_result=doris_result,
            codedit_result=codedit_result,
            doris_process_token=doris_process_token,
            doris_result_digest=doris_result_digest,
            doris_client_revision=doris_client_revision,
            doris_input_error=doris_input_error,
        )
    else:
        step1_fields = _masked_simple_step1_fields(
            va_sid, immediate_cod, antecedent_cod, other_conditions, payload_data
        )

    for existing_initial in db.session.scalars(
        sa.select(VaInitialAssessments).where(
            VaInitialAssessments.va_sid == va_sid,
            VaInitialAssessments.va_iniassess_by == user.user_id,
            VaInitialAssessments.va_iniassess_status == VaStatuses.active,
        )
    ).all():
        existing_initial.va_iniassess_status = VaStatuses.deactive
        db.session.add(
            VaSubmissionsAuditlog(
                va_sid=va_sid,
                va_audit_byrole="vacoder",
                va_audit_by=user.user_id,
                va_audit_operation="d",
                va_audit_action="superseded initial cod draft",
                va_audit_entityid=existing_initial.va_iniassess_id,
            )
        )
    gen_uuid = uuid.uuid4()
    new_initial = VaInitialAssessments(
        va_iniassess_id=gen_uuid,
        va_sid=va_sid,
        va_iniassess_by=user.user_id,
        is_tester=_is_tester_coding(user, va_sid, actiontype),
        **step1_fields,
    )
    db.session.add(new_initial)
    db.session.add(
        VaSubmissionsAuditlog(
            va_sid=va_sid,
            va_audit_byrole="vacoder",
            va_audit_by=user.user_id,
            va_audit_operation="c",
            va_audit_action="initial cod submitted",
            va_audit_entityid=gen_uuid,
        )
    )
    resaved = current_state == WORKFLOW_CODER_STEP1_SAVED
    try:
        mark_coder_step1_saved(
            va_sid,
            reason="initial_cod_updated" if resaved else "initial_cod_submitted",
            actor=coder_actor(user.user_id),
        )
    except WorkflowTransitionError as exc:
        log.warning(
            "coder_step1_saved blocked | sid=%s | current_state=%r | coder_user_id=%s",
            va_sid,
            current_state,
            user.user_id,
        )
        db.session.rollback()
        raise CoderCodingError(
            "This submission is not open for Step 1.", 409, code="wrong_state"
        ) from exc
    db.session.commit()
    return CoderInitialResult(assessment=new_initial, resaved=resaved)


def _masked_doris_step1_fields(
    user, va_sid, project, allocation, underlying_cod, *,
    certificate, doris_result, codedit_result,
    doris_process_token, doris_result_digest, doris_client_revision,
    doris_input_error,
) -> dict:
    """Verified Step 1 columns for a masked DORIS coder save.

    The immediate COD is the first condition on Part I line 1 of the verified
    certificate; the underlying (``va_antecedent_cod``) is the coder's own
    confirmed cause (owner decision 1). A missing cause or line is a 400.
    """
    who_image_digest = _who_image_digest()
    underlying_cod = (underlying_cod or "").strip()
    if not underlying_cod:
        raise CoderCodingError(
            "Confirm the underlying cause of death: use the DORIS result or search for your own code.",
            400,
            code="invalid_request",
        )
    active_payload_version = get_active_payload_version(va_sid)
    if active_payload_version is None:
        raise CoderCodingError(
            "An active coder allocation and submission payload are required to save Step 1.",
            409,
            code="no_payload",
        )
    verified = _verify_doris(
        user, va_sid, allocation, active_payload_version, who_image_digest,
        certificate=certificate,
        doris_result=doris_result,
        codedit_result=codedit_result,
        doris_process_token=doris_process_token,
        doris_result_digest=doris_result_digest,
        doris_client_revision=doris_client_revision,
        doris_input_error=doris_input_error,
    )
    immediate_cod = part1_line1_cod(verified["certificate"])
    if not immediate_cod:
        raise CoderCodingError(
            "Part I line 1 needs a condition: it is the immediate cause of death.",
            400,
            code="invalid_request",
        )
    try:
        validate_coding_value_for_submission(va_sid, underlying_cod)
        # The immediate cause was checked against WHO when the certificate
        # was processed; only the coder's own pick needs catalogue provenance.
        provenance = build_icd11_provenance_for_values(
            va_sid, {"antecedent": underlying_cod}
        )
    except (LookupError, ValueError) as exc:
        raise CoderCodingError(str(exc), 400, code="invalid_cod") from exc
    return {
        "va_immediate_cod": immediate_cod,
        "va_antecedent_cod": underlying_cod,
        "icd11_provenance": provenance,
        "va_other_conditions": None,
        "doris_certificate": verified["certificate"],
        "doris_result": verified["doris"],
        "codedit_result": verified["codedit"],
        "cod_entry_mode_snapshot": {
            **cod_entry_mode_snapshot(project, who_image_digest),
            "doris_prefill": doris_prefill_record(
                active_payload_version.payload_data, verified["certificate"]
            ),
        },
    }


def _masked_simple_step1_fields(
    va_sid, immediate_cod, antecedent_cod, other_conditions, payload_data
) -> dict:
    immediate_cod = (immediate_cod or "").strip()
    antecedent_cod = (antecedent_cod or "").strip()
    if not immediate_cod or not antecedent_cod:
        raise CoderCodingError(
            "immediate_cod and antecedent_cod are required.", 400, code="invalid_request"
        )
    errors: list[tuple[str, str]] = []
    classifications = set()
    for field, value in (("immediate_cod", immediate_cod), ("antecedent_cod", antecedent_cod)):
        try:
            classifications.add(validate_coding_value_for_submission(va_sid, value))
        except (LookupError, ValueError) as exc:
            errors.append((field, str(exc)))
    # One classification per save.
    if not errors and len(classifications) > 1:
        errors.append(
            (
                "antecedent_cod",
                "Immediate and antecedent causes must both be ICD-10 or both be ICD-11.",
            )
        )
    provenance = None
    if not errors:
        try:
            provenance = build_icd11_provenance_for_values(
                va_sid, {"immediate": immediate_cod, "antecedent": antecedent_cod}
            )
        except (LookupError, ValueError) as exc:
            errors.append(("immediate_cod", str(exc)))
    if errors:
        raise CoderCodingError(
            errors[0][1],
            400,
            code="invalid_cod",
            messages=[message for _, message in errors],
            fields=[field for field, _ in errors],
        )
    conditions = [c for c in (other_conditions or []) if c]
    if conditions:
        if payload_data is None:
            version = get_active_payload_version(va_sid)
            payload_data = version.payload_data if version else None
        allowed = set(other_conditions_choices(payload_data))
        invalid = [c for c in conditions if c not in allowed]
        if invalid:
            raise CoderCodingError(
                f"Not a valid choice: {invalid[0]}", 400, code="invalid_other_conditions"
            )
    return {
        "va_immediate_cod": immediate_cod,
        "va_antecedent_cod": antecedent_cod,
        "icd11_provenance": provenance,
        "va_other_conditions": " | ".join(conditions) if conditions else None,
    }


def _social_autopsy_required(project, submission, payload_data) -> bool:
    """Whether the coder must save the Social Autopsy analysis before the final."""
    if not project.social_autopsy_enabled:
        return False
    from app.services.category_rendering_service import (
        get_category_rendering_service,
        get_visible_category_codes,
    )
    from app.utils.va_form.va_form_02_formtyperesolution import (
        va_get_form_type_code_for_form,
    )

    return get_category_rendering_service().is_category_enabled(
        va_get_form_type_code_for_form(submission.va_form_id),
        "vacode",
        get_visible_category_codes(payload_data, submission.va_form_id),
        "social_autopsy",
    )


def submit_coder_final_cod(
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
    doris_client_revision: int | str = 0,
    cod_search_id=None,
    cod_chosen_code: str | None = None,
    cod_chosen_rank=None,
    doris_input_error: str | None = None,
    actiontype: str | None = None,
) -> CoderFinalResult:
    """Save the coder's final COD (Step 2, or the one step of an unmasked project).

    Unmasked simple takes the immediate cause (and free-text other
    conditions); unmasked DORIS the coder's verified certificate; masked
    modes link the active Step 1. Coder output supersedes earlier active
    finals, releases the allocation and moves the case to coder_finalized
    (a recode episode completes instead, a demo-training case goes straight to
    reviewer_eligible). A coding_tester's save is stored deactive and the case
    returns to the pool. Raises ``CoderCodingError``: 404/403 authz or no
    allocation, 409 ``wrong_state``, 400 ``invalid_request``
    (DORIS certificate sent to masked Step 2), the DORIS codes, 409
    ``wrong_state`` also for a masked project without the caller's own Step 1
    ("Save Step 1 first."), and 422
    ``final_blocked`` carrying every blocking message (invalid or missing COD,
    no active payload, Narrative QA or Social Autopsy not done).
    """
    actiontype = derive_actiontype(va_sid) if actiontype is None else actiontype
    # Authorize before the row lock: a refused caller never waits on it.
    allocation = _require_coding_write(user, va_sid, actiontype)
    project = _load_project(va_sid)
    mode = project_mode(project)
    # Masked DORIS Step 2 only confirms the underlying cause; the
    # certificate and its envelopes stay on the Step 1 row (decision 4).
    if mode == "masked_doris" and any(
        (doris_certificate, doris_result, codedit_result, doris_process_token, doris_result_digest)
    ):
        raise CoderCodingError(
            "Step 2 confirms the underlying cause only; the DORIS certificate belongs to Step 1.",
            400,
            code="invalid_request",
        )
    # Final assessment replacement is a single-writer operation per
    # submission: lock the submission before reading its allocation and
    # finals so two requests cannot both pass the check-then-insert window.
    submission = db.session.scalar(
        sa.select(VaSubmissions).where(VaSubmissions.va_sid == va_sid).with_for_update()
    )
    if submission is None:
        raise CoderCodingError("Submission not found.", 404, code="not_found")
    active_payload_version = get_active_payload_version(va_sid)
    blocking_messages: list[str] = []
    if active_payload_version is None:
        blocking_messages.append("This submission has no active payload version.")
    conclusive_cod = (conclusive_cod or "").strip()
    try:
        validate_coding_value_for_submission(va_sid, conclusive_cod)
    except (LookupError, ValueError) as exc:
        blocking_messages.append(str(exc))

    immediate_icd11_provenance = None
    verified_certificate = verified_doris = verified_codedit = None
    saved_immediate_cod = None
    saved_other_conditions = None
    who_image_digest = str(current_app.config.get("DORIS_WHO_IMAGE_DIGEST") or "").strip()
    if mode == "unmasked_simple":
        saved_immediate_cod = (immediate_cod or "").strip()
        saved_other_conditions = (other_conditions or "").strip() or None
        if not saved_immediate_cod:
            blocking_messages.append("Immediate cause of death is required.")
        else:
            try:
                validate_coding_value_for_submission(va_sid, saved_immediate_cod)
                immediate_icd11_provenance = build_icd11_provenance_for_values(
                    va_sid, {"immediate": saved_immediate_cod}
                )
            except (LookupError, ValueError) as exc:
                blocking_messages.append(str(exc))
        saved_immediate_cod = saved_immediate_cod or None
    elif mode == "unmasked_doris" and active_payload_version is not None:
        who_image_digest = _who_image_digest()
        verified = _verify_doris(
            user, va_sid, allocation, active_payload_version, who_image_digest,
            certificate=doris_certificate,
            doris_result=doris_result,
            codedit_result=codedit_result,
            doris_process_token=doris_process_token,
            doris_result_digest=doris_result_digest,
            doris_client_revision=doris_client_revision,
            doris_input_error=doris_input_error,
        )
        verified_certificate = verified["certificate"]
        verified_doris = verified["doris"]
        verified_codedit = verified["codedit"]

    if project.narrative_qa_enabled and not get_current_payload_narrative_assessment(
        va_sid, user.user_id
    ):
        blocking_messages.append(
            "Narrative Quality Assessment must be completed before submitting the final COD."
        )
    if _social_autopsy_required(
        project,
        submission,
        active_payload_version.payload_data if active_payload_version else None,
    ) and not get_current_payload_social_autopsy_analysis(va_sid, user.user_id):
        blocking_messages.append(
            "Social Autopsy Analysis must be completed before submitting the final COD."
        )
    final_icd11_provenance = None
    if not blocking_messages:
        try:
            final_icd11_provenance = build_icd11_provenance_for_values(
                va_sid, {"conclusive": conclusive_cod}
            )
        except (LookupError, ValueError) as exc:
            blocking_messages.append(str(exc))
    if blocking_messages:
        raise CoderCodingError(
            blocking_messages[0], 422, code="final_blocked", messages=blocking_messages
        )

    masked_initial = None
    smartva = None
    tester_output = _is_tester_coding(user, va_sid, actiontype)
    if is_masked(mode):
        # The caller's own Step 1 (a coder's never a tester's row), newest first.
        initial_query = (
            sa.select(VaInitialAssessments)
            .where(
                VaInitialAssessments.va_iniassess_status == VaStatuses.active,
                VaInitialAssessments.va_sid == va_sid,
                VaInitialAssessments.va_iniassess_by == user.user_id,
            )
            .order_by(VaInitialAssessments.va_iniassess_createdat.desc())
        )
        if not tester_output:
            initial_query = initial_query.where(VaInitialAssessments.is_tester.is_(False))
        masked_initial = db.session.scalar(initial_query)
        if masked_initial is None:
            raise CoderCodingError(STEP1_REQUIRED_MESSAGE, 409, code="wrong_state")
    if mode == "masked_doris":
        smartva = db.session.scalar(
            sa.select(VaSmartvaResults).where(
                VaSmartvaResults.va_sid == va_sid,
                VaSmartvaResults.va_smartva_status == VaStatuses.active,
            )
        )
    gen_uuid = uuid.uuid4()
    active_recode_episode = get_active_recode_episode(va_sid)
    prior_authoritative_final = get_authoritative_final_assessment(va_sid)
    snapshot = cod_entry_mode_snapshot(project, who_image_digest)
    if verified_certificate is not None:
        # Which fields the interview prefilled and whether the coder changed
        # them, recomputed here rather than trusted (digitva-hln).
        snapshot["doris_prefill"] = doris_prefill_record(
            active_payload_version.payload_data, verified_certificate
        )
    if mode == "masked_doris":
        snapshot["final_ucod_source"] = final_ucod_source(
            conclusive_cod,
            masked_initial.va_antecedent_cod if masked_initial else None,
            smartva_icd11_alternatives(smartva),
        )
    existing_active_finals = db.session.scalars(
        sa.select(VaFinalAssessments).where(
            VaFinalAssessments.va_sid == va_sid,
            VaFinalAssessments.payload_version_id == active_payload_version.payload_version_id,
            VaFinalAssessments.va_finassess_status == VaStatuses.active,
        )
    ).all()
    new_final = VaFinalAssessments(
        va_finassess_id=gen_uuid,
        va_sid=va_sid,
        payload_version_id=active_payload_version.payload_version_id,
        va_finassess_by=user.user_id,
        source_initial_assessment_id=(
            masked_initial.va_iniassess_id if masked_initial else None
        ),
        va_conclusive_cod=conclusive_cod,
        icd11_provenance=final_icd11_provenance,
        va_immediate_cod=saved_immediate_cod,
        immediate_icd11_provenance=immediate_icd11_provenance,
        va_other_conditions=saved_other_conditions,
        doris_certificate=verified_certificate,
        doris_result=verified_doris,
        codedit_result=verified_codedit,
        cod_entry_mode_snapshot=snapshot,
        va_finassess_remark=(remark or "").strip() or None,
        demo_expires_at=get_demo_expiry_for_submission(va_sid, actiontype),
        is_tester=tester_output,
        va_finassess_status=VaStatuses.deactive if tester_output else VaStatuses.active,
    )
    db.session.add(new_final)

    try:
        if tester_output:
            # Tester output never becomes the case's result: no coder final
            # is superseded, the authority and any recode episode stay, and
            # the case returns to the pool (digitva-ggc3).
            db.session.add(
                VaSubmissionsAuditlog(
                    va_sid=va_sid,
                    va_audit_byrole="vacoder",
                    va_audit_by=user.user_id,
                    va_audit_operation="c",
                    va_audit_action="final cod submitted by coding tester (not counted)",
                    va_audit_entityid=gen_uuid,
                )
            )
            db.session.flush()
            return_tester_coding_to_pool(allocation, reason="tester_final_cod_submitted")
            db.session.commit()
            bust_coder_dashboard_cache(user.user_id)
            return CoderFinalResult(assessment=new_final, tester=True)

        for existing_final in existing_active_finals:
            existing_final.va_finassess_status = VaStatuses.deactive
            db.session.add(
                VaSubmissionsAuditlog(
                    va_sid=va_sid,
                    va_audit_byrole="vacoder",
                    va_audit_by=user.user_id,
                    va_audit_operation="d",
                    va_audit_action=(
                        "superseded authoritative final cod"
                        if prior_authoritative_final
                        and existing_final.va_finassess_id
                        == prior_authoritative_final.va_finassess_id
                        else "deactivated superseded final cod"
                    ),
                    va_audit_entityid=existing_final.va_finassess_id,
                )
            )
        db.session.add(
            VaSubmissionsAuditlog(
                va_sid=va_sid,
                va_audit_byrole="vacoder",
                va_audit_by=user.user_id,
                va_audit_operation="c",
                va_audit_action="final cod submitted",
                va_audit_entityid=gen_uuid,
            )
        )
        allocation.va_allocation_status = VaStatuses.deactive
        db.session.add(
            VaSubmissionsAuditlog(
                va_sid=va_sid,
                va_audit_byrole="vacoder",
                va_audit_by=user.user_id,
                va_audit_operation="d",
                va_audit_action="allocated form released from coder",
                va_audit_entityid=allocation.va_allocation_id,
            )
        )
        db.session.flush()
        upsert_final_cod_authority(
            va_sid,
            new_final,
            reason=(
                "replacement_final_cod_submitted"
                if active_recode_episode
                else "final_cod_submitted"
            ),
            source_role="vacoder",
            updated_by=user.user_id,
        )
        if active_recode_episode:
            mark_recode_finalized(
                va_sid,
                reason="replacement_final_cod_submitted",
                actor=coder_actor(user.user_id),
            )
            complete_recode_episode(active_recode_episode, new_final)
        else:
            mark_coder_finalized(
                va_sid, reason="final_cod_submitted", actor=coder_actor(user.user_id)
            )
        # Demo/training projects skip the 24-hour recode window so trainees
        # can practise reviewing at once. Admin-started demo sessions on
        # ordinary projects keep the window.
        if is_demo_training_submission(va_sid):
            mark_reviewer_eligible_after_recode_window(
                va_sid,
                reason="demo_reviewer_eligible_immediately",
                actor=system_actor(),
            )
    except WorkflowTransitionError as exc:
        db.session.rollback()
        raise CoderCodingError(
            "This submission is not open for the final COD.", 409, code="wrong_state"
        ) from exc
    db.session.commit()
    bust_coder_dashboard_cache(user.user_id)
    # The conclusive COD is stored: attach the picked code to the search the
    # browser says produced it (digitva-zpe.3). Runs after the save
    # committed; a telemetry failure cannot unsave the COD.
    coding_search_telemetry_service.record_choice(
        search_id=cod_search_id,
        chosen_code=cod_chosen_code,
        chosen_rank=cod_chosen_rank,
        role=coding_search_telemetry_service.role_label(user),
    )
    return CoderFinalResult(assessment=new_final, tester=False)


def submit_coder_not_codeable(
    user,
    va_sid: str,
    *,
    reason: str,
    other: str | None = None,
    actiontype: str | None = None,
) -> CoderNotCodeableResult:
    """Report the case Not Codeable: release the allocation, exclude the case.

    *reason* is one of ``NOT_CODEABLE_REASONS``; ``others`` needs the *other*
    text. ODK Central is flagged for revision (a failure is reported in the
    result, not raised). A coding_tester's report is tester output: nothing is
    excluded, ODK is not touched and the case returns to the pool. Raises
    ``CoderCodingError``: 404/403 authz or no allocation, 400
    ``invalid_request``, 409 ``wrong_state``.
    """
    actiontype = derive_actiontype(va_sid) if actiontype is None else actiontype
    if db.session.get(VaSubmissions, va_sid) is None:
        raise CoderCodingError("Submission not found.", 404, code="not_found")
    allocation = _require_coding_write(user, va_sid, actiontype)
    if reason not in NOT_CODEABLE_REASONS:
        raise CoderCodingError(
            "Please describe the reason for why the VA form could not be coded.",
            400,
            code="invalid_request",
        )
    other_reason = (other or "").strip() or None
    if reason == "others" and not other_reason:
        raise CoderCodingError(
            "Please specify the other reason for why this VA form could not be coded.",
            400,
            code="invalid_request",
        )
    gen_uuid = uuid.uuid4()
    tester_output = _is_tester_coding(user, va_sid, actiontype)
    new_review = VaCoderReview(
        va_creview_id=gen_uuid,
        va_sid=va_sid,
        va_creview_by=user.user_id,
        va_creview_reason=reason,
        va_creview_other=other_reason,
        is_tester=tester_output,
        va_creview_status=VaStatuses.deactive if tester_output else VaStatuses.active,
    )
    try:
        if tester_output:
            # A tester's report is tester output: the case is not excluded,
            # ODK is not flagged, and it returns to the coding pool
            # (digitva-ggc3).
            db.session.add(new_review)
            db.session.add(
                VaSubmissionsAuditlog(
                    va_sid=va_sid,
                    va_audit_byrole="vacoder",
                    va_audit_by=user.user_id,
                    va_audit_operation="c",
                    va_audit_action="not codeable reported by coding tester (not counted)",
                    va_audit_entityid=gen_uuid,
                )
            )
            return_tester_coding_to_pool(allocation, reason="tester_not_codeable_submitted")
            db.session.commit()
            bust_coder_dashboard_cache(user.user_id)
            return CoderNotCodeableResult(tester=True, odk_synced=False, odk_error=None)

        db.session.add(
            VaSubmissionsAuditlog(
                va_sid=va_sid,
                va_audit_byrole="vacoder",
                va_audit_by=user.user_id,
                va_audit_operation="c",
                va_audit_action="error reported by coder",
                va_audit_entityid=gen_uuid,
            )
        )
        allocation.va_allocation_status = VaStatuses.deactive
        db.session.add(
            VaSubmissionsAuditlog(
                va_sid=va_sid,
                va_audit_byrole="vacoder",
                va_audit_by=user.user_id,
                va_audit_operation="d",
                va_audit_action="allocated form released from coder",
                va_audit_entityid=allocation.va_allocation_id,
            )
        )
        db.session.add(new_review)
        mark_coder_not_codeable(
            va_sid, reason="coder_marked_not_codeable", actor=coder_actor(user.user_id)
        )
    except WorkflowTransitionError as exc:
        db.session.rollback()
        raise CoderCodingError(
            "This submission cannot be reported not codeable now.",
            409,
            code="wrong_state",
        ) from exc
    odk_sync_result = sync_not_codeable_review_state(va_sid, reason, other_reason)
    db.session.add(
        VaSubmissionsAuditlog(
            va_sid=va_sid,
            va_audit_byrole="vacoder",
            va_audit_by=user.user_id,
            va_audit_operation="u",
            va_audit_action=(
                f"odk review state set to {odk_sync_result.review_state}"
                if odk_sync_result.success
                else "odk review state update failed"
            ),
        )
    )
    db.session.commit()
    bust_coder_dashboard_cache(user.user_id)
    return CoderNotCodeableResult(
        tester=False,
        odk_synced=odk_sync_result.success,
        odk_error=None if odk_sync_result.success else odk_sync_result.error_message,
    )
