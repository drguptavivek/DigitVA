"""Admin project-form mapping routes package.

Preserves the legacy import surface from
``app.routes.admin_sections.project_forms`` while splitting the panel and API
handlers into focused modules.
"""

from .connection import admin_project_odk_connection
from .mappings import (
    admin_odk_site_mappings_delete,
    admin_odk_site_mappings_list,
    admin_odk_site_mappings_save,
)
from .panel import admin_panel_project_forms

__all__ = [
    "admin_odk_site_mappings_delete",
    "admin_odk_site_mappings_list",
    "admin_odk_site_mappings_save",
    "admin_panel_project_forms",
    "admin_project_odk_connection",
]
