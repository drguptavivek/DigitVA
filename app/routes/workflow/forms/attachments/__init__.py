"""Attachment and media routes for workflow forms.

This package preserves the historical import surface of
``app.routes.workflow.forms.attachments`` while splitting the routes into
focused modules.
"""

from .attachment_routes import serve_attachment
from .media_routes import serve_media

__all__ = ["serve_attachment", "serve_media"]
