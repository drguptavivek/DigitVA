from app import db, limiter
from app.models import VaUsers
from app.forms import LoginForm, ForgotPasswordForm, ResetPasswordForm
import sqlalchemy as sa
import uuid
from flask import Blueprint, render_template, redirect, url_for, flash, session, request
from flask_login import login_user, logout_user, current_user
from urllib.parse import urlparse

va_auth = Blueprint("va_auth", __name__)


@va_auth.route("/valogin", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
@limiter.limit("20 per hour", methods=["POST"],
               key_func=lambda: (request.form.get("email") or "").lower().strip())
def va_login():
    if current_user.is_authenticated:
        return redirect(current_user.landing_url())
    form = LoginForm()
    if form.validate_on_submit():
        user = db.session.scalar(
            sa.select(VaUsers).where(VaUsers.email == form.email.data)
        )
        if user is None or not user.check_password(form.password.data):
            flash(
                "Invalid email or password. Please, re-check and login again.",
                "primary",
            )
            return redirect(url_for("va_auth.va_login"))

        # Block login if email not verified
        if not user.email_verified:
            flash("Please verify your email address before logging in.", "email_unverified")
            return redirect(url_for("va_auth.va_login"))

        session.permanent = True
        login_user(user, remember=form.remember_me.data)

        next_page = request.args.get('next')
        if not next_page or urlparse(next_page).netloc != '':
            next_page = current_user.landing_url()

        return redirect(next_page)
    return render_template("va_frontpages/va_login.html", form=form)


@va_auth.route("/valogout", methods=["POST"])
def va_logout():
    if current_user.is_anonymous:
        return redirect(url_for("va_main.va_index"))
    logout_user()
    flash("You have been successfully logged out.", "primary")
    return redirect(url_for("va_main.va_index"))


# ---------------------------------------------------------------------------
# Forgot Password
# ---------------------------------------------------------------------------

@va_auth.route("/forgot-password", methods=["GET", "POST"])
@limiter.limit("3 per hour", methods=["POST"])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(current_user.landing_url())
    form = ForgotPasswordForm()
    if form.validate_on_submit():
        user = db.session.scalar(
            sa.select(VaUsers).where(VaUsers.email == form.email.data)
        )
        if user:
            _send_password_reset(user)
        # Always show the same message to prevent email enumeration
        flash(
            "If that email address is registered, we've sent a password reset link. "
            "Please check your inbox (and spam folder).",
            "info",
        )
        return redirect(url_for("va_auth.forgot_password"))
    return render_template("va_frontpages/va_forgot_password.html", form=form)


@va_auth.route("/reset-password/<token>", methods=["GET", "POST"])
@limiter.limit("5 per minute", methods=["POST"])
def reset_password(token):
    if current_user.is_authenticated:
        return redirect(current_user.landing_url())

    from app.services.token_service import validate_token

    user_id = validate_token(token, "password_reset")
    if not user_id:
        return render_template(
            "va_frontpages/va_reset_password.html",
            form=ResetPasswordForm(),
            token=token,
            token_valid=False,
        )

    form = ResetPasswordForm()
    if form.validate_on_submit():
        try:
            uid = uuid.UUID(user_id)
        except (ValueError, TypeError):
            flash("Invalid reset link.", "danger")
            return redirect(url_for("va_auth.forgot_password"))

        user = db.session.get(VaUsers, uid)
        if not user:
            flash("User not found.", "danger")
            return redirect(url_for("va_auth.forgot_password"))

        user.set_password(form.new_password.data)
        user.pw_reset_t_and_c = False
        db.session.commit()

        flash(
            "Your password has been reset successfully. Please log in with your new password.",
            "success",
        )
        return redirect(url_for("va_auth.va_login"))

    return render_template(
        "va_frontpages/va_reset_password.html",
        form=form,
        token=token,
        token_valid=True,
    )


# ---------------------------------------------------------------------------
# Email Verification
# ---------------------------------------------------------------------------

@va_auth.route("/verify-email/<token>", methods=["GET"])
@limiter.limit("3 per minute")
def verify_email(token):
    from app.services.token_service import validate_token

    user_id = validate_token(token, "email_verify")
    if not user_id:
        flash(
            "This verification link is invalid or has expired. "
            "Please request a new one.",
            "danger",
        )
        return redirect(url_for("va_auth.va_login"))

    try:
        uid = uuid.UUID(user_id)
    except (ValueError, TypeError):
        flash("Invalid verification link.", "danger")
        return redirect(url_for("va_auth.va_login"))

    user = db.session.get(VaUsers, uid)
    if not user:
        flash("User not found.", "danger")
        return redirect(url_for("va_auth.va_login"))

    if user.email_verified:
        flash("Your email is already verified. Please log in.", "info")
    else:
        user.email_verified = True
        db.session.commit()
        flash(
            "Email verified successfully! You can now log in.",
            "success",
        )
    return redirect(url_for("va_auth.va_login"))


@va_auth.route("/resend-verification", methods=["GET", "POST"])
@limiter.limit("3 per hour", methods=["POST"])
def resend_verification():
    if current_user.is_authenticated:
        return redirect(current_user.landing_url())
    form = ForgotPasswordForm()
    if form.validate_on_submit():
        user = db.session.scalar(
            sa.select(VaUsers).where(VaUsers.email == form.email.data)
        )
        if user and not user.email_verified:
            _send_email_verification(user)
        # Same message regardless to prevent enumeration
        flash(
            "If that email address needs verification, we've sent a new link. "
            "Please check your inbox (and spam folder).",
            "info",
        )
        return redirect(url_for("va_auth.resend_verification"))
    return render_template("va_frontpages/va_resend_verification.html", form=form)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _send_password_reset(user):
    """Generate a password-reset token and dispatch the email."""
    from app.services.token_service import generate_token
    from app.services.email_service import send_password_reset_email

    token = generate_token(user.user_id, "password_reset")
    send_password_reset_email(user, token)


def _send_email_verification(user):
    """Generate an email-verification token and dispatch the email."""
    from app.services.token_service import generate_token
    from app.services.email_service import send_verification_email

    token = generate_token(user.user_id, "email_verify")
    send_verification_email(user, token)
