"""Focused handler modules for the `va_form.renderpartial` route."""

from .assessments import (  # noqa: F401
    handle_coder_review,
    handle_final_assessment,
    handle_initial_assessment,
    handle_reviewer_review,
    handle_user_note,
    handle_workflow_history,
)
from .category import handle_category_partial  # noqa: F401
