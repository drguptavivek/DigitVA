from datetime import datetime, timedelta, timezone

from app import db, limiter
from app.models import VaUsers
from app.forms import EmailStepForm, PasswordStepForm, ForgotPasswordForm, ResetPasswordForm
import sqlalchemy as sa
import uuid
from flask import Blueprint, current_app, render_template, redirect, url_for, flash, session, request, jsonify
from flask_login import login_user, logout_user, current_user
from urllib.parse import urlparse
from werkzeug.security import check_password_hash, generate_password_hash

from app.services.pow_captcha_service import issue_challenge, verify_challenge
from app.services.site_maintenance_service import (
    get_active_site_maintenance,
    serialize_site_maintenance,
    should_block_non_admin_after_cutoff,
)

va_auth = Blueprint("va_auth", __name__)

# docs/policy/authentication-factors.md section 1: pre-auth state is bound to
# one email, allows one outstanding challenge, and expires 5 minutes after
# the email step.
PREAUTH_TTL = timedelta(minutes=5)
INVALID_LOGIN_MESSAGE = "Invalid email or password. Please, re-check and login again."
_DUMMY_PASSWORD_HASH = generate_password_hash("digitva-timing-equaliser")


def _preauth_email_key_func():
    """Per-account limiter key for the password step: the pre-auth email, not
    a form field an attacker controls."""
    return (_preauth_state() or {}).get("email") or ""


def _preauth_state() -> dict | None:
    """The current pre-auth state if present and not expired, else None."""
    state = session.get("preauth")
    if not isinstance(state, dict) or not state.get("email") or not state.get("issued_at"):
        return None
    try:
        issued_at = datetime.fromisoformat(state["issued_at"])
    except (TypeError, ValueError):
        return None
    if datetime.now(timezone.utc) - issued_at > PREAUTH_TTL:
        return None
    return state


def _set_preauth(email: str, next_url: str | None) -> None:
    session["preauth"] = {
        "email": email,
        "issued_at": datetime.now(timezone.utc).isoformat(),
        "next": next_url,
    }


def _clear_preauth() -> None:
    session.pop("preauth", None)


