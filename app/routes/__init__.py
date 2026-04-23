"""Blueprint registration for the organized route packages.

Top-level compatibility modules still exist for older imports in tests and
transitional code, but new imports should use the domain packages directly.
"""

from app.routes.operations import data_management as data_management_routes
from app.routes.operations import sitepi as sitepi_routes
from app.routes import auth as auth_routes
from app.routes import health as health_routes
from app.routes import home as home_routes
from app.routes import profile as profile_routes
from app.routes.workflow import coding as coding_routes
from app.routes.workflow import forms as form_routes
from app.routes.workflow import reviewing as reviewing_routes
from app.routes.admin import admin
from app.routes.api import api_v1


def register_blueprints(app):
    app.register_blueprint(health_routes.health)
    app.register_blueprint(home_routes.va_main)
    app.register_blueprint(auth_routes.va_auth, url_prefix="/vaauth")
    app.register_blueprint(profile_routes.profile, url_prefix="/profile")
    app.register_blueprint(coding_routes.coding, url_prefix="/coding")
    app.register_blueprint(reviewing_routes.reviewing, url_prefix="/reviewing")
    app.register_blueprint(sitepi_routes.sitepi, url_prefix="/sitepi")
    app.register_blueprint(form_routes.va_form, url_prefix="/vaform")
    app.register_blueprint(admin, url_prefix="/admin")
    app.register_blueprint(
        data_management_routes.data_management,
        url_prefix="/data-management",
    )
    app.register_blueprint(api_v1, url_prefix="/api/v1")
