"""Email service — Flask-Mail + async Celery delivery.

Initialises Flask-Mail with SMTP config from environment variables and
provides a Celery task for async email delivery so that SMTP latency
never blocks a request.
"""

from __future__ import annotations

import logging
import smtplib
from datetime import datetime, timezone

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


def _normalized_email(value: str) -> str:
    return (value or "").strip().lower()


def _email_delivery_enabled() -> bool:
    return bool(current_app.config.get("EMAIL_DELIVERY_ENABLED", True))


def _email_suppression_cache_key(to: str) -> str:
    prefix = current_app.config.get("EMAIL_SUPPRESSION_CACHE_PREFIX", "digitva_email_suppressed:")
    return f"{prefix}{_normalized_email(to)}"


def _is_suppressed_recipient(to: str) -> bool:
    from app import cache

    key = _email_suppression_cache_key(to)
    try:
        return bool(cache.get(key))
    except Exception as exc:
        log.warning("Email suppression read failed for %s: %s", to, exc)
        return False


def _mark_suppressed_email(to: str, exc: Exception) -> None:
    from app import cache

    key = _email_suppression_cache_key(to)
    ttl_seconds = int(current_app.config.get("EMAIL_SUPPRESSION_TTL_SECONDS", 60 * 60 * 24 * 14))
    payload = {
        "reason": type(exc).__name__,
        "message": str(exc),
        "suppressed_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        cache.set(key, payload, timeout=ttl_seconds)
    except Exception as cache_exc:
        log.warning("Email suppression write failed for %s: %s", to, cache_exc)


def _should_attempt_email_delivery(to: str) -> bool:
    if not _email_delivery_enabled():
        log.info("Email delivery disabled by config — skipping %s", to)
        return False
    if _is_suppressed_recipient(to):
        log.warning("Email recipient is suppressed due to prior permanent failures: %s", to)
        return False
    return True


# ---------------------------------------------------------------------------
# High-level helpers (called from routes)
# ---------------------------------------------------------------------------

def send_password_reset_email(user, token: str, invite_mode: bool = False) -> None:
    """Dispatch a password email via Celery.

    invite_mode=True is used for first-time onboarding so the email copy
    instructs the user to set a password instead of resetting one.
    """

    base_url = current_app.config.get("MAIL_BASE_URL", "")
    if not base_url:
        base_url = current_app.config.get("SERVER_NAME", "localhost:5000")
        if not base_url.startswith("http"):
            base_url = "https://" + base_url

    reset_url = f"{base_url}/vaauth/reset-password/{token}"
    subject = "Set Your DigitVA Password" if invite_mode else "Reset Your DigitVA Password"

    if not _should_attempt_email_delivery(user.email):
        return

    _dispatch_email.delay(
        to=user.email,
        subject=subject,
        template_name="emails/reset_password",
        context={
            "name": user.name,
            "reset_url": reset_url,
            "invite_mode": invite_mode,
        },
    )


def send_verification_email(user, token: str) -> None:
    """Dispatch an email-verification email via Celery."""
    base_url = current_app.config.get("MAIL_BASE_URL", "")
    if not base_url:
        base_url = current_app.config.get("SERVER_NAME", "localhost:5000")
    if not base_url.startswith("http"):
        base_url = "https://" + base_url

    verify_url = f"{base_url}/vaauth/verify-email/{token}"

    if not _should_attempt_email_delivery(user.email):
        return

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


def _is_permanent_email_failure(exc: Exception) -> bool:
    """Return True for SMTP failures that should not be retried."""
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        recipient_errors = getattr(exc, "recipients", None) or {}
        if recipient_errors:
            for value in recipient_errors.values():
                code = value[0] if isinstance(value, tuple) and value else None
                if not isinstance(code, int) or code < 500 or code >= 600:
                    return False
            return True
        return False

    if isinstance(exc, smtplib.SMTPResponseException):
        return 500 <= exc.smtp_code < 600

    return False


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
        if not _should_attempt_email_delivery(to):
            return
        try:
            _actually_send_email(to, subject, template_name, context)
        except Exception as exc:
            if _is_permanent_email_failure(exc):
                _mark_suppressed_email(to, exc)
                log.error(
                    "Permanent email failure for %s (no retry): %s",
                    to,
                    exc,
                )
                return
            log.exception("Email send failed for %s: %s", to, exc)
            raise _dispatch_email.retry(exc=exc)

except ImportError:
    # Celery not available (e.g. in tests) — fall back to sync
    def _dispatch_email(to: str, subject: str, template_name: str, context: dict) -> None:
        if not _should_attempt_email_delivery(to):
            return
        _actually_send_email(to, subject, template_name, context)
