"""Project a normalized ODK payload onto the active va_submissions summary row."""

from __future__ import annotations

from dateutil import parser
import sqlalchemy as sa

from app import db
from app.models.mas_languages import MapLanguageAliases
from app.services.who_age_normalization import normalize_who_2022_age
from app.utils import (
    va_preprocess_categoriestodisplay,
    va_preprocess_summcatenotification,
)

_language_alias_cache: dict[str, str] | None = None


def _normalize_consent(raw_value) -> str:
    if raw_value is None:
        return ""
    return str(raw_value).strip()


def _normalize_language(raw: str | None) -> str:
    if not raw:
        return raw or ""

    global _language_alias_cache
    if _language_alias_cache is None:
        rows = db.session.execute(
            sa.select(MapLanguageAliases.alias, MapLanguageAliases.language_code)
        ).all()
        _language_alias_cache = {row.alias.lower(): row.language_code for row in rows}

    return _language_alias_cache.get(raw.lower(), raw)


def apply_payload_to_submission_summary(submission, payload_data: dict, *, source_updated_at=None) -> None:
    """Update the active submission summary row from a normalized ODK payload."""
    raw_language = payload_data.get("narr_language") or payload_data.get("language")
    normalized_age = normalize_who_2022_age(payload_data)
    submission_date = payload_data.get("SubmissionDate")

    submission.va_submission_date = (
        parser.isoparse(submission_date) if submission_date else submission.va_submission_date
    )
    submission.va_odk_updatedat = (
        source_updated_at
        if source_updated_at is not None
        else (
            parser.isoparse(payload_data.get("updatedAt")).replace(tzinfo=None)
            if payload_data.get("updatedAt")
            else submission.va_odk_updatedat
        )
    )
    submission.va_data_collector = payload_data.get("SubmitterName") or "unknown"
    submission.va_odk_reviewstate = payload_data.get("ReviewState")
    submission.va_odk_reviewcomments = payload_data.get("OdkReviewComments")
    submission.va_instance_name = payload_data.get("instanceName")
    submission.va_uniqueid_real = payload_data.get("unique_id")
    submission.va_uniqueid_masked = payload_data.get("unique_id2") or "Unavailable"
    submission.va_consent = _normalize_consent(payload_data.get("Id10013"))
    submission.va_narration_language = _normalize_language(raw_language)
    submission.va_deceased_age = normalized_age.legacy_age_years
    submission.va_deceased_age_normalized_days = normalized_age.normalized_age_days
    submission.va_deceased_age_normalized_years = normalized_age.normalized_age_years
    submission.va_deceased_age_source = normalized_age.normalized_age_source
    submission.va_deceased_gender = payload_data.get("Id10019") or "unknown"
    submission.va_sync_issue_code = None
    submission.va_sync_issue_detail = None
    submission.va_sync_issue_updated_at = None
    submission.va_data = payload_data
    submission.va_summary, submission.va_catcount = (
        va_preprocess_summcatenotification(payload_data)
    )
    submission.va_category_list = va_preprocess_categoriestodisplay(
        payload_data,
        submission.va_form_id,
    )
