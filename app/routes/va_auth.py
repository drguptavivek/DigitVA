from datetime import datetime, timedelta, timezone

from app import db, limiter
from app.models import AuthWebauthnCredential, VaUsers
from app.forms import (
    EmailStepForm,
    PasswordStepForm,
    SecondFactorForm,
    ForgotPasswordForm,
    ResetPasswordForm,
)
import sqlalchemy as sa
import uuid
from flask import Blueprint, current_app, render_template, redirect, url_for, flash, session, request, jsonify
from flask_login import login_user, logout_user, current_user
from urllib.parse import urlparse
from werkzeug.security import check_password_hash, generate_password_hash

from app.services import totp_service
from app.services.pow_captcha_service import issue_challenge, verify_challenge
from app.services.security_event_service import credential_id_prefix, record_security_event
from app.services.site_maintenance_service import (
    get_active_site_maintenance,
    serialize_site_maintenance,
    should_block_non_admin_after_cutoff,
)
from app.services.webauthn_service import (
    PasskeyVerificationError,
    base64url_to_bytes,
    build_authentication_options,
    clear_authentication_challenge,
    verify_authentication,
)

va_auth = Blueprint("va_auth", __name__)

# docs/policy/authentication-factors.md section 1: pre-auth state is bound to
# one email, allows one outstanding challenge, and expires 5 minutes after
# the email step.
PREAUTH_TTL = timedelta(minutes=5)
INVALID_LOGIN_MESSAGE = "Invalid email or password. Please, re-check and login again."
INVALID_SECOND_FACTOR_MESSAGE = "Invalid code. Please try again."
_DUMMY_PASSWORD_HASH = generate_password_hash("digitva-timing-equaliser")

# docs/policy/authentication-factors.md section 1: five failed second-factor
# attempts clear the pre-auth state and send the user back to the email step.
SECOND_FACTOR_MAX_FAILURES = 5


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


def _complete_login(user, *, remember: bool, nudge_if_no_passkey: bool) -> None:
    """Finish sign-in exactly once, shared by the password and passkey
    paths: drop every session key issued before authentication (the pre-auth
    state included), give the authenticated session a new ID, and record the
    reauthentication timestamp that Profile's passkey-management routes
    require to be fresh (docs/policy/authentication-factors.md section 7 --
    the 10-minute window itself is enforced in app/routes/api/profile.py).

    ``nudge_if_no_passkey`` flags the post-login passkey banner (section 2):
    the password path passes True, the passkey path False (a passkey
    sign-in needs no nudge to use a passkey).

    Caller is responsible for every check that must pass first (active,
    verified email, maintenance) and for the redirect afterwards.
    """
    has_passkey = db.session.scalar(
        sa.select(
            sa.exists().where(AuthWebauthnCredential.user_id == user.user_id)
        )
    )
    _clear_preauth()
    clear_authentication_challenge()
    # Session fixation: drop everything issued before authentication, then
    # give the authenticated session a new ID. regenerate() no-ops on an
    # empty session, so it must run after login_user has populated it.
    session.clear()
    session.permanent = True
    login_user(user, remember=remember)
    session["auth_verified_at"] = datetime.now(timezone.utc).isoformat()
    if nudge_if_no_passkey and not has_passkey:
        session["passkey_nudge"] = True
    current_app.session_interface.regenerate(session)


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
    section 1. Passkey verification runs through the JSON routes below.
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

        if totp_service.needs_second_factor(user):
            # Bind the verified password to the same pre-auth state (same
            # email, same 5-minute expiry) rather than completing sign-in --
            # docs/policy/authentication-factors.md section 3.
            preauth["second_factor_user_id"] = str(user.user_id)
            preauth["second_factor_failures"] = 0
            preauth["remember"] = bool(form.remember_me.data)
            session["preauth"] = preauth
            return redirect(_second_factor_step_url(next_url))

        _complete_login(user, remember=form.remember_me.data, nudge_if_no_passkey=True)

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


def _second_factor_step_url(next_url):
    if next_url:
        return url_for("va_auth.va_login_second_factor", next=next_url)
    return url_for("va_auth.va_login_second_factor")


def _second_factor_state() -> dict | None:
    """The pre-auth state, only if a password has already been verified for
    it in this same state -- the second-factor page is unreachable without
    that (docs/policy/authentication-factors.md section 1)."""
    preauth = _preauth_state()
    if preauth is None or not preauth.get("second_factor_user_id"):
        return None
    return preauth


