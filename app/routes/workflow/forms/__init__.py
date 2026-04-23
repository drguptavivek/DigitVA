"""Workflow form routes package.

This surface remains import-compatible as ``app.routes.workflow.forms`` while
splitting the large legacy module into focused helpers and route modules.
"""

from flask import Blueprint

va_form = Blueprint("va_form", __name__)

from . import attachments as _attachments  # noqa: F401,E402
from . import partials as _partials  # noqa: F401,E402
from .helpers import (  # noqa: E402
    _apply_partial_cache_policy,
    _get_display_initial_assessment,
)

# Preserve historical patch/import targets used by tests while the package
# migration is in progress.
renderpartial = _partials.renderpartial
bust_coder_dashboard_cache = _partials.bust_coder_dashboard_cache
get_category_rendering_service = _partials.get_category_rendering_service
sync_not_codeable_review_state = _partials.sync_not_codeable_review_state

__all__ = [
    "va_form",
    "renderpartial",
    "_apply_partial_cache_policy",
    "_get_display_initial_assessment",
    "bust_coder_dashboard_cache",
    "get_category_rendering_service",
    "sync_not_codeable_review_state",
]
