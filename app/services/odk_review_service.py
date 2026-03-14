"""Helpers for writing submission review state back to ODK Central."""

from dataclasses import dataclass
import re

from app import db
from app.models import VaForms, VaSubmissions
from app.services.odk_connection_guard_service import guarded_odk_call
from app.utils import va_odk_clientsetup


ODK_REVIEW_STATE_HAS_ISSUES = "hasIssues"
_UUID_INSTANCE_ID_PATTERN = re.compile(
    r"^(uuid:[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
)


@dataclass(slots=True)
class OdkReviewSyncResult:
    success: bool
    review_state: str | None = None
    comment: str | None = None
    error_message: str | None = None


def resolve_odk_instance_id(local_sid: str) -> str:
    """Return the raw ODK Central instance ID from a local DigitVA SID."""
    match = _UUID_INSTANCE_ID_PATTERN.match(local_sid or "")
    if match:
        return match.group(1)
    return local_sid


def build_not_codeable_review_comment(reason_code: str, other_text: str | None = None) -> str:
    """Return the comment sent to ODK Central for a not-codeable decision."""
    label_map = {
        "narration_language": "Narrative language is not readable by the coder.",
        "narration_doesnt_match": (
            "Narrative content does not match the deceased whose VA form was filled."
        ),
        "no_info": "There is no useful information available in questions or narration.",
        "form_is_empty": "The VA form is empty.",
        "others": "Other issue reported by coder.",
    }
    reason_label = label_map.get(reason_code, reason_code)
    if other_text:
        return f"DigitVA coder marked this submission as not codeable. Reason: {reason_label} Details: {other_text}"
    return f"DigitVA coder marked this submission as not codeable. Reason: {reason_label}"


def mark_submission_needs_revision(
    va_sid: str,
    reason_code: str,
    other_text: str | None = None,
) -> tuple[str, str]:
    """Mark the ODK Central submission as needing revision.

    Returns the applied review state and comment on success.
    Raises ValueError for missing local submission/form context.
    Raises Exception for ODK Central client or API failures.
    """
    submission = db.session.get(VaSubmissions, va_sid)
    if submission is None:
        raise ValueError(f"Submission not found for SID '{va_sid}'.")

    va_form = db.session.get(VaForms, submission.va_form_id)
    if va_form is None:
        raise ValueError(f"Form not found for submission SID '{va_sid}'.")
    if not va_form.project_id or not va_form.odk_form_id or not va_form.odk_project_id:
        raise ValueError(
            f"ODK mapping is incomplete for form '{va_form.form_id}'."
        )

    comment = build_not_codeable_review_comment(reason_code, other_text)
    instance_id = resolve_odk_instance_id(va_sid)
    client = va_odk_clientsetup(project_id=va_form.project_id)
    guarded_odk_call(
        lambda: client.submissions.review(
            instance_id=instance_id,
            review_state=ODK_REVIEW_STATE_HAS_ISSUES,
            form_id=va_form.odk_form_id,
            project_id=int(va_form.odk_project_id),
            comment=comment,
        ),
        client=client,
    )
    submission.va_odk_reviewstate = ODK_REVIEW_STATE_HAS_ISSUES
    return ODK_REVIEW_STATE_HAS_ISSUES, comment


def sync_not_codeable_review_state(
    va_sid: str,
    reason_code: str,
    other_text: str | None = None,
) -> OdkReviewSyncResult:
    """Attempt to sync not-codeable review state to ODK Central.

    Local workflow completion must not depend on ODK Central availability, so
    this helper captures failures for audit/logging without raising them.
    """
    try:
        review_state, comment = mark_submission_needs_revision(
            va_sid,
            reason_code,
            other_text,
        )
    except Exception as exc:  # pragma: no cover - exercised by tests via wrapper
        return OdkReviewSyncResult(success=False, error_message=str(exc))
    return OdkReviewSyncResult(
        success=True,
        review_state=review_state,
        comment=comment,
    )
