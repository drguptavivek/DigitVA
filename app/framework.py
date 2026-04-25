"""Framework adapter functions.

Domain service modules import this adapter instead of importing Flask directly.
That keeps Flask-specific objects out of `app/services` while preserving the
current application runtime.
"""

from __future__ import annotations

import flask
from flask import current_app
from flask import has_app_context as _has_app_context
from flask_login import current_user
from flask_mail import Mail, Message

mail = Mail()


def init_mail_extension(app) -> None:
    mail.init_app(app)


def send_mail_message(*, to: str, subject: str, html: str, body: str) -> None:
    mail.send(
        Message(
            subject=subject,
            recipients=[to],
            html=html,
            body=body,
        )
    )


def has_app_context() -> bool:
    return _has_app_context()


def app_object():
    return current_app._get_current_object() if has_app_context() else None


def config_get(key: str, default=None):
    return current_app.config.get(key, default)


def config_value(key: str):
    return current_app.config[key]


def logger_warning(message: str, *args, **kwargs) -> None:
    current_app.logger.warning(message, *args, **kwargs)


def current_user_object():
    return current_user


def template_render(template_name: str, **context):
    return flask.render_template(template_name, **context)


def route_url(endpoint: str, **values):
    return flask.url_for(endpoint, **values)


def json_response(*args, **kwargs):
    return flask.jsonify(*args, **kwargs)


def flash_message(message: str, category: str = "message") -> None:
    flask.flash(message, category)


def request_header(name: str, default=None):
    return flask.request.headers.get(name, default)