@va_auth.route("/valogin", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
@limiter.limit("20 per hour", methods=["POST"],
               key_func=lambda: (request.form.get("email") or "").lower().strip())
def va_login():
    """Step 1: email plus the proof-of-work CAPTCHA. Never looks the user up
    or branches on whether the account exists -- see docs/policy/
    authentication-factors.md section 1.
    """
    if current_user.is_authenticated:
        return redirect(current_user.landing_url())
    # A fresh visit to the email step always starts over (policy: "replaced
    # by a new email step"), including via the password page's "not you?"
    # link.
    _clear_preauth()
    form = EmailStepForm()
    maintenance_notice = None
    if should_block_non_admin_after_cutoff():
        maintenance = get_active_site_maintenance()
        if maintenance is not None:
            maintenance_notice = {
                "title": "Site is under maintenance.",
                "body": "Only admin login is allowed right now.",
                "message": maintenance.message or "",
            }
    if form.validate_on_submit():
        solved = verify_challenge(
            salt=form.captcha_salt.data,
            difficulty=form.captcha_difficulty.data,
            expires=form.captcha_expires.data,
            signature=form.captcha_signature.data,
            solution=form.captcha_solution.data,
        )
        if not solved:
            flash(
                "We couldn't verify that request. Please try again.",
                "primary",
            )
            return render_template(
                "va_frontpages/va_login.html",
                form=EmailStepForm(email=form.email.data),
                maintenance_notice=maintenance_notice,
            )

        next_url = _safe_next_url(request.args.get("next"))
        _set_preauth((form.email.data or "").strip().lower(), next_url)
        password_url = url_for("va_auth.va_login_password")
        if next_url:
            password_url = url_for("va_auth.va_login_password", next=next_url)
        return redirect(password_url)
    return render_template(
        "va_frontpages/va_login.html",
        form=form,
        maintenance_notice=maintenance_notice,
    )


@va_auth.route("/valogin/captcha-challenge", methods=["GET"])
def va_login_captcha_challenge():
    """JSON challenge for the email step's proof-of-work CAPTCHA."""
    return jsonify(issue_challenge())


@va_auth.route("/valogin/password", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
@limiter.limit("20 per hour", methods=["POST"], key_func=_preauth_email_key_func)
def va_login_password():
    """Step 2: the same page (a passkey button plus password) for every
    email, known or unknown -- see docs/policy/authentication-factors.md
    section 1. Passkey verification is a later phase (digitva-sn1.1.4+); this
    page shows only the password path for now.
    """
    if current_user.is_authenticated:
        return redirect(current_user.landing_url())
    preauth = _preauth_state()
    if preauth is None:
        flash("Please sign in again.", "primary")
        return redirect(url_for("va_auth.va_login"))

    next_url = _safe_next_url(request.args.get("next")) or preauth.get("next")
    form = PasswordStepForm()
    if form.validate_on_submit():
        # Re-check freshness: a long-open tab could submit after expiry.
        preauth = _preauth_state()
        if preauth is None:
            flash("Please sign in again.", "primary")
            return redirect(url_for("va_auth.va_login"))

        user = db.session.scalar(
            sa.select(VaUsers).where(VaUsers.email == preauth["email"])
        )
        # Inactive accounts get the wrong-password response: no enumeration.
        if user is None:
            # Spend a hash check anyway so unknown emails take as long.
            check_password_hash(_DUMMY_PASSWORD_HASH, form.password.data)
        if (
            user is None
            or not user.check_password(form.password.data)
            or not user.is_active
        ):
            flash(INVALID_LOGIN_MESSAGE, "primary")
            return redirect(_password_step_url(next_url))

        if not user.email_verified:
            flash("Please verify your email address before logging in.", "email_unverified")
            return redirect(_password_step_url(next_url))

        if not user.is_admin() and should_block_non_admin_after_cutoff():
            flash(
                "Site is under maintenance. Only admin login is allowed right now.",
                "warning",
            )
            return redirect(_password_step_url(next_url))

        _clear_preauth()
        # Session fixation: drop everything issued before authentication
        # (the pre-auth state above included), then give the authenticated
        # session a new ID. regenerate() no-ops on an empty session, so it
        # must run after login_user has populated it.
        session.clear()
        session.permanent = True
        login_user(user, remember=form.remember_me.data)
        current_app.session_interface.regenerate(session)

        return redirect(next_url or current_user.landing_url())
    return render_template(
        "va_frontpages/va_login_password.html",
        form=form,
        email=preauth["email"],
        next_url=next_url,
    )


def _password_step_url(next_url):
    if next_url:
        return url_for("va_auth.va_login_password", next=next_url)
    return url_for("va_auth.va_login_password")


@va_auth.route("/valogout", methods=["POST"])
def va_logout():
    if current_user.is_anonymous:
        return redirect(url_for("va_main.va_index"))
    logout_user()
    flash("You have been successfully logged out.", "primary")
    return redirect(url_for("va_main.va_index"))


@va_auth.route("/site-maintenance-status", methods=["GET"])
def site_maintenance_status():
    maintenance = get_active_site_maintenance()
    return jsonify({"maintenance": serialize_site_maintenance(maintenance)})


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
        # docs/policy/authentication-factors.md section 8: a password reset
        # ends every existing session and remember cookie for this user.
        user.bump_session_version()
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

    if not user.email_verified:
        user.email_verified = True
        db.session.commit()

    if not user.pw_reset_t_and_c:
        from app.services.token_service import generate_token

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

def _safe_next_url(target):
    """Return ``target`` if it is a safe post-login redirect, else None.

    Accepts a path starting with exactly one ``/`` (no scheme, no host), or an
    absolute http(s) URL on this request's host (role_required sends
    ``next=request.url``). Rejects backslashes, whitespace and control
    characters anywhere, since browsers normalise ``/\\host`` and ``///host``
    into off-site URLs.
    """
    if not target or "\\" in target:
        return None
    if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in target):
        return None
    if target.startswith("//"):
        return None
    parsed = urlparse(target)
    if not parsed.scheme and not parsed.netloc:
        return target if target.startswith("/") else None
    if parsed.scheme in ("http", "https") and parsed.netloc == request.host:
        return target
    return None


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
