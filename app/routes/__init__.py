from app.routes.va_main import va_main
from app.routes.va_auth import va_auth
from app.routes.va_cta import va_cta
from app.routes.coding import coding
from app.routes.admin import admin
from app.routes.data_management import data_management
from app.routes.health import health
from app.routes.api import api_v1


def register_blueprints(app):
    app.register_blueprint(health)
    app.register_blueprint(va_main)
    app.register_blueprint(va_auth, url_prefix="/vaauth")
    app.register_blueprint(va_cta, url_prefix="/vacta")
    app.register_blueprint(coding, url_prefix="/coding")
    app.register_blueprint(admin, url_prefix="/admin")
    app.register_blueprint(data_management, url_prefix="/data-management")
    app.register_blueprint(api_v1, url_prefix="/api/v1")
