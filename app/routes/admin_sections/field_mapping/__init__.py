"""Field mapping admin routes package.

Importing this package registers all field-mapping routes on the admin blueprint
and preserves the legacy import surface from
``app.routes.admin_sections.field_mapping``.
"""

from .api_browser import (
    admin_category_fields_reorder,
    admin_field_move_to_subcategory,
    admin_form_type_category_browser_state,
    admin_form_type_fields_search,
    admin_form_type_subcategories,
)
from .api_categories import (
    admin_category_create,
    admin_category_delete,
    admin_category_update,
    admin_subcategory_create,
    admin_subcategory_delete,
    admin_subcategory_update,
)
from .api_form_types import (
    admin_form_types_create,
    admin_form_types_duplicate,
    admin_form_types_export,
    admin_form_types_import,
    admin_form_types_list,
    admin_form_types_update,
)
from .panels import (
    admin_panel_field_mapping,
    admin_panel_field_mapping_categories,
    admin_panel_field_mapping_choices,
    admin_panel_field_mapping_field_edit,
    admin_panel_field_mapping_field_quick_category,
    admin_panel_field_mapping_field_quick_order,
    admin_panel_field_mapping_fields,
    admin_panel_field_mapping_sync,
    admin_panel_field_mapping_sync_apply,
    admin_panel_field_mapping_sync_preview,
    admin_panel_field_mapping_sync_run,
)

__all__ = [
    "admin_category_create",
    "admin_category_delete",
    "admin_category_fields_reorder",
    "admin_category_update",
    "admin_field_move_to_subcategory",
    "admin_form_type_category_browser_state",
    "admin_form_type_fields_search",
    "admin_form_type_subcategories",
    "admin_form_types_create",
    "admin_form_types_duplicate",
    "admin_form_types_export",
    "admin_form_types_import",
    "admin_form_types_list",
    "admin_form_types_update",
    "admin_panel_field_mapping",
    "admin_panel_field_mapping_categories",
    "admin_panel_field_mapping_choices",
    "admin_panel_field_mapping_field_edit",
    "admin_panel_field_mapping_field_quick_category",
    "admin_panel_field_mapping_field_quick_order",
    "admin_panel_field_mapping_fields",
    "admin_panel_field_mapping_sync",
    "admin_panel_field_mapping_sync_apply",
    "admin_panel_field_mapping_sync_preview",
    "admin_panel_field_mapping_sync_run",
    "admin_subcategory_create",
    "admin_subcategory_delete",
    "admin_subcategory_update",
]
