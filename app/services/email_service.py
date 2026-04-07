"""Email service — Flask-Mail + async Celery delivery.

Initialises Flask-Mail with SMTP config from environment variables and
provides a Celery task for async email delivery so that SMTP latency
never blocks a request.
"""

from __future__ import annotations

import logging

from flask import current_app, render_template
from flask_mail import Mail, Message

log = logging.getLogger(__name__)

mail = Mail()


def init_mail(app) -> None:
    """Configure Flask-Mail from environment and initialise the extension."""
    app.config.setdefault("MAIL_SERVER", "localhost")
    app.config.setdefault("MAIL_PORT", 587)
    app.config.setdefault("MAIL_USE_TLS", True)
    app.config.setdefault("MAIL_USE_SSL", False)
    app.config.setdefault("MAIL_USERNAME", "")
    app.config.setdefault("MAIL_PASSWORD", "")
    app.config.setdefault("MAIL_DEFAULT_SENDER", "noreply@digitva.org")
    mail.init_app(app)


def is_mail_configured() -> bool:
    """Return True if SMTP is configured (non-empty MAIL_SERVER)."""
    server = current_app.config.get("MAIL_SERVER", "")
    return bool(server and server != "localhost")


# ---------------------------------------------------------------------------
# High-level helpers (called from routes)
# ---------------------------------------------------------------------------

def send_password_reset_email(user, token: str) -> None:
    """Dispatch a password-reset email via Celery."""
    from app.services.token_service import TOKEN_PURPOSES

    base_url = current_app.config.get("MAIL_BASE_URL", "")
    if not base_url:
        base_url = current_app.config.get("SERVER_NAME", "localhost:5000")
        if not base_url.startswith("http"):
            base_url = "https://" + base_url

    reset_url = f"{base_url}/vaauth/reset-password/{token}"

    _dispatch_email.delay(
        to=user.email,
        subject="Reset Your DigitVA Password",
        template_name="emails/reset_password",
        context={"name": user.name, "reset_url": reset_url},
    )


def send_verification_email(user, token: str) -> None:
    """Dispatch an email-verification email via Celery."""
    base_url = current_app.config.get("MAIL_BASE_URL", "")
    if not base_url:
        base_url = current_app.config.get("SERVER_NAME", "localhost:5000")
        if not base_url.startswith("http"):
            base_url = "https://" + base_url

    verify_url = f"{base_url}/vaauth/verify-email/{token}"

    _dispatch_email.delay(
        to=user.email,
        subject="Verify Your DigitVA Email",
        template_name="emails/verify_email",
        context={"name": user.name, "verify_url": verify_url},
    )


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------

def _actually_send_email(to: str, subject: str, template_name: str, context: dict) -> None:
    """Render templates and send via Flask-Mail. Runs inside Celery worker."""
    from app import create_app

    app = create_app()
    with app.app_context():
        if not is_mail_configured():
            log.warning("Mail not configured — skipping email to %s", to)
            return

        html = render_template(template_name + ".html", **context)
        text = render_template(template_name + ".txt", **context)

        msg = Message(
            subject=subject,
            recipients=[to],
            html=html,
            body=text,
        )
        mail.send(msg)
        log.info("Email sent to %s: %s", to, subject)


try:
    from celery import shared_task

    @shared_task(
        name="email.send",
        time_limit=60,
        soft_time_limit=45,
        max_retries=3,
        default_retry_delay=30,
    )
    def _dispatch_email(to: str, subject: str, template_name: str, context: dict) -> None:
        """Celery task: render and send an email."""
        try:
            _actually_send_email(to, subject, template_name, context)
        except Exception as exc:
            log.exception("Email send failed for %s: %s", to, exc)
            raise _dispatch_email.retry(exc=exc)

except ImportError:
    # Celery not available (e.g. in tests) — fall back to sync
    def _dispatch_email(to: str, subject: str, template_name: str, context: dict) -> None:
        _actually_send_email(to, subject, template_name, context)
