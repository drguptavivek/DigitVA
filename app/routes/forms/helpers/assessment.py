"""Assessment and workflow helpers for VA form rendering."""

import sqlalchemy as sa
from flask_login import current_user

from app import db
from app.models import VaInitialAssessments, VaStatuses
from app.services.demo_training import get_demo_expiry_for_submission
from app.services.coding.final_cod_authority import get_authoritative_final_assessment
from app.services.assessments.payload_artifacts import (
    get_current_payload_narrative_assessment,
    get_current_payload_social_autopsy_analysis,
)
from app.services.projects.submission_lookup import (
    get_project_for_submission as _get_project_for_submission,
)


def _demo_expiry_for_actiontype(va_sid: str, va_actiontype: str):
    return get_demo_expiry_for_submission(va_sid, va_actiontype)


def _is_social_autopsy_enabled_for_submission(va_sid: str) -> bool:
    project = _get_project_for_submission(va_sid)
    if project is None:
        return True
    return bool(project.social_autopsy_enabled)


def _get_display_initial_assessment(va_sid: str):
    initial_assessment = db.session.scalar(
        sa.select(VaInitialAssessments).where(
            (VaInitialAssessments.va_iniassess_status == VaStatuses.active)
            & (VaInitialAssessments.va_sid == va_sid)
        )
    )
    if initial_assessment is not None:
        return initial_assessment

    authoritative_coder_final = get_authoritative_final_assessment(va_sid)
    if (
        authoritative_coder_final is None
        or authoritative_coder_final.source_initial_assessment_id is None
    ):
        return None

    return db.session.get(
        VaInitialAssessments,
        authoritative_coder_final.source_initial_assessment_id,
    )


def _data_manager_reason_label(reason_code: str) -> str:
    label_map = {
        "submission_incomplete": "Submission information is incomplete or unusable.",
        "source_data_mismatch": "Submission content does not match the expected deceased or source data.",
        "duplicate_submission": "This appears to be a duplicate submission.",
        "language_unreadable": "Narrative or key data cannot be understood for coding preparation.",
        "others": "Other issue reported by data manager.",
    }
    return label_map.get(reason_code, reason_code)


def _get_required_completion_block(
    va_sid: str,
    va_partial: str,
    va_action: str,
    va_actiontype: str,
):
    if va_action != "vacode":
        return None
    if va_actiontype not in {
        "vastartcoding",
        "vapickcoding",
        "varesumecoding",
        "vademo_start_coding",
    }:
        return None

    if va_partial == "social_autopsy" and _is_social_autopsy_enabled_for_submission(
        va_sid
    ):
        analysis = get_current_payload_social_autopsy_analysis(
            va_sid,
            current_user.user_id,
        )
        if not analysis:
            return "Save the Social Autopsy Analysis before proceeding to the next category."

    if va_partial == "vanarrationanddocuments":
        project = _get_project_for_submission(va_sid)
        if project and project.narrative_qa_enabled:
            nqa = get_current_payload_narrative_assessment(
                va_sid,
                current_user.user_id,
            )
            if not nqa:
                return "Complete the Narrative Quality Assessment before proceeding."

    return None
