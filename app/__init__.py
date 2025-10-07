from flask import Flask, request, redirect, url_for
from flask_migrate import Migrate
from flask_login import LoginManager, current_user
from flask_sqlalchemy import SQLAlchemy
from config import Config

db = SQLAlchemy()
migrate = Migrate()
login = LoginManager()

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    migrate.init_app(app, db)
    login.init_app(app)
    login.login_view = 'va_auth.va_login'
    login.login_message = 'Please log in to access this page.'

    from app.routes import register_blueprints  
    register_blueprints(app)
    from app.routes.va_errors import register_error_handlers
    register_error_handlers(app)
    from app.logging import va_logging
    va_logging(app)
    
    from app import models #noqa
    from app import services #noqa
    from app import utils #noqa
    
    # @app.before_request
    # def force_password_update():
    #     if current_user.is_authenticated:
    #         if not current_user.pw_reset_t_and_c and request.endpoint != 'va_main.force_password_change':
    #             return redirect(url_for('va_main.force_password_change'))
    
    @app.before_request
    def force_password_update():
        if not current_user.is_authenticated:
            return
        allowed_endpoints = {
            'static',
            'va_main.force_password_change',
            'va_auth.va_logout',
            'va_auth.va_login',
        }
        if current_user.pw_reset_t_and_c is False and request.endpoint not in allowed_endpoints:
            return redirect(url_for('va_main.force_password_change'))

    return app