"""Admin user routes package.

Importing this package registers all admin user routes on the admin blueprint
and preserves the legacy import surface from
``app.routes.admin_sections.users``.
"""

from .api import (
    admin_create_user,
    admin_resend_verification,
    admin_toggle_user,
    admin_toggle_user_admin,
    admin_update_user,
    admin_users,
)
from .helpers import _active_language_codes, _available_languages, _validate_languages
from .panels import admin_panel_users

__all__ = [
    "_active_language_codes",
    "_available_languages",
    "_validate_languages",
    "admin_create_user",
    "admin_panel_users",
    "admin_resend_verification",
    "admin_toggle_user",
    "admin_toggle_user_admin",
    "admin_update_user",
    "admin_users",
]
