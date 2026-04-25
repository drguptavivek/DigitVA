"""ODK connection admin routes package.

Importing this package registers all ODK-connection routes on the admin
blueprint and preserves the legacy import surface from
``app.routes.admin_sections.odk_connections``.
"""

import logging

from app.serializers import serialize_odk_connection as _serialize_odk_connection_payload
from app.routes.admin import admin
from app.admin_support.odk import (
    get_connection_project_ids as _get_connection_project_ids,
    get_odk_client_for_connection as _get_odk_client_for_connection,
    validate_odk_base_url as _validate_odk_base_url,
)
from app.services.odk.connection_guard import (
    OdkConnectionCooldownError,
    guarded_odk_call,
    serialize_connection_guard_state,
)

from .assignments import (
    admin_odk_assign_project,
    admin_odk_connection_projects,
    admin_odk_unassign_project,
)
from .crud import (
    admin_odk_connections_create,
    admin_odk_connections_list,
    admin_odk_connections_toggle,
    admin_odk_connections_update,
)
from .panel import admin_panel_odk_connections
from .remote import (
    admin_odk_connections_test,
    admin_odk_list_forms,
    admin_odk_list_odk_projects,
)

log = logging.getLogger(__name__)


def _serialize_odk_connection(conn, project_ids):
    return _serialize_odk_connection_payload(
        conn,
        project_ids,
        serialize_connection_guard_state(conn),
    )

__all__ = [
    "OdkConnectionCooldownError",
    "_get_connection_project_ids",
    "_get_odk_client_for_connection",
    "_serialize_odk_connection",
    "_validate_odk_base_url",
    "admin",
    "admin_odk_assign_project",
    "admin_odk_connection_projects",
    "admin_odk_connections_create",
    "admin_odk_connections_list",
    "admin_odk_connections_test",
    "admin_odk_connections_toggle",
    "admin_odk_connections_update",
    "admin_odk_list_forms",
    "admin_odk_list_odk_projects",
    "admin_odk_unassign_project",
    "admin_panel_odk_connections",
    "guarded_odk_call",
    "log",
]
