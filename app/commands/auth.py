"""Break-glass authentication recovery CLI.

Usage:
  flask auth reset-factors user@example.com --reason "lost authenticator"

Historical account reset. Run from a shell
in the app container -- container shell access is the safeguard, there is no
further authorization check. Does the same reset as the admin UI action
(app/routes/admin.py:admin_reset_user_factors), with ``actor_user_id`` NULL
and ``detail["via"] = "cli"``, then emails a single-use magic link that signs
the person in; it sets no password
(app/routes/va_auth.py ``factor_reset``). Never creates users or changes roles;
never prints an existing secret. The link is printed only if email delivery
fails, and only then -- never logged as a matter of course.
"""

import smtplib

import click
import sqlalchemy as sa

from app import db
from app.models import VaUsers
from app.services import totp_service
from app.services.email_service import factor_reset_link_url, send_factor_reset_link_email
from app.services.token_service import generate_token


def _get_user_by_email(email: str) -> VaUsers | None:
    normalized_email = email.strip().lower()
    return db.session.scalar(
        sa.select(VaUsers).where(VaUsers.email == normalized_email)
    )


@click.group("auth")
def auth_group():
    """Authentication recovery commands."""
    pass


@auth_group.command("reset-factors")
@click.argument("email")
@click.option("--reason", required=True, help="Why this reset is being performed.")
def reset_factors(email, reason):
    """Break-glass account reset: clear stale sign-in credentials, end the
    user's sessions, and email a single-use sign-in link."""
    reason = (reason or "").strip()
    if not reason:
        click.echo("A reason is required.")
        raise SystemExit(1)

    user = _get_user_by_email(email)
    if user is None:
        click.echo(f"User not found: {email.strip().lower()}")
        raise SystemExit(1)

    totp_service.reset_factors(user, actor_user_id=None, reason=reason, via="cli")
    db.session.commit()

    # Fingerprinted against the *new* session version, so any earlier
    # factor-reset link (or a password change) is already invalid.
    token = generate_token(user.user_id, "factor_reset")

    click.echo(f"Sign-in factors reset for: {user.email}")
    try:
        send_factor_reset_link_email(user, token)
    # Only actual delivery failures fall back to printing the link -- a bug
    # in the template or elsewhere must surface as a real traceback, not be
    # swallowed and misreported as "could not send".
    except (RuntimeError, smtplib.SMTPException, OSError) as exc:
        click.echo(f"Could not send the reset email ({exc}). Share this link directly:")
        click.echo(factor_reset_link_url(token))
        return

    click.echo("A sign-in link was emailed to the user.")


def init_app(app):
    """Register the auth CLI commands with the Flask app."""
    app.cli.add_command(auth_group)
