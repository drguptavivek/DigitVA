import uuid

from flask import Flask, request, redirect, session, url_for
from flask_migrate import Migrate
from flask_login import LoginManager, current_user
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from config import Config
from celery import Celery, Task

db = SQLAlchemy()
migrate = Migrate()
login = LoginManager()
csrf = CSRFProtect()

def celery_init_app(app: Flask) -> Celery:
    class FlaskTask(Task):
        def __call__(self, *args: object, **kwargs: object) -> object:
            with app.app_context():
                return self.run(*args, **kwargs)

    celery_app = Celery(app.name, task_cls=FlaskTask)
    celery_app.config_from_object(app.config.get("CELERY", {}))
    celery_app.set_default()
    app.extensions["celery"] = celery_app
    return celery_app

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    migrate.init_app(app, db)
    login.init_app(app)
    csrf.init_app(app)
    login.login_view = 'va_auth.va_login'
    login.login_message = 'Please log in to access this page.'
    app.config.setdefault("WTF_CSRF_HEADERS", ["X-CSRFToken"])
    
    # Initialize Celery
    celery_init_app(app)

    from app.routes import register_blueprints  
    register_blueprints(app)
    from app.routes.va_errors import register_error_handlers
    register_error_handlers(app)
    from app.logging import va_logging
    va_logging(app)
    
    from app import models #noqa
    from app import services #noqa
    from app import utils #noqa
    
    import pytz
    from datetime import datetime

    @app.template_filter('user_timezone')
    def user_timezone_filter(dt, format='%Y-%m-%d %H:%M:%S'):
        if not dt:
            return ""
        if isinstance(dt, str):
            try:
                dt = datetime.fromisoformat(dt.replace('Z', '+00:00'))
            except ValueError:
                return dt
                
        # If naive, assume UTC
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=pytz.UTC)
            
        tz_name = getattr(current_user, 'timezone', 'Asia/Kolkata')
        try:
            tz = pytz.timezone(tz_name)
        except pytz.UnknownTimeZoneError:
            tz = pytz.timezone('Asia/Kolkata')
            
        local_dt = dt.astimezone(tz)
        return local_dt.strftime(format)
    
    # @app.before_request
    # def force_password_update():
    #     if current_user.is_authenticated:
    #         if not current_user.pw_reset_t_and_c and request.endpoint != 'va_main.force_password_change':
    #             return redirect(url_for('va_main.force_password_change'))
    
    @app.before_request
    def force_password_update():
        current_user_id = session.get("_user_id")
        if not current_user_id:
            return
        try:
            current_user_id = uuid.UUID(current_user_id)
        except (TypeError, ValueError):
            return

        from app.models import VaUsers

        fresh_user = db.session.get(VaUsers, current_user_id)
        if fresh_user is None:
            return

        allowed_endpoints = {
            'static',
            'va_main.force_password_change',
            'va_auth.va_logout',
            'va_auth.va_login',
        }
        if fresh_user.pw_reset_t_and_c is False and request.endpoint not in allowed_endpoints:
            return redirect(url_for('va_main.force_password_change'))

    return app
