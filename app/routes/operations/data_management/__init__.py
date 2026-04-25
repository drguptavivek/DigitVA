"""Data management blueprint — /data-management/

Page routes and JSON API routes for data-manager user/grant management.
Submission-related JSON API routes live in app/routes/api/data_management.py.
Shared helpers live in app/services/data_management/dashboard.py.
"""

from app.services.data_management.dashboard import dm_scoped_forms
from app.services.analytics.submission_mv import get_dm_kpi_from_mv
from app.services.rendering.legacy.serialize_dates import va_render_serialisedates

from .base import data_management, log
from .helpers import (
    dm_can_manage_scope as _dm_can_manage_scope,
    dm_can_manage_target_user as _dm_can_manage_target_user,
    dm_grant_filter as _dm_grant_filter,
    require_dm_scope,
)
from .legacy_api import (
    legacy_project_site_submissions,
    legacy_sync_form,
    legacy_sync_preview,
    legacy_sync_submission,
)
from .user_management import (
    dm_can_edit_user_email as _dm_can_edit_user_email,
    manage_access_grants,
    manage_bootstrap,
    manage_create_access_grant,
    manage_create_user,
    manage_project_sites,
    manage_projects,
    manage_resend_verification,
    manage_toggle_access_grant,
    manage_update_user,
    manage_user_detail,
    manage_users,
    user_management,
)
from .views import (
    cod_bucket_reporting,
    dashboard,
    kpi_dashboard,
    submission_odk_edit,
    view_submission,
)

__all__ = [
    "data_management",
    "log",
    "require_dm_scope",
    "dashboard",
    "kpi_dashboard",
    "cod_bucket_reporting",
    "view_submission",
    "submission_odk_edit",
    "legacy_sync_preview",
    "legacy_project_site_submissions",
    "legacy_sync_form",
    "legacy_sync_submission",
    "user_management",
    "manage_bootstrap",
    "manage_projects",
    "manage_project_sites",
    "manage_users",
    "manage_create_user",
    "manage_user_detail",
    "manage_resend_verification",
    "manage_update_user",
    "manage_access_grants",
    "manage_create_access_grant",
    "manage_toggle_access_grant",
    "_dm_can_manage_scope",
    "_dm_grant_filter",
    "_dm_can_manage_target_user",
    "_dm_can_edit_user_email",
    "dm_scoped_forms",
    "get_dm_kpi_from_mv",
    "va_render_serialisedates",
]
