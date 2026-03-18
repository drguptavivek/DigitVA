from app.routes.va_main import va_main
from app.routes.va_auth import va_auth
from app.routes.coding import coding
from app.routes.reviewing import reviewing
from app.routes.sitepi import sitepi
from app.routes.va_form import va_form
from app.routes.admin import admin
from app.routes.data_management import data_management
from app.routes.health import health
from app.routes.profile import profile
from app.routes.api import api_v1


def register_blueprints(app):
    app.register_blueprint(health)
    app.register_blueprint(va_main)
    app.register_blueprint(va_auth, url_prefix="/vaauth")
    app.register_blueprint(profile, url_prefix="/profile")
    app.register_blueprint(coding, url_prefix="/coding")
    app.register_blueprint(reviewing, url_prefix="/reviewing")
    app.register_blueprint(sitepi, url_prefix="/sitepi")
    app.register_blueprint(va_form, url_prefix="/vaform")
    app.register_blueprint(admin, url_prefix="/admin")
    app.register_blueprint(data_management, url_prefix="/data-management")
    app.register_blueprint(api_v1, url_prefix="/api/v1")
