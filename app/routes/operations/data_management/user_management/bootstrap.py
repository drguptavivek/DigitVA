"""Bootstrap and page routes for data-management user management."""

import sqlalchemy as sa
from flask import jsonify, render_template
from flask_login import current_user
from flask_wtf.csrf import generate_csrf

from app import db
from app.authz.access import action_authorized
from app.authz.scope import user_has_role

from ..base import data_management


@data_management.get("/users")
@action_authorized("dm_user_management_view")
def user_management():
    """User + grant management page for data-managers."""
    from app.models.mas_languages import MasLanguages

    languages = db.session.scalars(
        sa.select(MasLanguages)
        .where(MasLanguages.is_active == True)
        .order_by(MasLanguages.language_name)
    ).all()
    return render_template(
        "va_frontpages/data_manager_partials/_user_management.html",
        available_languages=[
            {"code": lang.language_code, "name": lang.language_name}
            for lang in languages
        ],
    )


@data_management.get("/api/bootstrap")
@action_authorized("dm_user_management_bootstrap")
def manage_bootstrap():
    """Return CSRF token and scope context for the management JS."""
    is_admin = user_has_role(current_user, "admin")
    dm_projects = sorted(current_user.get_data_manager_projects())
    dm_site_pairs = current_user.get_data_manager_project_sites()
    is_project_scoped = is_admin or bool(dm_projects)

    return jsonify(
        {
            "csrf_header_name": "X-CSRFToken",
            "csrf_token": generate_csrf(),
            "user": {
                "user_id": str(current_user.user_id),
                "email": current_user.email,
                "name": current_user.name,
                "is_project_scoped": is_project_scoped,
                "managed_project_ids": dm_projects,
                "managed_site_pairs": [
                    {"project_id": project_id, "site_id": site_id}
                    for project_id, site_id in sorted(dm_site_pairs)
                ],
            },
            "allowed_roles": ["coder", "coding_tester", "data_manager"],
        }
    )
