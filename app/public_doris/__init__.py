"""Isolated public DORIS training application."""

from __future__ import annotations

import os
from pathlib import Path

from flask import Flask
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFError, CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix

csrf = CSRFProtect()
limiter = Limiter(key_func=get_remote_address, storage_uri="memory://")


def create_public_doris_app(config: dict | None = None) -> Flask:
    """Build the database-free public training service."""

    app = Flask(
        "digitva_public_doris",
        static_folder=str(Path(__file__).resolve().parents[1] / "static"),
        static_url_path="/static",
        template_folder=str(Path(__file__).resolve().parents[1] / "templates"),
    )
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("DORIS_PUBLIC_SECRET_KEY")
        or os.environ.get("SECRET_KEY"),
        SESSION_COOKIE_NAME="digitva_doris_public_session",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get(
            "DORIS_PUBLIC_COOKIE_SECURE", "true"
        ).lower()
        not in {"0", "false", "no"},
        WTF_CSRF_HEADERS=["X-CSRFToken"],
        MAX_CONTENT_LENGTH=128 * 1024,
        ICD11_API_BASE_URL=os.environ.get("ICD11_API_BASE_URL", "http://icd_api_service"),
        ICD11_API_TIMEOUT_SECONDS=5,
        DORIS_PROCESS_DEADLINE_SECONDS=12,
        DORIS_PROCESS_CAPACITY=5,
        DORIS_WHO_IMAGE_DIGEST=(
            "sha256:1b77eb6dc43e0c65a12e9e9340ad178493c93488e728d0d936507cc57ada1b7c"
        ),
        DORIS_EXAMPLES_PATH=str(
            Path(__file__).resolve().parents[2] / "resource" / "doris_help_examples.json"
        ),
    )
    if config:
        app.config.update(config)
    if not app.config["SECRET_KEY"]:
        raise RuntimeError("DORIS public service secret key is not configured")

    csrf.init_app(app)
    limiter.init_app(app)
    from app.public_doris.routes import bp

    app.register_blueprint(bp)

    @app.errorhandler(CSRFError)
    def csrf_error(_error):
        return {
            "schema_version": 1,
            "error": {"code": "CSRF_FAILED", "message": "Refresh the page and try again."},
        }, 400

    @app.errorhandler(429)
    def rate_limit_error(_error):
        return {
            "schema_version": 1,
            "error": {
                "code": "RATE_LIMITED",
                "message": "Too many training requests. Try again shortly.",
            },
        }, 429

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        return response

    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    return app
