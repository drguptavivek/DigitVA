"""Access-control helpers for attachment and media file routes."""

from flask import abort
from flask_login import current_user

from app.authz.scope import (
    user_has_active_allocation,
    user_has_form_access,
    user_has_role,
    user_requires_allocation_bound_attachment_access,
)
from app.models import VaAllocation


def _has_attachment_form_access(form_id: str) -> bool:
    return bool(
        user_has_form_access(current_user, form_id)
        or user_has_form_access(current_user, form_id, "coding_tester")
    )


def _user_has_active_attachment_allocation(va_sid: str) -> bool:
    allocation_for = (
        VaAllocation.reviewing
        if user_has_role(current_user, "reviewer")
        else VaAllocation.coding
    )
    return user_has_active_allocation(
        current_user,
        allocation_for,
        va_sid=va_sid,
    )


def _enforce_attachment_access(*, va_form_id: str, va_sid: str) -> None:
    if not user_requires_allocation_bound_attachment_access(current_user, va_form_id):
        return
    if not _has_attachment_form_access(va_form_id):
        abort(403)
    if not _user_has_active_attachment_allocation(va_sid):
        abort(403)
