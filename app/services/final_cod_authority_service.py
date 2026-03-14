"""Final COD authority and recode episode helpers."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import sqlalchemy as sa

from app import db
from app.models import (
    VaCodingEpisode,
    VaFinalAssessments,
    VaFinalCodAuthority,
    VaStatuses,
    VaSubmissionsAuditlog,
)


EPISODE_TYPE_RECODE = "recode"
EPISODE_STATUS_ACTIVE = "active"
EPISODE_STATUS_COMPLETED = "completed"
EPISODE_STATUS_ABANDONED = "abandoned"


def get_authoritative_final_assessment(va_sid: str) -> VaFinalAssessments | None:
    """Return the authoritative final COD row for a submission if one exists."""
    authority = db.session.scalar(
        sa.select(VaFinalCodAuthority).where(VaFinalCodAuthority.va_sid == va_sid)
    )
    if authority and authority.authoritative_final_assessment_id:
        final_row = db.session.get(
            VaFinalAssessments, authority.authoritative_final_assessment_id
        )
        if final_row:
            return final_row

    return db.session.scalar(
        sa.select(VaFinalAssessments)
        .where(
            VaFinalAssessments.va_sid == va_sid,
            VaFinalAssessments.va_finassess_status == VaStatuses.active,
        )
        .order_by(VaFinalAssessments.va_finassess_createdat.desc())
    )


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
    authority.authority_reason = reason
    authority.authority_source_role = source_role
    authority.updated_by = updated_by
    authority.effective_at = (
        final_assessment.va_finassess_createdat
        if final_assessment
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
