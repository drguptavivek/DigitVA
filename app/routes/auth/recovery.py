"""Password-reset and email-verification routes."""

import uuid

import sqlalchemy as sa
from flask import Blueprint, flash, redirect, render_template, url_for
from flask_login import current_user

from app import db, limiter
from app.forms import ForgotPasswordForm, ResetPasswordForm
from app.models import VaStatuses, VaUsers

from .common import inactive_account_response
from .emails import send_email_verification, send_password_reset

va_auth = Blueprint("va_auth", __name__)


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
            send_password_reset(user)
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

    from app.services.security.token import validate_token

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
        if user.user_status != VaStatuses.active:
            return inactive_account_response()

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


@va_auth.route("/verify-email/<token>", methods=["GET"])
@limiter.limit("3 per minute")
def verify_email(token):
    from app.services.security.token import generate_token, validate_token

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
    if user.user_status != VaStatuses.active:
        return inactive_account_response()

    if not user.email_verified:
        user.email_verified = True
        db.session.commit()

    if not user.pw_reset_t_and_c:
        reset_token = generate_token(user.user_id, "password_reset")
        flash(
            "Email verified successfully. Please set your password to continue.",
            "success",
        )
        return redirect(url_for("va_auth.reset_password", token=reset_token))

    flash("Email verified successfully! You can now log in.", "success")
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
            send_email_verification(user)
        flash(
            "If that email address needs verification, we've sent a new link. "
            "Please check your inbox (and spam folder).",
            "info",
        )
        return redirect(url_for("va_auth.resend_verification"))
    return render_template("va_frontpages/va_resend_verification.html", form=form)
