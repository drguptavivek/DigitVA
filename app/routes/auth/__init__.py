"""Authentication and account-recovery routes."""

from .common import inactive_account_response
from .emails import send_email_verification, send_password_reset
from .login import va_login, va_logout
from .recovery import (
    forgot_password,
    resend_verification,
    reset_password,
    va_auth,
    verify_email,
)

__all__ = [
    "forgot_password",
    "inactive_account_response",
    "resend_verification",
    "reset_password",
    "send_email_verification",
    "send_password_reset",
    "va_auth",
    "va_login",
    "va_logout",
    "verify_email",
]
