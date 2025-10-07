from app.routes.va_main import va_main
from app.routes.va_auth import va_auth
from app.routes.va_cta import va_cta
from app.routes.va_api import va_api


def register_blueprints(app):
    app.register_blueprint(va_main)
    app.register_blueprint(va_auth, url_prefix="/vaauth")
    app.register_blueprint(va_cta, url_prefix="/vacta")
    app.register_blueprint(va_api, url_prefix="/vaapi")
