"""Admin activity routes package.

Importing this package registers the admin activity routes on the admin
blueprint and preserves the legacy import surface from
``app.routes.admin_sections.activity``.
"""

from .panel import (
    _AUDIT_ACTION_DISPLAY,
    _AUDIT_ACTION_EXPLANATIONS,
    _build_activity_rows,
    VaForms,
    admin,
    admin_panel_activity,
    db,
    render_template,
    request,
    role_required,
    sa,
)

__all__ = [
    "_AUDIT_ACTION_DISPLAY",
    "_AUDIT_ACTION_EXPLANATIONS",
    "_build_activity_rows",
    "VaForms",
    "admin",
    "admin_panel_activity",
    "db",
    "render_template",
    "request",
    "role_required",
    "sa",
]
