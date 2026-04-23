"""Access grants admin routes package.

Importing this package registers all access-grants routes on the admin
blueprint and preserves the legacy import surface from
``app.routes.admin_sections.access_grants``.
"""

from .api_list import admin_access_grants, admin_orphaned_grants
from .api_mutations import admin_create_access_grant, admin_toggle_access_grant
from .common import _project_access_filter
from .panels import admin_panel_access_grants

__all__ = [
    "admin_access_grants",
    "admin_create_access_grant",
    "admin_orphaned_grants",
    "admin_panel_access_grants",
    "admin_toggle_access_grant",
    "_project_access_filter",
]
