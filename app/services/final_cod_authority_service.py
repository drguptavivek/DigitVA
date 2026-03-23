"""Final COD authority and recode episode helpers."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

import sqlalchemy as sa

from app import db
from app.models import (
    VaCodingEpisode,
    VaFinalAssessments,
    VaFinalCodAuthority,
    VaReviewerFinalAssessments,
    VaStatuses,
    VaSubmissions,
    VaSubmissionsAuditlog,
)


EPISODE_TYPE_RECODE = "recode"
EPISODE_STATUS_ACTIVE = "active"
EPISODE_STATUS_COMPLETED = "completed"
EPISODE_STATUS_ABANDONED = "abandoned"


@dataclass(frozen=True)
class AuthoritativeFinalCodRecord:
    va_sid: str
    source_role: str
    va_conclusive_cod: str
    va_finassess_remark: str | None
    effective_at: datetime | None
    payload_version_id: uuid.UUID | None = None
    coder_final_assessment_id: uuid.UUID | None = None
    reviewer_final_assessment_id: uuid.UUID | None = None


def _get_active_payload_version_id(va_sid: str) -> uuid.UUID | None:
    return db.session.scalar(
        sa.select(VaSubmissions.active_payload_version_id).where(
            VaSubmissions.va_sid == va_sid
        )
    )


def get_authoritative_final_assessment(va_sid: str) -> VaFinalAssessments | None:
    """Return the authoritative coder final COD row for recode-related logic."""
    active_payload_version_id = _get_active_payload_version_id(va_sid)
    authority = db.session.scalar(
        sa.select(VaFinalCodAuthority).where(VaFinalCodAuthority.va_sid == va_sid)
    )
    if authority and authority.authoritative_final_assessment_id:
        final_row = db.session.get(
            VaFinalAssessments, authority.authoritative_final_assessment_id
        )
        if final_row and (
            active_payload_version_id is None
            or final_row.payload_version_id == active_payload_version_id
        ):
            return final_row

    filters = [
        VaFinalAssessments.va_sid == va_sid,
        VaFinalAssessments.va_finassess_status == VaStatuses.active,
    ]
    if active_payload_version_id is not None:
        filters.append(
            VaFinalAssessments.payload_version_id == active_payload_version_id
        )

    return db.session.scalar(
        sa.select(VaFinalAssessments)
        .where(*filters)
        .order_by(VaFinalAssessments.va_finassess_createdat.desc())
    )


def get_authoritative_final_cod_record(
    va_sid: str,
) -> AuthoritativeFinalCodRecord | None:
    """Return the authoritative final COD across coder and reviewer artifacts."""
    active_payload_version_id = _get_active_payload_version_id(va_sid)
    authority = db.session.scalar(
        sa.select(VaFinalCodAuthority).where(VaFinalCodAuthority.va_sid == va_sid)
    )
    if authority and authority.authoritative_reviewer_final_assessment_id:
        reviewer_final = db.session.get(
            VaReviewerFinalAssessments,
            authority.authoritative_reviewer_final_assessment_id,
        )
        if reviewer_final and (
            active_payload_version_id is None
            or reviewer_final.payload_version_id == active_payload_version_id
        ):
            return AuthoritativeFinalCodRecord(
                va_sid=va_sid,
                source_role="reviewer",
                va_conclusive_cod=reviewer_final.va_conclusive_cod,
                va_finassess_remark=reviewer_final.va_rfinassess_remark,
                effective_at=reviewer_final.va_rfinassess_createdat,
                payload_version_id=reviewer_final.payload_version_id,
                reviewer_final_assessment_id=reviewer_final.va_rfinassess_id,
                coder_final_assessment_id=reviewer_final.supersedes_coder_final_assessment_id,
            )
    if authority and authority.authoritative_final_assessment_id:
        final_row = db.session.get(
            VaFinalAssessments, authority.authoritative_final_assessment_id
        )
        if final_row and (
            active_payload_version_id is None
            or final_row.payload_version_id == active_payload_version_id
        ):
            return AuthoritativeFinalCodRecord(
                va_sid=va_sid,
                source_role="coder",
                va_conclusive_cod=final_row.va_conclusive_cod,
                va_finassess_remark=final_row.va_finassess_remark,
                effective_at=final_row.va_finassess_createdat,
                payload_version_id=final_row.payload_version_id,
                coder_final_assessment_id=final_row.va_finassess_id,
            )

    reviewer_filters = [
        VaReviewerFinalAssessments.va_sid == va_sid,
        VaReviewerFinalAssessments.va_rfinassess_status == VaStatuses.active,
    ]
    if active_payload_version_id is not None:
        reviewer_filters.append(
            VaReviewerFinalAssessments.payload_version_id == active_payload_version_id
        )
    reviewer_fallback = db.session.scalar(
        sa.select(VaReviewerFinalAssessments)
        .where(*reviewer_filters)
        .order_by(VaReviewerFinalAssessments.va_rfinassess_createdat.desc())
    )
    if reviewer_fallback:
        return AuthoritativeFinalCodRecord(
            va_sid=va_sid,
            source_role="reviewer",
            va_conclusive_cod=reviewer_fallback.va_conclusive_cod,
            va_finassess_remark=reviewer_fallback.va_rfinassess_remark,
            effective_at=reviewer_fallback.va_rfinassess_createdat,
            payload_version_id=reviewer_fallback.payload_version_id,
            reviewer_final_assessment_id=reviewer_fallback.va_rfinassess_id,
            coder_final_assessment_id=reviewer_fallback.supersedes_coder_final_assessment_id,
        )

    coder_fallback = get_authoritative_final_assessment(va_sid)
    if coder_fallback:
        return AuthoritativeFinalCodRecord(
            va_sid=va_sid,
            source_role="coder",
            va_conclusive_cod=coder_fallback.va_conclusive_cod,
            va_finassess_remark=coder_fallback.va_finassess_remark,
            effective_at=coder_fallback.va_finassess_createdat,
            payload_version_id=coder_fallback.payload_version_id,
            coder_final_assessment_id=coder_fallback.va_finassess_id,
        )
    return None


def upsert_final_cod_authority(
    va_sid: str,
    final_assessment: VaFinalAssessments | None,
    *,
    reason: str,
    source_role: str,
    updated_by=None,
) -> VaFinalCodAuthority:
    """Upsert the authoritative final COD pointer for a submission."""
    authority = db.session.scalar(
        sa.select(VaFinalCodAuthority).where(VaFinalCodAuthority.va_sid == va_sid)
    )
    if not authority:
        authority = VaFinalCodAuthority(va_sid=va_sid)
        db.session.add(authority)

    authority.authoritative_final_assessment_id = (
        final_assessment.va_finassess_id if final_assessment else None
    )
    authority.authoritative_reviewer_final_assessment_id = None
    authority.authority_reason = reason
    authority.authority_source_role = source_role
    authority.updated_by = updated_by
    authority.effective_at = (
        final_assessment.va_finassess_createdat
        if final_assessment
        else datetime.now(timezone.utc)
    )
    return authority


def upsert_reviewer_final_cod_authority(
    va_sid: str,
    reviewer_final_assessment: VaReviewerFinalAssessments | None,
    *,
    reason: str,
    updated_by=None,
) -> VaFinalCodAuthority:
    """Upsert the authoritative final COD pointer to a reviewer-owned final COD."""
    authority = db.session.scalar(
        sa.select(VaFinalCodAuthority).where(VaFinalCodAuthority.va_sid == va_sid)
    )
    if not authority:
        authority = VaFinalCodAuthority(va_sid=va_sid)
        db.session.add(authority)

    authority.authoritative_final_assessment_id = None
    authority.authoritative_reviewer_final_assessment_id = (
        reviewer_final_assessment.va_rfinassess_id if reviewer_final_assessment else None
    )
    authority.authority_reason = reason
    authority.authority_source_role = "reviewer"
    authority.updated_by = updated_by
    authority.effective_at = (
        reviewer_final_assessment.va_rfinassess_createdat
        if reviewer_final_assessment
        else datetime.now(timezone.utc)
    )
    return authority


def get_active_recode_episode(va_sid: str) -> VaCodingEpisode | None:
    """Return the currently active recode episode for a submission, if any."""
    return db.session.scalar(
        sa.select(VaCodingEpisode).where(
            VaCodingEpisode.va_sid == va_sid,
            VaCodingEpisode.episode_type == EPISODE_TYPE_RECODE,
            VaCodingEpisode.episode_status == EPISODE_STATUS_ACTIVE,
        )
    )


def start_recode_episode(va_sid: str, started_by, *, base_final_assessment=None) -> VaCodingEpisode:
    """Create or reuse the active recode episode for a submission."""
    existing = get_active_recode_episode(va_sid)
    if existing:
        return existing

    episode = VaCodingEpisode(
        episode_id=uuid.uuid4(),
        va_sid=va_sid,
        episode_type=EPISODE_TYPE_RECODE,
        episode_status=EPISODE_STATUS_ACTIVE,
        started_by=started_by,
        base_final_assessment_id=(
            base_final_assessment.va_finassess_id if base_final_assessment else None
        ),
    )
    db.session.add(episode)
    return episode


def complete_recode_episode(episode: VaCodingEpisode, replacement_final: VaFinalAssessments) -> None:
    """Mark the active recode episode complete after replacement final COD save."""
    episode.episode_status = EPISODE_STATUS_COMPLETED
    episode.replacement_final_assessment_id = replacement_final.va_finassess_id
    episode.completed_at = datetime.now(timezone.utc)


def abandon_active_recode_episode(
    va_sid: str,
    *,
    by_role: str = "vasystem",
    by_user_id=None,
    audit_action: str = "recode episode abandoned",
) -> bool:
    """Mark an active recode episode abandoned if one exists."""
    episode = get_active_recode_episode(va_sid)
    if not episode:
        return False

    episode.episode_status = EPISODE_STATUS_ABANDONED
    episode.abandoned_at = datetime.now(timezone.utc)
    db.session.add(
        VaSubmissionsAuditlog(
            va_sid=va_sid,
            va_audit_byrole=by_role,
            va_audit_by=by_user_id,
            va_audit_operation="u",
            va_audit_action=audit_action,
            va_audit_entityid=episode.episode_id,
        )
    )
    return True
