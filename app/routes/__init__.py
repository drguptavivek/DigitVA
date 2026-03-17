from app.routes.va_main import va_main
from app.routes.va_auth import va_auth
from app.routes.va_cta import va_cta
from app.routes.va_api import va_api
from app.routes.admin import admin
from app.routes.dashboard_api import dashboard_api
from app.routes.analytics_api import analytics_api


def register_blueprints(app):
    app.register_blueprint(va_main)
    app.register_blueprint(va_auth, url_prefix="/vaauth")
    app.register_blueprint(va_cta, url_prefix="/vacta")
    app.register_blueprint(va_api, url_prefix="/vaapi")
    app.register_blueprint(admin, url_prefix="/admin")
    app.register_blueprint(dashboard_api, url_prefix="/vadashboard")
    app.register_blueprint(analytics_api, url_prefix="/api/analytics")
