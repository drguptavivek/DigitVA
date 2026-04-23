"""ICD-10 browser admin routes package.

Importing this package registers all ICD-10 browser routes on the admin
blueprint and preserves the legacy import surface from
``app.routes.admin_sections.icd10_browser``.
"""

from .api import (
    admin_icd10_2019_2_children,
    admin_icd10_2019_2_node,
    admin_icd10_2019_2_policy_export,
    admin_icd10_2019_2_policy_import,
    admin_icd10_2019_2_policy_options,
    admin_icd10_2019_2_update_policy,
)
from .panel import admin_panel_icd10_browser

__all__ = [
    "admin_icd10_2019_2_children",
    "admin_icd10_2019_2_node",
    "admin_icd10_2019_2_policy_export",
    "admin_icd10_2019_2_policy_import",
    "admin_icd10_2019_2_policy_options",
    "admin_icd10_2019_2_update_policy",
    "admin_panel_icd10_browser",
]
