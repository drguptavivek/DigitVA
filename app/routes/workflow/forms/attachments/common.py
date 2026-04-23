"""Shared helpers for workflow attachment routes."""

from __future__ import annotations

import os
import re

import sqlalchemy as sa
from flask import abort, current_app
from werkzeug.utils import secure_filename

from app import db
from app.models import VaSubmissions
from app.models.va_submission_attachments import VaSubmissionAttachments

from ..helpers import _enforce_attachment_access

STORAGE_NAME_PATTERN = re.compile(r"^[a-f0-9]{32}\.[a-z0-9]{1,5}$")
FORM_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


def validate_storage_name(storage_name_raw: str) -> str:
    """Return a validated storage token or abort with 404."""
    if not STORAGE_NAME_PATTERN.match(storage_name_raw):
        abort(404)
    return storage_name_raw


def get_attachment_lookup(storage_name: str):
    """Return attachment metadata for a storage token or abort with 404."""
    row = db.session.execute(
        sa.select(
            VaSubmissionAttachments.local_path,
            VaSubmissionAttachments.mime_type,
            VaSubmissions.va_form_id,
            VaSubmissionAttachments.va_sid,
        )
        .join(VaSubmissions, VaSubmissions.va_sid == VaSubmissionAttachments.va_sid)
        .where(VaSubmissionAttachments.storage_name == storage_name)
        .where(VaSubmissionAttachments.exists_on_odk == True)
    ).first()
    if not row:
        abort(404)
    return row


def enforce_attachment_file_access(*, va_form_id: str, va_sid: str, local_path: str) -> str:
    """Authorize access and verify the attachment stays under the form media root."""
    _enforce_attachment_access(va_form_id=va_form_id, va_sid=va_sid)

    media_base = os.path.realpath(
        os.path.join(current_app.config["APP_DATA"], va_form_id, "media")
    )
    resolved = os.path.realpath(local_path)
    if not resolved.startswith(media_base + os.sep) and resolved != media_base:
        abort(404)
    return resolved


def validate_media_request(va_form_id: str, va_filename: str) -> str:
    """Validate a media request and return the safe filename."""
    if not va_form_id or not FORM_ID_PATTERN.match(va_form_id):
        abort(400, description="Invalid form ID format")

    safe_filename = secure_filename(va_filename)
    if not safe_filename:
        abort(400, description="Invalid filename")
    if ".." in va_filename or va_filename.startswith("/") or va_filename.startswith("\\"):
        abort(400, description="Invalid filename")

    return safe_filename


def get_media_attachment_sid(*, va_form_id: str, va_filename: str):
    """Return the owning submission id for a form media file or abort with 404."""
    row = db.session.execute(
        sa.select(VaSubmissionAttachments.va_sid)
        .join(VaSubmissions, VaSubmissions.va_sid == VaSubmissionAttachments.va_sid)
        .where(
            VaSubmissions.va_form_id == va_form_id,
            VaSubmissionAttachments.filename == va_filename,
        )
    ).first()
    if not row:
        abort(404)
    return row.va_sid
