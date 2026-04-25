"""Email-dispatch helpers for auth routes."""

from app.services.notifications.email import send_password_reset_email, send_verification_email
from app.services.security.token import generate_token


def send_password_reset(user):
    token = generate_token(user.user_id, "password_reset")
    send_password_reset_email(user, token)


def send_email_verification(user):
    token = generate_token(user.user_id, "email_verify")
    send_verification_email(user, token)
