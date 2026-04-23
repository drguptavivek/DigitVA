"""User and grant management routes for data-management."""

from .bootstrap import manage_bootstrap, user_management
from .grants import (
    manage_access_grants,
    manage_create_access_grant,
    manage_toggle_access_grant,
)
from .helpers import dm_can_edit_user_email
from .projects import manage_project_sites, manage_projects
from .users import (
    manage_create_user,
    manage_resend_verification,
    manage_update_user,
    manage_user_detail,
    manage_users,
)

__all__ = [
    "dm_can_edit_user_email",
    "manage_access_grants",
    "manage_bootstrap",
    "manage_create_access_grant",
    "manage_create_user",
    "manage_project_sites",
    "manage_projects",
    "manage_resend_verification",
    "manage_toggle_access_grant",
    "manage_update_user",
    "manage_user_detail",
    "manage_users",
    "user_management",
]
