"""Admin project-site routes package.

Importing this package preserves the legacy import surface from
``app.routes.admin_sections.project_sites`` while splitting the route handlers
into focused modules.
"""

from .api import (
    admin_create_project_site,
    admin_project_sites,
    admin_toggle_project_site,
    admin_update_project_site_coding_settings,
)
from .common import _get_active_project_site
from .panel import admin_panel_project_sites

__all__ = [
    "_get_active_project_site",
    "admin_create_project_site",
    "admin_panel_project_sites",
    "admin_project_sites",
    "admin_toggle_project_site",
    "admin_update_project_site_coding_settings",
]