@va_auth.route("/valogin/second-factor", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
@limiter.limit("20 per hour", methods=["POST"], key_func=_preauth_email_key_func)
def va_login_second_factor():
    """Step 3, only for users who must give a second factor: a TOTP code or
    a recovery code (docs/policy/authentication-factors.md section 3).
    Reachable only after a correct password in the same pre-auth state.
    """
    if current_user.is_authenticated:
        return redirect(current_user.landing_url())
    preauth = _second_factor_state()
    if preauth is None:
        flash("Please sign in again.", "primary")
        return redirect(url_for("va_auth.va_login"))

    user = db.session.scalar(
        sa.select(VaUsers).where(VaUsers.user_id == uuid.UUID(preauth["second_factor_user_id"]))
    )
    if user is None or not user.is_active or user.email != preauth["email"]:
        _clear_preauth()
        flash("Please sign in again.", "primary")
        return redirect(url_for("va_auth.va_login"))

    has_passkey = db.session.scalar(
        sa.select(sa.exists().where(AuthWebauthnCredential.user_id == user.user_id))
    )
    has_totp = totp_service.has_confirmed_totp(user.user_id)
    next_url = _safe_next_url(request.args.get("next")) or preauth.get("next")
    form = SecondFactorForm()

    if form.validate_on_submit():
        # Re-check freshness and state: a long-open tab could submit after
        # expiry, or after the pre-auth state was cleared some other way.
        preauth = _second_factor_state()
        if preauth is None:
            flash("Please sign in again.", "primary")
            return redirect(url_for("va_auth.va_login"))

        code = (form.code.data or "").strip()
        verified_by_totp = has_totp and totp_service.verify(user, code)
        verified_by_recovery = (not verified_by_totp) and totp_service.verify_recovery_code(user, code)
        verified = verified_by_totp or verified_by_recovery

        if not verified:
            db.session.rollback()
            failures = preauth.get("second_factor_failures", 0) + 1
            if failures >= SECOND_FACTOR_MAX_FAILURES:
                _clear_preauth()
                record_security_event(user_id=user.user_id, event_type="second_factor_lockout")
                db.session.commit()
                flash("Too many attempts. Please sign in again.", "primary")
                return redirect(url_for("va_auth.va_login"))
            preauth["second_factor_failures"] = failures
            session["preauth"] = preauth
            flash(INVALID_SECOND_FACTOR_MESSAGE, "primary")
            return redirect(_second_factor_step_url(next_url))

        if verified_by_recovery:
            remaining = totp_service.remaining_recovery_code_count(user.user_id)
            record_security_event(
                user_id=user.user_id,
                event_type="recovery_code_used",
                detail={"remaining": remaining},
            )

        if not user.is_admin() and should_block_non_admin_after_cutoff():
            db.session.commit()
            flash(
                "Site is under maintenance. Only admin login is allowed right now.",
                "warning",
            )
            return redirect(_second_factor_step_url(next_url))

        remember = bool(preauth.get("remember"))
        _complete_login(user, remember=remember, nudge_if_no_passkey=not has_passkey)
        db.session.commit()
        return redirect(next_url or current_user.landing_url())

    return render_template(
        "va_frontpages/va_login_second_factor.html",
        form=form,
        email=user.email,
        next_url=next_url,
        has_totp=has_totp,
        has_passkey=has_passkey,
    )


@va_auth.route("/valogin/passkey/options", methods=["POST"])
@limiter.limit("10 per minute")
@limiter.limit("20 per hour", key_func=_preauth_email_key_func)
def va_login_passkey_options():
    """Discoverable-credential options for the passkey sign-in button.

    No ``allowCredentials`` and nothing derived from the pre-auth email --
    the response is identical for every email, known or not (section 1).
    Still requires a live pre-auth state, so this is unreachable without
    having passed the CAPTCHA-gated email step first.
    """
    if _preauth_state() is None:
        return jsonify({"error": "Please sign in again."}), 400
    return jsonify(build_authentication_options())


@va_auth.route("/valogin/passkey/verify", methods=["POST"])
@limiter.limit("10 per minute")
@limiter.limit("20 per hour", key_func=_preauth_email_key_func)
def va_login_passkey_verify():
    """Verify a passkey assertion and complete sign-in.

    The credential must belong to the account named by the pre-auth email
    (never the credential's own claim) -- an assertion for a real credential
    of a *different* account, or for no account at all, gets the same
    generic message as a wrong password (docs/policy/authentication-factors.md
    section 2).
    """
    preauth = _preauth_state()
    if preauth is None:
        clear_authentication_challenge()
        return jsonify({"error": "Please sign in again."}), 400

    body = request.get_json(silent=True) or {}
    credential = body.get("credential")
    if not isinstance(credential, dict):
        clear_authentication_challenge()
        return jsonify({"error": INVALID_LOGIN_MESSAGE}), 400

    try:
        raw_id = base64url_to_bytes(credential.get("rawId") or credential.get("id") or "")
    except Exception:
        clear_authentication_challenge()
        return jsonify({"error": INVALID_LOGIN_MESSAGE}), 400

    preauth_user = db.session.scalar(
        sa.select(VaUsers).where(VaUsers.email == preauth["email"])
    )
    stored = db.session.scalar(
        sa.select(AuthWebauthnCredential).where(
            AuthWebauthnCredential.credential_id == raw_id
        )
    )
    # The credential must belong to the pre-auth email's own account -- a
    # real credential of a different account (or of no account) is refused
    # with the same generic message, never distinguished.
    if (
        preauth_user is None
        or stored is None
        or stored.user_id != preauth_user.user_id
        or not preauth_user.is_active
    ):
        clear_authentication_challenge()
        return jsonify({"error": INVALID_LOGIN_MESSAGE}), 400

    user = preauth_user

    try:
        verified = verify_authentication(
            credential, credential_public_key=stored.public_key
        )
    except PasskeyVerificationError:
        return jsonify({"error": INVALID_LOGIN_MESSAGE}), 400

    # Signature-counter policy (section 2): 0/0 is fine (synced passkeys);
    # only a non-zero stored counter the new value fails to exceed is a
    # possible clone.
    if stored.sign_count > 0 and verified.new_sign_count <= stored.sign_count:
        record_security_event(
            user_id=user.user_id,
            event_type="counter_regression",
            detail={"credential_prefix": credential_id_prefix(stored.credential_id)},
        )
        db.session.commit()
        return jsonify({"error": INVALID_LOGIN_MESSAGE}), 400

    if not user.email_verified:
        return jsonify(
            {"error": "Please verify your email address before logging in."}
        ), 400

    if not user.is_admin() and should_block_non_admin_after_cutoff():
        return jsonify(
            {"error": "Site is under maintenance. Only admin login is allowed right now."}
        ), 400

    next_url = preauth.get("next")

    # Atomic counter update: only succeeds if sign_count still matches what
    # was just checked, so a concurrent use of the same credential cannot
    # both apply their counter bump.
    result = db.session.execute(
        sa.update(AuthWebauthnCredential)
        .where(
            AuthWebauthnCredential.id == stored.id,
            AuthWebauthnCredential.sign_count == stored.sign_count,
        )
        .values(
            sign_count=verified.new_sign_count,
            last_used_at=datetime.now(timezone.utc),
        )
    )
    if result.rowcount != 1:
        db.session.rollback()
        return jsonify({"error": INVALID_LOGIN_MESSAGE}), 400

    _complete_login(user, remember=False, nudge_if_no_passkey=False)
    db.session.commit()

    return jsonify({"redirect": next_url or current_user.landing_url()})


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
# Break-glass factor reset (docs/policy/authentication-factors.md section 8)
# ---------------------------------------------------------------------------

@va_auth.route("/factor-reset/<token>", methods=["GET", "POST"])
@limiter.limit("5 per minute", methods=["POST"])
def factor_reset(token):
    """Land the break-glass CLI's single-use magic link: set a new password
    (same policy checks as ``reset_password``), then sign the user straight
    in and send them to the Profile factor-setup section. Public by design --
    reachable only with a valid, unexpired, single-use token; see
    ``PUBLIC_BY_DESIGN`` in tests/test_route_auth_coverage.py.
    """
    if current_user.is_authenticated:
        return redirect(current_user.landing_url())

    from app.services.token_service import validate_token

    user_id = validate_token(token, "factor_reset")
    if not user_id:
        return render_template(
            "va_frontpages/va_reset_password.html",
            form=ResetPasswordForm(),
            token=token,
            token_valid=False,
        )

    form = ResetPasswordForm()
    if form.validate_on_submit():
        # Re-validate: a long-open tab could submit after expiry, or after a
        # later reset/password-change invalidated this same token.
        user_id = validate_token(token, "factor_reset")
        if not user_id:
            flash("This link is invalid or has expired.", "danger")
            return redirect(url_for("va_auth.va_login"))
        try:
            uid = uuid.UUID(user_id)
        except (ValueError, TypeError):
            flash("Invalid reset link.", "danger")
            return redirect(url_for("va_auth.va_login"))

        user = db.session.get(VaUsers, uid)
        # login_user() below refuses an inactive user silently -- check here
        # so the failure path is the same generic message, not a crash on
        # current_user.landing_url() for an anonymous session.
        if user is None or not user.is_active:
            flash("This link is invalid or has expired.", "danger")
            return redirect(url_for("va_auth.va_login"))

        user.set_password(form.new_password.data)
        if not user.email_verified:
            user.email_verified = True
        # docs/policy/authentication-factors.md section 8: using the link
        # (like a password reset) ends every other existing session and
        # remember cookie, and invalidates this and any other outstanding
        # factor-reset token (token_service fingerprints the new version).
        user.bump_session_version()
        # The magic link plus a freshly-set password is proof enough to sign
        # the user in immediately, same as the onboarding reset flow.
        _complete_login(user, remember=False, nudge_if_no_passkey=False)
        # Set after _complete_login: it calls session.clear() first.
        session["factor_setup_forced"] = True
        db.session.commit()

        flash(
            "Your password has been set. Please add a passkey or authenticator app.",
            "success",
        )
        return redirect(url_for("profile.view") + "#passkeys-card")

    return render_template(
        "va_frontpages/va_reset_password.html",
        form=form,
        token=token,
        token_valid=True,
        action_url=url_for("va_auth.factor_reset", token=token),
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
