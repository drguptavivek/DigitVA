"""Admin language routes package.

Importing this package registers all admin language routes on the admin
blueprint and preserves the legacy import surface from
``app.routes.admin_sections.languages``.
"""

from .api_list import admin_languages_list
from .api_mutations import (
    admin_languages_create,
    admin_languages_delete_alias,
    admin_languages_toggle,
    admin_languages_update,
)
from .panel import admin_panel_languages
from .queries import (
    _language_aliases_by_code,
    _language_submission_counts,
    _unmapped_submission_languages,
)

__all__ = [
    "_language_aliases_by_code",
    "_language_submission_counts",
    "_unmapped_submission_languages",
    "admin_languages_create",
    "admin_languages_delete_alias",
    "admin_languages_list",
    "admin_languages_toggle",
    "admin_languages_update",
    "admin_panel_languages",
]
