"""COD bucket admin routes package.

Preserves the legacy import surface from
``app.routes.admin_sections.cod_buckets`` while splitting the panel and API
handlers into focused modules.
"""

from .common import _cod_bucket_node_path_label, _cod_bucket_slugify
from .mappings import (
    admin_cod_bucket_scheme_add_mappings,
    admin_cod_bucket_scheme_delete_mapping,
    admin_cod_bucket_scheme_update_mapping,
)
from .nodes import (
    admin_cod_bucket_scheme_create_node,
    admin_cod_bucket_scheme_delete_node,
    admin_cod_bucket_scheme_node_mappings,
    admin_cod_bucket_scheme_reorder_nodes,
    admin_cod_bucket_scheme_update_node,
)
from .panel import admin_panel_cod_buckets
from .schemes import (
    admin_cod_bucket_scheme_create,
    admin_cod_bucket_scheme_detail,
    admin_cod_bucket_scheme_export,
    admin_cod_bucket_scheme_icd_search,
    admin_cod_bucket_scheme_reset_default,
    admin_cod_bucket_scheme_unmapped_icd,
    admin_cod_bucket_scheme_update,
    admin_cod_bucket_schemes,
)

__all__ = [
    "_cod_bucket_node_path_label",
    "_cod_bucket_slugify",
    "admin_cod_bucket_scheme_add_mappings",
    "admin_cod_bucket_scheme_create",
    "admin_cod_bucket_scheme_create_node",
    "admin_cod_bucket_scheme_delete_mapping",
    "admin_cod_bucket_scheme_delete_node",
    "admin_cod_bucket_scheme_detail",
    "admin_cod_bucket_scheme_export",
    "admin_cod_bucket_scheme_icd_search",
    "admin_cod_bucket_scheme_node_mappings",
    "admin_cod_bucket_scheme_reorder_nodes",
    "admin_cod_bucket_scheme_reset_default",
    "admin_cod_bucket_scheme_unmapped_icd",
    "admin_cod_bucket_scheme_update",
    "admin_cod_bucket_scheme_update_mapping",
    "admin_cod_bucket_scheme_update_node",
    "admin_cod_bucket_schemes",
    "admin_panel_cod_buckets",
]
